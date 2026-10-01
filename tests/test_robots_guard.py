"""Testy komunikatu o odmowie dostępu przez robots.txt (401/403 vs zakaz w pliku)."""

from __future__ import annotations

import httpx
import pytest

from evradar.robots import RobotsDisallowed, RobotsGuard


async def _guard(status: int, text: str = "") -> RobotsGuard:
    async def fetch(_: str) -> tuple[int, str]:
        return status, text

    return RobotsGuard(httpx.AsyncClient(), fetch=fetch)


async def test_http_403_is_reported_with_status() -> None:
    guard = await _guard(403)
    with pytest.raises(RobotsDisallowed, match="HTTP 403"):
        await guard.ensure_allowed("https://x.pl/oferty")


async def test_explicit_disallow_message() -> None:
    guard = await _guard(200, "User-agent: *\nDisallow: /oferty")
    with pytest.raises(RobotsDisallowed, match=r"robots\.txt zabrania"):
        await guard.ensure_allowed("https://x.pl/oferty")
    await guard.ensure_allowed("https://x.pl/inne")


async def test_missing_robots_allows() -> None:
    guard = await _guard(404)
    await guard.ensure_allowed("https://x.pl/cokolwiek")
