"""Test offline adaptera Automarket (fixture = realny listing Tesla EV z automarket.pl)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import load_models_config
from evradar.matching import ModelMatcher
from evradar.scrapers.automarket import parse_listing
from evradar.scrapers.nuxt import extract_nuxt_data

FIXTURE = Path(__file__).parent / "fixtures" / "automarket" / "listing_page.html"


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_automarket() -> None:
    listings, total = parse_listing(_html())
    assert total >= len(listings) >= 3
    for x in listings:
        assert x.url.startswith("https://automarket.pl/oferta/tesla/")
        assert x.url.endswith("/leasing")
        assert x.title_raw and x.year and x.mileage_km is not None
        assert x.price_net_pln and x.price_gross_pln is None  # cena podana tylko netto
        assert x.monthly_installment_pln and x.installment_basis == "net"
        assert x.fuel == "Elektryczny"


def test_known_offer() -> None:
    by_id = {x.external_id: x for x in parse_listing(_html())[0]}
    y = by_id["T171126"]
    assert y.url == "https://automarket.pl/oferta/tesla/model-y/T171126/leasing"
    assert (y.year, y.mileage_km, y.price_net_pln, y.monthly_installment_pln) == (
        2023,
        30239,
        116178,
        2114,
    )
    assert y.location == "Warszawa"
    assert y.image_url and y.image_url.startswith("https://cdn.automarket.pl/")


def test_matching() -> None:
    matcher = ModelMatcher(load_models_config().targets)
    matches = [matcher.match(x) for x in parse_listing(_html())[0]]
    models = {m.model for m in matches if m is not None}
    assert models and models <= {"Model 3", "Model Y"}


def test_nuxt_decoder_handles_missing_data() -> None:
    with pytest.raises(ValueError):
        extract_nuxt_data("<html></html>")
