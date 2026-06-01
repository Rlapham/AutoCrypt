"""DuckDB-backed event store (point-in-time-correct, append-only).

One unified `events` table: typed envelope columns (fast filtering on the replay gate
`knowable_at`) plus a JSON `payload` holding every type-specific field losslessly.
Idempotent on `event_id` (re-ingest replaces; corrections have a new id via `revision`).

The core replay primitive is a single ordered scan gated on `knowable_at`:
    SELECT * FROM events WHERE knowable_at <= :T ORDER BY knowable_at, block_slot
This is the ONLY sanctioned visibility filter — never gate on `observed_at`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from autocrypt.schema import BaseEvent, EventType


def _one(cur: duckdb.DuckDBPyConnection) -> tuple[Any, ...]:
    """fetchone() that asserts a row exists (aggregate queries always return one)."""
    row = cur.fetchone()
    assert row is not None
    return row


_DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id        VARCHAR PRIMARY KEY,
    schema_version  VARCHAR,
    event_type      VARCHAR,
    chain           VARCHAR,
    source          VARCHAR,
    event_time      TIMESTAMPTZ,
    knowable_at     TIMESTAMPTZ,
    observed_at     TIMESTAMPTZ,
    block_slot      BIGINT,
    commitment      VARCHAR,
    revision        INTEGER,
    pool_address    VARCHAR,
    base_mint       VARCHAR,
    quote_mint      VARCHAR,
    actor           VARCHAR,
    tx_signature    VARCHAR,
    amount_usd      DOUBLE,
    payload         VARCHAR,           -- full model_dump as JSON text (lossless)
    ingested_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_knowable  ON events(knowable_at);
CREATE INDEX IF NOT EXISTS idx_events_eventtime ON events(event_time);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_pool      ON events(pool_address);
CREATE INDEX IF NOT EXISTS idx_events_base      ON events(base_mint);
CREATE INDEX IF NOT EXISTS idx_events_actor     ON events(actor);
"""

_COLUMNS = [
    "event_id",
    "schema_version",
    "event_type",
    "chain",
    "source",
    "event_time",
    "knowable_at",
    "observed_at",
    "block_slot",
    "commitment",
    "revision",
    "pool_address",
    "base_mint",
    "quote_mint",
    "actor",
    "tx_signature",
    "amount_usd",
    "payload",
]


def _actor_of(payload: dict[str, Any]) -> str | None:
    """The principal wallet for the record (signer/wallet/creator), if any."""
    for key in ("signer", "wallet", "creator"):
        if payload.get(key):
            return payload[key]
    return None


def event_to_row(e: BaseEvent) -> list[Any]:
    """Flatten an event into the `events` column order."""
    payload = e.model_dump(mode="json")
    amt = payload.get("amount_usd")
    try:
        amount_usd = float(amt) if amt is not None else None
    except (TypeError, ValueError):
        amount_usd = None
    return [
        e.event_id(),
        e.schema_version,
        e.event_type.value,
        e.chain.value,
        e.source.value,
        e.event_time,
        e.knowable_at,
        e.observed_at,
        e.block_slot,
        e.commitment.value,
        e.revision,
        payload.get("pool_address"),
        payload.get("base_mint"),
        payload.get("quote_mint"),
        _actor_of(payload),
        payload.get("tx_signature"),
        amount_usd,
        json.dumps(payload, default=str),
    ]


class EventStore:
    """Thin DuckDB wrapper for the canonical event store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.db_path))
        self.con.execute(_DDL)

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── writes ────────────────────────────────────────────────────────────────
    def write_events(self, events: Iterable[BaseEvent]) -> int:
        rows = [event_to_row(e) for e in events]
        if not rows:
            return 0
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        cols = ", ".join(_COLUMNS)
        # INSERT OR REPLACE → idempotent re-ingest keyed on event_id.
        self.con.executemany(
            f"INSERT OR REPLACE INTO events ({cols}) VALUES ({placeholders})", rows
        )
        return len(rows)

    # ── reads ─────────────────────────────────────────────────────────────────
    def count(self) -> int:
        return _one(self.con.execute("SELECT count(*) FROM events"))[0]

    def counts_by_type(self) -> dict[str, int]:
        rows = self.con.execute(
            "SELECT event_type, count(*) FROM events GROUP BY event_type ORDER BY 2 DESC"
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def time_bounds(self) -> dict[str, Any]:
        row = _one(
            self.con.execute(
                "SELECT min(event_time), max(event_time), min(knowable_at), max(knowable_at) "
                "FROM events"
            )
        )
        return {
            "event_time_min": row[0],
            "event_time_max": row[1],
            "knowable_at_min": row[2],
            "knowable_at_max": row[3],
        }

    def distinct_pools(self) -> int:
        return _one(
            self.con.execute(
                "SELECT count(DISTINCT pool_address) FROM events WHERE pool_address IS NOT NULL"
            )
        )[0]

    def replay(
        self, until: datetime, types: Sequence[EventType] | None = None
    ) -> list[dict[str, Any]]:
        """Return all records visible at decision time `until` (knowable_at <= until),
        ordered by knowable_at then block_slot. This is the point-in-time replay gate."""
        q = "SELECT * FROM events WHERE knowable_at <= ?"
        params: list[Any] = [until]
        if types:
            placeholders = ", ".join(["?"] * len(types))
            q += f" AND event_type IN ({placeholders})"
            params.extend(t.value for t in types)
        q += " ORDER BY knowable_at, block_slot"
        cur = self.con.execute(q, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def export_parquet(self, out_dir: str | Path) -> list[Path]:
        """Export one Parquet file per event_type, partitioned implicitly by type."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for etype in self.counts_by_type():
            path = out / f"{etype}.parquet"
            # NOTE: DuckDB silently writes nothing when a bind parameter appears in BOTH
            # the WHERE clause and the COPY TO target. Keep the path a (quote-escaped)
            # literal and parameterize only the filter.
            literal = str(path).replace("'", "''")
            self.con.execute(
                f"COPY (SELECT * FROM events WHERE event_type = ? ORDER BY knowable_at) "
                f"TO '{literal}' (FORMAT PARQUET)",
                [etype],
            )
            written.append(path)
        return written
