"""Cars&Care (carsandcare.pl) — publiczne API JSON (Django REST) używane przez front.

Źródło danych: `https://api.carsandcare-prod.businesslease.cloud/api/v1/cars/` (host z frontu
carsandcare.pl, wykryty w zakładce Network na `/list`):
  * `car/?market=3&public=true&limit=100&offset=N&ordering=-created` — oferty (paginacja `next`)
  * `fuel/?market=3&limit=1000&language=pl` — słownik paliw (id -> nazwa)

Filtry URL: API dostępne jest bez filtra paliwa — aktualnie słownik paliw nie zawiera pozycji
elektrycznej (tylko benzyna/diesel/hybrydy), więc pobieramy wszystkie publiczne oferty
(~200, 2-3 żądania po 100) i filtrowanie modeli robi `matching.py`. Gdy pojawi się paliwo
"elektryczny", pole `fuel` zostanie rozpoznane automatycznie.

Ceny: `price` = NETTO, `sales_price` = BRUTTO (np. 60 081 -> 73 900 = ×1,23).
Strona nie ma osobnych podstron ofert (karty otwierają się bez zmiany URL), dlatego link
prowadzi do listingu z kotwicą `#car-<id>`; stabilny identyfikator to `id` z API.
Robots.txt: carsandcare.pl blokuje tylko `/oferta-klienta`; host API nie ma robots.txt (404).
"""

from __future__ import annotations

from typing import Any

from evradar.models import RawListing
from evradar.parsing import parse_kwh, parse_range_wltp
from evradar.scrapers.base import BaseScraper

API = "https://api.carsandcare-prod.businesslease.cloud/api/v1/cars"
PAGE_SIZE = 100


def parse_cars(
    cars: list[dict[str, Any]], fuels: dict[int, str], list_url: str
) -> list[RawListing]:
    """Czysta funkcja: wyniki API -> ogłoszenia."""
    listings: list[RawListing] = []
    for car in cars:
        title = str(car.get("title") or "").strip()
        comment = str(car.get("comment") or "").strip()
        if not title:
            continue
        brand = str(car.get("brand") or title.split()[0]).title()
        model = (
            title[len(title.split()[0]) :].strip()
            if title.lower().startswith(brand.lower())
            else title
        )
        photos = car.get("photos") or []
        photo = min(photos, key=lambda p: p.get("position", 99)) if photos else {}
        net = car.get("price")
        gross = car.get("sales_price")
        rate = car.get("monthly_payment") or None
        full_title = f"{title} {comment}".strip()
        listings.append(
            RawListing(
                source="carsandcare",
                external_id=str(car["id"]),
                url=f"{list_url}#car-{car['id']}",
                title_raw=full_title,
                brand=brand,
                model=model,
                fuel=fuels.get(car.get("fuel", -1)),
                description=str(car.get("description") or "") or None,
                year=car.get("year_of_manufacture"),
                mileage_km=car.get("mileage"),
                price_gross_pln=round(gross) if gross else None,
                price_net_pln=round(net) if net else None,
                monthly_installment_pln=round(rate) if rate else None,
                installment_basis=None,
                vat_invoice=car.get("vat_expel_flag"),
                battery_kwh=parse_kwh(full_title),
                range_km_wltp=parse_range_wltp(full_title),
                image_url=photo.get("thumbnail") or photo.get("image"),
            )
        )
    return listings


class CarsAndCareScraper(BaseScraper):
    source_id = "carsandcare"

    async def fetch(self) -> list[RawListing]:
        fuel_data = await self.get_json(
            f"{API}/fuel/", {"market": 3, "ordering": "name", "limit": 1000, "language": "pl"}
        )
        fuels = {f["id"]: f["name"] for f in fuel_data["results"]}
        list_url = f"{self.config.url.rstrip('/')}/list"
        results: list[RawListing] = []
        offset = 0
        for _ in range(self.config.max_pages * 4):
            page = await self.get_json(
                f"{API}/car/",
                {
                    "market": 3,
                    "public": "true",
                    "limit": PAGE_SIZE,
                    "offset": offset,
                    "ordering": "-created",
                },
            )
            results.extend(parse_cars(page["results"], fuels, list_url))
            if not page.get("next"):
                break
            offset += PAGE_SIZE
        return results
