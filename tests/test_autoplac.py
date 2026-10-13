"""Test offline adaptera Autoplac (fixture = /tesla/model-3/elektryczny, strona 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evradar.config import SourceConfig
from evradar.scrapers.autoplac import AutoplacScraper, parse_listing

FIXTURE = Path(__file__).parent / "fixtures" / "autoplac" / "listing_page.html"


def _cfg(paths: list[str]) -> SourceConfig:
    return SourceConfig(
        id="autoplac",
        name="Autoplac",
        url="https://a.pl",
        delay_min_s=0,
        delay_max_s=0,
        max_pages=1,
        params={"paths": paths},
    )


def test_parse_autoplac_listing() -> None:
    listings, total = parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert total == 114 and len(listings) == 24
    for x in listings:
        assert x.url.startswith("https://autoplac.pl/oferta/tesla/model-3/")
        assert x.brand == "Tesla" and x.model == "Model 3" and x.fuel == "Elektryczny"
        assert x.year and x.mileage_km is not None and x.price_gross_pln
        assert x.image_url and x.image_url.startswith("https://")


def test_known_offers() -> None:
    by_id = {x.external_id: x for x in parse_listing(FIXTURE.read_text(encoding="utf-8"))[0]}
    x = by_id["4741302"]
    assert (x.year, x.mileage_km, x.price_gross_pln, x.location) == (2021, 80370, 78000, "Warszawa")
    assert x.price_net_pln is None and x.vat_invoice is None
    vat = by_id["4743759"]
    assert (vat.price_gross_pln, vat.price_net_pln) == (129000, 104878)
    assert vat.vat_invoice is True and vat.location == "Tarnowskie Góry"
    assert vat.mileage_km == 148000


def test_missing_ng_state_raises() -> None:
    with pytest.raises(ValueError, match="ng-state"):
        parse_listing("<html><body>brak danych</body></html>")


async def test_one_broken_path_does_not_drop_other_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nieznany slug jednej ścieżki nie może wyzerować całego źródła (wzorzec z Otomoto)."""

    async def fake_get_text(
        self: AutoplacScraper, url: str, params: dict[str, object] | None = None
    ) -> str:
        if "kia/ev3" in url:
            raise ValueError("Nieznany model w ścieżce 'kia/ev3' — sprawdź slug")
        return FIXTURE.read_text(encoding="utf-8")

    monkeypatch.setattr(AutoplacScraper, "get_text", fake_get_text)
    listings = await AutoplacScraper(_cfg(["tesla/model-3", "kia/ev3"])).fetch()
    assert len(listings) == 24


async def test_all_paths_broken_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_text(
        self: AutoplacScraper, url: str, params: dict[str, object] | None = None
    ) -> str:
        raise ValueError("Nieznany model w ścieżce — sprawdź slug")

    monkeypatch.setattr(AutoplacScraper, "get_text", fake_get_text)
    with pytest.raises(ValueError, match="wszystkie ścieżki zawiodły"):
        await AutoplacScraper(_cfg(["tesla/model-3"])).fetch()
