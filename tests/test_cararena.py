"""Test offline adaptera Car Arena (fixture = realny listing EV z filtrem paliwa)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.scrapers.cararena import CarArenaScraper, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "cararena" / "listing_page.html"


def test_parse_tylko_glowna_lista() -> None:
    """Widget „top aukcje" (Corolla, Land Cruiser, BMW z ukrytą ceną) nie może się dostać."""
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    titles = {x.title_raw for x in listings}
    assert len(listings) == 3
    assert not titles & {"Toyota Corolla", "Toyota Land Cruiser", "BMW Seria 3", "BMW Seria 4"}
    assert all(x.fuel == "Elektryczny" for x in listings)
    assert all(x.price_gross_pln and x.price_net_pln is None for x in listings)
    assert all(x.url.startswith("https://cararena.pl/") and "?" not in x.url for x in listings)


def test_parse_znana_aukcja() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))}
    eqa = by_id["26746"]
    assert eqa.title_raw == "Mercedes-Benz EQA"
    assert (eqa.year, eqa.mileage_km, eqa.price_gross_pln) == (2023, 38644, 114000)
    assert eqa.location == "Gdynia"
    assert eqa.vat_invoice is True
    assert eqa.image_url and eqa.image_url.startswith("https://static.car-port.pl/")
    soul = by_id["26752"]
    assert (soul.title_raw, soul.price_gross_pln) == ("Kia Soul", 76000)


def test_parse_pusta_strona() -> None:
    assert parse_listing("<html><body></body></html>") == []


async def test_fetch_przekazuje_filtr_paliwa(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_get_text(
        self: CarArenaScraper, url: str, params: dict[str, object] | None = None
    ) -> str:
        calls.append({"url": url, **dict(params or {})})
        return FIXTURE.read_text(encoding="utf-8")

    monkeypatch.setattr(CarArenaScraper, "get_text", fake_get_text)
    cfg = SourceConfig(id="cararena", name="Car Arena", url="https://cararena.pl")
    results = await CarArenaScraper(cfg).fetch()
    assert len(results) == 3
    assert len(calls) == 1  # brak paginacji — jedno żądanie
    assert str(calls[0]["url"]).endswith("/aukcje/samochody-osobowe")
    assert calls[0]["field-fuel"] == "electric"
