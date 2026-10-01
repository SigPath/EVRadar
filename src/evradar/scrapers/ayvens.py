"""Ayvens — używane auta (usedcars.ayvens.com, Salesforce Commerce Cloud, HTML SSR).

Źródło danych: `www.ayvens.com/pl-pl/` odsyła do sklepu `https://usedcars.ayvens.com/pl-pl`.
Listing `/pl-pl/samochody` renderuje kafelki po stronie serwera; każdy kafelek zawiera
`<span data-tracking-productclick="[JSON]">` z markami, wariantem, paliwem
(`dimension2`: Petrol/Diesel/Hybrid/Electric), przebiegiem (`dimension5`), datą pierwszej
rejestracji (`dimension56`) i ceną (`price`) — parsujemy ten JSON zamiast kruchych selektorów CSS.

Parametry URL: `start=N&sz=200` (paginacja; całość to ~400 aut, 2-3 żądania).
Filtr paliwa (`prefn1=fuelType&prefv1=Electric`) jest ZABRONIONY w robots.txt
(`Disallow: *?*prefn1=*`), więc go nie używamy — pobieramy cały listing i filtrujemy lokalnie.

Ceny: strona podaje "Zawiera 23% VAT" -> cena BRUTTO. Raty: brak na listingu.
Dostępność (`dimension22`): część aut ma status "Coming soon" — nadal trafiają do oferty.
"""

from __future__ import annotations

import html as html_lib
import json
from typing import Any

from selectolax.parser import HTMLParser, Node

from evradar.models import RawListing
from evradar.parsing import parse_price, parse_year
from evradar.scrapers.base import BaseScraper

PAGE_SIZE = 200


def _tracking(tile: Node) -> dict[str, Any]:
    span = tile.css_first("[data-tracking-productclick]")
    if span is None:
        return {}
    raw = span.attributes.get("data-tracking-productclick") or "[]"
    try:
        data = json.loads(html_lib.unescape(raw))
        product: dict[str, Any] = data[0]["ecommerce"]["click"]["products"][0]
    except (ValueError, KeyError, IndexError, TypeError):
        return {}
    return product


def parse_listing(html: str, base_url: str) -> list[RawListing]:
    """Czysta funkcja: HTML listingu -> ogłoszenia."""
    listings: list[RawListing] = []
    for tile in HTMLParser(html).css("div.product-tile"):
        link = tile.css_first("a.link")
        if link is None or not link.attributes.get("href"):
            continue
        info = _tracking(tile)
        name = (info.get("name") or link.text(strip=True)).strip()
        variant = (info.get("variant") or "").strip()
        price = info.get("price")
        if not price:
            value = tile.css_first("span.sales span.value")
            parsed = parse_price(value.attributes.get("content") if value else None)
            price = parsed.amount if parsed else None
        img = tile.css_first("img.tile-image")
        image = (img.attributes.get("data-src") if img else None) or None
        pid = tile.parent.attributes.get("data-pid") if tile.parent else None
        href = link.attributes["href"] or ""
        reg_date = info.get("dimension56")
        listings.append(
            RawListing(
                source="ayvens",
                external_id=pid or info.get("id"),
                url=href if href.startswith("http") else f"{base_url}{href}",
                title_raw=f"{name} {variant}".strip(),
                brand=info.get("brand"),
                model=name,
                fuel=info.get("dimension2"),
                year=parse_year(reg_date),
                mileage_km=info.get("dimension5"),
                price_gross_pln=round(price) if price else None,
                vat_invoice=None,
                image_url=image.replace("&amp;", "&") if image else None,
            )
        )
    return listings


class AyvensScraper(BaseScraper):
    source_id = "ayvens"

    async def fetch(self) -> list[RawListing]:
        base = str(self.config.params.get("listing_base", "https://usedcars.ayvens.com"))
        results: list[RawListing] = []
        for page in range(self.config.max_pages):
            html = await self.get_text(
                f"{base}/pl-pl/samochody", {"start": page * PAGE_SIZE, "sz": PAGE_SIZE}
            )
            listings = parse_listing(html, base)
            results.extend(listings)
            if len(listings) < PAGE_SIZE:
                break
        return results
