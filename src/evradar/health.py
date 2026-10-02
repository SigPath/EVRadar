"""Ocena zdrowia źródła na podstawie historii liczby ofert z ostatnich przebiegów."""

from __future__ import annotations

from statistics import median

DROP_RATIO = 0.5  # spadek poniżej połowy zwykłej liczby ofert uznajemy za podejrzany
REF_WINDOW = 7

Run = tuple[str, str, int]  # (data ISO, status, liczba ofert)


def source_verdict(runs: list[Run]) -> tuple[str, int | None]:
    """Zwraca (kod oceny, mediana ofert z poprzednich udanych przebiegów).

    Kody: ok, drop, error, stale, skipped.
    """
    *earlier, last = runs
    ok_counts = [n for _, status, n in earlier if status == "OK" and n > 0][-REF_WINDOW:]
    ref = round(median(ok_counts)) if ok_counts else None
    status, count = last[1], last[2]
    if status == "OK":
        return ("drop" if ref and count < ref * DROP_RATIO else "ok"), ref
    return status.lower(), ref
