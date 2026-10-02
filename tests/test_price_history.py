"""Testy historii cen: odczyt z bazy i miniaturowy wykres (sparkline) w raporcie."""

from __future__ import annotations

from evradar import runner
from evradar.config import load_models_config
from evradar.demo import synthetic_report_data
from evradar.matching import ModelMatcher
from evradar.models import Offer, RawListing, utcnow
from evradar.report import _sparkline, render_report
from evradar.storage import Storage


def make_offer(price: int) -> Offer:
    models = load_models_config()
    models.filters.max_price_gross_pln = None
    models.filters.min_price_gross_pln = None
    models.filters.max_mileage_km = None
    models.filters.min_year = None
    raw = RawListing(
        source="s",
        url="https://s.pl/o/1",
        external_id="1",
        title_raw="Tesla Model 3 Long Range",
        brand="Tesla",
        fuel="Elektryczny",
        year=2022,
        mileage_km=40_000,
        price_gross_pln=price,
    )
    return runner.build_offers([raw], ModelMatcher(models.targets), models, utcnow())[0]


def test_load_price_history_keeps_only_changes() -> None:
    db = Storage(":memory:")
    for price in (130_000, 125_000, 125_000, 120_000):
        db.save_run(utcnow(), 0.1, [], [make_offer(price)], [])
    history = db.load_price_history()
    assert len(history) == 1
    (points,) = history.values()
    assert [p for _, p in points] == [130_000, 125_000, 120_000]


def test_offer_without_price_change_has_no_history() -> None:
    db = Storage(":memory:")
    for _ in range(3):
        db.save_run(utcnow(), 0.1, [], [make_offer(100_000)], [])
    assert db.load_price_history() == {}


T1, T2 = "2026-10-01T10:00:00+00:00", "2026-10-03T10:00:00+00:00"


def test_sparkline_direction_and_label() -> None:
    down = str(_sparkline([(T1, 130_000), (T2, 120_000)]))
    assert 'class="spark down"' in down and "-8%" in down and "<polyline" in down
    up = str(_sparkline([(T1, 100_000), (T2, 110_000)]))
    assert 'class="spark up"' in up
    same_time = str(_sparkline([(T1, 100_000), (T1, 90_000)]))
    assert "<polyline" in same_time
    assert str(_sparkline([(T1, 100_000)])) == ""


def test_report_shows_sparkline_only_for_changed_offers() -> None:
    data = synthetic_report_data()
    target = next(o for o in data.active if not o.uncertain_powertrain)
    assert 'class="spark' not in render_report(data)
    data.price_history = {target.offer_id: [(T1, 130_000), (T2, 120_000)]}
    html = render_report(data)
    assert html.count('<svg class="spark down"') == 1
