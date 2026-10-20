"""Car Arena (cararena.pl, Santander Leasing) — aukcje poleasingowe, HTML SSR.

Źródło danych: `GET /aukcje/samochody-osobowe?field-fuel=electric` (filtr paliwa działa
po stronie serwera — zweryfikowane 2026-10-20; bez niego listing zawiera wszystkie paliwa).
Kafelki `div.offers-item` występują w dwóch miejscach DOM: w głównej liście
(`auction_items_list`) i w sidebarze „top aukcje" (`top-auctions-widget`) — parser bierze
WYŁĄCZNIE główną listę, bo widget ignoruje filtr paliwa (stamtąd trafiały się spalinowe
Toyota Corolla czy Land Cruiser z ukrytą ceną).

Pola: `data-auction-id` (ID aukcji), `data-name` (nazwa), wiersze `.offer-item__info-row`
(pary „Rok produkcji/Przebieg/Paliwo/Forma sprzedaży/Lokalizacja"), cena w
`.offers-item__price` z jawną podstawą („brutto"). Aukcje z „CENA UKRYTA" (widok
zalogowanego) są pomijane — nie obchodzimy ograniczeń widoku gościa.

Bez paginacji (przy filtrowanej liście kilka–kilkanaście pozycji na jednej stronie).
Ceny brutto, faktura VAT (`Forma sprzedaży`). robots.txt: `Allow: /` (blokady tylko
admin/login/regulaminy). Zakończenie aukcji w `data-date-end` — wygasła aukcja znika
z listingu, co raport pokaże jako „zniknęło".
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from evradar.models import RawListing
from evradar.parsing import parse_int, parse_price
from evradar.scrapers.base import BaseScraper

LIST_URL = "https://cararena.pl/aukcje/samochody-osobowe"
_ID = re.compile(r"/(\d+)-")


def _info_rows(tile: Node) -> dict[str, str]:
    """„Rok produkcji:2023" -> {"Rok produkcji": "2023"} (kropka = separator w SSR)."""
    out: dict[str, str] = {}
    for row in tile.css(".offer-item__info-row"):
        parts = row.text(strip=True).split(":", 1)
        if len(parts) == 2:
            out[parts[0].strip()] = parts[1].strip()
    return out


def parse_listing(html: str) -> list[RawListing]:
    """Czysta funkcja: HTML listingu -> ogłoszenia (tylko główna lista, bez widgetu)."""
    listings: list[RawListing] = []
    for tile in HTMLParser(html).css("#auction_items_list div.offers-item"):
        price_node = tile.css_first(".offers-item__price")
        price_text = price_node.text(strip=True) if price_node else ""
        if not price_text or "UKRYTA" in price_text.upper():
            continue
        link = tile.css_first("a[href]")
        href = (link.attributes.get("href") or "").strip() if link is not None else ""
        if not href:
            continue
        url = href if href.startswith("http") else f"https://cararena.pl{href}"
        info = _info_rows(tile)
        auction_id = tile.attributes.get("data-auction-id")
        id_match = _ID.search(url)
        price = parse_price(price_text)
        listings.append(
            RawListing(
                source="cararena",
                external_id=auction_id or (id_match.group(1) if id_match else None),
                url=url.split("?")[0],
                title_raw=tile.attributes.get("data-name") or info.get("", "") or url,
                fuel=info.get("Paliwo"),
                year=parse_int(info.get("Rok produkcji")),
                mileage_km=parse_int(info.get("Przebieg")),
                price_gross_pln=(
                    price.amount if price and price.basis != "net" else None
                ),
                price_net_pln=price.amount if price and price.basis == "net" else None,
                vat_invoice=info.get("Forma sprzedaży", "").startswith("Faktura") or None,
                location=info.get("Lokalizacja"),
                image_url=tile.attributes.get("data-thumb"),
            )
        )
    return listings


class CarArenaScraper(BaseScraper):
    source_id = "cararena"

    async def fetch(self) -> list[RawListing]:
        html = await self.get_text(LIST_URL, {"field-fuel": "electric"})
        return [x for x in parse_listing(html) if x.fuel == "Elektryczny"]
