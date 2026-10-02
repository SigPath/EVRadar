"""BaseScraper: wspólna, "grzeczna" warstwa sieciowa (robots, opóźnienia, retry, semafor)."""

from __future__ import annotations

import asyncio
import json
import random
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, ClassVar, Self

import httpx
import structlog

from evradar.config import SourceConfig
from evradar.models import RawListing
from evradar.robots import RobotsGuard

log = structlog.get_logger()

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
RETRY_STATUS = {429, 500, 502, 503, 504}


class BaseScraper(ABC):
    """Adapter jednego źródła. Podklasa implementuje `fetch()` i czystą funkcję `parse()`."""

    source_id: ClassVar[str]

    def __init__(
        self,
        config: SourceConfig,
        *,
        headless: bool = True,
        brands: list[str] | None = None,
        max_price_gross_pln: int | None = None,
    ) -> None:
        self.config = config
        self.headless = headless
        self.brands = brands or []  # marki z config/models.yaml — do zawężania zapytań
        self.max_price_gross_pln = max_price_gross_pln  # filters.max_price_gross_pln z models.yaml
        self.last_html: str | None = None  # ostatnia pobrana treść — do katalogu debug/
        self._client: httpx.AsyncClient | None = None
        self._robots: RobotsGuard | None = None
        self._sem = asyncio.Semaphore(config.concurrency)
        self._requests = 0

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.5"},
            follow_redirects=True,
            timeout=self.config.timeout_s,
        )
        self._robots = RobotsGuard(self._client)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Użyj `async with scraper:`")
        return self._client

    @asynccontextmanager
    async def polite(self, url: str) -> AsyncIterator[None]:
        """Sprawdza robots.txt, ogranicza współbieżność i wstawia losowe opóźnienie."""
        assert self._robots is not None
        await self._robots.ensure_allowed(url)
        async with self._sem:
            if self._requests:
                await asyncio.sleep(
                    random.uniform(self.config.delay_min_s, self.config.delay_max_s)
                )
            self._requests += 1
            yield

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        """GET z robots.txt, opóźnieniem i retry z exponential backoff."""
        return await self._request("GET", url, params=params)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        last_exc: Exception | None = None
        full_url = str(httpx.URL(url).copy_merge_params(params or {}))
        for attempt in range(self.config.retries):
            try:
                async with self.polite(full_url):
                    resp = await self.client.request(
                        method, full_url, json=json_body, headers=headers
                    )
                if resp.status_code in RETRY_STATUS:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                self.last_html = resp.text
                return resp.text
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                wait = 2**attempt
                log.warning(
                    "request_retry",
                    source=self.source_id,
                    url=url,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt + 1 < self.config.retries:
                    await asyncio.sleep(wait if self.config.delay_max_s > 0 else 0)
        assert last_exc is not None
        raise last_exc

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        text = await self.get_text(url, params)
        return json.loads(text)

    async def post_json(self, url: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        """POST JSON (publiczne API frontu) z tymi samymi regułami co GET."""
        return json.loads(await self._request("POST", url, json_body=body, headers=headers))

    @abstractmethod
    async def fetch(self) -> list[RawListing]:
        """Pobiera i zwraca surowe ogłoszenia (bez filtrowania modeli)."""
