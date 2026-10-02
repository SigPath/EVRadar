"""Test offline adaptera Autoplac (fixture = /tesla/model-3/elektryczny, strona 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.scrapers.autoplac import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "autoplac" / "listing_page.html"


def test_parse_autoplac_listing() -> None:
    listings, total = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert total == 114 and len(listings) == 24
    for x in listings:
        assert x.url.startswith("https://autoplac.pl/oferta/tesla/model-3/")
        assert x.brand == "Tesla" and x.model == "Model 3" and x.fuel == "Elektryczny"
        assert x.year and x.mileage_km is not None and x.price_gross_pln
        assert x.image_url and x.image_url.startswith("https://")


def test_known_offers() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))[0]}
    x = by_id["4741302"]
    assert (x.year, x.mileage_km, x.price_gross_pln, x.location) == (2021, 80370, 78000, "Warszawa")
    assert x.price_net_pln is None and x.vat_invoice is None
    vat = by_id["4743759"]
    assert (vat.price_gross_pln, vat.price_net_pln) == (129000, 104878)
    assert vat.vat_invoice is True and vat.location == "Tarnowskie Góry"
    assert vat.mileage_km == 148000


def test_missing_ng_state_raises() -> None:
    with pytest.raises(ValueError, match="ng-state"):
        parse_listing("<html><body>brak danych</body></html>")
