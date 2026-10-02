"""CLI: evradar run | report | sources | demo-report."""

from __future__ import annotations

import asyncio
import logging
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import structlog
import typer
from rich.console import Console
from rich.table import Table

from evradar.config import ROOT_DIR, SourceConfig, load_models_config, load_sources_config
from evradar.demo import synthetic_report_data
from evradar.models import ReportData, SourceResult, SourceStatus
from evradar.notify import notify_new_offers
from evradar.report import build_alt_links, write_report
from evradar.runner import run_scan
from evradar.storage import Storage

app = typer.Typer(help="EV Radar — agregator ofert aut elektrycznych.", no_args_is_help=True)
console = Console()


@app.callback()
def _main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # polskie znaki w konsoli Windows


DB_PATH = ROOT_DIR / "data" / "evradar.db"
OUT_DIR = ROOT_DIR / "out"
DEBUG_DIR = ROOT_DIR / "debug"

_STATUS_STYLE = {
    SourceStatus.OK: "[green]OK[/]",
    SourceStatus.ERROR: "[red]BŁĄD[/]",
    SourceStatus.SKIPPED: "[dim]POMINIĘTE[/]",
    SourceStatus.STALE: "[yellow]DO AKTUALIZACJI[/]",
}


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(sys.stderr),
    )


def _summary(data: ReportData) -> None:
    table = Table(title="EV Radar — podsumowanie skanu")
    table.add_column("Źródło")
    table.add_column("Status")
    table.add_column("Ofert", justify="right")
    table.add_column("Czas [s]", justify="right")
    table.add_column("Uwagi", overflow="fold")
    for s in data.sources:
        table.add_row(
            s.name or s.source,
            _STATUS_STYLE[s.status],
            str(s.offers_count),
            f"{s.duration_s:.1f}",
            (s.error or s.note or "")[:90],
        )
    console.print(table)
    console.print(
        f"Aktywnych: [bold]{len(data.active)}[/] · nowych: [green]{len(data.new)}[/] · "
        f"obniżek: [yellow]{len(data.price_drops)}[/] · zniknęło: {len(data.gone)} · "
        f"do weryfikacji: {len(data.uncertain)} · czas: {data.run.duration_s:.1f} s"
    )


def _write(data: ReportData, out_dir: Path, *, first_run: bool = False) -> Path:
    models = load_models_config()
    max_price = models.filters.max_price_gross_pln
    return write_report(
        data,
        out_dir,
        first_run=first_run,
        alt_links=build_alt_links(models.alternatives, max_price),
        alt_max_price=max_price,
    )


def _finish(data: ReportData, first_run: bool, open_browser: bool) -> Path:
    path = _write(data, OUT_DIR, first_run=first_run)
    console.print(f"Raport: [link=file:///{path.as_posix()}]{path}[/]")
    if open_browser:
        webbrowser.open(path.resolve().as_uri())
    return path


def _select(all_sources: list[SourceConfig], wanted: str | None) -> list[SourceConfig]:
    if not wanted:
        return all_sources
    ids = {s.strip() for s in wanted.split(",") if s.strip()}
    unknown = ids - {s.id for s in all_sources}
    if unknown:
        raise typer.BadParameter(f"Nieznane źródła: {', '.join(sorted(unknown))}")
    return [s for s in all_sources if s.id in ids]


@app.command()
def run(
    source: Annotated[
        str | None, typer.Option(help="Lista źródeł po przecinku, np. vwfs,ayvens")
    ] = None,
    headless: Annotated[
        bool, typer.Option("--headless/--no-headless", help="Widoczna przeglądarka do debugowania")
    ] = True,
    dry_run: Annotated[bool, typer.Option(help="Bez zapisu do bazy")] = False,
    no_open: Annotated[
        bool, typer.Option("--no-open", help="Nie otwieraj raportu w przeglądarce")
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Skanuje źródła, porównuje ze stanem z bazy i generuje raport HTML."""
    _configure_logging(verbose)
    models = load_models_config()
    sources = _select(load_sources_config().sources, source)
    storage = Storage(DB_PATH)
    try:
        data, first_run = asyncio.run(
            run_scan(
                sources,
                models,
                storage,
                headless=headless,
                dry_run=dry_run,
                debug_dir=DEBUG_DIR,
                on_source_done=lambda r: _progress(r),
            )
        )
    finally:
        storage.close()
    _summary(data)
    _finish(data, first_run, open_browser=not no_open)
    if models.notifications.enabled:
        notify_new_offers(models.notifications, data)


def _progress(result: SourceResult) -> None:
    console.print(
        f"  {_STATUS_STYLE[result.status]} {result.name or result.source} ({result.offers_count})"
    )


@app.command()
def report(
    last: Annotated[
        bool, typer.Option("--last", help="Przegeneruj raport z ostatniego skanu")
    ] = True,
    no_open: Annotated[bool, typer.Option("--no-open")] = False,
) -> None:
    """Przegenerowuje raport z bazy, bez skanowania."""
    storage = Storage(DB_PATH)
    try:
        data = storage.load_report_data()
    finally:
        storage.close()
    if data is None:
        console.print("[red]Baza jest pusta — najpierw uruchom: evradar run[/]")
        raise typer.Exit(1)
    _finish(data, first_run=False, open_browser=not no_open)


@app.command()
def sources() -> None:
    """Lista źródeł i status ostatniego skanu."""
    storage = Storage(DB_PATH)
    try:
        last = storage.last_source_status()
    finally:
        storage.close()
    table = Table(title="Źródła")
    for col in ("ID", "Nazwa", "Włączone", "Ostatni skan", "Status", "Ofert", "Uwagi"):
        table.add_column(col, no_wrap=col in ("ID", "Status"), overflow="fold")
    for s in load_sources_config().sources:
        row = last.get(s.id)
        table.add_row(
            s.id,
            s.name,
            "tak" if s.enabled else "[dim]nie[/]",
            row["started_at"][:16].replace("T", " ") if row else "—",
            _STATUS_STYLE[SourceStatus(row["status"])] if row else "—",
            str(row["offers_count"]) if row else "—",
            (s.reason if not s.enabled else (row["error"] or row["note"] or "") if row else "")
            or "",
        )
    console.print(table)


@app.command("demo-report")
def demo_report(no_open: Annotated[bool, typer.Option("--no-open")] = False) -> None:
    """Raport na danych syntetycznych (podgląd wyglądu)."""
    path = _write(synthetic_report_data(), OUT_DIR / "demo")
    console.print(f"Raport demo: {path}")
    if not no_open:
        webbrowser.open(path.resolve().as_uri())


if __name__ == "__main__":
    app()
