"""Opcjonalne powiadomienia Telegram: nowe oferty i awarie źródeł (włączane w models.yaml)."""

from __future__ import annotations

import os

import httpx
import structlog

from evradar.config import Notifications
from evradar.models import ReportData, SourceResult, SourceStatus

log = structlog.get_logger()

MAX_LISTED = 10


def build_message(data: ReportData) -> str:
    lines = [f"EV Radar: {len(data.new)} nowych ofert, {len(data.price_drops)} obniżek."]
    for diff in data.new[:MAX_LISTED]:
        o = diff.offer
        price = o.price_gross_pln or o.price_net_pln
        lines.append(f"• {o.brand} {o.model_matched} {o.year or ''} — {price or '?'} zł\n{o.url}")
    return "\n".join(lines)


def problem_sources(data: ReportData) -> list[SourceResult]:
    """Źródła z błędem lub z parserem, który przestał zwracać oferty."""
    bad = (SourceStatus.ERROR, SourceStatus.STALE)
    return [s for s in data.sources if s.status in bad]


def build_problem_message(data: ReportData) -> str:
    lines = [f"EV Radar: problem z {len(problem_sources(data))} źródłem/źródłami."]
    for s in problem_sources(data):
        reason = s.error or s.note or s.status.value
        lines.append(f"• {s.name or s.source} ({s.status.value}): {reason[:150]}")
    return "\n".join(lines)


def _send_telegram(cfg: Notifications, text: str) -> bool:
    """Token i chat_id wyłącznie ze zmiennych środowiskowych."""
    if cfg.channel != "telegram":
        log.warning("notify_channel_unsupported", channel=cfg.channel)
        return False
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("notify_missing_credentials")
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("notify_failed", error=type(exc).__name__)
        return False
    return True


def notify_new_offers(cfg: Notifications, data: ReportData) -> bool:
    """Wysyła wiadomość o nowych ofertach."""
    if not cfg.enabled or not data.new or data.run.dry_run:
        return False
    return _send_telegram(cfg, build_message(data))


def notify_source_problems(cfg: Notifications, data: ReportData) -> bool:
    """Wysyła alert, gdy któreś źródło zawiodło (niezależnie od nowych ofert)."""
    if not cfg.enabled or not problem_sources(data) or data.run.dry_run:
        return False
    return _send_telegram(cfg, build_problem_message(data))
