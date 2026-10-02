"""Modele danych: surowe ogłoszenie, oferta, różnice, wynik źródła, dane raportu."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

PriceBasis = Literal["net", "gross"]
SellerType = Literal["dealer", "private"]

_TRACKING_PARAM = re.compile(r"^(utm_|fbclid|gclid|_ga)", re.IGNORECASE)


def utcnow() -> datetime:
    """Aktualny czas UTC (aware)."""
    return datetime.now(UTC)


def canonical_url(url: str) -> str:
    """URL bez fragmentu, parametrów śledzących i końcowego '/'."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAM.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, query, ""))


def make_offer_id(source: str, external_id: str | None, url: str) -> str:
    """Stabilny SHA-1 z źródła i ID/URL oferty — nigdy z ceny."""
    key = external_id.strip() if external_id else canonical_url(url)
    return hashlib.sha1(f"{source}|{key}".encode(), usedforsecurity=False).hexdigest()


class RawListing(BaseModel):
    """Ogłoszenie zwrócone przez adapter, przed dopasowaniem modelu."""

    source: str
    url: str
    title_raw: str
    external_id: str | None = None
    brand: str | None = None
    model: str | None = None
    fuel: str | None = None
    description: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    price_gross_pln: int | None = None
    price_net_pln: int | None = None
    monthly_installment_pln: int | None = None
    installment_basis: PriceBasis | None = None
    vat_invoice: bool | None = None
    battery_kwh: float | None = None
    range_km_wltp: int | None = None
    drivetrain: str | None = None
    location: str | None = None
    image_url: str | None = None
    seller_type: SellerType | None = None
    listed_at: datetime | None = None
    soh_pct: int | None = None


class Offer(BaseModel):
    """Oferta po dopasowaniu do konfiguracji modeli."""

    offer_id: str
    source: str
    url: str
    brand: str
    model_matched: str
    title_raw: str
    year: int | None = None
    mileage_km: int | None = None
    price_gross_pln: int | None = None
    price_net_pln: int | None = None
    monthly_installment_pln: int | None = None
    installment_basis: PriceBasis | None = None
    vat_invoice: bool | None = None
    battery_kwh: float | None = None
    range_km_wltp: int | None = None
    drivetrain: str | None = None
    location: str | None = None
    image_url: str | None = None
    seller_type: SellerType | None = None
    listed_at: datetime | None = None
    soh_pct: int | None = None
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    uncertain_powertrain: bool = False

    @property
    def price_for_diff(self) -> tuple[int, PriceBasis] | None:
        """Cena używana do porównań: brutto, a gdy brak — netto (bez przeliczeń)."""
        if self.price_gross_pln is not None:
            return self.price_gross_pln, "gross"
        if self.price_net_pln is not None:
            return self.price_net_pln, "net"
        return None


class StoredOffer(Offer):
    """Oferta odczytana z bazy."""

    active: bool = True


class DiffKind(StrEnum):
    NEW = "NEW"
    PRICE_DROP = "PRICE_DROP"
    PRICE_UP = "PRICE_UP"
    GONE = "GONE"
    BACK = "BACK"


class OfferDiff(BaseModel):
    """Zmiana oferty względem poprzedniego skanu."""

    kind: DiffKind
    offer: Offer
    old_price: int | None = None
    new_price: int | None = None
    price_basis: PriceBasis | None = None

    @property
    def delta(self) -> int | None:
        if self.old_price is None or self.new_price is None:
            return None
        return self.new_price - self.old_price

    @property
    def delta_pct(self) -> float | None:
        if self.old_price in (None, 0) or self.delta is None:
            return None
        assert self.old_price is not None
        return self.delta / self.old_price * 100


class SourceStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"
    STALE = "STALE"


class SourceResult(BaseModel):
    """Wynik skanu jednego źródła."""

    source: str
    name: str = ""
    status: SourceStatus
    offers: list[Offer] = Field(default_factory=list)
    offers_count: int = 0
    raw_count: int = 0
    error: str | None = None
    note: str | None = None
    duration_s: float = 0.0


class RunInfo(BaseModel):
    run_id: int | None = None
    started_at: datetime
    duration_s: float
    dry_run: bool = False


class ReportData(BaseModel):
    """Komplet danych do renderowania raportu."""

    run: RunInfo
    sources: list[SourceResult]
    active: list[Offer]
    new: list[OfferDiff]
    price_drops: list[OfferDiff]
    price_ups: list[OfferDiff]
    back: list[OfferDiff]
    gone: list[OfferDiff]
    uncertain: list[Offer]
    # offer_id -> [(data ISO, cena)] tylko dla ofert z co najmniej dwiema różnymi cenami
    price_history: dict[str, list[tuple[str, int]]] = Field(default_factory=dict)
    # "Marka Model" -> [(data ISO, mediana brutto, liczba ofert)]
    model_trend: dict[str, list[tuple[str, int, int]]] = Field(default_factory=dict)
    # source_id -> [(data ISO, status, liczba ofert)] z ostatnich przebiegów
    source_history: dict[str, list[tuple[str, str, int]]] = Field(default_factory=dict)
