"""Test offline adaptera Spoticar (fixture = realny listing aut elektrycznych, 12 kafelków)."""

from __future__ import annotations

from pathlib import Path

from evradar.scrapers.spoticar import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "spoticar" / "listing_page.html"


def test_parse_spoticar() -> None:
    listings, total = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert total >= len(listings) >= 3
    for x in listings:
        assert x.url.startswith("https://www.spoticar.pl/znajdz-uzywany-samochod/")
        assert x.title_raw and x.external_id
        assert x.price_gross_pln and x.year and x.mileage_km is not None
        assert x.price_net_pln is None  # serwis podaje tylko brutto
        assert x.fuel == "Elektryczny"


def test_known_offer() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))[0]}
    fiat = by_id["71805"]
    assert fiat.title_raw == "Fiat 600 e 56kWh RED"
    assert (fiat.year, fiat.mileage_km, fiat.price_gross_pln) == (2024, 1000, 169990)
    assert fiat.monthly_installment_pln == 2421 and fiat.installment_basis == "gross"
    assert fiat.drivetrain == "Automatyczna"
    assert fiat.image_url and fiat.image_url.startswith("https://s3.eu-central-1.amazonaws.com/")
