"""Test offline adaptera Poleasingowe.pl (fixture = realny listing aukcji aut elektrycznych)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.models import RawListing
from evradar.scrapers import poleasingowe
from evradar.scrapers.poleasingowe import PAGE_SIZE, PoleasingoweScraper, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "poleasingowe" / "listing_page.html"


def test_parse_poleasingowe() -> None:
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(listings) >= 3
    complete = [x for x in listings if x.price_net_pln and x.year and x.mileage_km is not None]
    assert len(complete) >= 3
    for x in listings:
        assert x.url.startswith(
            (
                "https://poleasingowe.pl/pl/auctions/details/",
                "https://aukcje.pkoleasing.pl/auctions/details/",
            )
        )
        assert "?" not in x.url
        assert x.title_raw and x.external_id
        assert x.price_gross_pln is None  # cena aukcyjna podana jako netto


def test_known_auction() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))}
    ev6 = by_id["523898"]
    assert ev6.title_raw == "KIA EV 6 SUV"
    assert (ev6.year, ev6.mileage_km, ev6.price_net_pln, ev6.fuel) == (
        2022,
        137696,
        65000,
        "Elektryczny",
    )
    assert ev6.location == "Tarczyn, Żytnia 2"
    assert ev6.image_url and ev6.image_url.startswith("https://poleasingowe.pl/images/")


def _item(n: int) -> RawListing:
    return RawListing(
        source="poleasingowe",
        external_id=str(n),
        url=f"https://poleasingowe.pl/pl/auctions/details/{n}",
        title_raw=f"aukcja {n}",
    )


def _scraper(
    monkeypatch: pytest.MonkeyPatch, pages: dict[int, int]
) -> tuple[PoleasingoweScraper, list[dict[str, object]]]:
    """Scraper z podmienioną siecią: `pages` mówi, ile kafelków ma każda strona."""
    seen: list[dict[str, object]] = []

    async def fake_get_text(
        self: PoleasingoweScraper, url: str, params: dict[str, object] | None = None
    ) -> str:
        seen.append(dict(params or {}))
        raw = (params or {}).get("page", 1)
        page = int(raw) if isinstance(raw, (int, str)) else 1
        return f"PAGE{page}"

    def fake_parse(html: str) -> list[RawListing]:
        page = int(html.removeprefix("PAGE"))
        return [_item(page * 1000 + i) for i in range(pages.get(page, 0))]

    monkeypatch.setattr(PoleasingoweScraper, "get_text", fake_get_text)
    monkeypatch.setattr(poleasingowe, "parse_listing", fake_parse)
    cfg = SourceConfig(
        id="poleasingowe",
        name="Poleasingowe.pl",
        url="https://poleasingowe.pl",
        delay_min_s=0,
        delay_max_s=0,
        max_pages=5,
    )
    return PoleasingoweScraper(cfg), seen


async def test_fetch_schodzi_na_kolejne_strony_mimo_limitu_20(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serwis ignoruje `list_pagesize` > 20: pełna strona nie może kończyć zbierania."""
    scraper, seen = _scraper(monkeypatch, {1: PAGE_SIZE, 2: 7})
    assert len(await scraper.fetch()) == PAGE_SIZE + 7
    assert [p.get("page") for p in seen] == [None, 2]


async def test_fetch_konczy_gdy_strona_niepelna(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper, seen = _scraper(monkeypatch, {1: 3})
    assert len(await scraper.fetch()) == 3
    assert len(seen) == 1


async def test_fetch_filtruje_tylko_osobowe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zapytanie musi zawierać filtr osobowy i twardy limit 20 pozycji na stronę."""
    scraper, seen = _scraper(monkeypatch, {1: 1})
    await scraper.fetch()
    assert seen[0]["list_pagesize"] == 20
    assert seen[0]["procsubcat"] == "ecr_cartypess"
    assert seen[0]["mainprodcat"] == "vehicles"
    assert seen[0]["fueltype"] == "216"
