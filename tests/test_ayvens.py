"""Test offline adaptera Ayvens (fixture = realne kafelki z usedcars.ayvens.com)."""

from __future__ import annotations

from pathlib import Path

from evradar.config import load_models_config
from evradar.matching import ModelMatcher
from evradar.scrapers.ayvens import parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "ayvens" / "listing_page.html"
BASE = "https://usedcars.ayvens.com"


def test_parse_ayvens() -> None:
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"), BASE)
    assert len(listings) >= 3
    for x in listings:
        assert x.url.startswith(BASE + "/pl-pl/") and x.url.endswith(".html")
        assert x.title_raw and x.price_gross_pln and x.year and x.mileage_km
        assert x.external_id


def test_tesla_values() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"), BASE)}
    tesla = by_id["2961312-pl-tesla-model3"]
    assert tesla.brand == "Tesla" and tesla.fuel == "Electric"
    assert (tesla.price_gross_pln, tesla.year, tesla.mileage_km) == (124899, 2024, 150757)
    assert tesla.title_raw == "Tesla Model 3 Long Range"
    assert tesla.image_url and tesla.image_url.startswith("https://")


def test_matching_on_real_tiles() -> None:
    matcher = ModelMatcher(load_models_config().targets)
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"), BASE)
    matched = {x.external_id: matcher.match(x) for x in listings}
    tesla = matched["2961312-pl-tesla-model3"]
    assert tesla is not None and tesla.model == "Model 3"
    assert matched["2764891-pl-kia-niro"] is None  # Niro Hybrid musi odpaść
    assert matched["2633889-pl-hyundai-tucson"] is None
