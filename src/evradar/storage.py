"""Magazyn stanu w SQLite: oferty, historia cen, przebiegi, różnice."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from evradar.models import (
    DiffKind,
    Offer,
    OfferDiff,
    ReportData,
    RunInfo,
    SourceResult,
    SourceStatus,
    StoredOffer,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    brand TEXT NOT NULL,
    model_matched TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    year INTEGER,
    mileage_km INTEGER,
    price_gross_pln INTEGER,
    price_net_pln INTEGER,
    monthly_installment_pln INTEGER,
    installment_basis TEXT,
    vat_invoice INTEGER,
    battery_kwh REAL,
    range_km_wltp INTEGER,
    drivetrain TEXT,
    location TEXT,
    image_url TEXT,
    seller_type TEXT,
    listed_at TEXT,
    soh_pct INTEGER,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    uncertain_powertrain INTEGER NOT NULL DEFAULT 0,
    also_on TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_offers_source ON offers(source, active);
CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id TEXT NOT NULL REFERENCES offers(offer_id),
    seen_at TEXT NOT NULL,
    price_gross_pln INTEGER,
    price_net_pln INTEGER
);
CREATE INDEX IF NOT EXISTS idx_history_offer ON price_history(offer_id);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    duration_s REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS source_runs (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    offers_count INTEGER NOT NULL DEFAULT 0,
    raw_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    note TEXT,
    duration_s REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS diffs (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    kind TEXT NOT NULL,
    offer_id TEXT NOT NULL REFERENCES offers(offer_id),
    old_price INTEGER,
    new_price INTEGER,
    price_basis TEXT
);
"""

# kolumny dodane po pierwszej wersji schematu (migracja istniejących baz)
_ADDED_COLUMNS = {
    "seller_type": "TEXT",
    "listed_at": "TEXT",
    "soh_pct": "INTEGER",
    "also_on": "TEXT",
}

