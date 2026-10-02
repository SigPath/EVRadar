"""Testy deduplikacji tego samego auta między źródłami."""

from __future__ import annotations

import pytest

from evradar import runner
from evradar.config import ModelsConfig, load_models_config
from evradar.matching import ModelMatcher
from evradar.models import RawListing, SourceResult, SourceStatus, utcnow


@pytest.fixture
def models() -> ModelsConfig:
    cfg = load_models_config()
    cfg.filters.max_price_gross_pln = None
    cfg.filters.min_price_gross_pln = None
    cfg.filters.max_mileage_km = None
    cfg.filters.min_year = None
    return cfg


def listing(
    source: str, ident: str, price: int, km: int | None = 148_000, loc: str | None = "Gdańsk"
) -> RawListing:
    return RawListing(
        source=source,
        url=f"https://{source}.pl/o/{ident}",
        external_id=ident,
        title_raw="Tesla Model 3 Long Range",
        brand="Tesla",
        fuel="Elektryczny",
        year=2021,
        mileage_km=km,
        price_gross_pln=price,
        location=loc,
    )


def result(models: ModelsConfig, source: str, raws: list[RawListing]) -> SourceResult:
    offers = runner.build_offers(raws, ModelMatcher(models.targets), models, utcnow())
    return SourceResult(
        source=source,
        name=source,
        status=SourceStatus.OK,
        offers=offers,
        offers_count=len(offers),
        raw_count=len(raws),
    )


def test_duplicate_removed_from_lower_priority_source(models: ModelsConfig) -> None:
    direct = result(models, "direct", [listing("direct", "1", 129_000)])
    agg = result(
        models, "agg", [listing("agg", "9", 129_000), listing("agg", "10", 120_000, km=90_000)]
    )
    removed = runner.dedupe_across_sources([agg, direct], {"direct": 100, "agg": 200})
    assert removed == 1
    assert [o.url for o in direct.offers] == ["https://direct.pl/o/1"]
    assert [o.url for o in agg.offers] == ["https://agg.pl/o/10"]
    assert agg.offers_count == 1 and agg.note and "duplikat" in agg.note
    assert direct.note is None


def test_different_price_or_mileage_is_not_duplicate(models: ModelsConfig) -> None:
    a = result(models, "a", [listing("a", "1", 129_000)])
    b = result(
        models, "b", [listing("b", "2", 128_000), listing("b", "3", 129_000, km=148_001)]
    )
    assert runner.dedupe_across_sources([a, b], {}) == 0
    assert len(a.offers) == 1 and len(b.offers) == 2


def test_missing_data_is_never_merged(models: ModelsConfig) -> None:
    a = result(models, "a", [listing("a", "1", 100_000, km=None)])
    b = result(models, "b", [listing("b", "2", 100_000, km=None)])
    assert runner.dedupe_across_sources([a, b], {}) == 0


def test_nearly_new_cars_need_same_city(models: ModelsConfig) -> None:
    a = result(models, "a", [listing("a", "1", 120_000, km=5, loc="Poznań")])
    b = result(models, "b", [listing("b", "2", 120_000, km=5, loc="Radom")])
    c = result(models, "c", [listing("c", "3", 120_000, km=5, loc="poznań")])
    d = result(models, "d", [listing("d", "4", 120_000, km=5, loc=None)])
    assert runner.dedupe_across_sources([a, b, c, d], {"a": 1, "b": 2, "c": 3, "d": 4}) == 1
    assert (len(a.offers), len(b.offers), len(c.offers), len(d.offers)) == (1, 1, 0, 1)


def test_failed_source_is_ignored(models: ModelsConfig) -> None:
    ok = result(models, "ok", [listing("ok", "1", 129_000)])
    bad = result(models, "bad", [listing("bad", "2", 129_000)])
    bad.status = SourceStatus.ERROR
    assert runner.dedupe_across_sources([ok, bad], {}) == 0
    assert len(bad.offers) == 1
