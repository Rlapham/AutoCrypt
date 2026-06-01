"""Data-quality checks over the event store.

Covers the failure modes that matter for this project: look-ahead (knowable_at <
event_time), future timestamps, duplicates, orphan references, bad amounts, and OHLCV
gaps. Each check returns ok / warn / fail so a run can be gated in CI or before Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from autocrypt.storage.store import EventStore

Status = Literal["ok", "warn", "fail"]


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    count: int = 0


@dataclass
class QCReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: Status, detail: str, count: int = 0) -> None:
        self.checks.append(Check(name, status, detail, count))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]

    def ok(self) -> bool:
        return not self.failed


def run_quality_checks(store: EventStore, now: datetime | None = None) -> QCReport:
    """Run all data-quality checks and return a structured report."""
    con = store.con
    now = now or datetime.now(UTC)
    future_cutoff = now + timedelta(minutes=5)  # allow minor clock skew
    r = QCReport()

    def scalar(sql: str, params: list[Any] | None = None) -> Any:
        row = con.execute(sql, params or []).fetchone()
        assert row is not None
        return row[0]

    def row1(sql: str, params: list[Any] | None = None) -> tuple[Any, ...]:
        row = con.execute(sql, params or []).fetchone()
        assert row is not None
        return row

    total = store.count()
    r.add("row_count", "ok" if total > 0 else "warn", f"{total} rows in store", total)
    if total == 0:
        return r

    # 1) LOOK-AHEAD: knowable_at must never precede event_time.
    n = scalar("SELECT count(*) FROM events WHERE knowable_at < event_time")
    r.add(
        "lookahead_knowable_before_event",
        "fail" if n else "ok",
        "rows where knowable_at < event_time (look-ahead!)" if n else "no look-ahead violations",
        n,
    )

    # 2) FUTURE timestamps (event_time / knowable_at beyond now+skew).
    n = scalar(
        "SELECT count(*) FROM events WHERE event_time > ? OR knowable_at > ?",
        [future_cutoff, future_cutoff],
    )
    r.add(
        "future_timestamps",
        "fail" if n else "ok",
        "rows stamped in the future" if n else "no future timestamps",
        n,
    )

    # 3) DUPLICATES: a genuine dupe is the SAME (tx_signature, instruction_index, type)
    # mapping to >1 event_id (i.e. a hashing/id bug). NOTE: one tx legitimately holds
    # many swaps at different instruction indices — those are NOT duplicates, so we must
    # key on instruction_index, not just tx_signature.
    n = scalar(
        """
        SELECT count(*) FROM (
            SELECT tx_signature,
                   json_extract_string(payload, '$.instruction_index') AS instr,
                   event_type
            FROM events WHERE tx_signature IS NOT NULL
            GROUP BY tx_signature, instr, event_type
            HAVING count(DISTINCT event_id) > 1
        )
        """
    )
    r.add(
        "logical_duplicates",
        "warn" if n else "ok",
        "(tx,instr,type) groups with >1 event_id (id bug)" if n else "no logical dupes",
        n,
    )

    # 4) ORPHAN swaps: a swap whose pool has no PoolCreated record.
    n = scalar(
        """
        SELECT count(*) FROM events s
        WHERE s.event_type = 'swap'
          AND NOT EXISTS (
            SELECT 1 FROM events p
            WHERE p.event_type = 'pool_created' AND p.pool_address = s.pool_address
          )
        """
    )
    r.add(
        "orphan_swaps",
        "warn" if n else "ok",
        "swaps with no PoolCreated for their pool" if n else "every swap has a pool",
        n,
    )

    # 5) BAD AMOUNTS: negative USD amounts (raw amounts are stored as magnitudes).
    n = scalar("SELECT count(*) FROM events WHERE amount_usd < 0")
    r.add(
        "negative_amount_usd",
        "fail" if n else "ok",
        "rows with negative amount_usd" if n else "no negative USD amounts",
        n,
    )

    # 6) NULL critical fields on swaps (signer / tx_signature).
    n = scalar(
        "SELECT count(*) FROM events WHERE event_type='swap' AND (actor IS NULL OR tx_signature IS NULL)"
    )
    r.add(
        "swap_missing_keys",
        "fail" if n else "ok",
        "swaps missing signer/tx_signature" if n else "swaps have signer+signature",
        n,
    )

    # 7) INGEST LATENCY sanity: knowable_at - event_time should be small + positive.
    row = row1(
        "SELECT avg(date_diff('second', event_time, knowable_at)), "
        "max(date_diff('second', event_time, knowable_at)) FROM events"
    )
    avg_lat, max_lat = row[0] or 0, row[1] or 0
    r.add(
        "ingest_latency",
        "warn" if max_lat > 3600 else "ok",
        f"avg {avg_lat:.1f}s / max {max_lat:.0f}s assumed ingest latency",
    )

    # 8) OHLCV gaps: bars per (pool, interval) should be contiguous; count gaps.
    n = scalar(
        """
        WITH bars AS (
            SELECT pool_address,
                   json_extract_string(payload, '$.interval') AS interval,
                   event_time,
                   lag(event_time) OVER (
                       PARTITION BY pool_address, json_extract_string(payload, '$.interval')
                       ORDER BY event_time
                   ) AS prev_close
            FROM events WHERE event_type = 'ohlcv_bar'
        )
        SELECT count(*) FROM bars
        WHERE prev_close IS NOT NULL
          AND date_diff('second', prev_close, event_time) >
              2 * CASE interval WHEN '1m' THEN 60 WHEN '5m' THEN 300 WHEN '15m' THEN 900
                                WHEN '1h' THEN 3600 WHEN '4h' THEN 14400 WHEN '1d' THEN 86400
                                ELSE 3600 END
        """
    )
    r.add(
        "ohlcv_gaps",
        "warn" if n else "ok",
        "OHLCV bar gaps > 2x interval" if n else "no OHLCV gaps (or no bars)",
        n,
    )

    return r


def summary(report: QCReport) -> dict[str, Any]:
    return {
        "total_checks": len(report.checks),
        "failed": len(report.failed),
        "warned": len(report.warned),
        "ok": report.ok(),
    }
