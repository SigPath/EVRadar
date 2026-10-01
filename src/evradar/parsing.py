"""Odporne parsowanie cen, przebiegów, lat i parametrów baterii z tekstu."""

from __future__ import annotations

import re
from dataclasses import dataclass

from evradar.models import PriceBasis

_NUMBER = re.compile(r"\d{1,3}(?:[ .,\u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?")
_NET = re.compile(r"\bnetto\b|\bnet\b|bez\s+vat", re.IGNORECASE)
_GROSS = re.compile(r"\bbrutto\b|\bgross\b|z\s+vat", re.IGNORECASE)

VAT_RATE = 0.23


def net_to_gross(net: int) -> int:
    """Cena brutto z netto: +23% VAT (złotówki, zaokrąglone)."""
    return round(net * (1 + VAT_RATE))


_YEAR = re.compile(r"(?<!\d)(19[89]\d|20[0-4]\d)(?!\d)")
_KWH = re.compile(r"(\d{2,3}(?:[.,]\d{1,2})?)\s*kwh", re.IGNORECASE)
_RANGE = re.compile(r"(\d{2,3})\s*km\s*\(?\s*wltp|wltp[^0-9]{0,20}(\d{2,3})\s*km", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedPrice:
    amount: int
    basis: PriceBasis | None


def _to_number(token: str) -> float:
    s = re.sub(r"[\s\u00a0\u202f]", "", token)
    last_sep = max(s.rfind(","), s.rfind("."))
    if last_sep == -1:
        return float(s)
    frac = s[last_sep + 1 :]
    if len(frac) in (1, 2):
        # separator dziesiętny; pozostałe separatory to tysiące
        whole = re.sub(r"[.,]", "", s[:last_sep])
        return float(f"{whole}.{frac}")
    return float(re.sub(r"[.,]", "", s))


def parse_price(text: str | None) -> ParsedPrice | None:
    """Wyciąga pierwszą kwotę i (jeśli podano) informację netto/brutto — bez zgadywania."""
    if not text:
        return None
    match = _NUMBER.search(text)
    if match is None:
        return None
    amount = round(_to_number(match.group(0)))
    if amount <= 0:
        return None
    basis: PriceBasis | None = None
    if _NET.search(text):
        basis = "net"
    elif _GROSS.search(text):
        basis = "gross"
    return ParsedPrice(amount=amount, basis=basis)


def parse_int(text: str | None) -> int | None:
    """Liczba całkowita z tekstu typu '45 000 km' lub '45 tys. km'."""
    if not text:
        return None
    if re.search(r"tys\b", text, re.IGNORECASE):
        match = re.search(r"\d+(?:[.,]\d+)?", text)
        if match:
            return round(float(match.group(0).replace(",", ".")) * 1000)
    digits = re.sub(r"\D", "", text.split(",")[0] if re.search(r",\d{1,2}\b", text) else text)
    return int(digits) if digits else None


def parse_year(text: str | None) -> int | None:
    """Rok produkcji z tekstu (np. '03/2022' lub '2022')."""
    if not text:
        return None
    match = _YEAR.search(text)
    return int(match.group(1)) if match else None


def parse_kwh(text: str | None) -> float | None:
    """Pojemność baterii w kWh."""
    if not text:
        return None
    match = _KWH.search(text)
    return float(match.group(1).replace(",", ".")) if match else None


def parse_range_wltp(text: str | None) -> int | None:
    """Zasięg WLTP w km."""
    if not text:
        return None
    match = _RANGE.search(text)
    if not match:
        return None
    return int(match.group(1) or match.group(2))
