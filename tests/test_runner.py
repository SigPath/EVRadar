"""Testy orkiestracji: izolacja awarii, STALE, robots, cykl NEW -> obniżka -> zniknięcie."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

import pytest

from evradar import runner
from evradar.config import ModelsConfig, SourceConfig, load_models_config
from evradar.matching import ModelMatcher
from evradar.models import RawListing, SourceStatus, utcnow
from evradar.robots import RobotsDisallowed
from evradar.scrapers.base import BaseScraper
from evradar.storage import Storage


def make_listing(source: str, price: int, ident: str = "1") -> RawListing:
    return RawListing(
        source=source,
        url=f"https://{source}.pl/o/{ident}",
        external_id=ident,
        title_raw="Tesla Model 3 Long Range",
        brand="Tesla",
        fuel="Elektryczny",
        year=2022,
        mileage_km=40_000,
        price_gross_pln=price,
    )


class FakeScraper(BaseScraper):
    source_id: ClassVar[str] = "fake"
    behaviour: ClassVar[Callable[[str], list[RawListing]]]

    async def fetch(self) -> list[RawListing]:
        self.last_html = "<html>snapshot</html>"
        return type(self).behaviour(self.config.id)


def patch_scrapers(
    monkeypatch: pytest.MonkeyPatch, behaviours: dict[str, Callable[[], object]]
) -> None:
    def factory(source_id: str) -> type[BaseScraper]:
        def fetch_impl(_: str) -> list[RawListing]:
            result = behaviours[source_id]()
            assert isinstance(result, list)
            return result

        return type("S", (FakeScraper,), {"behaviour": staticmethod(fetch_impl)})

    monkeypatch.setattr(runner, "get_scraper_class", factory)


def cfg(source_id: str, **kw: object) -> SourceConfig:
    return SourceConfig(
        id=source_id,
        name=source_id.upper(),
        url=f"https://{source_id}.pl",
        delay_min_s=0,
        delay_max_s=0,
        **kw,
    )


@pytest.fixture
def models() -> ModelsConfig:
    cfg = load_models_config()
    cfg.filters.max_price_gross_pln = None  # testy nie zależą od limitu ceny z configu
    return cfg


async def test_failure_is_isolated(
    monkeypatch: pytest.MonkeyPatch, models: ModelsConfig, tmp_path: Path
) -> None:
    def boom() -> list[RawListing]:
        raise RuntimeError("zmiana API")

    def robots() -> list[RawListing]:
        raise RobotsDisallowed("robots.txt zabrania: x")

    patch_scrapers(
        monkeypatch,
        {"good": lambda: [make_listing("good", 150_000)], "bad": boom, "blocked": robots},
    )
    db = Storage(":memory:")
    data, first = await runner.run_scan(
        [cfg("good"), cfg("bad"), cfg("blocked"), cfg("off", enabled=False, reason="powód")],
        models,
        db,
        debug_dir=tmp_path,
    )
    status = {s.source: s for s in data.sources}
    assert first
    assert status["good"].status is SourceStatus.OK and status["good"].offers_count == 1
    assert status["bad"].status is SourceStatus.ERROR and "zmiana API" in (
        status["bad"].error or ""
    )
    assert status["blocked"].status is SourceStatus.SKIPPED and "robots" in (
        status["blocked"].note or ""
    )
    assert status["off"].status is SourceStatus.SKIPPED and status["off"].note == "powód"
    assert len(data.new) == 1


async def test_stale_detection_saves_debug_html(
    monkeypatch: pytest.MonkeyPatch, models: ModelsConfig, tmp_path: Path
) -> None:
    calls = iter([[make_listing("s", 100_000)], []])
    patch_scrapers(monkeypatch, {"s": lambda: next(calls)})
    db = Storage(":memory:")
    first, _ = await runner.run_scan([cfg("s")], models, db, debug_dir=tmp_path)
    assert first.sources[0].status is SourceStatus.OK

    second, _ = await runner.run_scan([cfg("s")], models, db, debug_dir=tmp_path)
    res = second.sources[0]
    assert res.status is SourceStatus.STALE
    assert list(tmp_path.glob("s-*.html"))
    assert second.gone == []  # STALE nie oznacza zniknięcia ofert
    assert len(second.active) == 1


async def test_new_drop_gone_cycle(
    monkeypatch: pytest.MonkeyPatch, models: ModelsConfig, tmp_path: Path
) -> None:
    states: list[list[RawListing]] = [
        [make_listing("s", 150_000, "1"), make_listing("s", 160_000, "2")],
        [make_listing("s", 140_000, "1"), make_listing("s", 160_000, "2")],
        [make_listing("s", 140_000, "1")],
    ]
    it = iter(states)
    patch_scrapers(monkeypatch, {"s": lambda: next(it)})
    db = Storage(":memory:")

    d1, _ = await runner.run_scan([cfg("s")], models, db, debug_dir=tmp_path)
    assert len(d1.new) == 2

    d2, first = await runner.run_scan([cfg("s")], models, db, debug_dir=tmp_path)
    assert not first
    assert len(d2.new) == 0 and len(d2.price_drops) == 1
    assert d2.price_drops[0].delta == -10_000

    d3, _ = await runner.run_scan([cfg("s")], models, db, debug_dir=tmp_path)
    assert len(d3.gone) == 1 and len(d3.active) == 1

    from_db = db.load_report_data()
    assert from_db is not None and len(from_db.gone) == 1


async def test_dry_run_does_not_write(
    monkeypatch: pytest.MonkeyPatch, models: ModelsConfig, tmp_path: Path
) -> None:
    patch_scrapers(monkeypatch, {"s": lambda: [make_listing("s", 100_000)]})
    db = Storage(":memory:")
    data, _ = await runner.run_scan([cfg("s")], models, db, dry_run=True, debug_dir=tmp_path)
    assert data.run.dry_run and len(data.new) == 1
    assert db.load_offers() == {} and db.last_run_id() is None


def test_net_only_price_gets_gross_with_vat(models: ModelsConfig) -> None:
    listing = make_listing("s", 0).model_copy(
        update={"price_gross_pln": None, "price_net_pln": 100_000}
    )
    offers = runner.build_offers([listing], ModelMatcher(models.targets), models, utcnow())
    assert offers[0].price_net_pln == 100_000
    assert offers[0].price_gross_pln == 123_000


def test_gross_only_price_gets_net_without_vat(models: ModelsConfig) -> None:
    listing = make_listing("s", 123_000)
    offers = runner.build_offers([listing], ModelMatcher(models.targets), models, utcnow())
    assert offers[0].price_gross_pln == 123_000
    assert offers[0].price_net_pln == 100_000


def test_max_price_filter_drops_expensive(models: ModelsConfig) -> None:
    models.filters.max_price_gross_pln = 130_000
    listings = [make_listing('s', 130_000, '1'), make_listing('s', 130_001, '2')]
    offers = runner.build_offers(listings, ModelMatcher(models.targets), models, utcnow())
    assert [o.price_gross_pln for o in offers] == [130_000]
