"""Dawro (dawro.pl) — aukcje poleasingowe Santander Consumer Multirent, HTML SSR.

Źródło danych: listing ścieżkowy `GET /aukcje/sortuj,data-zakonczenia,kierunek,rosnaco,
strona,N,ilosc,100,wyswietlanie,boxy,sprzedawca,santander_scm,typ,10` (parametry w ścieżce,
nie w query — tak generuje je własny filtr serwisu; `typ,10` = samochody osobowe,
`sprzedawca,santander_scm` = Santander Consumer Multirent, `ilosc,100` działa — zweryfikowane
2026-10-20). **Pułapka paginacji:** pusty zakres (`strona` poza listą) nie zwraca błędu ani
pustej strony — serwis po cichu zwraca PIERWSZĄ stronę; dlatego pętla kończy się też,
gdy pierwsze ID aukcji powtórzy się z poprzedniej strony.

Kafelek `div.aukcja-box`: czysta nazwa w atrybucie `title` nagłówka `h2.nazwa` (w tekście
jest doklejona tablica rejestracyjna), ID aukcji w URL `/aukcja/<id>,<slug>`, parametry
w parach `div.k`/`div.w` (Rok produkcji, Przebieg, Forma sprzedaży), zdjęcie w atrybucie
`data-original` (lazy loading).

Ceny BRUTTO: regulamin aukcji — „Twoja Oferta stanowi cenę brutto" (inaczej niż w ECR/EFL,
gdzie aukcje idą netto). Zapisujemy najwyższą ofertę (`.najwyzsza-oferta-kwota`), a przy
braku ofert — cenę wywoławczą; zmiana oferty = obniżka/podwyżka w raporcie.

**Brak danych o paliwie** — Dawro nie podaje paliwa ani w kafelku, ani w szczegółach aukcji
(select `rodzaj_paliwa[]` ładuje opcje dynamicznie z blokowanej robots-em ścieżki `*-ajax-`).
Klasyfikację napędu przejmuje warstwa matching po tytule (np. „KIA EV 6", „Tesla Model 3").
robots.txt: `Allow: /` (blokady: /reklama/, /*-ajax/, /webservice/, /temp/).
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from evradar.models import RawListing
from evradar.parsing import parse_int, parse_price
from evradar.scrapers.base import BaseScraper

PAGE_SIZE = 100  # ilosc,100 — obecnie 19 aukcji SCM osobowych = 1 strona
_LIST_PATH = (
    "/aukcje/sortuj,data-zakonczenia,kierunek,rosnaco,strona,{page},"
    "ilosc,100,wyswietlanie,boxy,sprzedawca,santander_scm,typ,10"
)
_ID = re.compile(r"/aukcja/(\d+)")


def _next_element(node: Node) -> Node | None:
    """Następny element-rodzeństwo (pomija węzły tekstowe między div-ami)."""
    sibling = node.next
    while sibling is not None and sibling.tag == "-text":
        sibling = sibling.next
    return sibling


def _kv(tile: Node) -> dict[str, str]:
    """Pary div.k -> następujący div.w z bloku parametrów."""
    out: dict[str, str] = {}
    for key_node in tile.css(".parametry div.k"):
        value_node = _next_element(key_node)
        if value_node is not None and "w" in (value_node.attributes.get("class") or "").split():
            out[key_node.text(strip=True).rstrip(":")] = value_node.text(strip=True)
    return out


def parse_listing(html: str) -> list[RawListing]:
    """Czysta funkcja: HTML listingu -> ogłoszenia (wszystkie paliwa — brak danych)."""
    listings: list[RawListing] = []
    for tile in HTMLParser(html).css("div.aukcja-box"):
        link = tile.css_first("a[href]")
        href = (link.attributes.get("href") or "").strip() if link is not None else ""
        id_match = _ID.search(href)
        if not href or not id_match:
            continue
        kv = _kv(tile)
        bid = tile.css_first(".najwyzsza-oferta-kwota")
        bid_price = parse_price(bid.text(strip=True)) if bid is not None else None
        start_price = parse_price(kv.get("Cena wywoławcza"))
        price = bid_price or start_price
        heading = tile.css_first("h2.nazwa")
        img = tile.css_first(".zdjecie img")
        photo = img.attributes.get("data-original") if img is not None else None
        vat_invoice = kv.get("Forma sprzedaży", "").lower().startswith("faktura")
        listings.append(
            RawListing(
                source="dawro",
                external_id=id_match.group(1),
                url=f"https://www.dawro.pl{href.split('?')[0]}",
                title_raw=(heading.attributes.get("title") or heading.text(strip=True))
                if heading is not None
                else href,
                year=parse_int(kv.get("Rok produkcji")),
                mileage_km=parse_int(kv.get("Przebieg")),
                price_gross_pln=price.amount if price else None,  # aukcje brutto
                vat_invoice=True if vat_invoice else None,
                image_url=f"https://www.dawro.pl{photo}" if photo else None,
            )
        )
    return listings


class DawroScraper(BaseScraper):
    source_id = "dawro"

    async def fetch(self) -> list[RawListing]:
        results: list[RawListing] = []
        first_ids: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            html = await self.get_text(
                f"{self.config.url.rstrip('/')}{_LIST_PATH.format(page=page)}"
            )
            listings = parse_listing(html)
            if not listings:
                break
            page_first = listings[0].external_id or ""
            if page_first in first_ids:  # serwis zwraca strone 1 poza zakresem
                break
            first_ids.add(page_first)
            results.extend(listings)
            if len(listings) < PAGE_SIZE:
                break
        return results
