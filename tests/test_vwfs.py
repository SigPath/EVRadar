"""Test offline adaptera VWFS (fixture = zapisany realny listing /oferty?rodzajPaliwa=5)."""

from __future__ import annotations

from pathlib import Path

from evradar.scrapers.vwfs import parse_offers

FIXTURE = Path(__file__).parent / "fixtures" / "vwfs" / "listing_page.html"


def test_parse_vwfs_listing() -> None:
    listings, total = parse_offers(FIXTURE.read_text(encoding="utf-8"))
    assert total >= len(listings) >= 3
    complete = [
        x
        for x in listings
        if x.price_gross_pln and x.price_net_pln and x.year and x.mileage_km is not None
    ]
    assert len(complete) >= 3
    first = listings[0]
    assert first.url.startswith("https://store.vwfs.pl/oferta/") and "-id-" in first.url
    assert first.title_raw and first.fuel == "Elektryczny"
    assert first.price_net_pln is not None and first.price_gross_pln is not None
    assert first.price_net_pln < first.price_gross_pln
    assert first.image_url and first.image_url.startswith("https://")


def test_known_offer_values() -> None:
    listings, _ = parse_offers(FIXTURE.read_text(encoding="utf-8"))
    by_id = {x.external_id: x for x in listings}
    q4 = by_id["92984"]
    assert q4.brand == "Audi" and q4.model == "Q4 e-tron"
    assert (q4.year, q4.mileage_km, q4.price_gross_pln) == (2024, 70266, 162900)
    assert q4.price_net_pln == 132439
    assert q4.monthly_installment_pln == 2621 and q4.installment_basis == "net"
    assert q4.battery_kwh == 82
    assert q4.url == "https://store.vwfs.pl/oferta/audi-q4-e-tron-id-92984"
