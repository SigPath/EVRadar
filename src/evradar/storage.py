"""Magazyn stanu w SQLite: oferty, historia cen, przebiegi, różnice."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
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
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    uncertain_powertrain INTEGER NOT NULL DEFAULT 0,
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

_OFFER_COLUMNS = [
    "offer_id", "source", "url", "brand", "model_matched", "title_raw", "year", "mileage_km",
    "price_gross_pln", "price_net_pln", "monthly_installment_pln", "installment_basis",
    "vat_invoice", "battery_kwh", "range_km_wltp", "drivetrain", "location", "image_url",
    "first_seen_at", "last_seen_at", "uncertain_powertrain",
]  # fmt: skip


class Storage:
    """Cienka warstwa nad `sqlite3` (bez ORM)."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

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

    # --- zapis ------------------------------------------------------------------

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
        return run_id

    def _upsert_offer(self, offer: Offer, old: StoredOffer | None) -> None:
        data = offer.model_dump()
        data["first_seen_at"] = (old.first_seen_at if old else offer.first_seen_at).isoformat()
        data["last_seen_at"] = offer.last_seen_at.isoformat()
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
        )
