"""Test offline adaptera Dawro (fixture = realny listing aukcji Santander Consumer Multirent)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.scrapers.dawro import PAGE_SIZE, DawroScraper, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "dawro" / "listing_page.html"
AUCTION_URL = "https://www.dawro.pl/aukcja/"


def test_parse_listing() -> None:
    """19 aukcji; każda z ceną brutto, rokiem, przebiegiem, ID i czystym URL-em."""
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(listings) == 19
    assert all(x.price_gross_pln and x.year and x.mileage_km for x in listings)
    assert all(x.price_net_pln is None for x in listings)  # aukcje Dawro = brutto
    assert all(x.vat_invoice is True for x in listings)
    assert all(x.url.startswith(AUCTION_URL) and "?" not in x.url for x in listings)
    assert all(x.external_id and x.external_id.isdigit() for x in listings)
    assert all(x.fuel is None for x in listings)  # serwis nie podaje paliwa


def test_tytul_bez_tablicy_rejestracyjnej() -> None:
    """W tekście h2 jest doklejona rejestracja (`..., SJZ7RW2`) — bierzemy atrybut title."""
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert all("," not in x.title_raw for x in listings)
    ford = next(x for x in listings if x.external_id == "17100")
    assert ford.title_raw == "FORD Edge 2.0 EcoBoost AWD aut SEL"


def test_znana_aukcja_i_cena_wywolawcza() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))}
    ford = by_id["17100"]
    # cena = najwyższa oferta (20 000), nie wywoławcza (43 200)
    assert (ford.year, ford.mileage_km, ford.price_gross_pln) == (2017, 104844, 20000)
    assert ford.image_url and ford.image_url.startswith("https://www.dawro.pl/cache/zdjecia/")
    audi = by_id["17146"]
    assert audi.price_gross_pln == 63900  # brak ofert -> cena wywoławcza


def _page(ids: list[int]) -> str:
    tiles = "".join(
        f'<div class="fl aukcja-box"><a href="/aukcja/{i},auto-{i}">'
        f'<h2 class="nazwa" title="AUTO {i}">AUTO {i}, XX00000</h2>'
        '<div class="parametry"><div class="k">Cena wywoławcza:</div>'
        '<div class="w">10 000,00 zł</div>'
        '<div class="odstepy"><div class="k">Rok produkcji:</div><div class="w">2020 r.</div>'
        '<div class="k">Przebieg:</div><div class="w">50000 km</div></div></div></a></div>'
        for i in ids
    )
    return f"<html><body>{tiles}</body></html>"


def _scraper(
    monkeypatch: pytest.MonkeyPatch, pages: list[str]
) -> tuple[DawroScraper, list[str]]:
    seen: list[str] = []

    async def fake_get_text(
        self: DawroScraper, url: str, params: dict[str, object] | None = None
    ) -> str:
        seen.append(url)
        return pages[min(len(seen) - 1, len(pages) - 1)]

    monkeypatch.setattr(DawroScraper, "get_text", fake_get_text)
    cfg = SourceConfig(id="dawro", name="Dawro", url="https://www.dawro.pl", max_pages=5)
    return DawroScraper(cfg), seen


async def test_fetch_zatrzymuje_sie_gdy_serwis_powtarza_strone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Poza zakresem Dawro zwraca stronę 1 zamiast pustej — pętla nie może się zapętlić."""
    full = _page(list(range(1, PAGE_SIZE + 1)))
    scraper, seen = _scraper(monkeypatch, [full, full])
    results = await scraper.fetch()
    assert len(results) == PAGE_SIZE  # druga (powtórzona) strona odrzucona
    assert len(seen) == 2
    assert "strona,1," in seen[0] and "strona,2," in seen[1]
    assert "sprzedawca,santander_scm" in seen[0] and "typ,10" in seen[0] and "ilosc,100" in seen[0]


async def test_fetch_konczy_na_niepelnej_stronie(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper, seen = _scraper(monkeypatch, [_page([1, 2, 3])])
    assert len(await scraper.fetch()) == 3
    assert len(seen) == 1


async def test_fetch_laczy_kolejne_strony(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper, seen = _scraper(
        monkeypatch, [_page(list(range(1, PAGE_SIZE + 1))), _page([500, 501])]
    )
    results = await scraper.fetch()
    assert len(results) == PAGE_SIZE + 2
    assert len(seen) == 2


def test_parse_pusta_strona() -> None:
    assert parse_listing("<html></html>") == []
