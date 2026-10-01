"""Smoke testy CLI (bez sieci)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from typer.testing import CliRunner

from evradar import cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(cli, "DB_PATH", tmp_path / "db" / "evradar.db")
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path / "out")
    yield
    structlog.reset_defaults()  # CLI konfiguruje logger na strumieniu CliRunnera


def test_demo_report(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["demo-report", "--no-open"])
    assert result.exit_code == 0
    assert list((tmp_path / "out" / "demo").glob("report-*.html"))


def test_report_on_empty_db_fails_gracefully() -> None:
    result = runner.invoke(cli.app, ["report", "--no-open"])
    assert result.exit_code == 1


def test_sources_lists_configured_sources() -> None:
    result = runner.invoke(cli.app, ["sources"])
    assert result.exit_code == 0
    for source_id in ("vwfs", "stellantis", "poleasingowe"):
        assert source_id in result.output
    assert "spoticar" not in result.output
    assert "leasygroup" not in result.output


def test_unknown_source_is_rejected() -> None:
    result = runner.invoke(cli.app, ["run", "--source", "nie-ma", "--no-open", "--dry-run"])
    assert result.exit_code != 0
