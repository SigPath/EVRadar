"""Autoplac (autoplac.pl) — listing ofert (Angular SSR, dane w `ng-state`).

Źródło danych: `<script id="ng-state">` → wpis `https://api.autoplac.pl/offers/search?...` →
`body.offerList[].offer` (marka, model, rocznik, przebieg, `priceInfo`, miasto, `webUrl`) oraz
`photoList[]`. Host `api.autoplac.pl` zwraca 403 na `robots.txt`, więc NIE wołamy API wprost —
czytamy wyłącznie dane osadzone w stronie `autoplac.pl` (jej `robots.txt` zezwala na `/oferty/...`;
zabronione są m.in. parametry `offset`, `sortOrder`, `brandModelIds`, `fullTextQuery`, nieużywane).

Adresy zapytań (zweryfikowane na żywo): `/oferty/samochody-osobowe/<marka>/<model>/elektryczny`,
a kolejne strony to `?p=N` (24 oferty na stronę, `offerCount` = łączna liczba). Poza zakresem strona
zwraca pierwszą stronę, więc kończymy po `offerCount`. Ścieżki `<marka>/<model>` są w
`config/sources.yaml` (`params.paths`); nieznany model cicho zwraca całą markę (wykrywamy to po
`filters.brandModelIds` i zgłaszamy błąd). Nieudana ścieżka nie przerywa pozostałych — błąd źródła
dopiero, gdy zawiodą wszystkie (wzorzec z Otomoto).

Ceny: `priceInfo.primary` (`brutto: true` = brutto), `priceInfo.secondary` to cena w drugiej
postaci tylko jako tekst ("32 439 zł" netto) — czytamy ją z tekstu, nic nie przeliczamy.
Oferty bywają "FV 23%" (`invoiceType`). Adres oferty: `https://autoplac.pl` + `webUrl`.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from evradar.models import RawListing
from evradar.parsing import parse_kwh
from evradar.scrapers.base import BaseScraper
from evradar.scrapers.ngstate import extract_ng_state

log = structlog.get_logger()

BASE_URL = "https://autoplac.pl"
PAGE_SIZE = 24
_SEARCH_PREFIX = "https://api.autoplac.pl/offers/search"
_DIGITS = re.compile(r"\D")


def _digits(text: str | None) -> int | None:
    value = _DIGITS.sub("", text or "")
    return int(value) if value else None


def _search_body(html: str) -> dict[str, Any]:
    state = extract_ng_state(html)
    key = next((k for k in state if k.startswith(_SEARCH_PREFIX)), None)
    if key is None:
        raise ValueError("Brak wyników wyszukiwania w ng-state — zmieniła się struktura strony")
    body: dict[str, Any] = state[key]["body"]
    return body


def parse_listing(html: str) -> tuple[list[RawListing], int]:
    """Czysta funkcja: HTML -> (ogłoszenia, łączna liczba ofert wg serwisu)."""
    body = _search_body(html)
    listings: list[RawListing] = []
    for item in body["offerList"]:
        o = item["offer"]
        if o.get("status") not in (None, "PUBLISHED"):
            continue
        price = o.get("priceInfo") or {}
        primary = price.get("primary") or {}
        secondary = price.get("secondary") or {}
        amount = primary.get("price")
        gross = amount if amount and primary.get("brutto") else None
        net = amount if amount and not primary.get("brutto") else None
        if gross and secondary and not secondary.get("brutto"):
            net = _digits(secondary.get("value"))
        photo = (item.get("photoList") or [{}])[0]
        invoice = str(price.get("invoiceType") or "")
        listings.append(
            RawListing(
                source="autoplac",
                external_id=str(o["id"]),
                url=f"{BASE_URL}{o['webUrl']}",
                title_raw=o.get("title") or f"{o['brand']} {o['model']}",
                brand=o.get("brand"),
                model=o.get("model"),
                fuel=o.get("fuelTypeText"),
                year=o.get("productionYear"),
                mileage_km=o.get("mileage"),
                price_gross_pln=int(gross) if gross else None,
                price_net_pln=int(net) if net else None,
                vat_invoice=True if invoice.startswith("FV") else None,
                battery_kwh=parse_kwh(o.get("title")),
                location=o.get("city"),
                image_url=photo.get("webpMiniatureUrl") or photo.get("miniatureUrl"),
            )
        )
    return listings, int(body.get("offerCount", len(listings)))


class AutoplacScraper(BaseScraper):
    source_id = "autoplac"

    async def _collect(self, base: str, path: str) -> dict[str, RawListing]:
        """Wszystkie strony jednej ścieżki modelu (limit `max_pages`); wykrywa nieznany slug."""
        url = f"{base}/oferty/samochody-osobowe/{quote(path, safe='/')}/elektryczny"
        found: dict[str, RawListing] = {}
        fetched = 0
        for page in range(1, self.config.max_pages + 1):
            html = await self.get_text(url, {"p": page} if page > 1 else None)
            if page == 1:
                ids = _search_body(html).get("filters", {}).get("brandModelIds") or []
                if "/" in path and not any("_" in str(i) for i in ids):
                    raise ValueError(f"Nieznany model w ścieżce '{path}' — sprawdź slug")
            listings, total = parse_listing(html)
            fetched += len(listings)
            for item in listings:
                found[item.external_id or item.url] = item
            if not listings or fetched >= total:
                break
        return found

    async def fetch(self) -> list[RawListing]:
        base = self.config.url.rstrip("/")
        paths = list(self.config.params.get("paths", []))
        results: dict[str, RawListing] = {}
        failed: list[str] = []
        for path in paths:
            try:
                results.update(await self._collect(base, path))
            except (ValueError, httpx.HTTPError) as exc:
                # jedna ścieżka (nieznany slug, awaria) nie może przewrócić całego źródła
                failed.append(path)
                log.warning("autoplac_path_failed", path=path, error=str(exc))
                continue
        if failed and not results:
            raise ValueError(f"wszystkie ścieżki zawiodły: {', '.join(failed)}")
        if failed:
            log.warning("autoplac_paths_partial", failed=failed, total=len(paths))
        return list(results.values())
