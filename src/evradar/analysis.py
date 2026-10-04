"""Analizy rynku na danych ofert: deprecjacja (cena vs wiek i przebieg) oraz czas ekspozycji."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from evradar.models import Offer, as_utc

MIN_FIT_POINTS = 8  # minimum ofert modelu do regresji
KM_UNIT = 10_000


@dataclass(frozen=True)
class YearRow:
    year: int
    n: int
    price: int
    mileage_km: int | None
    step_pct: float | None  # zmiana mediany względem roku o 1 młodszego


@dataclass(frozen=True)
class Depreciation:
    model: str
    n: int
    years: list[YearRow]
    per_year_pln: int | None  # średni spadek ceny za rok wieku (przy stałym przebiegu)
    per_10k_km_pln: int | None  # średni spadek ceny za 10 tys. km (przy stałym wieku)
    r2: float | None
    points: list[tuple[int, int, int]]  # (przebieg km, cena brutto, rocznik)


@dataclass(frozen=True)
class Exposure:
    model: str
    active_n: int
    active_median_days: int | None
    gone_n: int
    gone_median_days: int | None


def days_listed(offer: Offer, now: datetime, until: datetime | None = None) -> tuple[int, bool]:
    """Dni w ofercie i czy liczone od daty z ogłoszenia (False = od pierwszego skanu)."""
    start = as_utc(offer.listed_at or offer.first_seen_at)
    days = (as_utc(until or now) - start).days
    return max(days, 0), offer.listed_at is not None


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Układ równań liniowych (eliminacja Gaussa z wyborem elementu głównego)."""
    n = len(b)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-9:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def _ols(xs: list[list[float]], ys: list[float]) -> list[float] | None:
    """Regresja liniowa z wyrazem wolnym: [b0, b1, ...]."""
    k = len(xs[0]) + 1
    rows = [[1.0, *x] for x in xs]
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    aty = [sum(r[i] * y for r, y in zip(rows, ys, strict=True)) for i in range(k)]
    return _solve(ata, aty)


def _fit(pts: list[tuple[float, float, float]]) -> tuple[float | None, float | None, float] | None:
    """Cena ~ wiek + przebieg; współczynnik o nielogicznym znaku (>0) jest odrzucany.

    Zwraca (spadek za rok, spadek za 10 tys. km, R²) albo None, gdy dopasowanie niemożliwe.
    """
    ys = [p[2] for p in pts]
    use = [0, 1]  # 0 = wiek, 1 = przebieg
    while use:
        coef = _ols([[p[i] for i in use] for p in pts], ys)
        if coef is None:
            return None
        bad = [i for i, c in zip(use, coef[1:], strict=True) if c > 0]
        if not bad:
            break
        use = [i for i in use if i != bad[0]]
    else:
        return None
    pred = [coef[0] + sum(c * p[i] for c, i in zip(coef[1:], use, strict=True)) for p in pts]
    mean = sum(ys) / len(ys)
    ss_tot = sum((y - mean) ** 2 for y in ys)
    ss_res = sum((y - f) ** 2 for y, f in zip(ys, pred, strict=True))
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    by_var = dict(zip(use, coef[1:], strict=True))
    per_year = -by_var[0] if 0 in by_var else None
    per_km = -by_var[1] if 1 in by_var else None
    return per_year, per_km, r2


def depreciation(offers: list[Offer], ref_year: int) -> list[Depreciation]:
    """Krzywa deprecjacji każdego modelu: mediany cen po rocznikach i spadek za rok / 10 tys. km."""
    groups: dict[str, list[Offer]] = defaultdict(list)
    for o in offers:
        if o.price_gross_pln and o.year and o.mileage_km is not None:
            groups[f"{o.brand} {o.model_matched}"].append(o)
    out: list[Depreciation] = []
    for model, group in sorted(groups.items()):
        by_year: dict[int, list[Offer]] = defaultdict(list)
        for o in group:
            assert o.year is not None
            by_year[o.year].append(o)
        medians = {
            y: round(median(o.price_gross_pln or 0 for o in os)) for y, os in by_year.items()
        }
        rows = []
        for y in sorted(by_year, reverse=True):
            os = by_year[y]
            newer = medians.get(y + 1)
            rows.append(
                YearRow(
                    year=y,
                    n=len(os),
                    price=medians[y],
                    mileage_km=round(median(o.mileage_km or 0 for o in os)),
                    step_pct=(medians[y] - newer) / newer * 100 if newer else None,
                )
            )
        fit = None
        if len(group) >= MIN_FIT_POINTS:
            fit = _fit(
                [
                    (
                        float(max(ref_year - (o.year or ref_year), 0)),
                        (o.mileage_km or 0) / KM_UNIT,
                        float(o.price_gross_pln or 0),
                    )
                    for o in group
                ]
            )
        out.append(
            Depreciation(
                model=model,
                n=len(group),
                years=rows,
                per_year_pln=round(fit[0]) if fit and fit[0] is not None else None,
                per_10k_km_pln=round(fit[1]) if fit and fit[1] is not None else None,
                r2=fit[2] if fit else None,
                points=[(o.mileage_km or 0, o.price_gross_pln or 0, o.year or 0) for o in group],
            )
        )
    return out


def exposure(
    active: list[Offer], gone_days: dict[str, list[int]], now: datetime
) -> list[Exposure]:
    """Czas ekspozycji modeli: wiek aktywnych ofert i czas do zniknięcia tych, które zniknęły."""
    ages: dict[str, list[int]] = defaultdict(list)
    for o in active:
        ages[f"{o.brand} {o.model_matched}"].append(days_listed(o, now)[0])
    rows = []
    for model in sorted(set(ages) | set(gone_days)):
        a, g = ages.get(model, []), gone_days.get(model, [])
        rows.append(
            Exposure(
                model=model,
                active_n=len(a),
                active_median_days=round(median(a)) if a else None,
                gone_n=len(g),
                gone_median_days=round(median(g)) if g else None,
            )
        )
    return rows
