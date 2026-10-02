"""Testy filtra ofert po treści (cesja leasingu, przejęcie leasingu, rata)."""

from __future__ import annotations

import pytest

from evradar import runner
from evradar.config import ModelsConfig, load_models_config
from evradar.matching import ModelMatcher, text_excluded
from evradar.models import RawListing, utcnow


@pytest.fixture
def models() -> ModelsConfig:
    cfg = load_models_config()
    cfg.filters.max_price_gross_pln = None
    cfg.filters.min_price_gross_pln = None
    cfg.filters.max_mileage_km = None
    cfg.filters.min_year = None
    return cfg


@pytest.mark.parametrize(
    "text",
    [
        "Tesla Model 3 CESJA LEASINGU",
        "Cesji leasingu, rata 1500",
        "Przejęcie leasingu, niski wkład",
        "przejecie umowy leasingu Tesla",
        "Rata 1 500 zł netto",
        "RATA MIESIĘCZNA: 1450 zł",
        "rata od 999 zł",
    ],
)
def test_excluded_phrases(models: ModelsConfig, text: str) -> None:
    assert text_excluded(models.filters.exclude_text_patterns, text)


@pytest.mark.parametrize(
    "text",
    [
        "Tesla Model 3 Long Range, bezwypadkowa, salon PL",
        "Możliwość zakupu na raty 0% lub w leasingu",
        "Auto z leasingu, faktura VAT 23%",
        "Ostatnia rata kredytu spłacona",
        "Kia Niro 64kWh, pierwsza rejestracja 2021",
    ],
)
def test_normal_ads_are_kept(models: ModelsConfig, text: str) -> None:
    assert not text_excluded(models.filters.exclude_text_patterns, text)


def listing(title: str, description: str | None = None, price: int = 55_000) -> RawListing:
    return RawListing(
        source="s",
        url=f"https://s.pl/{abs(hash(title))}",
        external_id=str(abs(hash(title))),
        title_raw=title,
        description=description,
        brand="Tesla",
        fuel="Elektryczny",
        year=2022,
        mileage_km=40_000,
        price_gross_pln=price,
    )


def test_build_offers_drops_lease_takeovers_but_keeps_cheap_normal_cars(
    models: ModelsConfig,
) -> None:
    raws = [
        listing("Tesla Model 3 Long Range"),
        listing("Tesla Model 3 Performance", "Cesja leasingu, rata 1500 zł"),
        listing("Tesla Model 3 RWD", "Przejęcie leasingu 36 mies."),
    ]
    offers = runner.build_offers(raws, ModelMatcher(models.targets), models, utcnow())
    assert [o.title_raw for o in offers] == ["Tesla Model 3 Long Range"]
    assert offers[0].price_gross_pln == 55_000
