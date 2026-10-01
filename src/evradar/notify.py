"""Opcjonalne powiadomienie Telegram, gdy liczba nowych ofert > 0 (włączane w models.yaml)."""

from __future__ import annotations

import os

import httpx
import structlog

from evradar.config import Notifications
from evradar.models import ReportData

log = structlog.get_logger()

MAX_LISTED = 10


def build_message(data: ReportData) -> str:
    lines = [f"EV Radar: {len(data.new)} nowych ofert, {len(data.price_drops)} obniżek."]
    for diff in data.new[:MAX_LISTED]:
        o = diff.offer
        price = o.price_gross_pln or o.price_net_pln
        lines.append(f"• {o.brand} {o.model_matched} {o.year or ''} — {price or '?'} zł\n{o.url}")
    return "\n".join(lines)


def notify_new_offers(cfg: Notifications, data: ReportData) -> bool:
    """Wysyła wiadomość; token i chat_id wyłącznie ze zmiennych środowiskowych."""
    if not cfg.enabled or not data.new or data.run.dry_run:
        return False
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
            json={
                "chat_id": chat_id,
                "text": build_message(data),
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("notify_failed", error=type(exc).__name__)
        return False
    return True
