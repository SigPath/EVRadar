"""Spoticar (spoticar.pl, Drupal) — HTML kafelków ofert, pobierany prawdziwym Chrome.

Źródło danych: `https://www.spoticar.pl/znajdz-uzywany-samochod` z filtrem energii. Serwer (Akamai)
odpowiada 403 klientom HTTP i trybowi headless, dlatego adapter używa zwykłego, zainstalowanego
Chrome w trybie z oknem (`BrowserScraper`, bez żadnego maskowania) — wymaga lokalnego środowiska
z Chrome i ekranu; w CI (zmienna `CI`) źródło jest pomijane (`params.local_only`).

Stan: nawet w Chrome Akamai zwraca 403 po ok. 5 żądaniach skanu (ręcznie działa) — nie obchodzimy
tej blokady, dlatego źródło jest domyślnie wyłączone w `config/sources.yaml`.

Parametry URL (zweryfikowane w Chrome):
  * `filters[0][energy]=elektryczny` — tylko auta elektryczne (≈55 ofert)
  * `page=N`                         — paginacja, 12 kafelków na stronę ("(55 wyniki wyszukiwania)")
Kafelek `div.vehicle-card` (`data-vo-id`) zawiera tytuł, tagi (przebieg, paliwo, data, skrzynia),
cenę i ukryty JSON `.vo_json_new_gateway` z kalkulacją leasingu. robots.txt (Drupal) nie blokuje
listingu; pobieramy go tą samą przeglądarką.

Ceny: "CENA SPRZEDAŻY POJAZDU BRUTTO" -> BRUTTO; rata "MIESIĘCZNA RATA LEASINGU BRUTTO" -> BRUTTO
(36 mies., 20 000 km/rok). Lokalizacja nie jest podawana na kafelku.
"""

from __future__ import annotations

import json
import re
from typing import Any

from selectolax.parser import HTMLParser, Node

from evradar.models import RawListing
from evradar.parsing import parse_int, parse_price, parse_year
from evradar.scrapers.browser import BrowserScraper

BASE = "https://www.spoticar.pl"
LIST_PATH = "/znajdz-uzywany-samochod"
_TOTAL = re.compile(r"\((\d+)\s+wynik", re.IGNORECASE)
_KM = re.compile(r"\bkm\b", re.IGNORECASE)
_DATE = re.compile(r"^\d{2}-\d{4}$")
_GEARBOX = re.compile(r"automatyczn|manualn", re.IGNORECASE)


def _leasing_rate(card: Node) -> int | None:
    """Rata leasingu BRUTTO z ukrytego JSON-a kafelka (None gdy brak/zmieniony format)."""
    node = card.css_first("input.vo_json_new_gateway")
    if node is None:
        return None
    try:
        data: dict[str, Any] = json.loads(node.attributes.get("value") or "")
        blocks = data["result"]["displayBlocks"]
    except (ValueError, KeyError, TypeError):
        return None
    for block in blocks:
        for line in block.get("displayLines", []):
            if "RATA LEASINGU BRUTTO" in str(line.get("label", "")).upper():
                try:
                    return round(float(line["value"]))
                except (ValueError, KeyError, TypeError):
                    return None
    return None


def parse_listing(html: str) -> tuple[list[RawListing], int]:
    """Czysta funkcja: HTML listingu -> (ogłoszenia, liczba wyników wg serwisu)."""
    tree = HTMLParser(html)
    total_match = _TOTAL.search(tree.body.text() if tree.body else "")
    listings: list[RawListing] = []
    for card in tree.css("div.vehicle-card"):
        link = card.css_first("a.vehicle-card-link")
        title_node = card.css_first(".vehicle-card-title h3")
        vo_id = card.attributes.get("data-vo-id")
        if link is None or title_node is None or not vo_id or not link.attributes.get("href"):
            continue
        title = re.sub(r"\s+", " ", title_node.text()).strip()
        brand, _, model = title.partition(" ")

        mileage = year = None
        fuel = gearbox = None
        for tag in card.css(".characteristics-tags .tag"):
            text = tag.text(strip=True)
            if _KM.search(text):
                mileage = parse_int(text)
            elif _DATE.match(text):
                year = parse_year(text)
            elif _GEARBOX.search(text):
                gearbox = text
            elif text and fuel is None:
                fuel = text

        price_node = card.css_first(".price-value")
        price = parse_price(price_node.text(strip=True)) if price_node else None
        img = card.css_first("img.car-image")
        image = (img.attributes.get("src") or img.attributes.get("data-src")) if img else None
        rate = _leasing_rate(card)
        href = link.attributes["href"] or ""

        listings.append(
            RawListing(
                source="spoticar",
                external_id=vo_id,
                url=f"{BASE}{href}" if href.startswith("/") else href,
                title_raw=title,
                brand=brand,
                model=model,
                fuel=fuel,
                year=year,
                mileage_km=mileage,
                price_gross_pln=price.amount if price else None,
                monthly_installment_pln=rate,
                installment_basis="gross" if rate else None,
                drivetrain=gearbox,
                image_url=image,
            )
        )
    return listings, int(total_match.group(1)) if total_match else len(listings)


class SpoticarScraper(BrowserScraper):
    source_id = "spoticar"

    async def fetch(self) -> list[RawListing]:
        # per marka z configu: kilka lekkich zapytań zamiast ~5 stron wszystkich marek
        paths = [f"{LIST_PATH}/{b.lower().replace(' ', '-')}" for b in self.brands] or [LIST_PATH]
        results: list[RawListing] = []
        for path in paths:
            collected, total = 0, 0
            for page in range(1, self.config.max_pages + 1):
                html = await self.get_html(
                    f"{BASE}{path}",
                    {"page": page, "filters[0][energy]": "elektryczny"},
                    wait_selector="div.vehicle-card",
                    missing_ok=True,
                )
                listings, total = parse_listing(html) if html else ([], 0)
                results.extend(listings)
                collected += len(listings)
                if not listings or collected >= total:
                    break
            if total and not collected:
                raise RuntimeError(f"Serwis zgłasza {total} ofert, parser nie znalazł kafelków")
        return results
