"""Automarket (automarket.pl, PKO Leasing) — Nuxt 3 SSR, dane z `__NUXT_DATA__`.

Źródło danych: strona listingu jest renderowana po stronie serwera, a pełne dane ofert są w
`<script id="__NUXT_DATA__">` (format devalue) -> `data.<klucz>.items[]` + `pagination`.

Parametry URL (zweryfikowane na żywo):
  * ścieżka `/samochody/uzywane/leasing/<marka>`  — marki z `config/models.yaml` (kia, hyundai, tesla)
  * `fuel_type=Elektryczny`                       — tylko elektryczne
  * `page=N`                                      — paginacja (29 ofert/stronę; `pagination.totalCount`)
Bez listy marek: `/samochody/uzywane/wszystkie?fuel_type=Elektryczny` (≈670 aut, ~23 stron).
robots.txt blokuje `*mrk=`, `*mod=`, `*_page=`, `*per_page=` — używamy wyłącznie `page=`.

Ceny: oferty dla firm (`isCompany=1`) — cena pojazdu (`cashVariant.installment`) jest NETTO
(strona: "Cena pojazdu: 116 178 zł netto", "Faktura VAT 23%"), rata (`dynamicVariant.installment`)
to rata leasingowa NETTO (36 mies., wkład 20%). Brak ceny brutto w danych — nie przeliczamy.
Link: `/oferta/<marka>/<model>/<sku>/leasing` (bierzemy dokładny href z kafelka).
Zdjęcia: CDN `cdn.automarket.pl/i/_/rs:fill:372:210/<ścieżka>.webp`.
"""

from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser

from evradar.models import RawListing
from evradar.scrapers.base import BaseScraper
from evradar.scrapers.nuxt import extract_nuxt_data

BASE = "https://automarket.pl"
IMG_CDN = "https://cdn.automarket.pl/i/_/rs:fill:372:210/"
_OFFER_HREF = re.compile(r"^/oferta/[^/]+/[^/]+/([^/?]+)/leasing")


def _listing_block(html: str) -> dict[str, Any]:
    root = extract_nuxt_data(html)
    for value in root["data"].values():
        if isinstance(value, dict) and "items" in value and "pagination" in value:
            block: dict[str, Any] = value
            return block
    raise ValueError("Brak bloku z ofertami w __NUXT_DATA__")


def parse_listing(html: str) -> tuple[list[RawListing], int]:
    """Czysta funkcja: HTML -> (ogłoszenia, `pagination.totalCount`)."""
    block = _listing_block(html)
    hrefs: dict[str, str] = {}
    for anchor in HTMLParser(html).css('a[href^="/oferta/"]'):
        href = (anchor.attributes.get("href") or "").replace("&#39;", "'")
        match = _OFFER_HREF.match(href)
        if match:
            hrefs.setdefault(match.group(1), href.split("?")[0])

    listings: list[RawListing] = []
    for it in block["items"]:
        sku = str(it["sku"])
        path = hrefs.get(sku)
        if path is None:
            continue
        cash = (it.get("cashVariant") or {}).get("installment")
        dyn = it.get("dynamicVariant") or {}
        rate = dyn.get("installment")
        gallery = it.get("mediaGallery") or []
        image = f"{IMG_CDN}{gallery[0]['url']}.webp" if gallery else None
        version = str(it.get("equipmentVersion") or "").strip()
        title = f"{it['name']} {version}".strip() if version not in ("", "-") else str(it["name"])
        net_company = bool(dyn.get("isCompany", 1))
        listings.append(
            RawListing(
                source="automarket",
                external_id=sku,
                url=f"{BASE}{path}",
                title_raw=title,
                brand=str(it["brand"]).title(),
                model=it.get("model"),
                fuel=it.get("fuelType"),
                year=it.get("productionYear"),
                mileage_km=it.get("course"),
                price_net_pln=round(cash) if cash and net_company else None,
                price_gross_pln=round(cash) if cash and not net_company else None,
                monthly_installment_pln=round(rate) if rate else None,
                installment_basis=("net" if net_company else "gross") if rate else None,
                vat_invoice=True if net_company else None,
                drivetrain=it.get("wheelDriveType"),
                location=it.get("locationCity"),
                image_url=image,
            )
        )
    return listings, int(block["pagination"].get("totalCount", len(listings)))


class AutomarketScraper(BaseScraper):
    source_id = "automarket"

    def _paths(self) -> list[str]:
        if self.brands:
            slugs = [b.lower().replace(" ", "-") for b in self.brands]
            return [f"/samochody/uzywane/leasing/{s}" for s in slugs]
        return ["/samochody/uzywane/wszystkie"]

    async def fetch(self) -> list[RawListing]:
        results: list[RawListing] = []
        seen: set[str] = set()
        for path in self._paths():
            collected = 0
            for page in range(1, self.config.max_pages + 1):
                params: dict[str, Any] = {"fuel_type": "Elektryczny", "is_company": 1}
                if page > 1:
                    params["page"] = page
                html = await self.get_text(f"{BASE}{path}", params)
                listings, total = parse_listing(html)
                collected += len(listings)
                results.extend(x for x in listings if x.external_id not in seen)
                seen.update(x.external_id or "" for x in listings)
                if not listings or collected >= total:
                    break
        return results
