"""G0 — graduation-event detection (the discrete liquidity-deepening milestone).

Track G's thesis enters tokens *after they graduate* — when a launch survives its
bonding-curve phase and migrates to a real AMM pool with deep liquidity — and rides a
multi-day "accumulator" arc, rather than predicting fresh-launch pumps (Iteration 1's dead
corner). The prerequisite is a point-in-time, survivorship-complete detector of the
graduation milestone itself. This module is that detector.

WHAT "GRADUATION" IS, ON-CHAIN, IN THIS DATA
────────────────────────────────────────────
The forward collector (`ingestion/collect.py`) records `pool_created` for every newly
created pool, with a `dex` venue tag, selected by CREATION (never by survival). The Solana
launchpad lifecycle maps cleanly onto two venue *phases*:

  • BONDING-CURVE (pre-graduation): a token first trades on a bonding-curve venue
    (`pumpfun`, `meteora_dbc` = Dynamic Bonding Curve). ~99% of launches die here.
  • AMM (post-graduation / deep): when the curve completes, liquidity migrates to a
    constant-product / concentrated AMM pool (`pumpswap`, `raydium`, `orca`,
    `meteora_daam_v2`, …). The *creation of that AMM pool* is the discrete
    liquidity-deepening milestone — the graduation event.

So a graduation, for a base mint, is: **the first AMM-venue `pool_created` that follows a
bonding-curve `pool_created` for the same mint.** Its `knowable_at` is the AMM pool
creation's `knowable_at` — the earliest wall-clock our system could have known the token
graduated. That is the only time a downstream decision (G2 entry) may gate on.

NO-LOOK-AHEAD. The milestone is stamped at the AMM pool's `knowable_at`, never at the
bonding-curve creation. Nothing here reads `observed_at`.

SURVIVORSHIP. The denominator is every bonding-curve-origin mint in the window (enumerated
by creation). Mints that never graduate are *kept* as the failures — the graduation rate is
honest, not computed over survivors.

THE CO-LAUNCH ARTIFACT (an honesty caveat encoded as a flag)
────────────────────────────────────────────────────────────
Not every BC→AMM venue pair is a genuine "curve filled over time, then graduated" arc. The
Meteora family in particular seeds the DAMM (`meteora_daam_v2`) pool *at launch alongside*
the DBC pool — the two `pool_created` events land within seconds, so the AMM pool's creation
time is a config artifact, not the real liquidity-migration moment. We do NOT silently count
those as graduations: any transition whose BC→AMM lag is below `min_lag_s` is flagged
`suspect_colaunch` and reported separately from genuine graduations. The pump.fun →
pumpswap transition, by contrast, creates the pumpswap pool *at* migration, so its
`pool_created` time is a faithful graduation timestamp.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from autocrypt.storage.store import EventStore

# ── Venue taxonomy ────────────────────────────────────────────────────────────
# Phase of a launch's lifecycle that a `dex` venue represents. Deliberately explicit:
# an unrecognised venue is OTHER (never silently treated as a graduation target), so a new
# launchpad string can't fake a graduation until it is classified here on purpose.
BONDING_CURVE_VENUES: frozenset[str] = frozenset({"pumpfun", "meteora_dbc"})
AMM_VENUES: frozenset[str] = frozenset(
    {
        "pumpswap",
        "raydium",
        "raydium_clmm",
        "orca",
        "meteora",
        "meteora_daam_v2",
        "manifest",
    }
)


def venue_phase(dex: str | None) -> str:
    """Map a `dex` venue string to a lifecycle phase: 'BC' | 'AMM' | 'OTHER'."""
    if dex in BONDING_CURVE_VENUES:
        return "BC"
    if dex in AMM_VENUES:
        return "AMM"
    return "OTHER"


@dataclass(slots=True)
class PoolCreation:
    """One `pool_created` record, reduced to what graduation detection needs."""

    pool_address: str
    dex: str | None
    event_time: datetime  # valid time (block time of the creation tx)
    knowable_at: datetime  # the no-look-ahead gate

    @property
    def phase(self) -> str:
        return venue_phase(self.dex)


@dataclass(slots=True)
class GraduationEvent:
    """A detected graduation (BC→AMM transition) for one base mint, point-in-time."""

    base_mint: str
    bc_dex: str | None
    bc_pool_address: str
    bc_event_time: datetime
    amm_dex: str | None
    amm_pool_address: str
    # THE milestone times: graduation is knowable when the AMM pool's creation is knowable.
    grad_event_time: datetime  # valid time of the AMM pool creation
    grad_knowable_at: datetime  # decision gate — never use bc_event_time for a decision
    lag_s: float  # grad_event_time - bc_event_time, seconds
    suspect_colaunch: bool  # lag < min_lag_s ⇒ likely a co-launch config artifact, not a fill
    post_grad_swaps: int = 0  # swaps on the AMM pool knowable at/after graduation (coverage)

    @property
    def transition(self) -> str:
        return f"{self.bc_dex}->{self.amm_dex}"


@dataclass(slots=True)
class GraduationCensus:
    """Survivorship-complete census of the graduation funnel over the collected window."""

    n_pool_creations: int
    n_distinct_mints: int
    n_bc_origin: int  # denominator: mints that began on a bonding curve
    n_graduated: int  # BC-origin mints with a later AMM pool (incl. suspect)
    n_genuine: int  # graduations with lag >= min_lag_s
    n_suspect_colaunch: int  # graduations flagged as co-launch artifacts
    n_direct_amm: int  # mints whose first/only pool is already AMM (deep from birth)
    n_never_graduated: int  # BC-origin mints with no AMM pool in-window
    n_with_post_grad_swaps: int  # genuine graduations that have ANY post-grad AMM swap
    min_lag_s: float
    events: list[GraduationEvent] = field(default_factory=list)
    by_transition: dict[str, int] = field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None

    @property
    def graduation_rate(self) -> float:
        """Genuine graduations per bonding-curve-origin mint (the honest base rate)."""
        return self.n_genuine / self.n_bc_origin if self.n_bc_origin else 0.0


def _load_pool_creations(store: EventStore) -> dict[str, list[PoolCreation]]:
    """All `pool_created` rows grouped by base mint, ascending by event_time. Read-only."""
    by_mint: dict[str, list[PoolCreation]] = defaultdict(list)
    cur = store.con.execute(
        "SELECT base_mint, pool_address, event_time, knowable_at, payload FROM events "
        "WHERE event_type='pool_created' AND base_mint IS NOT NULL "
        "ORDER BY base_mint, event_time"
    )
    for base_mint, pool_address, event_time, knowable_at, payload_json in cur.fetchall():
        if not pool_address:
            continue
        dex = json.loads(payload_json).get("dex")
        by_mint[base_mint].append(
            PoolCreation(
                pool_address=pool_address,
                dex=dex,
                event_time=event_time,
                knowable_at=knowable_at,
            )
        )
    return by_mint


def _post_grad_swap_counts(
    store: EventStore, amm_pools: dict[str, datetime]
) -> dict[str, int]:
    """For each graduated AMM pool, count swaps knowable AT OR AFTER its graduation time.

    `amm_pools` maps pool_address → grad_knowable_at. The knowable-at gate keeps the count
    point-in-time: a swap counts toward post-graduation coverage only once it could have been
    known, and only if it lands at/after the graduation became knowable.
    """
    if not amm_pools:
        return {}
    counts: dict[str, int] = dict.fromkeys(amm_pools, 0)
    cur = store.con.execute(
        "SELECT pool_address, knowable_at FROM events "
        "WHERE event_type='swap' AND pool_address IS NOT NULL"
    )
    for pool_address, knowable_at in cur.fetchall():
        grad_kt = amm_pools.get(pool_address)
        if grad_kt is not None and knowable_at >= grad_kt:
            counts[pool_address] += 1
    return counts


def detect_graduations(store: EventStore, *, min_lag_s: float = 120.0) -> GraduationCensus:
    """Detect graduation milestones across the store, survivorship-complete & point-in-time.

    For every base mint we order its pool creations and find (a) the first bonding-curve
    pool and (b) the first AMM pool created at/after it. That BC→AMM pair is a graduation,
    flagged `suspect_colaunch` when the lag is under `min_lag_s` (the Meteora co-launch
    artifact). Mints that begin on an AMM are `direct_amm` (deep from birth, not a
    transition); BC-origin mints with no AMM pool are `never_graduated` failures retained in
    the denominator.
    """
    by_mint = _load_pool_creations(store)
    events: list[GraduationEvent] = []
    n_bc_origin = n_direct_amm = n_never = 0
    n_creations = 0
    win_start: datetime | None = None
    win_end: datetime | None = None

    # First pass: classify mints and assemble graduation events (no swap join yet).
    for base_mint, creations in by_mint.items():
        n_creations += len(creations)
        for c in creations:
            if win_start is None or c.event_time < win_start:
                win_start = c.event_time
            if win_end is None or c.event_time > win_end:
                win_end = c.event_time

        first_bc = next((c for c in creations if c.phase == "BC"), None)
        first_amm_overall = next((c for c in creations if c.phase == "AMM"), None)

        if first_bc is None:
            # No bonding-curve phase observed. If it has an AMM pool, it launched deep.
            if first_amm_overall is not None:
                n_direct_amm += 1
            continue

        n_bc_origin += 1
        # First AMM pool created at/after the first bonding-curve pool = the graduation.
        amm = next(
            (c for c in creations if c.phase == "AMM" and c.event_time >= first_bc.event_time),
            None,
        )
        if amm is None:
            n_never += 1
            continue

        lag_s = (amm.event_time - first_bc.event_time).total_seconds()
        events.append(
            GraduationEvent(
                base_mint=base_mint,
                bc_dex=first_bc.dex,
                bc_pool_address=first_bc.pool_address,
                bc_event_time=first_bc.event_time,
                amm_dex=amm.dex,
                amm_pool_address=amm.pool_address,
                grad_event_time=amm.event_time,
                grad_knowable_at=amm.knowable_at,
                lag_s=lag_s,
                suspect_colaunch=lag_s < min_lag_s,
            )
        )

    # Second pass: attach point-in-time post-graduation swap coverage.
    swap_counts = _post_grad_swap_counts(
        store, {e.amm_pool_address: e.grad_knowable_at for e in events}
    )
    for e in events:
        e.post_grad_swaps = swap_counts.get(e.amm_pool_address, 0)

    by_transition: dict[str, int] = defaultdict(int)
    for e in events:
        by_transition[e.transition] += 1

    n_genuine = sum(1 for e in events if not e.suspect_colaunch)
    n_suspect = sum(1 for e in events if e.suspect_colaunch)
    n_post = sum(1 for e in events if not e.suspect_colaunch and e.post_grad_swaps > 0)

    return GraduationCensus(
        n_pool_creations=n_creations,
        n_distinct_mints=len(by_mint),
        n_bc_origin=n_bc_origin,
        n_graduated=len(events),
        n_genuine=n_genuine,
        n_suspect_colaunch=n_suspect,
        n_direct_amm=n_direct_amm,
        n_never_graduated=n_never,
        n_with_post_grad_swaps=n_post,
        min_lag_s=min_lag_s,
        events=events,
        by_transition=dict(sorted(by_transition.items(), key=lambda kv: -kv[1])),
        window_start=win_start,
        window_end=win_end,
    )


def _quantile(xs: list[float], q: float) -> float:
    """Linear-interpolated quantile of a NON-empty, already-sorted list."""
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(pos)
    frac = pos - lo
    if lo + 1 >= len(xs):
        return xs[-1]
    return xs[lo] * (1 - frac) + xs[lo + 1] * frac


def render_markdown(census: GraduationCensus) -> str:
    """Full evidence doc for the graduation census (regenerate via `autocrypt grad-detect`)."""
    c = census
    genuine = [e for e in c.events if not e.suspect_colaunch]
    lags_min = sorted(e.lag_s / 60.0 for e in genuine)
    lines: list[str] = []
    lines.append("# G0 — Graduation-event detection (census)\n")
    win = (
        f"{c.window_start:%Y-%m-%d %H:%M} → {c.window_end:%Y-%m-%d %H:%M} UTC"
        if c.window_start and c.window_end
        else "n/a"
    )
    span_h = (
        (c.window_end - c.window_start).total_seconds() / 3600.0
        if c.window_start and c.window_end
        else 0.0
    )
    lines.append(
        f"- Window (pool creations): **{win}**  (~{span_h:.1f}h of wall-clock)\n"
        f"- `pool_created` rows: **{c.n_pool_creations:,}** over **{c.n_distinct_mints:,}** "
        f"distinct mints\n"
        f"- Graduation = first AMM-venue pool created at/after a bonding-curve pool for the "
        f"same mint; milestone stamped at the AMM pool's `knowable_at` (no look-ahead).\n"
        f"- Co-launch guard: BC→AMM lag < **{c.min_lag_s:.0f}s** ⇒ flagged "
        f"`suspect_colaunch` (config artifact, not a genuine curve-fill).\n"
    )

    lines.append("\n## Funnel (survivorship-complete)\n")
    lines.append("| stage | count |")
    lines.append("|---|---:|")
    lines.append(f"| bonding-curve-origin mints (denominator) | {c.n_bc_origin:,} |")
    lines.append(f"| → graduated (BC→AMM, incl. suspect) | {c.n_graduated:,} |")
    lines.append(f"| → **genuine** graduations (lag ≥ {c.min_lag_s:.0f}s) | {c.n_genuine:,} |")
    lines.append(f"| → suspect co-launch artifacts | {c.n_suspect_colaunch:,} |")
    lines.append(f"| never graduated (died on the curve) | {c.n_never_graduated:,} |")
    lines.append(f"| direct-AMM launches (deep from birth, no BC) | {c.n_direct_amm:,} |")
    lines.append(
        f"\n**Genuine graduation rate: {c.graduation_rate:.2%}** "
        f"({c.n_genuine}/{c.n_bc_origin} bonding-curve-origin mints).\n"
    )

    if lags_min:
        lines.append("\n## Genuine-graduation lag (bonding-curve create → AMM create)\n")
        lines.append("| p10 | p50 | p90 | min | max |")
        lines.append("|---:|---:|---:|---:|---:|")
        lines.append(
            f"| {_quantile(lags_min, 0.1):.1f}m | {_quantile(lags_min, 0.5):.1f}m | "
            f"{_quantile(lags_min, 0.9):.1f}m | {lags_min[0]:.1f}m | {lags_min[-1]:.1f}m |"
        )

    lines.append("\n## Transitions (BC venue → AMM venue)\n")
    lines.append("| transition | count |")
    lines.append("|---|---:|")
    for trans, n in c.by_transition.items():
        lines.append(f"| {trans} | {n} |")

    lines.append("\n## Post-graduation swap coverage (the collection gap)\n")
    cov = c.n_with_post_grad_swaps
    pct = cov / c.n_genuine if c.n_genuine else 0.0
    lines.append(
        f"Of **{c.n_genuine}** genuine graduations, **{cov}** ({pct:.0%}) have ANY swap on "
        f"their AMM pool knowable at/after graduation. Root cause: the forward collector "
        f"tailed newest pools by creation (overwhelmingly bonding-curve), so the "
        f"later-created AMM pool of a graduated token rarely won a watchlist slot. **Fix "
        f"deployed (G0 session):** `collect --amm-reserved` reserves watchlist capacity for "
        f"AMM (graduation-target) pools, so coverage should climb from here as graduated "
        f"pools accrue their multi-day arcs. This historical census still reflects the "
        f"pre-fix data; G1/G2 need the post-fix coverage to ripen before they can run.\n"
    )
    return "\n".join(lines) + "\n"
