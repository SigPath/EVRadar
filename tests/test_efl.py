"""Test offline adaptera Aukcje EFL (fixture = realna strona 2 listingu osobowych)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.scrapers import efl
from evradar.scrapers.efl import PAGE_SIZE, EflScraper, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "efl" / "listing_page.html"


def test_parse_pelna_strona() -> None:
    """Strona pełna (8 ofert): ID, URL-e, rok, przebieg i cena netto w każdej ofercie."""
    listings = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert len(listings) == PAGE_SIZE
    complete = [x for x in listings if x.price_net_pln and x.year and x.mileage_km]
    assert len(complete) >= 7  # pojedyncze aukcje moga miec brakujacy parametr
    for x in listings:
        assert x.url.startswith("https://aukcje.efl.com.pl/Auction/")
        assert "?" not in x.url and x.external_id
        assert x.price_gross_pln is None  # cena aukcyjna = netto (bez VAT)
        assert x.title_raw


def test_parse_znana_aukcja_ev() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))}
    tesla = by_id["438309"]
    assert tesla.title_raw == "TESLA MODEL X BLACK PS DUAL MOTOR 2023r."
    assert (tesla.year, tesla.mileage_km, tesla.price_net_pln, tesla.fuel) == (
        2023,
        44572,
        152800,
        "Elektryczny",
    )
    assert tesla.image_url and tesla.image_url.startswith("https://aukcje.efl.com.pl/Content/Media/")


def _page(n_ev: int, n_all: int) -> str:
    def tile(i: int, ev: bool) -> str:
        fuel = "Napęd elektryczny" if ev else "Benzyna"
        return (
            '<div class="OfferListInner"><div class="AuctionTitle">'
            f'<a class="title" href="/Auction/AUTO-{i}-id{i}00"><h3>AUTO {i}</h3></a></div>'
            '<div class="ListAuctionInfo"><div class="price">10&nbsp;000,00 zł</div></div>'
            '<table class="simple-table">'
            f'<tr><td><label for="Rok_produkcji:">Rok produkcji:</label></td><td>2023</td>'
            f'<td><label for="Rodzaj_paliwa:">Rodzaj paliwa:</label></td><td>{fuel}</td></tr>'
            '<tr><td><label for="Przebieg:">Przebieg odczytany:</label></td><td>1000km</td></tr>'
            "</table></div>"
        )

    evs = "".join(tile(i, True) for i in range(n_ev))
    rest = "".join(tile(100 + i, False) for i in range(n_all - n_ev))
    return f'<html><body>{evs}{rest}</body></html>'


def _scraper(
    monkeypatch: pytest.MonkeyPatch, pages: list[str]
) -> tuple[EflScraper, list[dict[str, object]]]:
    seen: list[dict[str, object]] = []

    async def fake_get_text(
        self: EflScraper, url: str, params: dict[str, object] | None = None
    ) -> str:
        seen.append(dict(params or {}))
        return pages[len(seen) - 1]

    monkeypatch.setattr(EflScraper, "get_text", fake_get_text)
    cfg = SourceConfig(
        id="efl", name="Aukcje EFL", url="https://aukcje.efl.com.pl", max_pages=5
    )
    return EflScraper(cfg), seen


async def test_fetch_stronicowanie_i_filtr_ev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pełna strona wymusza kolejną; niepełna kończy; spalinowe są odsiewane."""
    scraper, seen = _scraper(
        monkeypatch,
        [_page(1, PAGE_SIZE), _page(2, PAGE_SIZE), _page(1, 3)],
    )
    results = await scraper.fetch()
    assert len(results) == 4  # 1 EV + 2 EV + 1 EV; benzyniaki (7+6+2) odrzucone
    assert [p.get("page") for p in seen] == [0, 1, 2]
    assert seen[0]["fc"] == "10" and seen[0]["category"] == "12"
    assert all(x.fuel == "Elektryczny" for x in results)


async def test_fetch_stop_po_niepelnej_stronie(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper, seen = _scraper(monkeypatch, [_page(0, 2)])
    assert len(await scraper.fetch()) == 0
    assert len(seen) == 1


def test_parser_odporny_na_pusta_strone() -> None:
    assert parse_listing("<html><body></body></html>") == []
    assert parse_listing("") == []
    assert efl.PAGE_SIZE == 8
