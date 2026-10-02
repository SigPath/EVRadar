"""Testy renderowania raportu na danych syntetycznych."""

from __future__ import annotations

from pathlib import Path

from evradar.config import load_models_config
from evradar.demo import synthetic_report_data
from evradar.models import DiffKind, Offer, OfferDiff
from evradar.report import build_alt_links, render_report, write_report


def test_alt_links_use_config_and_price_limit() -> None:
    alt = load_models_config().alternatives
    rows = dict(build_alt_links(alt, 130_000))
    links = dict(rows["Volkswagen ID.4"])
    assert links["Otomoto"].startswith("https://www.otomoto.pl/osobowe/volkswagen/id4?")
    assert "fuel_type%5D=electric" in links["Otomoto"]
    assert links["Otomoto"].endswith("%5D=130000")
    assert links["OLX"] == (
        "https://www.olx.pl/motoryzacja/samochody/volkswagen/q-id4/"
        "?search%5Bfilter_float_price%3Ato%5D=130000"
    )
    no_limit = dict(dict(build_alt_links(alt, None))["Volkswagen ID.4"])
    assert "price" not in no_limit["Otomoto"] and "price" not in no_limit["OLX"]


def test_render_alternatives_section() -> None:
    alt = load_models_config().alternatives
    html = render_report(
        synthetic_report_data(), alt_links=build_alt_links(alt, 130_000), alt_max_price=130_000
    )
    assert "Alternatywnie: Otomoto i OLX" in html
    assert "https://www.otomoto.pl/osobowe/tesla/y?" in html
    assert "Alternatywnie" not in render_report(synthetic_report_data())


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
