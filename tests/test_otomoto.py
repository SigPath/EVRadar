"""Test offline adaptera Otomoto (fixture = przycięty prawdziwy listing VW ID.4 do 130 tys.)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.models import RawListing
from evradar.scrapers import otomoto
from evradar.scrapers.otomoto import ListingUnavailable, OtomotoScraper, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "otomoto" / "listing_page.html"


def test_parse_otomoto_listing() -> None:
    listings, total = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert total >= len(listings) >= 10
    for x in listings:
        assert x.url.startswith("https://www.otomoto.pl/osobowe/oferta/")
        assert x.title_raw and x.brand == "Volkswagen" and x.model == "ID.4"
        assert x.fuel == "Elektryczny"
        assert x.year and x.mileage_km is not None
        assert x.price_gross_pln or x.price_net_pln
        assert x.image_url and x.image_url.startswith("https://")


def test_known_gross_offer() -> None:
    listings, _ = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    by_id = {x.external_id: x for x in listings}
    x = by_id["6150822885"]
    assert x.title_raw == "Volkswagen ID.4 Pro Energy"
    assert (x.year, x.mileage_km, x.price_gross_pln, x.location) == (2026, 7700, 99000, "Słupca")
    assert x.price_net_pln is None and x.vat_invoice is None
    assert x.url == "https://www.otomoto.pl/osobowe/oferta/volkswagen-id4-ID6Ige0J.html"
    assert by_id["6150827453"].battery_kwh == 77


def test_company_offer_is_net_and_not_converted() -> None:
    listings, _ = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    x = {x.external_id: x for x in listings}["6150770501"]
    assert x.price_net_pln == 105999 and x.price_gross_pln is None and x.vat_invoice is True


def test_missing_next_data_raises() -> None:
    with pytest.raises(ValueError, match="__NEXT_DATA__"):
        parse_listing("<html><body>brak danych</body></html>")


def _ssr_page(state: dict[str, object]) -> str:
    payload = {"props": {"pageProps": {"urqlState": state}}}
    return (
        '<html><head><script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script></head></html>"
    )


def test_ssr_timeout_is_retryable_not_structure_change() -> None:
    """Przypadek z 13.10.2026: HTTP 200, ale zapytanie `listingScreen` padło na timeout."""
    state = {
        "1": {"data": '{"__typename":"Query","filters":[]}', "hasNext": True},
        "2": {
            "data": None,
            "hasNext": False,
            "error": {
                "networkError": "OptimusTimeoutError: [HTTP408] Timeout after 10000ms for the "
                "request url: GET:https://www.otomoto.pl/graphql?operationName=listingScreen"
            },
        },
    }
    with pytest.raises(ListingUnavailable, match="HTTP408"):
        parse_listing(_ssr_page(state))


async def test_ssr_retry_recovers_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pierwsza odpowiedź bez wyników, druga poprawna — strona ma być doliczona."""
    calls = {"n": 0}

    async def fake_get_text(
        self: OtomotoScraper, url: str, query: dict[str, object] | None = None
    ) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return _ssr_page(
                {"2": {"data": None, "error": {"networkError": "OptimusTimeoutError: [HTTP408]"}}}
            )
        return "ALL"

    def fake_parse(html: str) -> tuple[list[RawListing], int]:
        if html == "ALL":
            item = RawListing(
                source="otomoto", external_id="1", url="https://o.pl/1", title_raw="t"
            )
            return [item], 1
        return parse_listing(html)

    monkeypatch.setattr(OtomotoScraper, "get_text", fake_get_text)
    monkeypatch.setattr(otomoto, "parse_listing", fake_parse)
    scraper = OtomotoScraper(
        SourceConfig(
            id="otomoto",
            name="Otomoto",
            url="https://o.pl",
            delay_min_s=0,
            delay_max_s=0,
            max_pages=1,
            params={"paths": ["tesla/y"], "exclude_damaged": False},
        )
    )
    assert [x.external_id for x in await scraper.fetch()] == ["1"]
    assert calls["n"] == 2


