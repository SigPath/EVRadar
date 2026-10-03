"""Renderowanie samodzielnego raportu HTML (Jinja2)."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import NamedTuple
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from evradar.config import Alternatives
from evradar.health import Run, source_verdict
from evradar.models import Offer, OfferDiff, ReportData
from evradar.notify import problem_sources

TEMPLATE_DIR = Path(__file__).parent / "templates"
LOCAL_TZ = ZoneInfo("Europe/Warsaw")
NBSP = "\u00a0"
SPARK_W, SPARK_H, SPARK_PAD = 56, 16, 2
MIN_GROUP_YEAR, MIN_GROUP_MODEL = 4, 5  # minimalna liczba ofert do wyliczenia mediany

SELLER_LABELS = {"dealer": "Firma", "private": "Prywatna"}
AltRow = tuple[str, list[tuple[str, str]]]  # (etykieta, [(portal, url)])


class MarketRef(NamedTuple):
    """Cena oferty na tle mediany porównywalnych ofert (brutto)."""

    pct: float
    median: int
    n: int
    scope: str


def market_refs(offers: list[Offer]) -> dict[str, MarketRef]:
    """Odchylenie ceny brutto od mediany: ten sam model i rocznik, a przy małej próbie sam model."""
    by_year: dict[tuple[str, str, int | None], list[int]] = defaultdict(list)
    by_model: dict[tuple[str, str], list[int]] = defaultdict(list)
    for o in offers:
        if o.price_gross_pln:
            by_year[(o.brand, o.model_matched, o.year)].append(o.price_gross_pln)
            by_model[(o.brand, o.model_matched)].append(o.price_gross_pln)
    refs: dict[str, MarketRef] = {}
    for o in offers:
        price = o.price_gross_pln
        if not price:
            continue
        group, scope, need = by_year[(o.brand, o.model_matched, o.year)], "rocznik", MIN_GROUP_YEAR
        if o.year is None or len(group) < need:
            group, scope, need = by_model[(o.brand, o.model_matched)], "model", MIN_GROUP_MODEL
        if len(group) < need:
            continue
        med = round(median(group))
        refs[o.offer_id] = MarketRef((price - med) / med * 100, med, len(group), scope)
    return refs


def build_alt_links(alt: Alternatives, max_price_gross_pln: int | None) -> list[AltRow]:
    """Linki do gotowych wyszukiwań na portalach, których nie skanujemy."""
    rows: list[AltRow] = []
    for search in alt.searches:
        links: list[tuple[str, str]] = []
        for key, site in alt.sites.items():
            path = search.paths.get(key)
            if not path:
                continue
            url = site.url.format(path=path)
            if max_price_gross_pln is not None:
                sep = "&" if "?" in url else "?"
                url += f"{sep}{site.price_param}={max_price_gross_pln}"
            links.append((site.name, url))
        if links:
            rows.append((search.label, links))
    return rows


def _pln(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{round(value):,}".replace(",", NBSP) + f"{NBSP}zł"


def _km(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}".replace(",", NBSP) + f"{NBSP}km"


def _short_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(LOCAL_TZ).strftime("%d.%m.%Y")
    return ""


def _sparkline(points: list[tuple[str, int]]) -> Markup:
    """Miniaturowy wykres zmian ceny (SVG); pusty, gdy oferta nie zmieniała ceny."""
    if len(points) < 2:
        return Markup("")
    stamps = [datetime.fromisoformat(t) for t, _ in points]
    prices = [p for _, p in points]
    t0, span = stamps[0].timestamp(), stamps[-1].timestamp() - stamps[0].timestamp()
    lo, hi = min(prices), max(prices)
    inner_w, inner_h = SPARK_W - 2 * SPARK_PAD, SPARK_H - 2 * SPARK_PAD

    def xy(i: int) -> tuple[float, float]:
        frac = (stamps[i].timestamp() - t0) / span if span else i / (len(points) - 1)
        y = SPARK_PAD + (hi - prices[i]) / (hi - lo) * inner_h if hi > lo else SPARK_H / 2
        return SPARK_PAD + frac * inner_w, y

    coords = [xy(i) for i in range(len(points))]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    kind = "down" if prices[-1] < prices[0] else "up" if prices[-1] > prices[0] else "flat"
    first, last = stamps[0].astimezone(LOCAL_TZ), stamps[-1].astimezone(LOCAL_TZ)
    pct = (prices[-1] - prices[0]) / prices[0] * 100
    label = (
        f"{first:%d.%m} {_pln(prices[0])} → {last:%d.%m} {_pln(prices[-1])} ({pct:+.0f}%)"
    )
    ex, ey = coords[-1]
    return Markup(
        f'<svg class="spark {kind}" width="{SPARK_W}" height="{SPARK_H}" '
        f'viewBox="0 0 {SPARK_W} {SPARK_H}" role="img" aria-label="{label}">'
        f"<title>{label}</title><polyline points=\"{line}\"/>"
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2"/></svg>'
    )


BAR_W, BAR_H, BAR_GAP = 7, 22, 2
_BAR_CLASS = {"OK": "ok", "ERROR": "err", "STALE": "stale", "SKIPPED": "skip"}


class HealthRow(NamedTuple):
    """Zdrowie jednego źródła: ocena, mediana z poprzednich przebiegów i wykres słupkowy."""

    verdict: str
    ref: int | None
    bars: Markup


def _health_bars(runs: list[Run]) -> Markup:
    """Słupki liczby ofert z ostatnich przebiegów (kolor = status)."""
    top = max((n for _, _, n in runs), default=0) or 1
    width = len(runs) * (BAR_W + BAR_GAP)
    parts = []
    for i, (stamp, status, n) in enumerate(runs):
        h = max(2, round(n / top * (BAR_H - 2))) if n else 2
        when = datetime.fromisoformat(stamp).astimezone(LOCAL_TZ)
        css = _BAR_CLASS.get(status, "skip")
        parts.append(
            f'<rect class="{css}" x="{i * (BAR_W + BAR_GAP)}" y="{BAR_H - h}" '
            f'width="{BAR_W}" height="{h}" rx="1">'
            f"<title>{when:%d.%m %H:%M}: {n} ofert ({status})</title></rect>"
        )
    return Markup(
        f'<svg class="bars" width="{width}" height="{BAR_H}" viewBox="0 0 {width} {BAR_H}" '
        f'role="img" aria-label="Liczba ofert w ostatnich przebiegach">{"".join(parts)}</svg>'
    )


def health_rows(data: ReportData) -> dict[str, HealthRow]:
    rows: dict[str, HealthRow] = {}
    for source, runs in data.source_history.items():
        if runs:
            verdict, ref = source_verdict(runs)
            rows[source] = HealthRow(verdict, ref, _health_bars(runs))
    return rows


class TrendRow(NamedTuple):
    model: str
    latest: int
    n: int
    change_pct: float | None
    since: str
    spark: Markup


def trend_rows(trend: dict[str, list[tuple[str, int, int]]]) -> list[TrendRow]:
    """Mediana ceny modelu w czasie (jeden punkt na dzień skanu), posortowane po modelu."""
    rows = []
    for model, points in sorted(trend.items()):
        first, last = points[0], points[-1]
        change = (last[1] - first[1]) / first[1] * 100 if len(points) >= 2 else None
        since = _short_date(datetime.fromisoformat(first[0]))
        spark = _sparkline([(t, m) for t, m, _ in points])
        rows.append(TrendRow(model, last[1], last[2], change, since, spark))
    return rows


def _offer_sort_key(o: Offer) -> tuple[str, str, int]:
    price = o.price_gross_pln if o.price_gross_pln is not None else o.price_net_pln
    return (o.brand, o.model_matched, price if price is not None else 10**9)


def _chips(
    offers: list[Offer], names: dict[str, str]
) -> list[tuple[str, str, list[tuple[str, int]]]]:
    brands = Counter(o.brand for o in offers)
    models = Counter(f"{o.brand} {o.model_matched}" for o in offers)
    sources = Counter(
        names.get(s, s) for o in offers for s in (o.source, *(link.source for link in o.also_on))
    )
    sellers = Counter(SELLER_LABELS[o.seller_type] for o in offers if o.seller_type)
    groups = [
        ("brand", "Marka", sorted(brands.items())),
        ("model", "Model", sorted(models.items())),
        ("source", "Źródło", sorted(sources.items())),
    ]
    if sellers:
        groups.append(("seller", "Sprzedawca", sorted(sellers.items())))
    return groups


def render_report(
    data: ReportData,
    *,
    first_run: bool = False,
    alt_links: list[AltRow] | None = None,
    alt_max_price: int | None = None,
) -> str:
    """Zwraca kompletny HTML raportu (CSS i JS inline)."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pln"] = _pln
    env.filters["km"] = _km
    env.filters["short_date"] = _short_date

    def by_price(diffs: list[OfferDiff]) -> list[OfferDiff]:
        return sorted(diffs, key=lambda x: _offer_sort_key(x.offer))

    data = data.model_copy(
        update={
            "active": sorted(data.active, key=_offer_sort_key),
            "new": by_price(data.new),
            "price_drops": sorted(data.price_drops, key=lambda x: x.delta or 0),
            "price_ups": by_price(data.price_ups),
            "back": by_price(data.back),
            "gone": by_price(data.gone),
            "uncertain": sorted(data.uncertain, key=_offer_sort_key),
        }
    )
    names = {s.source: (s.name or s.source) for s in data.sources}
    history = data.price_history
    env.globals["spark"] = lambda offer_id: _sparkline(history.get(offer_id, []))
    env.globals["offer_sources"] = lambda o: [
        names.get(s, s) for s in (o.source, *(link.source for link in o.also_on))
    ]
    confirmed = [o for o in data.active if not o.uncertain_powertrain]
    tracked_models = {f"{o.brand} {o.model_matched}" for o in data.active}
    local = data.run.started_at.astimezone(LOCAL_TZ)
    return env.get_template("report.html.j2").render(
        d=data,
        source_names=names,
        confirmed=confirmed,
        chip_groups=_chips(confirmed, names),
        market=market_refs(confirmed),
        health=health_rows(data),
        seller_labels=SELLER_LABELS,
        trend=trend_rows(
            {m: pts for m, pts in data.model_trend.items() if m in tracked_models}
        ),
        problems=problem_sources(data),
        run_iso=data.run.started_at.isoformat(),
        new_ids={x.offer.offer_id for x in data.new},
        drop_ids={x.offer.offer_id for x in data.price_drops},
        ok_count=sum(1 for s in data.sources if s.status.value == "OK"),
        run_date=local.strftime("%d.%m.%Y"),
        run_time=local.strftime("%H:%M"),
        first_run=first_run,
        alt_links=alt_links or [],
        alt_max_price=alt_max_price,
    )


def write_report(
    data: ReportData,
    out_dir: Path,
    *,
    first_run: bool = False,
    alt_links: list[AltRow] | None = None,
    alt_max_price: int | None = None,
) -> Path:
    """Zapisuje raport jako out/index.html (nadpisywany przy każdym skanie)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    html = render_report(
        data, first_run=first_run, alt_links=alt_links, alt_max_price=alt_max_price
    )
    path.write_text(html, encoding="utf-8")
    return path
