"""Test offline adaptera Arval AutoSelect (fixtures = realne odpowiedzi API)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evradar.config import SourceConfig
from evradar.scrapers.arval import ArvalScraper, _parse_dt, parse_announcements

FIXTURES = Path(__file__).parent / "fixtures" / "arval"
OFFER_URL = "https://autoselect.arval.pl/uzywane-samochody/oferta/"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def test_parse_strona_ev() -> None:
    """Strona `energies=Electric`: 32 oferty, wszystkie elektryczne, URL-e ofert z frontu."""
    listings = parse_announcements(_load("ev_page.json"))
    assert len(listings) == 32
    assert all(x.fuel == "Elektryczny" for x in listings)
    assert all(x.url.startswith(OFFER_URL) for x in listings)
    assert all("?" not in x.url and x.external_id for x in listings)
    assert sum(1 for x in listings if x.year and x.mileage_km) >= 30
    # wszystkie EV w tym stanie portalu to przedluzony najem: cena sprzedazy = 0 -> None
    assert all(x.price_gross_pln is None and x.price_net_pln is None for x in listings)


def test_parse_znana_oferta_ev() -> None:
    by_id = {x.external_id: x for x in parse_announcements(_load("ev_page.json"))}
    ev6 = by_id["154143"]
    assert ev6.brand == "Kia" and ev6.model == "EV6"
    assert (ev6.year, ev6.mileage_km) == (2024, 30088)
    assert "kia-ev6" in ev6.url
    assert ev6.image_url and ev6.image_url.startswith("https://")
    assert ev6.listed_at is not None and ev6.listed_at.year == 2026


def test_parse_strona_sprzedazowa_ceny() -> None:
    """Realna strona ofert sprzedazowych: ceny brutto+netto, faktura VAT, data dodania."""
    listings = parse_announcements(_load("sale_page.json"))
    priced = [x for x in listings if x.price_gross_pln and x.price_net_pln]
    assert len(priced) >= 3
    assert all(x.vat_invoice for x in priced)
    camry = next(x for x in listings if x.model == "Camry")
    assert (camry.price_gross_pln, camry.price_net_pln) == (89900, 73089)
    assert (camry.year, camry.mileage_km, camry.fuel) == (2022, 149570, "Hybryda")


def test_parse_dt_siedmiocyfrowy_ulamek() -> None:
    assert _parse_dt("2026-10-20T07:31:40.8468737Z") is not None
    assert _parse_dt("2026-10-20T07:31:40.8468737Z").microsecond == 846873  # type: ignore[union-attr]
    assert _parse_dt(None) is None
    assert _parse_dt("smietnik") is None


def _payload(cars: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"announcements": {"announcements": cars, "allAnnouncementsCount": total}}


def _car(id_: int, price: float, fuel: str = "Elektryczny") -> dict[str, Any]:
    return {
        "id": id_,
        "make": "Kia",
        "model": "EV6",
        "trim": "77.4kWh 325km AWD GT-Line 5d",
        "offerUrl": f"https://autoselect.arval.pl/uzywane-samochody/oferta/kia-ev6-{id_}",
        "purchaseOption": "sale" if price else "release",
        "salePriceGross": price,
        "salePriceNet": round(price / 1.23),
        "location": "Krze Duże",
        "mainImage": None,
        "createdAt": "2026-10-20T07:31:40.8468737Z",
        "details": {
            "fuelTypeLabel": fuel,
            "registrationYear": 2024,
            "mileage": 30088.0,
        },
    }


def _scraper(monkeypatch: pytest.MonkeyPatch, pages: list[dict[str, Any]]) -> ArvalScraper:
    calls: list[dict[str, Any]] = []

    async def fake_get_json(
        self: ArvalScraper, url: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        calls.append(dict(params or {}))
        return pages[len(calls) - 1]

    monkeypatch.setattr(ArvalScraper, "get_json", fake_get_json)
    cfg = SourceConfig(
        id="arval", name="Arval AutoSelect", url="https://autoselect.arval.pl", max_pages=3
    )
    scraper = ArvalScraper(cfg)
    scraper._calls = calls  # type: ignore[attr-defined]
    return scraper


async def test_fetch_pomija_najem_i_filtruje_sale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Oferty bez ceny (przedluzony najem, salePrice=0) nie moga trafic do raportu."""
    scraper = _scraper(
        monkeypatch, [_payload([_car(1, 89900.0), _car(2, 0.0), _car(3, 124600.0)], 3)]
    )
    results = await scraper.fetch()
    assert [x.external_id for x in results] == ["1", "3"]
    assert all(x.price_gross_pln for x in results)
    assert len(scraper._calls) == 1  # type: ignore[attr-defined]


async def test_fetch_parametry_i_paginacja(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zapytanie musi uzywac kodu `Electric` (nie „elektryczny") i kierowac strony."""
    scraper = _scraper(
        monkeypatch,
        [_payload([_car(i, 89900.0) for i in range(50)], 60), _payload([_car(99, 89900.0)], 60)],
    )
    results = await scraper.fetch()
    assert len(results) == 51
    calls = scraper._calls  # type: ignore[attr-defined]
    assert calls[0]["energies"] == "Electric"
    assert calls[1]["page"] == 2
