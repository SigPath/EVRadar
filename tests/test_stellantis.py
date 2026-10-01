"""Test offline adaptera Stellantis &You (fixture = realne trafienia Algolii)."""

from __future__ import annotations

import json
from pathlib import Path

from evradar.scrapers.stellantis import parse_hits

FIXTURE = Path(__file__).parent / "fixtures" / "stellantis" / "listing_page.json"


def _hits() -> list[dict[str, object]]:
    hits: list[dict[str, object]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["hits"]
    return hits


def test_parse_stellantis() -> None:
    listings = parse_hits(_hits())
    assert len(listings) >= 3
    for x in listings:
        assert x.url.startswith("https://www.stellantisandyou.com/pl/samochody/pojazd.")
        assert x.title_raw and x.price_gross_pln and x.year and x.mileage_km is not None
        assert x.price_net_pln is None  # strona podaje wyłącznie brutto
        assert x.installment_basis == "gross"


def test_known_offer() -> None:
    by_id = {x.external_id: x for x in parse_hits(_hits())}
    c5 = by_id["99972"]
    assert c5.brand == "Citroen" and c5.model == "C5 AIRCROSS"
    assert (c5.price_gross_pln, c5.year, c5.mileage_km, c5.monthly_installment_pln) == (
        93900,
        2024,
        28433,
        1302,
    )
    assert c5.fuel == "Benzyna" and c5.location == "Warszawa"
