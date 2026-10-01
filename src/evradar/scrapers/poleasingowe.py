"""Poleasingowe.pl (ECR) — platforma aukcyjna aut poleasingowych, HTML renderowany po stronie serwera.

Źródło danych: listing `https://poleasingowe.pl/pl/auctions/list/pub/all/vehicles` (formularz GET
`#topsearchform`). Użyte parametry URL (zweryfikowane na żywo):
  * `fueltype=216`      — rodzaj paliwa "Elektryczny" (id z `<select name="fueltype">`)
  * `list_pagesize=50`  — liczba aukcji na stronę (domyślnie 10)
  * `page=N`            — kolejne strony (gdy strona jest pełna)
Kafelek `div.auction-element` ma `data-auction-id`, tytuł, etykiety `.filter-label` (rok, paliwo,
przebieg), lokalizację i "Aktualna cena". robots.txt blokuje tylko panel licytującego i pliki.

Ceny: to AUKCJE — "Aktualna cena" to bieżąca oferta (bez prowizji, "AUKCJA Z PROWIZJĄ").
Strona aukcji pokazuje cenę z przełącznikiem "netto / brutto" (domyślnie netto, sprzedaż na
fakturę VAT), dlatego zapisujemy ją jako NETTO i nigdy nie przeliczamy na brutto. Zmiana ceny
w trakcie aukcji (nowa oferta) zostanie więc pokazana w raporcie jako obniżka/podwyżka.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from evradar.models import RawListing
from evradar.parsing import parse_int, parse_price
from evradar.scrapers.base import BaseScraper

LIST_URL = "https://poleasingowe.pl/pl/auctions/list/pub/all/vehicles"
PAGE_SIZE = 50
_BG = re.compile(r"url\(([^)]+)\)")
_KM = re.compile(r"\bkm\b", re.IGNORECASE)
_YEAR = re.compile(r"^(19|20)\d{2}$")


def _line(tile: Node, title: str) -> str | None:
    for line in tile.css(".listing-box-line"):
        label = line.css_first(".line-title")
        value = line.css_first(".line-value")
        if label and value and label.text(strip=True).lower().startswith(title.lower()):
            return value.text(strip=True)
    return None


def parse_listing(html: str) -> list[RawListing]:
    """Czysta funkcja: HTML listingu -> ogłoszenia."""
    listings: list[RawListing] = []
    for tile in HTMLParser(html).css("div.auction-element"):
        link = tile.css_first("h2 a")
        auction_id = tile.attributes.get("data-auction-id")
        if link is None or not link.attributes.get("href") or not auction_id:
            continue
        title_node = link.css_first("span")
        title = (title_node or link).text(strip=True)

        year: int | None = None
        mileage: int | None = None
        fuel: str | None = None
        for label in tile.css(".filter-labels .filter-label"):
            text = label.text(strip=True)
            if _YEAR.match(text):
                year = int(text)
            elif _KM.search(text):
                mileage = parse_int(text)
            elif text:
                fuel = text

        price_node = tile.css_first("span.listing-price")
        price = parse_price(price_node.text(strip=True)) if price_node else None
        image_node = tile.css_first(".image-container .image")
        bg = _BG.search(image_node.attributes.get("style") or "") if image_node else None

        listings.append(
            RawListing(
                source="poleasingowe",
                external_id=auction_id,
                url=(link.attributes["href"] or "").split("?")[0],  # bez tokenów partnera (afs/acs)
                title_raw=title,
                fuel=fuel,
                year=year or parse_int(_line(tile, "Rok produkcji")),
                mileage_km=mileage,
                price_net_pln=price.amount if price else None,
                location=_line(tile, "Lokalizacja"),
                image_url=bg.group(1).strip("'\"") if bg else None,
            )
        )
    return listings


class PoleasingoweScraper(BaseScraper):
    source_id = "poleasingowe"

    async def fetch(self) -> list[RawListing]:
        results: list[RawListing] = []
        for page in range(1, self.config.max_pages + 1):
            params: dict[str, str | int] = {"fueltype": "216", "list_pagesize": PAGE_SIZE}
            if page > 1:
                params["page"] = page
            listings = parse_listing(await self.get_text(LIST_URL, params))
            results.extend(listings)
            if len(listings) < PAGE_SIZE:
                break
        return results
