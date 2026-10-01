"""mAuto (mauto.pl, mLeasing / mBank) — publiczne API JSON używane przez front React.

Źródło danych: `https://as-mleasing-mauto-api-prod.azurewebsites.net/api` (wykryte w Network):
  * `POST /Offers/AfterLease`  — auta poleasingowe (`Status: ["Poleasingowy"]`)
  * `POST /Offers/NewVehicles` — nowe auta z finansowaniem/najmem (`Status: ["Nowy"]`)
Treść żądania odwzorowuje filtry strony; kluczowe pola: `FuelTypes: ["5"]` (5 = ELEKTRYCZNY,
wartość ze słownika `GET /OffersFilterData`), `ResultsPerPage`, `Page`, `isCompany: true`.
Dzięki filtrowi paliwa wystarcza 1-2 żądania zamiast ~1000 ofert. Host API nie ma robots.txt (404),
a `mauto.pl/robots.txt` zezwala na `/`.

Ceny: `FinalPriceBrutto` i `FinalPriceNetto` (po rabacie) podawane osobno — bez przeliczeń.
Rata: `LeasePrice` (>0) = rata leasingowa NETTO (strona pokazuje "rata netto od …"); dla aut
nowych bez leasingu brak raty.
Adresy ofert: `/samochody-poleasingowe/<marka-model>-id-<AuctionId>` oraz
`/nowe-samochody/<marka-model>-id-<AuctionId>`.
Zdjęcia: `MainPhotoUrl` z szablonem `[size]` -> `640` + `.jpg`.
"""

from __future__ import annotations

import re
from typing import Any

from evradar.models import RawListing
from evradar.parsing import parse_int, parse_kwh
from evradar.scrapers.base import BaseScraper

API = "https://as-mleasing-mauto-api-prod.azurewebsites.net/api"
PAGE_SIZE = 100
_SLUG_CLEAN = re.compile(r"[^a-z0-9.]+")
_FUEL = {"EL": "Elektryczny", "PB": "Benzyna", "ON": "Olej napędowy", "HY": "Hybryda"}
_SECTIONS = {"Poleasingowy": "samochody-poleasingowe", "Nowy": "nowe-samochody"}


def _slug(text: str) -> str:
    return _SLUG_CLEAN.sub("-", text.lower()).strip("-")


def _photo(url: str | None) -> str | None:
    if not url:
        return None
    return url.replace("[size]", "640") + ".jpg" if "[size]" in url else url


def parse_tails(tails: list[dict[str, Any]], base_url: str) -> list[RawListing]:
    """Czysta funkcja: `Tails` z API -> ogłoszenia."""
    listings: list[RawListing] = []
    for t in tails:
        make_model = str(t["MakeModel"]).strip()
        brand, _, model = make_model.partition(" ")
        auction_id = t["AuctionId"]
        section = _SECTIONS.get(str(t.get("Status")), "samochody-poleasingowe")
        type_ = str(t.get("Type") or "").strip()
        lease = t.get("LeasePrice") or 0
        listings.append(
            RawListing(
                source="mauto",
                external_id=str(auction_id),
                url=f"{base_url}/{section}/{_slug(make_model)}-id-{auction_id}",
                title_raw=f"{make_model} {type_}".strip(),
                brand=brand.title(),
                model=model,
                fuel=_FUEL.get(str(t.get("FuelType")), t.get("FuelType")),
                year=parse_int(str(t.get("Year") or "")),
                mileage_km=t.get("Mileage"),
                price_gross_pln=t.get("FinalPriceBrutto") or None,
                price_net_pln=t.get("FinalPriceNetto") or None,
                monthly_installment_pln=lease or None,
                installment_basis="net" if lease else None,
                vat_invoice=True if t.get("FinalPriceNetto") else None,
                battery_kwh=parse_kwh(type_),
                range_km_wltp=t.get("VehicleRange") or None,
                image_url=_photo(t.get("MainPhotoUrl")),
            )
        )
    return listings


class MautoScraper(BaseScraper):
    source_id = "mauto"

    def _body(self, status: str, page: int) -> dict[str, Any]:
        return {
            "MakesAndModels": [], "MileageFrom": 0, "MileageTo": 0, "YearFrom": 0, "YearTo": 0,
            "BodyTypes": [], "FuelTypes": ["5"], "GearBoxTypes": [], "DoorsCount": [],
            "SeatsCount": [], "TotalPriceFrom": 0, "TotalPriceTo": 0, "InstallmentFrom": 0,
            "InstallmentTo": 0, "Locations": [], "PlateNumber": "", "HpFrom": 0, "HpTo": 0,
            "CapacityFrom": 0, "CapacityTo": 0, "Status": [status], "isPerfect": False,
            "SortType": 0, "ResultsPerPage": PAGE_SIZE, "Page": page, "isRent": False,
            "isLeasing": False, "isCash": False, "isCompany": True, "SpecialPromotions": [],
        }  # fmt: skip

    async def fetch(self) -> list[RawListing]:
        base = self.config.url.rstrip("/")
        headers = {"Origin": base, "Referer": base + "/"}
        results: list[RawListing] = []
        for endpoint, status in (("AfterLease", "Poleasingowy"), ("NewVehicles", "Nowy")):
            fetched = 0
            for page in range(1, self.config.max_pages + 1):
                data = await self.post_json(
                    f"{API}/Offers/{endpoint}", self._body(status, page), headers
                )
                tails = data.get("Tails") or []
                results.extend(parse_tails(tails, base))
                fetched += len(tails)
                if not tails or fetched >= int(data.get("Count", 0)):
                    break
        return results
