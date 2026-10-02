"""FindCar (findcar.pl) — ogłoszenia salonów (Angular SSR, `ng-state` -> TanStack Query).

Źródło danych: `<script id="ng-state">` -> `TANSTACK_QUERY_STATE.queries[]` o kluczu
`["_listings_core_", "listings", <filtry>, <strona>]` -> `state.data.content[]` (marka, model,
wersja, rocznik, przebieg, `pricing.offer`, salon, zdjęcie). Strona nie wymaga przeglądarki;
`robots.txt` nie zabrania niczego.

Adresy zapytań (zweryfikowane na żywo): `/znajdz-samochod?fuelTypes=electric&makes=<marka>`, kolejne
strony to `/znajdz-samochod/<N>?...` (15 ofert na stronę, `totalPages`). Filtr modelu w URL nie
działa, więc zawężamy po marce (marki z `config/models.yaml`), a modele dopasowuje matcher.
Nieznany parametr jest ignorowany i zwraca wszystkie auta, dlatego sprawdzamy, że klucz
zapytania zawiera nasze `makeSlugs`.

Ceny: `pricing.offer.offerPricePln100` to cena BRUTTO w groszach (tekst: "... zł brutto"), bez
przeliczenń. Adres oferty: `https://findcar.pl/oferty-dealerow/<slug>`. Salony sprzedają auta
nowe i używane.
"""

from __future__ import annotations

from typing import Any

from evradar.models import RawListing
from evradar.parsing import parse_kwh
from evradar.scrapers.base import BaseScraper
from evradar.scrapers.ngstate import extract_ng_state

BASE_URL = "https://findcar.pl"
_PATH = "/znajdz-samochod"


def _listing_query(html: str, make_slug: str | None) -> dict[str, Any]:
    """Zwraca `state.data` zapytania o listing (i weryfikuje, że filtr marki został zastosowany)."""
    queries = extract_ng_state(html).get("TANSTACK_QUERY_STATE", {}).get("queries", [])
    for q in queries:
        key = q.get("queryKey") or []
        if key[:2] == ["_listings_core_", "listings"]:
            if make_slug is not None and (key[2] or {}).get("makeSlugs") != [make_slug]:
                raise ValueError(f"Filtr marki '{make_slug}' nie został zastosowany przez serwis")
            data: dict[str, Any] = q["state"]["data"]
            return data
    raise ValueError("Brak zapytania listings w ng-state — zmieniła się struktura strony")


def parse_listing(html: str, make_slug: str | None = None) -> tuple[list[RawListing], int]:
    """Czysta funkcja: HTML -> (ogłoszenia, liczba stron wg serwisu)."""
    data = _listing_query(html, make_slug)
    listings: list[RawListing] = []
    for c in data["content"]:
        offer = (c.get("pricing") or {}).get("offer") or {}
        pln100 = offer.get("offerPricePln100")
        version = c.get("version")
        make, model = c["make"]["text"], c["model"]["text"]
        title = " ".join(x for x in (make, model, version) if x)
        listings.append(
            RawListing(
                source="findcar",
                external_id=str(c["publicListingNumber"]),
                url=f"{BASE_URL}/oferty-dealerow/{c['slug']}",
                title_raw=title,
                brand=make,
                model=model,
                fuel=(c.get("fuelType") or {}).get("text"),
                year=c.get("productionYear"),
                mileage_km=c.get("mileageKm"),
                price_gross_pln=round(pln100 / 100) if pln100 else None,
                battery_kwh=parse_kwh(version),
                location=(c.get("dealer") or {}).get("city"),
                image_url=c.get("primaryImage"),
            )
        )
    return listings, int(data.get("totalPages", 1))


class FindcarScraper(BaseScraper):
    source_id = "findcar"

    async def fetch(self) -> list[RawListing]:
        base = self.config.url.rstrip("/")
        results: dict[str, RawListing] = {}
        for brand in self.brands:
            slug = brand.lower().replace(" ", "-")
            params = {"fuelTypes": "electric", "makes": slug}
            for page in range(1, self.config.max_pages + 1):
                path = _PATH if page == 1 else f"{_PATH}/{page}"
                html = await self.get_text(f"{base}{path}", params)
                listings, total_pages = parse_listing(html, slug)
                for item in listings:
                    results[item.external_id or item.url] = item
                if not listings or page >= total_pages:
                    break
        return list(results.values())
