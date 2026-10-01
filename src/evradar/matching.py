"""Normalizacja tekstu, dopasowanie modeli z konfiguracji i ocena napędu (`is_electric`)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from rapidfuzz import fuzz

from evradar.config import Filters, ModelTarget
from evradar.models import RawListing

FUZZY_THRESHOLD = 90
FUZZY_MIN_LEN = 5
MAX_NGRAM = 4

_TOKEN = re.compile(r"[a-z0-9]+")
_FUEL_POSITIVE = re.compile(r"elektry|electric|\bbev\b|\bev\b|\bprad\b")
_FUEL_NEGATIVE = re.compile(
    r"hybryd|hybrid|phev|\bhev\b|mhev|plug|spalin|benzyn|diesel|\bon\b|\bpb\b|lpg|\bcng\b|gasoline"
)
_TEXT_STRONG_POSITIVE = re.compile(r"elektryczn|\belectric\b|\bbev\b|\bev\b|\be-?niro\b|zeroemisy")
_TEXT_KWH = re.compile(r"\bkwh\b")
_TEXT_NEGATIVE = re.compile(
    r"hybryd|hybrid|\bphev\b|\bhev\b|\bmhev\b|plug-?in|spalinow|benzyn|diesel|\btdi\b|\bgdi\b"
)


class Powertrain(StrEnum):
    ELECTRIC = "electric"
    NOT_ELECTRIC = "not_electric"
    UNCERTAIN = "uncertain"


def _fold(text: str) -> str:
    """Małe litery + usunięcie diakrytyków (ł -> l)."""
    text = text.replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def tokens(text: str) -> list[str]:
    """Tokeny alfanumeryczne (bez myślników, spacji i diakrytyków)."""
    return _TOKEN.findall(_fold(text))


def normalize(text: str) -> str:
    """Postać porównawcza: lowercase, bez diakrytyków, myślników i spacji."""
    return "".join(tokens(text))


def is_electric(fuel: str | None, title: str | None, description: str | None = None) -> Powertrain:
    """Niezależnie ocenia pole paliwa oraz tytuł/opis; konflikt lub brak danych = UNCERTAIN."""
    fuel_f = _fold(fuel or "")
    text_f = _fold(f"{title or ''} {description or ''}")

    fuel_pos = bool(fuel_f and _FUEL_POSITIVE.search(fuel_f))
    fuel_neg = bool(fuel_f and _FUEL_NEGATIVE.search(fuel_f))
    text_pos_strong = bool(_TEXT_STRONG_POSITIVE.search(text_f))
    text_kwh = bool(_TEXT_KWH.search(text_f))
    text_neg = bool(_TEXT_NEGATIVE.search(text_f))

    if fuel_pos and not fuel_neg:
        return Powertrain.UNCERTAIN if text_neg else Powertrain.ELECTRIC
    if fuel_neg and not fuel_pos:
        return Powertrain.UNCERTAIN if text_pos_strong and not text_neg else Powertrain.NOT_ELECTRIC
    if fuel_pos and fuel_neg:
        return Powertrain.UNCERTAIN
    # brak informacji o paliwie — tylko tekst
    if text_neg:
        return Powertrain.UNCERTAIN if text_pos_strong and not text_kwh else Powertrain.NOT_ELECTRIC
    if text_pos_strong or text_kwh:
        return Powertrain.ELECTRIC
    return Powertrain.UNCERTAIN


@dataclass(frozen=True)
class MatchResult:
    brand: str
    model: str
    powertrain: Powertrain
    via_fuzzy: bool = False


@dataclass(frozen=True)
class _Alias:
    target: ModelTarget
    norm: str


class ModelMatcher:
    """Dopasowuje ogłoszenie do modeli z `config/models.yaml`."""

    def __init__(self, targets: list[ModelTarget]) -> None:
        self._aliases: list[_Alias] = []
        for target in targets:
            seen: set[str] = set()
            for alias in [target.model, *target.aliases]:
                norm = normalize(alias)
                if norm and norm not in seen:
                    seen.add(norm)
                    self._aliases.append(_Alias(target, norm))
        self._brands = {normalize(t.brand): t.brand for t in targets}

    @staticmethod
    def _ngrams(toks: list[str]) -> set[str]:
        grams: set[str] = set()
        for i in range(len(toks)):
            for n in range(1, MAX_NGRAM + 1):
                if i + n <= len(toks):
                    grams.add("".join(toks[i : i + n]))
        return grams

    def _find(self, brand_norm: str, grams: set[str]) -> tuple[ModelTarget, str, bool] | None:
        """Najlepszy (najdłuższy) trafiony alias: dokładny, a potem rozmyty."""
        best: tuple[ModelTarget, str, bool] | None = None
        for alias in self._aliases:
            if normalize(alias.target.brand) != brand_norm:
                continue
            if alias.norm in grams and (best is None or len(alias.norm) > len(best[1])):
                best = (alias.target, alias.norm, False)
        if best:
            return best
        for alias in self._aliases:
            if normalize(alias.target.brand) != brand_norm or len(alias.norm) < FUZZY_MIN_LEN:
                continue
            for gram in grams:
                if len(gram) < FUZZY_MIN_LEN or _digits(gram) != _digits(alias.norm):
                    continue  # różnica w cyfrach to inny model (Ioniq 5 vs 6)
                if alias.norm.startswith(gram):
                    continue  # ucięty alias to inny model (Model vs Model Y)
                if fuzz.ratio(alias.norm, gram) >= FUZZY_THRESHOLD:
                    return alias.target, alias.norm, True
        return None

    def match(self, listing: RawListing) -> MatchResult | None:
        """Zwraca dopasowanie albo None (inny model, nie-elektryk dla `require_electric`)."""
        haystack = " ".join(p for p in (listing.brand, listing.model, listing.title_raw) if p)
        toks = tokens(haystack)
        grams = self._ngrams(toks)
        candidates = [b for b in self._brands if b in toks or b in grams]
        if listing.brand and normalize(listing.brand) in self._brands:
            candidates.insert(0, normalize(listing.brand))

        for brand_norm in dict.fromkeys(candidates):
            found = self._find(brand_norm, grams)
            if found is None:
                continue
            target, _, fuzzy = found
            power = is_electric(listing.fuel, haystack, listing.description)
            if target.require_electric:
                if power is Powertrain.NOT_ELECTRIC:
                    return None
            else:
                # model wyłącznie elektryczny: brak danych = EV, sprzeczność = do weryfikacji
                power = (
                    Powertrain.UNCERTAIN
                    if power is Powertrain.NOT_ELECTRIC
                    else Powertrain.ELECTRIC
                )
            return MatchResult(
                brand=target.brand.title(),
                model=target.model,
                powertrain=power,
                via_fuzzy=fuzzy,
            )
        return None


def passes_filters(
    filters: Filters, *, year: int | None, mileage_km: int | None, price_gross: int | None
) -> bool:
    """Filtry z konfiguracji; brak danych w ofercie nie wyklucza jej (nie zgadujemy)."""
    if filters.min_year is not None and year is not None and year < filters.min_year:
        return False
    max_km = filters.max_mileage_km
    if max_km is not None and mileage_km is not None and mileage_km > max_km:
        return False
    max_price = filters.max_price_gross_pln
    return not (max_price is not None and price_gross is not None and price_gross > max_price)