async def test_one_broken_path_does_not_drop_other_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ścieżka z timeoutem nie może wyzerować całego źródła (błąd z 13.10.2026)."""

    async def fake_get_text(
        self: OtomotoScraper, url: str, query: dict[str, object] | None = None
    ) -> str:
        if "ioniq-6" in url:
            raise ListingUnavailable("SSR bez wyników — OptimusTimeoutError: [HTTP408]")
        return "ALL"

    def fake_parse(html: str) -> tuple[list[RawListing], int]:
        items = [RawListing(source="otomoto", external_id="1", url="https://o.pl/1", title_raw="t")]
        return items, len(items)

    monkeypatch.setattr(OtomotoScraper, "get_text", fake_get_text)
    monkeypatch.setattr(otomoto, "parse_listing", fake_parse)
    cfg = SourceConfig(
        id="otomoto",
        name="Otomoto",
        url="https://o.pl",
        delay_min_s=0,
        delay_max_s=0,
        max_pages=1,
        params={"paths": ["tesla/y", "hyundai/ioniq-6"], "exclude_damaged": False},
    )
    assert [x.external_id for x in await OtomotoScraper(cfg).fetch()] == ["1"]


async def test_all_paths_broken_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_text(
        self: OtomotoScraper, url: str, query: dict[str, object] | None = None
    ) -> str:
        raise ListingUnavailable("SSR bez wyników — OptimusTimeoutError: [HTTP408]")

    monkeypatch.setattr(OtomotoScraper, "get_text", fake_get_text)
    cfg = SourceConfig(
        id="otomoto",
        name="Otomoto",
        url="https://o.pl",
        delay_min_s=0,
        delay_max_s=0,
        max_pages=1,
        params={"paths": ["tesla/y", "hyundai/ioniq-6"], "exclude_damaged": False},
    )
    with pytest.raises(ListingUnavailable, match="wszystkie ścieżki zawiodły"):
        await OtomotoScraper(cfg).fetch()


def _scraper(
    monkeypatch: pytest.MonkeyPatch, damaged_ids: list[str], **params: object
) -> OtomotoScraper:
    """Scraper z podmienioną siecią: zwykłe zapytanie daje ID 1-4, `damaged=1` podane ID."""
    all_items = [
        RawListing(source="otomoto", external_id=str(i), url=f"https://o.pl/{i}", title_raw="t")
        for i in range(1, 5)
    ]

    async def fake_get_text(
        self: OtomotoScraper, url: str, query: dict[str, object] | None = None
    ) -> str:
        return "DAMAGED" if "search[filter_enum_damaged]" in (query or {}) else "ALL"

    def fake_parse(html: str) -> tuple[list[RawListing], int]:
        items = [x for x in all_items if html == "ALL" or x.external_id in damaged_ids]
        return items, len(items)

    monkeypatch.setattr(OtomotoScraper, "get_text", fake_get_text)
    monkeypatch.setattr(otomoto, "parse_listing", fake_parse)
    cfg = SourceConfig(
        id="otomoto",
        name="Otomoto",
        url="https://o.pl",
        delay_min_s=0,
        delay_max_s=0,
        max_pages=2,
        params={"paths": ["tesla/y"], **params},
    )
    return OtomotoScraper(cfg)


async def test_damaged_offers_are_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = _scraper(monkeypatch, ["2", "4"])
    assert sorted(x.external_id or "" for x in await scraper.fetch()) == ["1", "3"]


async def test_ignored_damaged_filter_does_not_drop_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scraper = _scraper(monkeypatch, ["1", "2", "3", "4"])
    assert len(await scraper.fetch()) == 4


async def test_damaged_exclusion_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = _scraper(monkeypatch, ["2"], exclude_damaged=False)
    assert len(await scraper.fetch()) == 4
