"""Testy renderowania raportu na danych syntetycznych."""

from __future__ import annotations

from pathlib import Path

from evradar.demo import synthetic_report_data
from evradar.models import DiffKind, Offer, OfferDiff
from evradar.report import render_report, write_report


def test_render_contains_all_sections() -> None:
    html = render_report(synthetic_report_data())
    for marker in (
        "Status źródeł",
        "Nowe oferty",
        "Obniżki cen",
        "Wszystkie aktywne oferty",
        "Do weryfikacji",
        "Zniknęły od ostatniego skanu",
        "prefers-color-scheme",
        "@media print",
        "DO AKTUALIZACJI",
        "POMINIĘTE",
        "BŁĄD",
    ):
        assert marker in html
    assert "<link" not in html


def test_html_is_escaped() -> None:
    data = synthetic_report_data()
    evil = data.new[0].offer.model_copy(update={"title_raw": "<script>alert(1)</script>"})
    data = data.model_copy(update={"new": [OfferDiff(kind=DiffKind.NEW, offer=evil)]})
    html = render_report(data)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_uncertain_not_in_main_table() -> None:
    data = synthetic_report_data()
    html = render_report(data)
    uncertain: Offer = data.uncertain[0]
    table = html.split('id="offers"')[1].split("</table>")[0]
    assert uncertain.url not in table
    assert uncertain.url in html


def test_write_report(tmp_path: Path) -> None:
    path = write_report(synthetic_report_data(), tmp_path)
    assert path.name == "index.html"
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
