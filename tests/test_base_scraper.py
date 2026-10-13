"""Testy warstwy sieciowej BaseScraper (retry, `Retry-After`)."""

from __future__ import annotations

import httpx
import pytest

from evradar.scrapers.base import _retry_after


def _status_error(status: int, headers: dict[str, str]) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.pl/")
    response = httpx.Response(status, headers=headers, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


def test_retry_after_seconds() -> None:
    assert _retry_after(_status_error(429, {"Retry-After": "7"})) == 7.0
    assert _retry_after(_status_error(503, {"Retry-After": "2.5"})) == 2.5


def test_retry_after_ignored_when_missing_or_not_numeric() -> None:
    assert _retry_after(_status_error(503, {})) is None
    # daty (format HTTP) nie są obsługiwane — wracamy do wykładniczego backoffu
    http_date = "Wed, 21 Oct 2026 07:28:00 GMT"
    assert _retry_after(_status_error(429, {"Retry-After": http_date})) is None


def test_retry_after_negative_is_ignored() -> None:
    assert _retry_after(_status_error(429, {"Retry-After": "-5"})) is None


def test_retry_after_other_exceptions() -> None:
    assert _retry_after(httpx.ConnectError("brak połączenia")) is None


@pytest.mark.parametrize("value", ["0", "120"])
def test_retry_after_valid_edge_values(value: str) -> None:
    assert _retry_after(_status_error(429, {"Retry-After": value})) == float(value)
