"""Stellantis &You (stellantisandyou.com/pl) — indeks Algolia używany przez front.

Źródło danych: strona listingu `/pl/samochody` filtruje oferty po stronie klienta, pytając
Algolię: `POST https://<appId>-dsn.algolia.net/1/indexes/*/queries`, indeks
`prod_sandy_used_vehicles_pl` (auta używane/poleasingowe, filtr `available=1 AND locale:"pl_PL"`).
Identyfikator aplikacji i klucz *search-only* są publiczne — serwuje je sama strona w
`/content/stellantis-and-you/website/pl/pl.sandy-const.json` (`algolia.*`);
trzymamy je w `config/sources.yaml` (`params`). Gdy Algolia zwróci 403 — klucz się zmienił i trzeba
go odświeżyć z tego pliku.

Dlaczego nie HTML: `stellantisandyou.com` zwraca Akamai 403 dla klientów bez przeglądarki, a
robots.txt zabrania URL-i z parametrami filtrów (`Disallow: /pl/samochody?*`). Nie omijamy tego —
nie pobieramy stron serwisu, tylko wołamy publiczne API wyszukiwarki.

Parametry zapytania: `hitsPerPage=100`, `page=N` (do `nbPages`). Filtr paliwa nie jest użyty —
w indeksie jest obecnie ~200 aut, więc pobieramy całość (2 żądania) i filtrujemy lokalnie.

Ceny: `final_price` to cena BRUTTO ("93 900 zł Brutto" na stronie), `monthly_payment` to rata BRUTTO
(36 mies.). Link: `pdp_url`. Zdjęcia: wzorzec CDN nie został zweryfikowany — pole puste.
"""

from __future__ import annotations

from typing import Any

from evradar.models import RawListing
from evradar.parsing import parse_year
from evradar.scrapers.base import BaseScraper

HITS_PER_PAGE = 100


def parse_hits(hits: list[dict[str, Any]]) -> list[RawListing]:
    """Czysta funkcja: trafienia Algolii -> ogłoszenia."""
    listings: list[RawListing] = []
    for hit in hits:
        brand = str(hit.get("brand") or "").title()
        model_full = str(hit.get("model") or "").strip()
        model = (
            model_full[len(brand) :].strip()
            if model_full.lower().startswith(brand.lower())
            else model_full
        )
        version = str(hit.get("version") or "").strip()
        price = hit.get("final_price") or hit.get("price")
        rate = hit.get("monthly_payment")
        if not hit.get("pdp_url"):
            continue
        listings.append(
            RawListing(
                source="stellantis",
                external_id=str(hit["vehicle_id"]),
                url=hit["pdp_url"],
                title_raw=f"{brand} {model} {version}".strip(),
                brand=brand,
                model=model,
                fuel=hit.get("fuel_type"),
                year=parse_year(hit.get("first_registration_date")),
                mileage_km=round(hit["kilometres"]) if hit.get("kilometres") is not None else None,
                price_gross_pln=round(price) if price else None,
                monthly_installment_pln=round(rate) if rate else None,
                installment_basis="gross" if rate else None,
                drivetrain=hit.get("gearbox"),
                location=hit.get("dealer_city"),
            )
        )
    return listings


class StellantisScraper(BaseScraper):
    source_id = "stellantis"

    async def fetch(self) -> list[RawListing]:
        p = self.config.params
        app_id = str(p["algolia_app_id"])
        url = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
        headers = {
            "x-algolia-application-id": app_id,
            "x-algolia-api-key": str(p["algolia_api_key"]),
        }
        results: list[RawListing] = []
        for page in range(self.config.max_pages * 4):
            body = {
                "requests": [
                    {
                        "indexName": p.get("index", "prod_sandy_used_vehicles_pl"),
                        "filters": 'available=1 AND locale:"pl_PL"',
                        "hitsPerPage": HITS_PER_PAGE,
                        "page": page,
                        "query": "",
                    }
                ]
            }
            data = await self.post_json(url, body, headers)
            res = data["results"][0]
            results.extend(parse_hits(res["hits"]))
            if page + 1 >= int(res.get("nbPages", 1)):
                break
        return results
