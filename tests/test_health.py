"""Testy: zdrowie źródeł, kopia bazy, trend mediany modelu, migracja kolumn i nowe pola raportu."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from evradar.config import load_models_config
from evradar.demo import synthetic_report_data
from evradar.health import source_verdict
from evradar.matching import ModelMatcher
from evradar.models import Offer, RawListing, SourceResult, SourceStatus, utcnow
from evradar.parsing import parse_soh
from evradar.report import render_report, trend_rows
from evradar.runner import build_offers
from evradar.storage import Storage, make_backup

T = "2026-10-01T10:00:00+00:00"
T3 = "2026-10-03T10:00:00+00:00"


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
    return build_offers([raw], ModelMatcher(models.targets), models, utcnow())[0]


def run(status: str, n: int) -> tuple[str, str, int]:
    return (T, status, n)


def test_verdict_detects_drop_and_failures() -> None:
    history = [run("OK", 100), run("OK", 110), run("OK", 105)]
    assert source_verdict([*history, run("OK", 100)]) == ("ok", 105)
    assert source_verdict([*history, run("OK", 20)])[0] == "drop"
    assert source_verdict([*history, run("ERROR", 0)])[0] == "error"
    assert source_verdict([*history, run("STALE", 0)])[0] == "stale"
    assert source_verdict([run("OK", 5)]) == ("ok", None)
    assert source_verdict([run("OK", 1), run("OK", 0)]) == ("ok", 1)


def test_source_history_keeps_last_runs() -> None:
    db = Storage(":memory:")
    for n in range(5):
        res = SourceResult(source="s", status=SourceStatus.OK, offers_count=n)
        db.save_run(utcnow(), 0.1, [res], [], [])
    assert [c for _, _, c in db.source_history(last_n=3)["s"]] == [2, 3, 4]


def test_parse_soh() -> None:
    assert parse_soh("Bateria SOH 96%, serwisowany") == 96
    assert parse_soh("stan baterii: 92 %") == 92
    assert parse_soh("98% SOH") == 98
    assert parse_soh("bateria 100% sprawna") is None
    assert parse_soh("SOH 12%") is None
    assert parse_soh(None) is None


def test_model_trend_needs_min_group_and_one_point_per_day() -> None:
    db = Storage(":memory:")
    offers = []
    for i, price in enumerate((100_000, 110_000, 120_000)):
        o = make_offer(price)
        o.offer_id = f"id{i}"
        offers.append(o)
    db.save_run(utcnow(), 0.1, [], offers, [])
    db.save_run(utcnow(), 0.1, [], offers, [])
    trend = db.load_model_trend()
    assert list(trend) == ["Tesla Model 3"]
    ((_, med, n),) = trend["Tesla Model 3"]
    assert (med, n) == (110_000, 3)

    db2 = Storage(":memory:")
    db2.save_run(utcnow(), 0.1, [], offers[:2], [])
    assert db2.load_model_trend() == {}


def test_trend_rows_change() -> None:
    rows = trend_rows({"Tesla Model 3": [(T, 100_000, 5), (T3, 90_000, 6)]})
    assert rows[0].change_pct == -10 and rows[0].latest == 90_000 and "<polyline" in rows[0].spark


def test_backup_rotation(tmp_path: Path) -> None:
    db = Storage(tmp_path / "evradar.db")
    db.save_run(utcnow(), 0.1, [], [make_offer(100_000)], [])
    for day in ("20260101", "20260102", "20260103"):
        make_backup(db, tmp_path / "backups", day=day, keep=2)
    names = sorted(p.name for p in (tmp_path / "backups").glob("*.db"))
    assert names == ["evradar-20260102.db", "evradar-20260103.db"]
    copy = Storage(tmp_path / "backups" / names[-1])
    assert len(copy.load_offers()) == 1


def test_old_database_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE offers (offer_id TEXT PRIMARY KEY, source TEXT NOT NULL, url TEXT NOT NULL, "
        "brand TEXT NOT NULL, model_matched TEXT NOT NULL, title_raw TEXT NOT NULL, year INTEGER, "
        "mileage_km INTEGER, price_gross_pln INTEGER, price_net_pln INTEGER, "
        "monthly_installment_pln INTEGER, installment_basis TEXT, vat_invoice INTEGER, "
        "battery_kwh REAL, range_km_wltp INTEGER, drivetrain TEXT, location TEXT, image_url TEXT, "
        "first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, "
        "uncertain_powertrain INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1)"
    )
    conn.commit()
    conn.close()
    db = Storage(path)
    offer = make_offer(100_000)
    offer.seller_type, offer.soh_pct = "dealer", 95
    offer.listed_at = datetime(2026, 9, 1, tzinfo=UTC)
    db.save_run(utcnow(), 0.1, [], [offer], [])
    stored = db.load_offers()[offer.offer_id]
    assert (stored.seller_type, stored.soh_pct, stored.listed_at) == (
        "dealer",
        95,
        datetime(2026, 9, 1, tzinfo=UTC),
    )


def test_report_has_ranges_compare_and_seller_badges() -> None:
    data = synthetic_report_data()
    target = next(o for o in data.active if not o.uncertain_powertrain)
    target.seller_type, target.soh_pct = "private", 94
    data.model_trend = {"Tesla Model 3": [(T, 100_000, 5), (T3, 95_000, 5)]}
    data.source_history = {
        data.sources[0].source: [(T, "OK", 100), ("2026-10-02T10:00:00+00:00", "OK", 10)]
    }
    html = render_report(data)
    for needle in ('id="r-price"', 'data-act="fav"', "SOH 94%"):
        assert needle in html
    assert 'data-value="Prywatna"' in html
    assert 'class="trend"' in html and "−5.0%" in html
    assert 'class="bars"' in html and "Podejrzany spadek" in html


def test_offers_of_removed_models_are_deactivated_quietly() -> None:
    db = Storage(":memory:")
    db.save_run(utcnow(), 0.1, [], [make_offer(100_000)], [])
    assert db.deactivate_untracked({("Tesla", "Model 3")}) == 0
    assert db.deactivate_untracked({("Kia", "EV6")}) == 1
    (stored,) = db.load_offers().values()
    assert stored.active is False


def test_trend_hides_models_without_active_offers() -> None:
    data = synthetic_report_data()
    data.model_trend = {"Tesla Model S": [(T, 100_000, 5), (T3, 95_000, 5)]}
    assert "Tesla Model S" not in render_report(data)

