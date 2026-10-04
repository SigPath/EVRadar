"""Testy analiz (deprecjacja, czas ekspozycji), zasięgu WLTP z configu i VIN w adapterach."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from evradar.analysis import MIN_FIT_POINTS, days_listed, depreciation, exposure
from evradar.config import RangeRule
from evradar.matching import lookup_range_wltp
from evradar.models import Offer, normalize_vin
from evradar.report import depreciation_views
from evradar.scrapers import automarket, ayvens, stellantis

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 3, tzinfo=UTC)


def offer(year: int, km: int, price: int, idx: int = 0, **kw: object) -> Offer:
    return Offer(
        offer_id=f"{year}-{km}-{idx}",
        source="s",
        url="https://s.pl/o",
        brand="Tesla",
        model_matched="Model 3",
        title_raw="Tesla Model 3",
        year=year,
        mileage_km=km,
        price_gross_pln=price,
        first_seen_at=NOW - timedelta(days=10),
        last_seen_at=NOW,
        **kw,
    )


def synthetic() -> list[Offer]:
    """Cena = 200 000 - 15 000 * wiek - 4 000 * (km / 10 tys.) — dokładna zależność liniowa."""
    rows = [(2025, 5_000), (2024, 40_000), (2024, 20_000), (2023, 80_000), (2023, 30_000)]
    rows += [(2022, 90_000), (2022, 50_000), (2021, 120_000), (2021, 70_000), (2025, 15_000)]
    return [
        offer(y, km, 200_000 - 15_000 * (2026 - y) - 4_000 * km // 10_000, i)
        for i, (y, km) in enumerate(rows)
    ]


def test_depreciation_recovers_linear_coefficients() -> None:
    offers = synthetic()
    assert len(offers) >= MIN_FIT_POINTS
    (dep,) = depreciation(offers, 2026)
    assert dep.per_year_pln is not None and abs(dep.per_year_pln - 15_000) <= 1
    assert dep.per_10k_km_pln is not None and abs(dep.per_10k_km_pln - 4_000) <= 1
    assert dep.r2 is not None and dep.r2 > 0.999
    assert [r.year for r in dep.years] == [2025, 2024, 2023, 2022, 2021]
    assert dep.years[0].step_pct is None and dep.years[1].step_pct is not None
    assert dep.years[1].step_pct < 0


def test_depreciation_without_enough_points_has_no_fit() -> None:
    (dep,) = depreciation(synthetic()[:4], 2026)
    assert dep.per_year_pln is None and dep.per_10k_km_pln is None and dep.r2 is None
    assert dep.years  # tabela po rocznikach jest zawsze


def test_positive_coefficient_is_dropped_not_reported() -> None:
    # starsze auta droższe przy tym samym przebiegu -> wiek odrzucony, zostaje przebieg
    offers = [
        offer(2020 + i % 5, 10_000 + 20_000 * i, 150_000 - 5_000 * i - (i % 5) * 4_000, i)
        for i in range(10)
    ]
    (dep,) = depreciation(offers, 2026)
    assert dep.per_year_pln is None
    assert dep.per_10k_km_pln is not None and dep.per_10k_km_pln > 0


def test_depreciation_ignores_offers_without_year_mileage_or_price() -> None:
    incomplete = [
        Offer(
            offer_id="x", source="s", url="u", brand="Tesla", model_matched="Model 3",
            title_raw="t", year=None, mileage_km=1, price_gross_pln=1,
        ),
    ]  # fmt: skip
    assert depreciation(incomplete, 2026) == []


def test_scatter_view_renders_one_dot_per_offer() -> None:
    (view,) = depreciation_views(synthetic(), 2026)
    assert str(view.scatter).count("<circle") == len(synthetic())
    assert set(view.colors) == {2021, 2022, 2023, 2024, 2025}


def test_days_listed_prefers_listing_date_and_flags_it() -> None:
    plain = offer(2022, 1, 1)
    assert days_listed(plain, NOW) == (10, False)
    listed = offer(2022, 1, 1, listed_at=datetime(2026, 9, 3))  # data bez strefy = UTC
    assert days_listed(listed, NOW) == (30, True)
    assert days_listed(plain, NOW, until=NOW - timedelta(days=4)) == (6, False)


def test_exposure_medians_for_active_and_gone() -> None:
    a = [offer(2022, 1, 1, 1), offer(2022, 2, 1, 2, listed_at=NOW - timedelta(days=30))]
    (row,) = exposure(a, {"Tesla Model 3": [3, 5, 40]}, NOW)
    assert (row.active_n, row.active_median_days) == (2, 20)
    assert (row.gone_n, row.gone_median_days) == (3, 5)
    only_gone = exposure([], {"Kia EV6": [7]}, NOW)
    assert (only_gone[0].active_median_days, only_gone[0].gone_median_days) == (None, 7)


RULES = [
    RangeRule(brand="Hyundai", model="Kona Electric", km=484, kwh=64, year_to=2022),
    RangeRule(brand="Hyundai", model="Kona Electric", km=514, kwh=65.4, year_from=2023),
    RangeRule(brand="Tesla", model="Model 3", km=614, title="long range"),
]


def rng(
    year: int | None, kwh: float | None, title: str = "", model: str = "Kona Electric"
) -> int | None:
    brand = "Tesla" if model == "Model 3" else "Hyundai"
    return lookup_range_wltp(
        RULES, brand=brand, model=model, year=year, battery_kwh=kwh, title=title
    )


def test_range_lookup_matches_battery_and_year() -> None:
    assert rng(2021, 64.0) == 484
    assert rng(2021, 64.4) == 484  # tolerancja ±0,5 kWh
    assert rng(2024, 65.0) == 514
    assert rng(2024, 64.0) is None  # nowsza generacja nie dostaje zasięgu starszej


def test_range_lookup_never_guesses_missing_conditions() -> None:
    assert rng(2021, None) is None  # reguła wymaga kWh
    assert rng(None, 64.0) is None  # reguła wymaga roku
    assert rng(2021, 40.0) is None
    assert rng(2022, None, "Tesla Model 3 Long Range AWD", model="Model 3") == 614
    assert rng(2022, None, "Tesla Model 3", model="Model 3") is None


def test_vin_normalization() -> None:
    assert normalize_vin("vr7arhpyerl009323") == "VR7ARHPYERL009323"
    assert normalize_vin("VR7ARHPYERL00932") is None
    assert normalize_vin(None) is None


def test_adapters_extract_vin() -> None:
    hits = json.loads((FIXTURES / "stellantis" / "listing_page.json").read_text("utf-8"))["hits"]
    st = stellantis.parse_hits(hits)
    assert st and all(x.vin for x in st)

    am_html = (FIXTURES / "automarket" / "listing_page.html").read_text("utf-8")
    am, _ = automarket.parse_listing(am_html)
    by_id = {x.external_id: x.vin for x in am}
    assert by_id["T171126"] == "XP7YGCESXRB299472"
    assert by_id["T133559"] is None  # atrapa "11111111111111111" w danych źródła

    ay_html = (FIXTURES / "ayvens" / "listing_page.html").read_text("utf-8")
    ay = ayvens.parse_listing(ay_html, "https://usedcars.ayvens.com")
    assert "KNACR81EGP5074650" in {x.vin for x in ay}
