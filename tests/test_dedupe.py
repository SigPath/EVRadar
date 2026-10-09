"""Testy deduplikacji tego samego auta między źródłami."""

from __future__ import annotations

import pytest

from evradar import runner
from evradar.config import ModelsConfig, load_models_config
from evradar.matching import ModelMatcher
from evradar.models import RawListing, SourceResult, SourceStatus, utcnow
from evradar.report import render_report
from evradar.storage import Storage


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


def test_kept_offer_lists_all_other_sources(models: ModelsConfig) -> None:
    direct = result(models, "direct", [listing("direct", "1", 129_000)])
    agg1 = result(models, "agg1", [listing("agg1", "9", 129_000)])
    agg2 = result(models, "agg2", [listing("agg2", "7", 129_000)])
    runner.dedupe_across_sources([agg1, agg2, direct], {"direct": 100, "agg1": 200, "agg2": 210})
    (kept,) = direct.offers
    assert [(x.source, x.url) for x in kept.also_on] == [
        ("agg1", "https://agg1.pl/o/9"),
        ("agg2", "https://agg2.pl/o/7"),
    ]


def test_also_on_survives_database_roundtrip(models: ModelsConfig) -> None:
    direct = result(models, "direct", [listing("direct", "1", 129_000)])
    agg = result(models, "agg", [listing("agg", "9", 129_000)])
    runner.dedupe_across_sources([direct, agg], {"direct": 100, "agg": 200})
    db = Storage(":memory:")
    db.save_run(utcnow(), 0.1, [direct, agg], direct.offers, [])
    (stored,) = db.load_offers().values()
    assert [(x.source, x.url) for x in stored.also_on] == [("agg", "https://agg.pl/o/9")]

    html = render_report(db.load_report_data() or pytest.fail("brak danych"))
    assert 'data-source-all="direct|agg"' in html
    assert 'href="https://agg.pl/o/9"' in html and "To samo auto (VIN lub zgodne parametry)" in html


VIN_A = "VR7ARHPYERL009323"
VIN_B = "VR3F45GBTPY605063"


def with_vin(raw: RawListing, vin: str | None) -> RawListing:
    return RawListing.model_validate({**raw.model_dump(), "vin": vin})


def test_same_vin_is_grouped_despite_different_price_and_mileage(models: ModelsConfig) -> None:
    direct = result(
        models, "direct", [with_vin(listing("direct", "1", 129_000), VIN_A)]
    )
    agg = result(
        models,
        "agg",
        [with_vin(listing("agg", "9", 125_000, km=148_500, loc=None), VIN_A.lower())],
    )
    assert runner.dedupe_across_sources([agg, direct], {"direct": 100, "agg": 200}) == 1
    (kept,) = direct.offers
    assert [(x.source, x.price_gross_pln) for x in kept.also_on] == [("agg", 125_000)]
    assert not agg.offers


def test_vin_duplicate_is_marked_in_report_but_parameter_match_is_not(
    models: ModelsConfig,
) -> None:
    direct = result(models, "direct", [with_vin(listing("direct", "1", 129_000), VIN_A)])
    by_vin = result(models, "vin", [with_vin(listing("vin", "2", 125_000, km=148_500), VIN_A)])
    by_params = result(models, "params", [listing("params", "3", 129_000)])
    runner.dedupe_across_sources(
        [direct, by_vin, by_params], {"direct": 100, "vin": 200, "params": 300}
    )
    (kept,) = direct.offers
    assert [(x.source, x.vin_match) for x in kept.also_on] == [("vin", True), ("params", False)]

    db = Storage(":memory:")
    db.save_run(utcnow(), 0.1, [direct, by_vin, by_params], direct.offers, [])
    html = render_report(db.load_report_data() or pytest.fail("brak danych"))
    assert html.count('<small class="dup">Duplikat</small>') == 1


def test_different_vins_are_never_merged_even_with_equal_parameters(models: ModelsConfig) -> None:
    a = result(models, "a", [with_vin(listing("a", "1", 129_000), VIN_A)])
    b = result(models, "b", [with_vin(listing("b", "2", 129_000), VIN_B)])
    assert runner.dedupe_across_sources([a, b], {}) == 0


def test_offer_without_vin_merges_by_parameters_and_inherits_vin(models: ModelsConfig) -> None:
    a = result(models, "a", [listing("a", "1", 129_000)])
    b = result(models, "b", [with_vin(listing("b", "2", 129_000), VIN_A)])
    assert runner.dedupe_across_sources([a, b], {"a": 1, "b": 2}) == 1
    assert a.offers[0].vin == VIN_A


def test_invalid_vin_is_dropped() -> None:
    for bad in ("12345678901234567", "ABCDEFGHJKLMNPRST", "short", "VR7ARHPYERL00932O", None):
        assert RawListing(source="s", url="u", title_raw="t", vin=bad).vin is None
    assert RawListing(source="s", url="u", title_raw="t", vin=" vr7arhpyerl009323 ").vin == VIN_A


def test_vin_survives_database_roundtrip(models: ModelsConfig) -> None:
    offers = result(models, "direct", [with_vin(listing("direct", "1", 129_000), VIN_A)])
    db = Storage(":memory:")
    db.save_run(utcnow(), 0.1, [offers], offers.offers, [])
    (stored,) = db.load_offers().values()
    assert stored.vin == VIN_A
