"""Testy parsowania cen i liczb."""

from __future__ import annotations

import pytest

from evradar.parsing import (
    ParsedPrice,
    parse_int,
    parse_kwh,
    parse_price,
    parse_range_wltp,
    parse_year,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("89 900 zł", ParsedPrice(89900, None)),
        ("89\u00a0900\u00a0zł brutto", ParsedPrice(89900, "gross")),
        ("73 008,13 zł netto", ParsedPrice(73008, "net")),
        ("89.900 PLN", ParsedPrice(89900, None)),
        ("89900", ParsedPrice(89900, None)),
        ("1 299,50 zł/mc netto", ParsedPrice(1300, "net")),
        ("od 1,299 zł", ParsedPrice(1299, None)),
        ("Cena: 120 000 zł z VAT", ParsedPrice(120000, "gross")),
    ],
)
def test_parse_price(text: str, expected: ParsedPrice) -> None:
    assert parse_price(text) == expected


def test_parse_price_none() -> None:
    assert parse_price(None) is None
    assert parse_price("Zapytaj o cenę") is None
    assert parse_price("0 zł") is None


def test_parse_misc() -> None:
    assert parse_int("45 000 km") == 45000
    assert parse_int("45.000 km") == 45000
    assert parse_int("45 tys. km") == 45000
    assert parse_int("brak") is None
    assert parse_year("03/2022") == 2022
    assert parse_year("rok 2021") == 2021
    assert parse_kwh("Kia e-Niro 64,8 kWh") == 64.8
    assert parse_range_wltp("zasięg 455 km WLTP") == 455
