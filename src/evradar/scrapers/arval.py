"""Arval AutoSelect (autoselect.arval.pl, Arval / BNP Paribas) — publiczne API JSON frontu.

Źródło danych: `https://portalapi-prod.autoselect.cloud/api` (wykryte w bundlach frontu):
  * `GET /Announcements/17` — lista ofert portalu PL (portalId = 17), parametry
    `energies=Electric` (kod ze słownika `GET /Filters/17`; UWAGA: wartość z URL-a
    frontu „elektryczny" jest tłumaczona przez JS i API jej NIE rozumie), `page`, `pageSize`.
  * `GET /Filters/17` — słownik filtrów z licznikami (używany do diagnozy, nie do pobierania).
robots.txt frontu (`autoselect.arval.pl`) zabrania URL-i z parametrami (`/*?energies=*`
itd.), dlatego adapter odpytuje WYŁĄCZNIE host API, który nie ma pliku robots.txt —
ten sam wzorzec co mAuto i Stellantis.

Pułapka backendu (zweryfikowana 2026-10-20): parametr `purchaseOption` w żądaniu
`Announcements` po cichu KASUJE filtr `energies` (zwraca 351 ofert wszystkich paliw).
Dlatego pobieramy bez niego, a oferty `purchaseOption != "sale"` (przedłużony najem,
`salePrice*` = 0) odrzucamy w adapterze. Stan na 2026-10-20: wszystkie 32 EV Arvala
to `release` (przedłużony najem) — źródło wróci 0 ofert do czasu wystawienia EV na sprzedaż.

Ceny: `salePriceGross`/`salePriceNet` osobno (faktura VAT — `vat_invoice=True`).
Datum `createdAt` ma 7-cyfrową część ułamkową i sufiks `Z` — normalizowana przed parsowaniem.
Adresy ofert: gotowe `offerUrl` z API (front, bez parametrów).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from evradar.models import RawListing
from evradar.scrapers.base import BaseScraper

API = "https://portalapi-prod.autoselect.cloud/api"
PORTAL_ID = 17  # portal Arval Polska
PAGE_SIZE = 50
_FRACTION = re.compile(r"\.(\d{7,})Z$")


def _parse_dt(value: str | None) -> datetime | None:
    """`2026-10-20T07:31:40.8468737Z` -> datetime UTC (ułamek tniony do 6 cyfr)."""
    if not value:
        return None
    def cut(m: re.Match[str]) -> str:
        return "." + m.group(1)[:6] + "+00:00"
    normalized = _FRACTION.sub(cut, value.strip()).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def parse_announcements(payload: dict[str, Any]) -> list[RawListing]:
    """Czysta funkcja: odpowiedź `Announcements` -> ogłoszenia (bez filtrowania najmu)."""
    listings: list[RawListing] = []
    for c in payload.get("announcements", {}).get("announcements", []):
        details = c.get("details") or {}
        gross = c.get("salePriceGross") or 0
        net = c.get("salePriceNet") or 0
        make = str(c.get("make") or "").strip()
        model = str(c.get("model") or "").strip()
        trim = str(c.get("trim") or "").strip()
        listings.append(
            RawListing(
                source="arval",
                external_id=str(c.get("id") or "") or None,
                url=str(c.get("offerUrl") or ""),
                title_raw=" ".join(x for x in (make, model, trim) if x),
                brand=make or None,
                model=model or None,
                fuel=details.get("fuelTypeLabel"),
                year=details.get("registrationYear"),
                mileage_km=int(details["mileage"]) if details.get("mileage") else None,
                price_gross_pln=int(gross) if gross else None,
                price_net_pln=int(net) if net else None,
                vat_invoice=True if net else None,
                location=c.get("location"),
                image_url=c.get("mainImage"),
                listed_at=_parse_dt(c.get("createdAt")),
            )
        )
    return listings


class ArvalScraper(BaseScraper):
    source_id = "arval"

    async def fetch(self) -> list[RawListing]:
        total = None
        results: list[RawListing] = []
        for page in range(1, self.config.max_pages + 1):
            data = await self.get_json(
                f"{API}/Announcements/{PORTAL_ID}",
                {"energies": "Electric", "page": page, "pageSize": PAGE_SIZE},
            )
            announcements = parse_announcements(data)
            results.extend(a for a in announcements if a.price_gross_pln)  # tylko sprzedaż
            info = data.get("announcements", {})
            total = int(info.get("allAnnouncementsCount") or 0)
            if not announcements or (total and page * PAGE_SIZE >= total):
                break
        return results
