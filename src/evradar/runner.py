"""Orkiestracja skanu: źródła -> dopasowanie -> diff -> zapis -> dane raportu."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import structlog

from evradar.config import ModelsConfig, SourceConfig
from evradar.diff import compute_diff
from evradar.matching import ModelMatcher, Powertrain, passes_filters
from evradar.models import (
    DiffKind,
    Offer,
    OfferDiff,
    RawListing,
    ReportData,
    RunInfo,
    SourceResult,
    SourceStatus,
    StoredOffer,
    make_offer_id,
    utcnow,
)
from evradar.robots import RobotsDisallowed
from evradar.scrapers import get_scraper_class
from evradar.storage import Storage

log = structlog.get_logger()

SOURCE_TIMEOUT_S = 600


def build_offers(
    listings: list[RawListing], matcher: ModelMatcher, models: ModelsConfig, now: datetime
) -> list[Offer]:
    """Dopasowuje surowe ogłoszenia do modeli z configu, stosuje filtry i deduplikuje."""
    offers: dict[str, Offer] = {}
    for item in listings:
        match = matcher.match(item)
        if match is None:
            continue
        if not passes_filters(
            models.filters,
            year=item.year,
            mileage_km=item.mileage_km,
            price_gross=item.price_gross_pln,
        ):
            continue
        offer_id = make_offer_id(item.source, item.external_id, item.url)
        offers[offer_id] = Offer(
            offer_id=offer_id,
            source=item.source,
            url=item.url,
            brand=match.brand,
            model_matched=match.model,
            title_raw=item.title_raw,
            year=item.year,
            mileage_km=item.mileage_km,
            price_gross_pln=item.price_gross_pln,
            price_net_pln=item.price_net_pln,
            monthly_installment_pln=item.monthly_installment_pln,
            installment_basis=item.installment_basis,
            vat_invoice=item.vat_invoice,
            battery_kwh=item.battery_kwh,
            range_km_wltp=item.range_km_wltp,
            drivetrain=item.drivetrain,
            location=item.location,
            image_url=item.image_url,
            first_seen_at=now,
            last_seen_at=now,
            uncertain_powertrain=match.powertrain is Powertrain.UNCERTAIN,
        )
    return list(offers.values())


def _save_debug(source: str, html: str | None, debug_dir: Path) -> Path | None:
    if not html:
        return None
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{source}-{utcnow():%Y%m%d-%H%M%S}.html"
    path.write_text(html, encoding="utf-8")
    return path


async def scan_source(
    cfg: SourceConfig,
    matcher: ModelMatcher,
    models: ModelsConfig,
    *,
    headless: bool,
    prev_raw_count: int,
    debug_dir: Path,
) -> SourceResult:
    """Skanuje jedno źródło; żaden wyjątek nie wychodzi poza tę funkcję."""
    started = time.monotonic()
    result = SourceResult(source=cfg.id, name=cfg.name, status=SourceStatus.OK)
    if not cfg.enabled:
        result.status = SourceStatus.SKIPPED
        result.note = cfg.reason or "źródło wyłączone w config/sources.yaml"
        return result
    try:
        scraper_cls = get_scraper_class(cfg.id)
    except ModuleNotFoundError:
        result.status = SourceStatus.SKIPPED
        result.note = "brak adaptera dla tego źródła"
        return result

    scraper = scraper_cls(cfg, headless=headless)
    try:
        async with scraper, asyncio.timeout(SOURCE_TIMEOUT_S):
            raw = await scraper.fetch()
        result.raw_count = len(raw)
        if not raw and prev_raw_count > 0:
            path = _save_debug(cfg.id, scraper.last_html, debug_dir)
            result.status = SourceStatus.STALE
            result.note = f"parser zwrócił 0 ogłoszeń (wcześniej {prev_raw_count})" + (
                f"; zapisano {path}" if path else ""
            )
            log.warning("source_stale", source=cfg.id, previous=prev_raw_count, debug=str(path))
        else:
            result.offers = build_offers(raw, matcher, models, utcnow())
    except RobotsDisallowed as exc:
        result.status = SourceStatus.SKIPPED
        result.note = str(exc)
        log.warning("source_skipped_robots", source=cfg.id, reason=str(exc))
    except Exception as exc:
        result.status = SourceStatus.ERROR
        result.error = f"{type(exc).__name__}: {exc}"
        _save_debug(cfg.id, scraper.last_html, debug_dir)
        log.error("source_failed", source=cfg.id, error=result.error)
    result.offers_count = len(result.offers)
    result.duration_s = round(time.monotonic() - started, 2)
    log.info(
        "source_done",
        source=cfg.id,
        status=result.status.value,
        raw=result.raw_count,
        offers=result.offers_count,
        duration_s=result.duration_s,
    )
    return result


def assemble_report_data(
    previous: dict[str, StoredOffer],
    results: list[SourceResult],
    diffs: list[OfferDiff],
    started_at: datetime,
    duration_s: float,
    *,
    run_id: int | None,
    dry_run: bool,
) -> ReportData:
    """Składa dane raportu w pamięci (ten sam wynik dla zwykłego runu i dry-run)."""
    scanned = {r.source for r in results if r.status is SourceStatus.OK}
    current: dict[str, Offer] = {o.offer_id: o for r in results for o in r.offers}
    gone_ids = {d.offer.offer_id for d in diffs if d.kind is DiffKind.GONE}
    active: dict[str, Offer] = {
        oid: o
        for oid, o in previous.items()
        if o.active and o.source not in scanned and oid not in gone_ids
    }
    active.update(current)
    by_kind = {k: [d for d in diffs if d.kind is k] for k in DiffKind}
    return ReportData(
        run=RunInfo(run_id=run_id, started_at=started_at, duration_s=duration_s, dry_run=dry_run),
        sources=results,
        active=list(active.values()),
        new=by_kind[DiffKind.NEW],
        price_drops=by_kind[DiffKind.PRICE_DROP],
        price_ups=by_kind[DiffKind.PRICE_UP],
        back=by_kind[DiffKind.BACK],
        gone=by_kind[DiffKind.GONE],
        uncertain=[o for o in active.values() if o.uncertain_powertrain],
    )


async def run_scan(
    sources: list[SourceConfig],
    models: ModelsConfig,
    storage: Storage,
    *,
    headless: bool = True,
    dry_run: bool = False,
    debug_dir: Path = Path("debug"),
    on_source_done: Callable[[SourceResult], None] | None = None,
) -> tuple[ReportData, bool]:
    """Pełny przebieg. Zwraca (dane raportu, czy to pierwszy skan w bazie)."""
    started_at = utcnow()
    t0 = time.monotonic()
    matcher = ModelMatcher(models.targets)

    async def one(cfg: SourceConfig) -> SourceResult:
        res = await scan_source(
            cfg,
            matcher,
            models,
            headless=headless,
            prev_raw_count=storage.last_raw_count(cfg.id),
            debug_dir=debug_dir,
        )
        if on_source_done:
            on_source_done(res)
        return res

    results = list(await asyncio.gather(*(one(c) for c in sources)))

    previous = storage.load_offers()
    first_run = not previous
    scanned = {r.source for r in results if r.status is SourceStatus.OK}
    current = [o for r in results if r.status is SourceStatus.OK for o in r.offers]
    for offer in current:
        old = previous.get(offer.offer_id)
        if old is not None:
            offer.first_seen_at = old.first_seen_at
    diffs = compute_diff(previous, current, scanned)
    duration = round(time.monotonic() - t0, 2)

    run_id: int | None = None
    if not dry_run:
        run_id = storage.save_run(started_at, duration, results, current, diffs)
    data = assemble_report_data(
        previous, results, diffs, started_at, duration, run_id=run_id, dry_run=dry_run
    )
    return data, first_run
