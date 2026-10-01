"""Test offline adaptera Cars&Care (fixture = 12 realnych ofert z API + słownik paliw)."""

from __future__ import annotations

import json
from pathlib import Path

from evradar.models import RawListing
from evradar.scrapers.carsandcare import parse_cars

FIXTURE = Path(__file__).parent / "fixtures" / "carsandcare" / "listing_page.json"


def _load() -> list[RawListing]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fuels = {f["id"]: f["name"] for f in data["fuels"]["results"]}
    return parse_cars(data["cars"]["results"], fuels, "https://carsandcare.pl/list")


def test_parse_carsandcare() -> None:
    listings = _load()
    assert len(listings) >= 3
    complete = [
        x for x in listings if x.price_gross_pln and x.price_net_pln and x.year and x.mileage_km
    ]
    assert len(complete) >= 3
    first = listings[0]
    assert first.url.startswith("https://carsandcare.pl/list#car-")
    assert first.title_raw and first.fuel


def test_net_and_gross_are_not_swapped() -> None:
    for x in _load():
        assert x.price_gross_pln is not None and x.price_net_pln is not None
        assert x.price_net_pln < x.price_gross_pln
        assert (
            abs(x.price_net_pln * 1.23 - x.price_gross_pln) < 2
        )  # VAT 23% (potwierdza netto/brutto)


def test_known_offer() -> None:
    by_id = {x.external_id: x for x in _load()}
    car = by_id["29663"]
    assert car.brand == "Skoda" and car.model == "Superb Combi"
    assert (car.price_net_pln, car.price_gross_pln, car.year, car.mileage_km) == (
        60081,
        73900,
        2022,
        171113,
    )
    assert car.fuel == "diesel"
