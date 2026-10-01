"""Respektowanie robots.txt (urllib.robotparser + reguły z wildcardami) z cache'em per origin."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import structlog

log = structlog.get_logger()

ROBOTS_USER_AGENT = "*"

RobotsFetch = Callable[[str], Awaitable[tuple[int, str]]]


class RobotsDisallowed(Exception):
    """Ścieżka zabroniona przez robots.txt (lub robots.txt niedostępny z 401/403)."""


@dataclass(frozen=True)
class _Rule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]


def _compile(pattern: str) -> re.Pattern[str]:
    body = re.escape(pattern).replace(r"\*", ".*")
    if body.endswith(r"\$"):
        body = body[:-2] + "$"
    return re.compile(body)


def parse_wildcard_rules(text: str) -> list[_Rule]:
    """Reguły grupy `User-agent: *` zawierające `*` lub `$` (stdlib ich nie obsługuje)."""
    rules: list[_Rule] = []
    in_star = False
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            in_star = (in_star or value == "*") if last_was_agent else (value == "*")
            last_was_agent = True
            continue
        last_was_agent = False
        if in_star and key in ("allow", "disallow") and value and ("*" in value or "$" in value):
            rules.append(_Rule(key == "allow", value, _compile(value)))
    return rules


def wildcard_blocked(rules: list[_Rule], path_and_query: str) -> bool:
    """Najdłuższa pasująca reguła wygrywa; remis rozstrzyga Allow."""
    best: _Rule | None = None
    for rule in rules:
        if rule.regex.match(path_and_query) and (
            best is None
            or len(rule.pattern) > len(best.pattern)
            or (len(rule.pattern) == len(best.pattern) and rule.allow)
        ):
            best = rule
    return best is not None and not best.allow


class RobotsGuard:
    """Pobiera i interpretuje robots.txt; nie próbuje niczego obchodzić."""

    def __init__(self, client: httpx.AsyncClient, fetch: RobotsFetch | None = None) -> None:
        self._client = client
        self._fetch = fetch or self._fetch_httpx
        self._parsers: dict[str, tuple[RobotFileParser, list[_Rule]] | None] = {}

    async def _fetch_httpx(self, url: str) -> tuple[int, str]:
        resp = await self._client.get(url)
        return resp.status_code, resp.text

    async def _load(self, origin: str) -> tuple[RobotFileParser, list[_Rule]] | None:
        """None = brak robots.txt (404 itp.) lub błąd sieci — wtedy brak ograniczeń."""
        parser = RobotFileParser()
        try:
            status, text = await self._fetch(f"{origin}/robots.txt")
        except Exception as exc:
            log.warning("robots_unreachable", origin=origin, error=str(exc))
            return None
        if status in (401, 403):
            parser.parse(["User-agent: *", "Disallow: /"])  # jak RobotFileParser.read()
            return parser, []
        if status >= 400:
            return None
        parser.parse(text.splitlines())
        return parser, parse_wildcard_rules(text)

    async def ensure_allowed(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = await self._load(origin)
        loaded = self._parsers[origin]
        if loaded is None:
            return
        parser, rules = loaded
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        if not parser.can_fetch(ROBOTS_USER_AGENT, url) or wildcard_blocked(rules, target):
            raise RobotsDisallowed(f"robots.txt zabrania: {url}")
