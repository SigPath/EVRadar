"""Test offline adaptera Poleasingowe.pl (fixture = realny listing aukcji aut elektrycznych)."""

from __future__ import annotations

from pathlib import Path

from evradar.scrapers.poleasingowe import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "poleasingowe" / "listing_page.html"


def test_parse_poleasingowe() -> None:
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(listings) >= 3
    complete = [x for x in listings if x.price_net_pln and x.year and x.mileage_km is not None]
    assert len(complete) >= 3
    for x in listings:
        assert x.url.startswith(
            (
                "https://poleasingowe.pl/pl/auctions/details/",
                "https://aukcje.pkoleasing.pl/auctions/details/",
            )
        )
        assert "?" not in x.url
        assert x.title_raw and x.external_id
        assert x.price_gross_pln is None  # cena aukcyjna podana jako netto


def test_known_auction() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))}
    ev6 = by_id["523898"]
    assert ev6.title_raw == "KIA EV 6 SUV"
    assert (ev6.year, ev6.mileage_km, ev6.price_net_pln, ev6.fuel) == (
        2022,
        137696,
        65000,
        "Elektryczny",
    )
    assert ev6.location == "Tarczyn, Żytnia 2"
    assert ev6.image_url and ev6.image_url.startswith("https://poleasingowe.pl/images/")
