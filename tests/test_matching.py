"""Testy dopasowania modeli, normalizacji i is_electric()."""

from __future__ import annotations

import pytest

from evradar.config import ModelTarget, load_models_config
from evradar.matching import ModelMatcher, Powertrain, is_electric, normalize
from evradar.models import RawListing


@pytest.fixture(scope="module")
def matcher() -> ModelMatcher:
    cfg = load_models_config()
    return ModelMatcher(cfg.targets, cfg.brand_aliases)


def listing(title: str, brand: str | None = None, fuel: str | None = None, **kw: str) -> RawListing:
    return RawListing(
        source="test", url="https://x.pl/1", title_raw=title, brand=brand, fuel=fuel, **kw
    )


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Volkswagen ID.5 Pro Performance", None),
        ("VOLKSWAGEN ID.5 77kWh 4Mot. GTX", "Volkswagen"),
        ("VW ID.5 GTX", None),
        ("Vw ID5 Pro", "VW"),
        ("ID 5 Pro", "Volkswagen"),
    ],
)
def test_vw_id5_matches(matcher: ModelMatcher, title: str, brand: str | None) -> None:
    m = matcher.match(listing(title, brand=brand, fuel="Elektryczny"))
    assert m is not None and (m.brand, m.model) == ("Volkswagen", "ID.5")


@pytest.mark.parametrize(
    ("title", "brand"),
    [
        ("Volkswagen ID.4 77kWh", None),
        ("VW ID.4 GTX", None),
        ("Vw ID4 Pro", "VW"),
        ("ID 4 Pure", "Volkswagen"),
    ],
)
def test_vw_id4_matches(matcher: ModelMatcher, title: str, brand: str | None) -> None:
    m = matcher.match(listing(title, brand=brand, fuel="Elektryczny"))
    assert m is not None and (m.brand, m.model) == ("Volkswagen", "ID.4")


def test_vw_other_models_rejected(matcher: ModelMatcher) -> None:
    assert matcher.match(listing("VW ID. Buzz", fuel="Elektryczny")) is None
    assert matcher.match(listing("Volkswagen Golf 1.5 TSI")) is None
    assert matcher.match(listing("BMW iX3 ID.5")) is None


@pytest.mark.parametrize(
    "title",
    ["Audi Q4 e-tron 40", "Audi Q4 Sportback e-tron 35", "AUDI Q4 etron 45 quattro", "Audi Q4 40"],
)
def test_audi_q4_matches(matcher: ModelMatcher, title: str) -> None:
    m = matcher.match(listing(title, fuel="Elektryczny"))
    assert m is not None and (m.brand, m.model) == ("Audi", "Q4 e-tron")
    assert matcher.match(listing("Audi Q5 40 TDI")) is None


@pytest.mark.parametrize(
    ("title", "brand", "model"),
    [
        ("VW ID.3 Pro", None, "ID.3"),
        ("Volkswagen ID.7 Tourer GTX", None, "ID.7"),
        ("Skoda Enyaq iV 85", None, "Enyaq"),
        ("Enyaq Coupe", "Škoda", "Enyaq"),
        ("Hyundai Ioniq 6 77 kWh", None, "Ioniq 6"),
        ("Kia EV6 GT", None, "EV6"),
        ("Kia EV3 Earth", None, "EV3"),
        ("Tesla Model S Plaid", None, "Model S"),
        ("Tesla X", "Tesla", "Model X"),
    ],
)
def test_added_models_match(
    matcher: ModelMatcher, title: str, brand: str | None, model: str
) -> None:
    m = matcher.match(listing(title, brand=brand, fuel="Elektryczny"))
    assert m is not None and m.model == model


def test_normalize() -> None:
    assert normalize("Kona Elektryczna") == "konaelektryczna"
    assert normalize("e-Niro") == normalize("e Niro") == "eniro"
    assert normalize("Łódź Żółć") == "lodzzolc"


