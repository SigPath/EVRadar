"""Aukcje EFL (aukcje.efl.com.pl, EFL / Crédit Agricole) — HTML SSR, aukcje poleasingowe.

Źródło danych: `GET /AuctionList` (formularz GET). Zweryfikowane na żywo 2026-10-20:
  * `category=12`            — samochody osobowe (bez tego wchodzą też maszyny/sprzęt)
  * `fc=10&sort=Title-asc`   — wartości wzięte z linków własnego pagera serwisu;
    **bez `fc` paginacja nie działa** — `page=N` jest wtedy po cichu ignorowane
    (kanoniczny `/AuctionList/Pojazdy/Osobowe` zawsze zwraca stronę 1)
  * `page=0..N`              — numeracja od ZERA; twardy limit 8 ofert na stronę,
    `perPage` jest ignorowany (analogia limitu 20 w Poleasingowe.pl)
Oferty: `div.OfferListInner` — tytuł w `.AuctionTitle h3`, parametry w tabeli
`table.simple-table` (pary label/value), cena w `.ListAuctionInfo .price`,
zdjęcie w `.AuctionPhoto img` (ścieżka relatywna). ID aukcji w URL `/Auction/<slug>-id<id>`.

Ceny: strona aukcji podaje „Aktualna cena (bez VAT)" — zapisujemy jako NETTO
(sprzedaż na fakturę, konwencja jak w Poleasingowe.pl; bez przeliczeń na brutto).
Paliwo „Napęd elektryczny" normalizowane na „Elektryczny"; adapter odsiewa
nieelektryczne po stronie klienta (kody filtrów paliwa w URL są nieudokumentowane).
robots.txt: `Allow: /`.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from evradar.models import RawListing
from evradar.parsing import parse_int, parse_price
from evradar.scrapers.base import BaseScraper

LIST_URL = "https://aukcje.efl.com.pl/AuctionList"
PAGE_SIZE = 8  # twardy limit serwisu; `perPage` ignorowane
_ID = re.compile(r"-id(\d+)$")
_FUEL = {"Napęd elektryczny": "Elektryczny"}


def _params(tile: Node) -> dict[str, str]:
    """Pary label -> value z tabeli parametrów (wiersze: label, value, pusta, label, value)."""
    out: dict[str, str] = {}
    for row in tile.css("table.simple-table tr"):
        cells = row.css("td")
        for i, cell in enumerate(cells):
            label = cell.css_first("label")
            if label is not None and i + 1 < len(cells):
                out[label.text(strip=True).rstrip(":")] = cells[i + 1].text(strip=True)
    return out


def parse_listing(html: str) -> list[RawListing]:
    """Czysta funkcja: HTML listingu -> ogłoszenia (wszystkie paliwa)."""
    listings: list[RawListing] = []
    for tile in HTMLParser(html).css("div.OfferListInner"):
        link = tile.css_first(".AuctionTitle a.title")
        if link is None or not link.attributes.get("href"):
            continue
        href = link.attributes["href"] or ""
        id_match = _ID.search(href)
        params = _params(tile)
        price_node = tile.css_first(".ListAuctionInfo .price")
        price = parse_price(price_node.text(strip=True)) if price_node else None
        img = tile.css_first(".AuctionPhoto img")
        src = img.attributes.get("src") if img is not None else None
        fuel = _FUEL.get(params.get("Rodzaj paliwa", ""), params.get("Rodzaj paliwa"))
        listings.append(
            RawListing(
                source="efl",
                external_id=id_match.group(1) if id_match else None,
                url=f"https://aukcje.efl.com.pl{href.split('?')[0]}",
                title_raw=(link.css_first("h3") or link).text(strip=True),
                fuel=fuel,
                year=parse_int(params.get("Rok produkcji")),
                mileage_km=parse_int(params.get("Przebieg odczytany")),
                price_net_pln=price.amount if price else None,  # cena aukcyjna bez VAT
                image_url=f"https://aukcje.efl.com.pl/{src.lstrip('/')}" if src else None,
            )
        )
    return listings


class EflScraper(BaseScraper):
    source_id = "efl"

    async def fetch(self) -> list[RawListing]:
        results: list[RawListing] = []
        for page in range(self.config.max_pages):  # numeracja od 0
            html = await self.get_text(
                LIST_URL,
                {"category": "12", "sort": "Title-asc", "fc": "10", "page": page},
            )
            listings = parse_listing(html)
            results.extend(x for x in listings if x.fuel == "Elektryczny")
            if len(listings) < PAGE_SIZE:
                break
        return results
