"""Test offline adaptera Otomoto (fixture = przycięty prawdziwy listing VW ID.4 do 130 tys.)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.scrapers.otomoto import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "otomoto" / "listing_page.html"


def test_parse_otomoto_listing() -> None:
    listings, total = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert total >= len(listings) >= 10
    for x in listings:
        assert x.url.startswith("https://www.otomoto.pl/osobowe/oferta/")
        assert x.title_raw and x.brand == "Volkswagen" and x.model == "ID.4"
        assert x.fuel == "Elektryczny"
        assert x.year and x.mileage_km is not None
        assert x.price_gross_pln or x.price_net_pln
        assert x.image_url and x.image_url.startswith("https://")


def test_known_gross_offer() -> None:
    listings, _ = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    by_id = {x.external_id: x for x in listings}
    x = by_id["6150822885"]
    assert x.title_raw == "Volkswagen ID.4 Pro Energy"
    assert (x.year, x.mileage_km, x.price_gross_pln, x.location) == (2026, 7700, 99000, "Słupca")
    assert x.price_net_pln is None and x.vat_invoice is None
    assert x.url == "https://www.otomoto.pl/osobowe/oferta/volkswagen-id4-ID6Ige0J.html"
    assert by_id["6150827453"].battery_kwh == 77


def test_company_offer_is_net_and_not_converted() -> None:
    listings, _ = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    x = {x.external_id: x for x in listings}["6150770501"]
    assert x.price_net_pln == 105999 and x.price_gross_pln is None and x.vat_invoice is True


def test_missing_next_data_raises() -> None:
    with pytest.raises(ValueError, match="__NEXT_DATA__"):
        parse_listing("<html><body>brak danych</body></html>")
