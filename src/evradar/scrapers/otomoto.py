"""Otomoto (otomoto.pl) — listing wyszukiwania w SSR (Next.js + urql).

Źródło danych: `<script id="__NEXT_DATA__">` → `props.pageProps.urqlState.*.data` (JSON w stringu)
→ `advertSearch.edges[].node` (id, tytuł, url, cena, parametry, lokalizacja, miniatura).
Strona nie wymaga przeglądarki; `robots.txt` zezwala na `/osobowe/...` (zakazane są m.in. `/api/`).

Adresy zapytań (zweryfikowane na żywo): `/osobowe/<marka>/<model>` z parametrem
`search[filter_enum_fuel_type]=electric`, a ponadto:
  * `search[filter_float_price:to]=N` — limit ceny (z `filters.max_price_gross_pln`)
  * `page=N`                          — paginacja po 32 oferty (`pageInfo.pageSize`)
Ścieżki `<marka>/<model>` są w `config/sources.yaml` (`params.paths`); slugi modeli bywają
nieoczywiste (Tesla Model Y = `tesla/y`), a nieznany slug cicho zwraca całą markę.

Ceny: `price.isGross` mówi, czy podana kwota jest brutto, czy netto (oferty firm z fakturą VAT);
nie przeliczamy — brakującą cenę dolicza runner. Dane zawierają też ogłoszenia z OLX (id `OLX_ID…`).
Dodatkowo: `createdAt` (data dodania), `seller.__typename` (Professional/PrivateSeller)
i SOH baterii wyciągane z tytułu i krótkiego opisu.

Uszkodzone ("Uszkodzony: Tak"): pole nie występuje w liście wyników, więc dla każdej ścieżki
pobieramy dodatkowo wyniki z `search[filter_enum_damaged]=1` i wycinamy te ID (oferty bez
deklaracji zostają).
Wyłączenie: `params.exclude_damaged: false` w `config/sources.yaml`.

Odporność: Otomoto renderuje listingi po stronie serwera, ale jego własne zapytanie
`listingScreen` potrafi przekroczyć limit czasu i wtedy strona wraca z HTTP 200 **bez wyników**
(w `urqlState` jest wtedy `error.networkError`, np. `OptimusTimeoutError: [HTTP408] Timeout
after 10000ms`). Taka odpowiedź to `ListingUnavailable` — ponawiamy stronę (`_SSR_RETRIES`),
a nieudana ścieżka nie przerywa pozostałych: źródło zgłasza błąd dopiero, gdy zawiodą
wszystkie ścieżki.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
import structlog
from selectolax.parser import HTMLParser

from evradar.models import RawListing, SellerType
from evradar.parsing import parse_int, parse_kwh, parse_soh
from evradar.scrapers.base import BaseScraper

log = structlog.get_logger()

_PRICE_PARAM = "search[filter_float_price:to]"
_FUEL_PARAM = "search[filter_enum_fuel_type]"
_DAMAGED_PARAM = "search[filter_enum_damaged]"
_SELLER_TYPES: dict[str, SellerType] = {"ProfessionalSeller": "dealer", "PrivateSeller": "private"}
_SSR_RETRIES = 2  # dodatkowe próby strony, gdy SSR wróci bez wyników (timeout/eksperyment serwisu)


class ListingUnavailable(Exception):
    """SSR bez wyników wyszukiwania (timeout serwisu, zmiana struktury) — stan przejściowy."""


def _created_at(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _ssr_reason(state: dict[str, Any]) -> str:
    """Powód braku wyników: błąd zapytania `listingScreen` (np. timeout) albo zmiana struktury."""
    for entry in state.values():
        error = entry.get("error") or {}
        detail = error.get("networkError") or error.get("message")
        if detail:
            return f"SSR bez wyników — {str(detail)[:200]}"
    return "Brak advertSearch w urqlState — zmieniła się struktura strony"


def _search_node(html: str) -> dict[str, Any]:
    """Wyciąga `advertSearch` z `__NEXT_DATA__`."""
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        raise ValueError("Brak __NEXT_DATA__ — zmieniła się struktura strony")
    state = json.loads(node.text())["props"]["pageProps"]["urqlState"]
    for entry in state.values():
        data = entry.get("data")
        data = json.loads(data) if isinstance(data, str) else data
        if isinstance(data, dict) and "advertSearch" in data:
            search: dict[str, Any] = data["advertSearch"]
            return search
    raise ListingUnavailable(_ssr_reason(state))


def parse_listing(html: str) -> tuple[list[RawListing], int]:
    """Czysta funkcja: HTML -> (ogłoszenia, łączna liczba ofert wg serwisu)."""
    search = _search_node(html)
    listings: list[RawListing] = []
    for edge in search["edges"]:
        n = edge["node"]
        params = {p["key"]: p for p in n.get("parameters") or []}
        amount = ((n.get("price") or {}).get("amount") or {}).get("units")
        is_gross = bool((n.get("price") or {}).get("isGross", True))
        version = (params.get("version") or {}).get("displayValue")
        city = ((n.get("location") or {}).get("city") or {}).get("name")
        thumb = (n.get("thumbnail") or {}).get("x2") or (n.get("thumbnail") or {}).get("x1")
        title = n["title"] if not version or version in n["title"] else f"{n['title']} {version}"
        listings.append(
            RawListing(
                source="otomoto",
                external_id=str(n["id"]),
                url=n["url"],
                title_raw=title,
                description=n.get("shortDescription"),
                brand=(params.get("make") or {}).get("displayValue"),
                model=(params.get("model") or {}).get("displayValue"),
                fuel=(params.get("fuel_type") or {}).get("displayValue"),
                year=parse_int((params.get("year") or {}).get("value")),
                mileage_km=parse_int((params.get("mileage") or {}).get("value")),
                price_gross_pln=int(amount) if amount and is_gross else None,
                price_net_pln=int(amount) if amount and not is_gross else None,
                vat_invoice=True if amount and not is_gross else None,
                battery_kwh=parse_kwh(title),
                location=city,
                image_url=thumb,
                seller_type=_SELLER_TYPES.get(str((n.get("seller") or {}).get("__typename"))),
                listed_at=_created_at(n.get("createdAt")),
                soh_pct=parse_soh(f"{title} {n.get('shortDescription') or ''}"),
            )
        )
    return listings, int(search.get("totalCount", len(listings)))


class OtomotoScraper(BaseScraper):
    source_id = "otomoto"

    async def _page(
        self, url: str, params: dict[str, str], page: int, path: str
    ) -> tuple[list[RawListing], int]:
        """Jedna strona wyników; `ListingUnavailable` ponawiamy (timeout bywa jednostkowy)."""
        last: ListingUnavailable | None = None
        for attempt in range(_SSR_RETRIES + 1):
            html = await self.get_text(url, {**params, "page": page})
            try:
                return parse_listing(html)
            except ListingUnavailable as exc:
                last = exc
                if attempt < _SSR_RETRIES:
                    log.warning(
                        "otomoto_ssr_retry",
                        path=path,
                        page=page,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    await asyncio.sleep((2**attempt) if self.config.delay_max_s > 0 else 0)
        assert last is not None
        raise last

    async def _collect(self, base: str, path: str, params: dict[str, str]) -> dict[str, RawListing]:
        """Wszystkie strony wyników jednej ścieżki modelu (limit `max_pages`)."""
        found: dict[str, RawListing] = {}
        url = f"{base}/osobowe/{quote(path, safe='/')}"
        for page in range(1, self.config.max_pages + 1):
            listings, total = await self._page(url, params, page, path)
            for item in listings:
                found[item.external_id or item.url] = item
            if not listings or len(found) >= total:
                break
        return found

    async def fetch(self) -> list[RawListing]:
        base = self.config.url.rstrip("/")
        params: dict[str, str] = {_FUEL_PARAM: "electric"}
        if self.max_price_gross_pln is not None:
            params[_PRICE_PARAM] = str(self.max_price_gross_pln)
        exclude_damaged = bool(self.config.params.get("exclude_damaged", True))
        paths: list[str] = list(self.config.params.get("paths", []))
        results: dict[str, RawListing] = {}
        damaged: set[str] = set()
        failed: list[str] = []
        for path in paths:
            try:
                found = await self._collect(base, path, params)
            except (ListingUnavailable, httpx.HTTPError) as exc:
                # jedna ścieżka nie może przewrócić całego źródła (oferty pozostałych są cenne)
                failed.append(path)
                log.warning("otomoto_path_failed", path=path, error=str(exc))
                continue
            results.update(found)
            if not (exclude_damaged and found):
                continue
            try:
                marked = await self._collect(base, path, {**params, _DAMAGED_PARAM: "1"})
            except (ListingUnavailable, httpx.HTTPError) as exc:
                log.warning("otomoto_path_failed", path=path, damaged=True, error=str(exc))
                continue
            if len(marked) >= len(found):
                # filtr zignorowany (zmiana serwisu) — nie wycinamy wszystkiego
                log.warning("otomoto_damaged_filter_ignored", path=path)
            else:
                damaged.update(marked)
        if failed and not results:
            raise ListingUnavailable(f"wszystkie ścieżki zawiodły: {', '.join(failed)}")
        if failed:
            log.warning("otomoto_paths_partial", failed=failed, total=len(paths))
        if damaged:
            log.info("excluded_damaged", count=len(damaged & results.keys()))
        return [item for key, item in results.items() if key not in damaged]
