"""Respektowanie robots.txt (urllib.robotparser) z cache'em per origin."""

from __future__ import annotations

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import structlog

log = structlog.get_logger()

ROBOTS_USER_AGENT = "*"


class RobotsDisallowed(Exception):
    """Ścieżka zabroniona przez robots.txt (lub robots.txt niedostępny z 401/403)."""


class RobotsGuard:
    """Pobiera i interpretuje robots.txt; nie próbuje niczego obchodzić."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._parsers: dict[str, RobotFileParser | None] = {}

    async def _load(self, origin: str) -> RobotFileParser | None:
        """None = brak robots.txt (404 itp.) lub błąd sieci — wtedy brak ograniczeń."""
        parser = RobotFileParser()
        try:
            resp = await self._client.get(f"{origin}/robots.txt")
        except httpx.HTTPError as exc:
            log.warning("robots_unreachable", origin=origin, error=str(exc))
            return None
        if resp.status_code in (401, 403):
            parser.disallow_all = True  # tak samo jak RobotFileParser.read()
            return parser
        if resp.status_code >= 400:
            return None
        parser.parse(resp.text.splitlines())
        return parser

    async def ensure_allowed(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = await self._load(origin)
        parser = self._parsers[origin]
        if parser is not None and not parser.can_fetch(ROBOTS_USER_AGENT, url):
            raise RobotsDisallowed(f"robots.txt zabrania: {url}")
