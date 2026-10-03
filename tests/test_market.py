"""Wycena ofert względem mediany rynku oraz znaczniki ulubionych/ukrytych w raporcie."""

from __future__ import annotations

from evradar.demo import synthetic_report_data
from evradar.models import Offer
from evradar.report import market_refs, render_report


def _offer(i: int, price: int | None, *, year: int | None = 2022, model: str = "Model 3") -> Offer:
    return Offer(
        offer_id=f"id{i}",
        source="otomoto",
        url=f"https://example.com/{i}",
        brand="Tesla",
        model_matched=model,
        title_raw="t",
        year=year,
        price_gross_pln=price,
    )


def test_market_median_by_year() -> None:
    offers = [_offer(i, p) for i, p in enumerate([100_000, 100_000, 100_000, 80_000, 120_000])]
    refs = market_refs(offers)
    assert refs["id3"].pct == -20.0 and refs["id3"].scope == "rocznik"
    assert refs["id4"].median == 100_000 and refs["id4"].n == 5


def test_market_falls_back_to_model_then_skips() -> None:
    offers = [_offer(i, 100_000 + i * 1000, year=2021 + i) for i in range(5)]
    assert {r.scope for r in market_refs(offers).values()} == {"model"}
    assert market_refs(offers[:3]) == {}


def test_market_ignores_missing_price() -> None:
    offers = [_offer(i, 100_000) for i in range(4)] + [_offer(9, None)]
    refs = market_refs(offers)
    assert "id9" not in refs and len(refs) == 4


def test_report_has_market_column_and_marks() -> None:
    html = render_report(synthetic_report_data())
    table = html.split('id="offers"')[1].split("</table>")[0]
    assert "Vs rynek" in html and 'data-act="fav"' in table and 'data-act="hide"' in table
    assert table.count("data-id=") == table.count("<tr data-id=")
    assert "evradar:marks" in html


def test_new_offers_use_the_same_table_rows_as_the_main_list() -> None:
    data = synthetic_report_data()
    assert data.new
    html = render_report(data)
    section = html.split("Nowe oferty")[1].split("<h2>")[0]
    assert '<table class="offers">' in section and "<article" not in html
    assert section.count("<tr data-id=") == len(data.new)
    assert 'data-act="fav"' in section and "Vs rynek" in section
