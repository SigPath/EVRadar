"""VWFS Store (store.vwfs.pl) — REFERENCYJNY adapter.

Źródło danych: aplikacja Next.js; strona listingu wstrzykuje komplet danych do
`<script id="__NEXT_DATA__">` → `props.pageProps.offers.tails[]` (JSON, bez HTML-owych selektorów).

Użyte parametry URL (`/oferty`), odkryte z `pageProps.filters` i zweryfikowane na żywo:
  * `rodzajPaliwa=5`          — tylko auta elektryczne (5 = ELEKTRYCZNY)
  * `elementowNaStronie=100`  — 100 ofert na stronę (domyślnie 20), zwykle 1 żądanie
  * `strona=N`                — kolejne strony, gdy `offers.count` > liczba pobranych

Ceny: źródło podaje jednocześnie brutto (`totalPriceBrutto`) i netto (`totalPriceNetto`).
Rata (`leasingInstallment.installmentAmountNetto`) jest ratą leasingową NETTO.
Adres oferty: `/oferta/<marka-model>-id-<auctionId>` (slug jest ignorowany przez serwis).

Uwaga: sklep oferuje wyłącznie marki grupy VW (Audi, Cupra, Porsche, Seat, Skoda, VW),
więc przy domyślnym `config/models.yaml` zwykle nie ma dopasowań — adapter działa jednak
i zwraca surowe oferty (np. po dopisaniu `ID.4` do configu pojawią się w raporcie).
"""

from __future__ import annotations

import json
import re
from typing import Any

from selectolax.parser import HTMLParser

from evradar.models import RawListing
from evradar.parsing import parse_kwh
from evradar.scrapers.base import BaseScraper

BASE_URL = "https://store.vwfs.pl"
_SLUG_CLEAN = re.compile(r"[^a-z0-9.]+")


def _slug(text: str) -> str:
    return _SLUG_CLEAN.sub("-", text.lower()).strip("-")


def extract_next_data(html: str) -> dict[str, Any]:
    """Wyciąga JSON z `<script id="__NEXT_DATA__">`."""
    node = HTMLParser(html).css_first("script#__NEXT_DATA__")
    if node is None:
        raise ValueError("Brak __NEXT_DATA__ — zmieniła się struktura strony")
    data: dict[str, Any] = json.loads(node.text())
    return data


def _final_price(total: int | float | None, discounted: int | float | None) -> int | None:
    if total:
        if discounted and 0 < discounted < total:
            return round(discounted)
        return round(total)
    return None


def parse_offers(html: str) -> tuple[list[RawListing], int]:
    """Czysta funkcja: HTML -> (ogłoszenia, łączna liczba ofert wg serwisu)."""
    offers = extract_next_data(html)["props"]["pageProps"]["offers"]
    listings: list[RawListing] = []
    for t in offers["tails"]:
        if t.get("isSold"):
            continue
        auction_id = t["auctionId"]
        title = f"{t['make']} {t['model']} {t.get('type') or ''}".strip()
        gross = _final_price(t.get("totalPriceBrutto"), t.get("discountTotalPriceBrutto"))
        net = _final_price(t.get("totalPriceNetto"), t.get("discountTotalPriceNetto"))
        leasing = (t.get("installmentsInfo") or {}).get("leasingInstallment") or {}
        rate = leasing.get("installmentAmountNetto") or None
        photo = t.get("mainPhotoUrl") or {}
        fuel = (t.get("fuelType") or {}).get("pl")
        listings.append(
            RawListing(
                source="vwfs",
                external_id=str(auction_id),
                url=f"{BASE_URL}/oferta/{_slug(t['make'] + ' ' + t['model'])}-id-{auction_id}",
                title_raw=title,
                brand=str(t["make"]).title(),
                model=t["model"],
                fuel=fuel,
                year=t.get("year"),
                mileage_km=t.get("mileage"),
                price_gross_pln=gross,
                price_net_pln=net,
                monthly_installment_pln=rate if not leasing.get("isError") else None,
                installment_basis="net" if rate and not leasing.get("isError") else None,
                vat_invoice=True if net else None,
                battery_kwh=parse_kwh(t.get("type")),
                drivetrain=t.get("drivetrain"),
                image_url=photo.get("bigThumbnailReference") or photo.get("fullSizeReference"),
            )
        )
    return listings, int(offers.get("count", len(listings)))


class VwfsScraper(BaseScraper):
    source_id = "vwfs"

    async def fetch(self) -> list[RawListing]:
        params = {"rodzajPaliwa": "5", "elementowNaStronie": "100", **self.config.params}
        results: list[RawListing] = []
        total = 0
        for page in range(1, self.config.max_pages + 1):
            html = await self.get_text(f"{self.config.url.rstrip('/')}/oferty", {**params, "strona": page})
            listings, total = parse_offers(html)
            results.extend(listings)
            if not listings or len(results) >= total:
                break
        return results
