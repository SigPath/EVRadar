"""Alerty o awariach źródeł (Telegram) i baner awarii w raporcie."""

from __future__ import annotations

import httpx
import pytest

from evradar.config import Notifications
from evradar.demo import synthetic_report_data
from evradar.models import ReportData, RunInfo, SourceResult, SourceStatus
from evradar.notify import build_problem_message, notify_source_problems, problem_sources
from evradar.report import render_report


def _data(status: SourceStatus, *, dry_run: bool = False) -> ReportData:
    base = synthetic_report_data()
    source = SourceResult(source="x", name="Zepsute", status=status, error="Boom: 500")
    run = RunInfo(started_at=base.run.started_at, duration_s=1.0, dry_run=dry_run)
    return base.model_copy(update={"sources": [source], "run": run})


def test_problem_sources_lists_only_failures() -> None:
    assert problem_sources(_data(SourceStatus.OK)) == []
    assert problem_sources(_data(SourceStatus.SKIPPED)) == []
    broken = _data(SourceStatus.ERROR)
    assert [s.source for s in problem_sources(broken)] == ["x"]
    assert "Zepsute (ERROR): Boom: 500" in build_problem_message(broken)


def test_report_banner_only_with_problems() -> None:
    assert "Problem ze źródłami" not in render_report(_data(SourceStatus.OK))
    html = render_report(_data(SourceStatus.STALE))
    assert "Problem ze źródłami" in html and "<b>Zepsute</b> (brak ofert)" in html
    assert 'id="stale"' in html


def test_notify_problems(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        sent.append(str(kwargs["json"]))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    cfg = Notifications(enabled=True, channel="telegram")
    assert notify_source_problems(cfg, _data(SourceStatus.OK)) is False
    assert notify_source_problems(cfg, _data(SourceStatus.ERROR, dry_run=True)) is False
    assert notify_source_problems(Notifications(enabled=False), _data(SourceStatus.ERROR)) is False
    assert sent == []
    assert notify_source_problems(cfg, _data(SourceStatus.ERROR)) is True
    assert len(sent) == 1 and "Zepsute" in sent[0]
