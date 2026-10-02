"""Renderowanie samodzielnego raportu HTML (Jinja2)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from evradar.config import Alternatives
from evradar.models import Offer, OfferDiff, ReportData

TEMPLATE_DIR = Path(__file__).parent / "templates"
LOCAL_TZ = ZoneInfo("Europe/Warsaw")
NBSP = "\u00a0"

AltRow = tuple[str, list[tuple[str, str]]]  # (etykieta, [(portal, url)])


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


def _offer_sort_key(o: Offer) -> tuple[str, str, int]:
    price = o.price_gross_pln if o.price_gross_pln is not None else o.price_net_pln
    return (o.brand, o.model_matched, price if price is not None else 10**9)


def _chips(
    offers: list[Offer], names: dict[str, str]
) -> list[tuple[str, str, list[tuple[str, int]]]]:
    brands = Counter(o.brand for o in offers)
    models = Counter(f"{o.brand} {o.model_matched}" for o in offers)
    sources = Counter(names.get(o.source, o.source) for o in offers)
    return [
        ("brand", "Marka", sorted(brands.items())),
        ("model", "Model", sorted(models.items())),
        ("source", "Źródło", sorted(sources.items())),
    ]


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
    confirmed = [o for o in data.active if not o.uncertain_powertrain]
    local = data.run.started_at.astimezone(LOCAL_TZ)
    return env.get_template("report.html.j2").render(
        d=data,
        source_names=names,
        confirmed=confirmed,
        chip_groups=_chips(confirmed, names),
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
