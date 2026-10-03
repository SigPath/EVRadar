"""Test offline adaptera mAuto (fixture = realne odpowiedzi API Offers/AfterLease i NewVehicles)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from evradar.config import load_models_config
from evradar.matching import ModelMatcher
from evradar.models import RawListing
from evradar.scrapers.mauto import parse_tails

FIXTURE = Path(__file__).parent / "fixtures" / "mauto" / "listing_page.json"
BASE = "https://mauto.pl"


def _load() -> list[RawListing]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_tails(data["after_lease"]["Tails"], BASE) + parse_tails(data["new"]["Tails"], BASE)


def test_parse_mauto() -> None:
    listings = _load()
    assert len(listings) >= 3
    for x in listings:
        assert x.url.startswith(BASE + "/") and "-id-" in x.url
        assert x.title_raw and x.price_gross_pln and x.price_net_pln and x.year
        assert x.price_net_pln < x.price_gross_pln
        assert x.fuel == "Elektryczny"


def test_known_leaf() -> None:
    leaf = next(x for x in _load() if x.external_id == "26900")
    assert leaf.url == "https://mauto.pl/samochody-poleasingowe/nissan-leaf-id-26900"
    assert (leaf.price_gross_pln, leaf.price_net_pln, leaf.year, leaf.mileage_km) == (
        84750,
        68902,
        2023,
        30192,
    )
    assert leaf.monthly_installment_pln == 668 and leaf.installment_basis == "net"
    assert leaf.battery_kwh == 40
    assert leaf.image_url and leaf.image_url.endswith("/640/DETAL_10_04_2026_12_15_121.jpg")


def test_new_tesla_matches_model_y() -> None:
    matcher = ModelMatcher(load_models_config().targets)
    tesla = next(x for x in _load() if x.brand == "Tesla")
    assert "/nowe-samochody/" in tesla.url
    match = matcher.match(tesla)
    assert match is not None and match.model == "Model Y"


def test_ioniq_6_is_not_matched_as_ioniq_5_and_kona_matches() -> None:
    matcher = ModelMatcher(load_models_config().targets)
    for x in _load():
        m = matcher.match(x)
        if "Ioni" in x.title_raw:
            if re.search(r"(?i)ioni[qc]\s*6", x.title_raw):
                assert m is None  # Ioniq 6 nie jest sledzony i nie moze przejsc jako Ioniq 5
            else:
                assert m is not None and m.model == "Ioniq 5"
        if x.model and x.model.startswith("Kona"):
            assert m is not None and m.model == "Kona Electric"
