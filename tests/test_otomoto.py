"""Test offline adaptera Otomoto (fixture = przycięty prawdziwy listing VW ID.4 do 130 tys.)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.models import RawListing
from evradar.scrapers import otomoto
from evradar.scrapers.otomoto import OtomotoScraper, parse_listing

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
