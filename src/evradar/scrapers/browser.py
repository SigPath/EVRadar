"""BrowserScraper: adaptery wymagające prawdziwej przeglądarki (Playwright + zainstalowany Chrome).

Używa zwykłej przeglądarki bez żadnego maskowania (bez stealth, bez podmiany odcisku) — tak jak
użytkownik. Parametry w `config/sources.yaml` (`params`):
  * `browser_channel: chrome` — użyj zainstalowanego Chrome zamiast pakietowego Chromium
  * `headed_only: true`       — zawsze z widocznym oknem (serwis nie wpuszcza trybu headless)
Robots.txt jest pobierany tą samą przeglądarką (kontekst Playwright).
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlencode

import structlog
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    async_playwright,
)
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from evradar.robots import RobotsDisallowed, RobotsGuard
from evradar.scrapers.base import BaseScraper

log = structlog.get_logger()


class AccessBlocked(Exception):
    """Serwis odmówił dostępu (401/403) — nie ponawiamy i nie obchodzimy blokady."""


class BrowserScraper(BaseScraper, ABC):
    _pw: Playwright | None = None
    _browser: Browser | None = None
    _context: BrowserContext | None = None

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        try:
            params = self.config.params
            headless = self.headless and not params.get("headed_only", False)
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                channel=params.get("browser_channel"), headless=headless
            )
            self._context = await self._browser.new_context(locale="pl-PL")
            self._robots = RobotsGuard(self.client, fetch=self._robots_via_browser)
        except BaseException:
            await self._close_browser()
            await super().__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._close_browser()
        await super().__aexit__(exc_type, exc, tb)

    async def _close_browser(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._context = self._browser = self._pw = None

    async def _robots_via_browser(self, url: str) -> tuple[int, str]:
        assert self._context is not None
        resp = await self._context.request.get(url, timeout=self.config.timeout_s * 1000)
        return resp.status, await resp.text()

    async def get_html(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        wait_selector: str | None = None,
        missing_ok: bool = False,
    ) -> str:
        """Ładuje stronę w przeglądarce (robots, opóźnienie, retry) i zwraca wyrenderowany HTML."""
        assert self._context is not None
        full_url = f"{url}?{urlencode(params)}" if params else url
        last_exc: Exception | None = None
        for attempt in range(self.config.retries):
            try:
                async with self.polite(full_url):
                    page = await self._context.new_page()
                    try:
                        resp = await page.goto(
                            full_url,
                            wait_until="domcontentloaded",
                            timeout=self.config.timeout_s * 1000,
                        )
                        if resp is not None and resp.status in (401, 403):
                            raise AccessBlocked(
                                f"HTTP {resp.status} (blokada serwisu) dla {full_url}"
                            )
                        if resp is not None and resp.status == 404 and missing_ok:
                            self.last_html = ""
                            return ""
                        if resp is None or resp.status >= 400:
                            raise RuntimeError(
                                f"HTTP {resp.status if resp else '?'} dla {full_url}"
                            )
                        if wait_selector:
                            with contextlib.suppress(PlaywrightTimeoutError):
                                await page.wait_for_selector(wait_selector, timeout=8000)
                        html = await page.content()
                    finally:
                        await page.close()
                self.last_html = html
                return html
            except (RobotsDisallowed, AccessBlocked):
                raise
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "browser_retry", source=self.source_id, url=full_url, attempt=attempt + 1,
                    error=str(exc)[:200],
                )  # fmt: skip
                if attempt + 1 < self.config.retries:
                    await asyncio.sleep(2**attempt if self.config.delay_max_s > 0 else 0)
        assert last_exc is not None
        raise last_exc