def test_niro_hev_rejected(matcher: ModelMatcher) -> None:
    assert matcher.match(listing("Kia Niro 1.6 GDI HEV Business Line")) is None
    assert matcher.match(listing("Kia Niro", fuel="Hybryda")) is None
    assert matcher.match(listing("Kia Niro 1.6 Plug-in Hybrid 11 kWh")) is None


def test_niro_ev_and_eniro_pass(matcher: ModelMatcher) -> None:
    m = matcher.match(listing("Kia e-Niro 64 kWh Business Line"))
    assert m is not None and m.model == "e-Niro" and m.powertrain is Powertrain.ELECTRIC
    m2 = matcher.match(listing("Kia Niro EV 64kWh"))
    assert m2 is not None and m2.model in {"e-Niro", "Niro"}
    m3 = matcher.match(listing("Niro", brand="Kia", fuel="Elektryczny"))
    assert m3 is not None and m3.model == "Niro" and m3.powertrain is Powertrain.ELECTRIC


def test_niro_without_fuel_is_uncertain(matcher: ModelMatcher) -> None:
    m = matcher.match(listing("Kia Niro 2022 Business Line"))
    assert m is not None and m.powertrain is Powertrain.UNCERTAIN


def test_ioniq5_variants_same_model(matcher: ModelMatcher) -> None:
    a = matcher.match(listing("Hyundai IONIQ5 77 kWh"))
    b = matcher.match(listing("Hyundai Ioniq 5 Techniq"))
    c = matcher.match(listing("Ioniq5", brand="Hyundai"))
    assert a and b and c
    assert a.model == b.model == c.model == "Ioniq 5"


def test_tesla_model_3_performance(matcher: ModelMatcher) -> None:
    m = matcher.match(listing("Tesla Model 3 Performance AWD"))
    assert m is not None and m.model == "Model 3" and m.brand == "Tesla"
    y = matcher.match(listing("Model Y Long Range", brand="Tesla"))
    assert y is not None and y.model == "Model Y"


def test_other_brand_or_model_rejected(matcher: ModelMatcher) -> None:
    assert matcher.match(listing("Hyundai Ioniq 9 110 kWh")) is None
    assert matcher.match(listing("Tesla Cybertruck")) is None
    assert matcher.match(listing("BMW iX3")) is None
    assert matcher.match(listing("Kia EV9 GT-Line")) is None


def test_ev4_not_matched_inside_longer_token(matcher: ModelMatcher) -> None:
    assert matcher.match(listing("Kia EV400 special")) is None
    assert matcher.match(listing("Kia EV4 Earth 81 kWh")) is not None


def test_kona(matcher: ModelMatcher) -> None:
    assert matcher.match(listing("Hyundai Kona Electric 64 kWh")) is not None
    assert matcher.match(listing("Hyundai Kona 1.0 T-GDI")) is None
    assert matcher.match(listing("Hyundai Kona", fuel="Elektryczny")) is not None


def test_fuzzy_fallback() -> None:
    m = ModelMatcher([ModelTarget(brand="hyundai", model="Kona Electric")])
    res = m.match(listing("Hyundai Kona Electrik"))
    assert res is not None and res.via_fuzzy


@pytest.mark.parametrize(
    ("fuel", "title", "expected"),
    [
        ("Elektryczny", "Kia Niro", Powertrain.ELECTRIC),
        ("Hybryda", "Kia Niro 64 kWh", Powertrain.NOT_ELECTRIC),
        ("Benzyna", "Kia Niro", Powertrain.NOT_ELECTRIC),
        ("Elektryczny", "Kia Niro Hybrid", Powertrain.UNCERTAIN),
        (None, "Kia Niro 64 kWh", Powertrain.ELECTRIC),
        (None, "Kia Niro PHEV 11 kWh", Powertrain.NOT_ELECTRIC),
        (None, "Kia Niro", Powertrain.UNCERTAIN),
        (None, "Kia Niro Hybrid BEV", Powertrain.UNCERTAIN),
    ],
)
def test_is_electric(fuel: str | None, title: str, expected: Powertrain) -> None:
    assert is_electric(fuel, title) is expected