_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_stats (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    model TEXT NOT NULL,
    n INTEGER NOT NULL,
    median_gross_pln INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stats_model ON model_stats(model);
"""

MIN_STATS_GROUP = 3  # minimalna liczba ofert modelu w statystyce trendu

_OFFER_COLUMNS = [
    "offer_id", "source", "url", "brand", "model_matched", "title_raw", "year", "mileage_km",
    "price_gross_pln", "price_net_pln", "monthly_installment_pln", "installment_basis",
    "vat_invoice", "battery_kwh", "range_km_wltp", "drivetrain", "location", "image_url",
    "seller_type", "listed_at", "soh_pct",
    "first_seen_at", "last_seen_at", "uncertain_powertrain", "also_on",
]  # fmt: skip


class Storage:
    """Cienka warstwa nad `sqlite3` (bez ORM)."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(offers)")}
        for column, sql_type in _ADDED_COLUMNS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE offers ADD COLUMN {column} {sql_type}")
        self.conn.executescript(_STATS_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def backup(self, dest: Path) -> None:
        """Spójna kopia bazy (API backup SQLite, bezpieczna przy otwartym połączeniu)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        try:
            self.conn.backup(target)
        finally:
            target.close()

    # --- odczyt -----------------------------------------------------------------

    def load_offers(self) -> dict[str, StoredOffer]:
        rows = self.conn.execute("SELECT * FROM offers").fetchall()
        return {r["offer_id"]: StoredOffer.model_validate(dict(r)) for r in rows}

    def last_raw_count(self, source: str) -> int:
        """Ile surowych ogłoszeń zwrócił parser w ostatnim skanie źródła (0 = brak danych)."""
        row = self.conn.execute(
            "SELECT raw_count FROM source_runs WHERE source = ? AND status IN ('OK') "
            "ORDER BY run_id DESC LIMIT 1",
            (source,),
        ).fetchone()
        return int(row["raw_count"]) if row else 0

    def last_run_id(self) -> int | None:
        row = self.conn.execute("SELECT MAX(id) AS id FROM runs").fetchone()
        return int(row["id"]) if row and row["id"] is not None else None

    def last_source_status(self) -> dict[str, dict[str, Any]]:
        """Ostatni znany wynik każdego źródła."""
        rows = self.conn.execute(
            "SELECT sr.*, r.started_at FROM source_runs sr JOIN runs r ON r.id = sr.run_id "
            "WHERE sr.run_id = (SELECT MAX(run_id) FROM source_runs s2 WHERE s2.source = sr.source)"
        ).fetchall()
        return {r["source"]: dict(r) for r in rows}

    def price_history(self, offer_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM price_history WHERE offer_id = ? ORDER BY id", (offer_id,)
        ).fetchall()

    def load_price_history(self) -> dict[str, list[tuple[str, int]]]:
        """Zmiany ceny (brutto, a gdy brak — netto); tylko oferty z co najmniej dwiema cenami."""
        rows = self.conn.execute(
            "SELECT offer_id, seen_at, price_gross_pln, price_net_pln "
            "FROM price_history ORDER BY id"
        )
        out: dict[str, list[tuple[str, int]]] = {}
        for r in rows:
            price = r["price_gross_pln"] if r["price_gross_pln"] is not None else r["price_net_pln"]
            if price is None:
                continue
            points = out.setdefault(r["offer_id"], [])
            if not points or points[-1][1] != price:
                points.append((r["seen_at"], int(price)))
        return {k: v for k, v in out.items() if len(v) >= 2}

    def load_model_trend(self) -> dict[str, list[tuple[str, int, int]]]:
        """Mediana ceny brutto modelu w czasie: model -> [(data ISO, mediana, liczba ofert)]."""
        rows = self.conn.execute(
            "SELECT ms.model, r.started_at, ms.median_gross_pln, ms.n "
            "FROM model_stats ms JOIN runs r ON r.id = ms.run_id ORDER BY r.id"
        )
        by_day: dict[str, dict[str, tuple[str, int, int]]] = {}
        for r in rows:
            day = str(r["started_at"])[:10]
            by_day.setdefault(r["model"], {})[day] = (
                r["started_at"],
                int(r["median_gross_pln"]),
                int(r["n"]),
            )
        return {m: list(days.values()) for m, days in by_day.items()}

    def source_history(self, last_n: int = 14) -> dict[str, list[tuple[str, str, int]]]:
        """Ostatnie przebiegi źródła: source -> [(data ISO, status, ofert)], od najstarszych."""
        rows = self.conn.execute(
            "SELECT sr.source, r.started_at, sr.status, sr.offers_count FROM source_runs sr "
            "JOIN runs r ON r.id = sr.run_id ORDER BY sr.run_id"
        )
        out: dict[str, list[tuple[str, str, int]]] = {}
        for r in rows:
            out.setdefault(r["source"], []).append(
                (r["started_at"], r["status"], int(r["offers_count"]))
            )
        return {k: v[-last_n:] for k, v in out.items()}

    # --- zapis ------------------------------------------------------------------

    def deactivate_untracked(self, tracked: set[tuple[str, str]]) -> int:
        """Wyłącza oferty modeli usuniętych z configu (bez wpisu w różnicach „znikło”)."""
        stale = [
            (r["offer_id"],)
            for r in self.conn.execute(
                "SELECT offer_id, brand, model_matched FROM offers WHERE active = 1"
            )
            if (r["brand"], r["model_matched"]) not in tracked
        ]
        with self.conn:
            self.conn.executemany("UPDATE offers SET active = 0 WHERE offer_id = ?", stale)
        return len(stale)

    def save_run(
        self,
        started_at: datetime,
        duration_s: float,
        results: list[SourceResult],
        offers: list[Offer],
        diffs: list[OfferDiff],
    ) -> int:
        """Zapisuje przebieg atomowo: oferty (upsert), historię cen, zniknięcia, różnice."""
        previous = self.load_offers()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs (started_at, duration_s) VALUES (?, ?)",
                (started_at.isoformat(), duration_s),
            )
            run_id = int(cur.lastrowid or 0)

            for offer in offers:
                self._upsert_offer(offer, previous.get(offer.offer_id))

            for diff in diffs:
                if diff.kind is DiffKind.GONE:
                    self.conn.execute(
                        "UPDATE offers SET active = 0 WHERE offer_id = ?", (diff.offer.offer_id,)
                    )
                self.conn.execute(
                    "INSERT INTO diffs (run_id, kind, offer_id, old_price, new_price, price_basis) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        diff.kind.value,
                        diff.offer.offer_id,
                        diff.old_price,
                        diff.new_price,
                        diff.price_basis,
                    ),
                )

            for res in results:
                self.conn.execute(
                    "INSERT INTO source_runs (run_id, source, name, status, offers_count, "
                    "raw_count, error, note, duration_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        res.source,
                        res.name,
                        res.status.value,
                        res.offers_count,
                        res.raw_count,
                        res.error,
                        res.note,
                        res.duration_s,
                    ),
                )
            self._save_model_stats(run_id)
        return run_id

    def _save_model_stats(self, run_id: int) -> None:
        """Zapisuje medianę ceny brutto każdego modelu (aktywne, potwierdzone oferty)."""
        groups: dict[str, list[int]] = {}
        for r in self.conn.execute(
            "SELECT brand, model_matched, price_gross_pln FROM offers "
            "WHERE active = 1 AND uncertain_powertrain = 0 AND price_gross_pln IS NOT NULL"
        ):
            groups.setdefault(f"{r['brand']} {r['model_matched']}", []).append(r["price_gross_pln"])
        for model, prices in groups.items():
            if len(prices) >= MIN_STATS_GROUP:
                self.conn.execute(
                    "INSERT INTO model_stats (run_id, model, n, median_gross_pln) "
                    "VALUES (?, ?, ?, ?)",
                    (run_id, model, len(prices), round(median(prices))),
                )

    def _upsert_offer(self, offer: Offer, old: StoredOffer | None) -> None:
        data = offer.model_dump()
        data["first_seen_at"] = (old.first_seen_at if old else offer.first_seen_at).isoformat()
        data["last_seen_at"] = offer.last_seen_at.isoformat()
        data["listed_at"] = offer.listed_at.isoformat() if offer.listed_at else None
        data["also_on"] = json.dumps(data["also_on"]) if data["also_on"] else None
        values = [data[c] for c in _OFFER_COLUMNS]
        placeholders = ", ".join("?" for _ in _OFFER_COLUMNS)
        updates = ", ".join(
            f"{c}=excluded.{c}" for c in _OFFER_COLUMNS if c not in ("offer_id", "first_seen_at")
        )
        self.conn.execute(
            f"INSERT INTO offers ({', '.join(_OFFER_COLUMNS)}, active) "
            f"VALUES ({placeholders}, 1) ON CONFLICT(offer_id) DO UPDATE SET {updates}, active=1",
            values,
        )
        changed = (
            old is None
            or not old.active
            or old.price_gross_pln != offer.price_gross_pln
            or old.price_net_pln != offer.price_net_pln
        )
        if changed:
            self.conn.execute(
                "INSERT INTO price_history (offer_id, seen_at, price_gross_pln, price_net_pln) "
                "VALUES (?, ?, ?, ?)",
                (
                    offer.offer_id,
                    offer.last_seen_at.isoformat(),
                    offer.price_gross_pln,
                    offer.price_net_pln,
                ),
            )

    # --- raport z bazy ------------------------------------------------------------

    def load_report_data(self, run_id: int | None = None) -> ReportData | None:
        """Odtwarza dane raportu dla przebiegu (domyślnie ostatniego) bez skanowania."""
        run_id = run_id or self.last_run_id()
        if run_id is None:
            return None
        run_row = self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run_row is None:
            return None

        offers = self.load_offers()
        sources = [
            SourceResult(
                source=r["source"],
                name=r["name"],
                status=SourceStatus(r["status"]),
                offers_count=r["offers_count"],
                raw_count=r["raw_count"],
                error=r["error"],
                note=r["note"],
                duration_s=r["duration_s"],
            )
            for r in self.conn.execute(
                "SELECT * FROM source_runs WHERE run_id = ? ORDER BY rowid", (run_id,)
            )
        ]
        by_kind: dict[DiffKind, list[OfferDiff]] = {k: [] for k in DiffKind}
        for r in self.conn.execute("SELECT * FROM diffs WHERE run_id = ?", (run_id,)):
            offer = offers.get(r["offer_id"])
            if offer is None:
                continue
            kind = DiffKind(r["kind"])
            by_kind[kind].append(
                OfferDiff(
                    kind=kind,
                    offer=offer,
                    old_price=r["old_price"],
                    new_price=r["new_price"],
                    price_basis=r["price_basis"],
                )
            )
        active = [o for o in offers.values() if o.active]
        return ReportData(
            run=RunInfo(
                run_id=run_id,
                started_at=datetime.fromisoformat(run_row["started_at"]),
                duration_s=run_row["duration_s"],
            ),
            sources=sources,
            active=active,
            new=by_kind[DiffKind.NEW],
            price_drops=by_kind[DiffKind.PRICE_DROP],
            price_ups=by_kind[DiffKind.PRICE_UP],
            back=by_kind[DiffKind.BACK],
            gone=by_kind[DiffKind.GONE],
            uncertain=[o for o in active if o.uncertain_powertrain],
            price_history=self.load_price_history(),
            model_trend=self.load_model_trend(),
            source_history=self.source_history(),
        )


def make_backup(storage: Storage, backup_dir: Path, *, day: str, keep: int = 14) -> Path:
    """Kopia dzienna `evradar-<day>.db` (nadpisywana tego dnia); zostaje `keep` najnowszych."""
    dest = backup_dir / f"evradar-{day}.db"
    storage.backup(dest)
    for old in sorted(backup_dir.glob("evradar-*.db"), reverse=True)[keep:]:
        old.unlink()
    return dest
