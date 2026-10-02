"""Test offline adaptera FindCar (fixture = listing ?fuelTypes=electric&makes=volkswagen)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.scrapers.findcar import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "findcar" / "listing_page.html"


def test_parse_findcar_listing() -> None:
    listings, pages = parse_listing(FIXTURE.read_text(encoding="utf-8"), "volkswagen")
    assert pages == 8 and len(listings) == 15
    for x in listings:
        assert x.url.startswith("https://findcar.pl/oferty-dealerow/")
        assert x.brand == "Volkswagen" and x.fuel == "Elektryczny"
        assert x.year and x.mileage_km is not None and x.price_gross_pln
        assert x.price_net_pln is None  # serwis podaje tylko brutto


def test_known_offers() -> None:
    by_id = {
        x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"), None)[0]
    }
    id7 = by_id["043635979"]
    assert id7.title_raw == "Volkswagen ID.7 Pro S Plus 86kWh" and id7.model == "ID.7"
    assert (id7.year, id7.mileage_km, id7.price_gross_pln) == (2026, 5, 227700)
    assert id7.location == "Ząbki" and id7.battery_kwh == 86
    id4 = by_id["068059334"]
    assert (id4.model, id4.year, id4.mileage_km) == ("ID.4", 2023, 23000)
    assert id4.price_gross_pln == 145900
    assert id4.image_url and id4.image_url.startswith("https://")


def test_ignored_make_filter_raises() -> None:
    with pytest.raises(ValueError, match="Filtr marki"):
        parse_listing(FIXTURE.read_text(encoding="utf-8"), "tesla")


def test_missing_ng_state_raises() -> None:
    with pytest.raises(ValueError, match="ng-state"):
        parse_listing("<html><body>brak danych</body></html>")
