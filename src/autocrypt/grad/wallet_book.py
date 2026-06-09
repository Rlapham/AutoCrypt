"""G1 — accumulator wallet-attribution book over the GRADUATED cohort.

This is the wiring the G1 kickoff calls for: feed Track G's days-horizon survive-AND-appreciate
label (`grad/accumulator_label.py`) into the same point-in-time `WalletScoreBook` machinery the
Iteration-1 attribution used (`attribution/wallet_book.py`), but over a *graduated* universe and
with the accumulator success definition instead of the fast-pump run-up label. The goal is to
surface a **followable accumulator cohort** — wallets whose first buy *after a token graduates*
tends to precede a multi-day survive-and-appreciate arc (not a pump the orchestrators run).

DISCIPLINE (unchanged from the attribution model, re-validated for this cohort):

  * UNIVERSE = every GENUINE graduation (BC→AMM, lag ≥ min_lag_s) with at least one post-grad
    swap. Graduations that later rugged are KEPT — their wallets' trials are the failures in the
    denominator — so the score is survivorship-safe by construction. Graduations with zero
    post-grad swaps contribute no trials; that is a *coverage gap*, reported plainly, not a bias.
  * A TRIAL is one wallet's first buy in a pool's POST-GRADUATION swap stream (swaps knowable at
    or after the graduation became knowable — never the bonding-curve phase). One Bernoulli trial
    per wallet-pool.
  * SUCCESS uses `label_accumulator_entry`: within `n_days`, the token appreciates ≥ `appreciate_pct`
    AND survives (no rug below `survival_floor`, still trading at the horizon). It resolves at the
    HORIZON (`entry_knowable_at + n_days`), so a moon-then-rug is a failure and the outcome is not
    knowable early.
  * NO LOOK-AHEAD: forward price path is read in event-time order; resolution time is a
    `knowable_at`. The resulting `WalletScoreBook` honours the same `knowable_at <= T` gate.

DATA-GATED. A trial only *resolves* `n_days` after entry, so until the durable collector has
accrued multi-day post-graduation arcs almost nothing is resolved and the book scores nobody.
That is the honest state, not a bug — `build_accumulator_book` reports resolved-vs-pending counts
so the operator can see ripening rather than a fabricated cohort.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autocrypt.attribution.wallet_book import Attempt, AttributionConfig, WalletScoreBook
from autocrypt.grad.accumulator_label import AccumulatorLabel, PricePoint, label_accumulator_entry
from autocrypt.grad.graduation import detect_graduations
from autocrypt.profiler.dataset import PoolData, SwapRow, load_pools
from autocrypt.storage.store import EventStore


@dataclass(slots=True)
class GradCohortPool:
    """One genuine graduation's AMM pool, reduced to its post-graduation swap arc."""

    pool_address: str
    base_mint: str
    transition: str  # e.g. "pumpfun->pumpswap"
    grad_knowable_at: float  # epoch seconds — graduation milestone gate
    swaps: list[SwapRow] = field(default_factory=list)  # post-grad only, event-time ascending


@dataclass(slots=True)
class AccumulatorBookStats:
    """What the cohort yielded — written so ripening is visible and never overstated."""

    n_genuine_graduations: int  # genuine grads in the census (the honest denominator)
    n_cohort_pools: int  # genuine grads with ≥1 post-grad swap (have any data)
    n_pools_with_attempts: int  # of those, how many produced at least one wallet trial
    n_attempts: int  # total wallet-pool trials
    n_wallets: int  # distinct wallets with ≥1 trial
    n_resolved: int  # trials whose horizon has elapsed as of `now_ts`
    n_resolved_successes: int  # of the resolved trials, how many succeeded
    n_scorable_wallets: int  # wallets with ≥ min_attempts RESOLVED trials as of now
    base_rate_now: float  # point-in-time population accumulator rate as of `now_ts`
    now_ts: float  # the latest knowable_at in the store (the evaluation "now")
    horizon_days: float

    @property
    def ripened(self) -> bool:
        """True once the cohort can actually score someone (≥1 scorable wallet)."""
        return self.n_scorable_wallets > 0


def load_graduated_cohort(
    store: EventStore, *, min_lag_s: float = 120.0, min_post_grad_swaps: int = 1
) -> list[GradCohortPool]:
    """Genuine graduations joined to their AMM pool's POST-graduation swap arc (read-only).

    Reuses `detect_graduations` (survivorship-complete, point-in-time) for the cohort and
    `load_pools` for the swaps, then keeps only swaps `knowable_at >= grad_knowable_at` — the
    bonding-curve phase is never scored. Pools below `min_post_grad_swaps` are dropped from the
    cohort (no data to label) but their absence is surfaced by the census numerator/denominator.
    """
    census = detect_graduations(store, min_lag_s=min_lag_s)
    grad_kt: dict[str, tuple[str, str]] = {}  # amm_pool_address → (base_mint, transition)
    grad_kt_epoch: dict[str, float] = {}
    for e in census.events:
        if e.suspect_colaunch:
            continue  # genuine graduations only
        grad_kt[e.amm_pool_address] = (e.base_mint, e.transition)
        grad_kt_epoch[e.amm_pool_address] = e.grad_knowable_at.timestamp()

    pools_by_addr: dict[str, PoolData] = {p.pool_address: p for p in load_pools(store)}

    cohort: list[GradCohortPool] = []
    for addr, (base_mint, transition) in grad_kt.items():
        pool = pools_by_addr.get(addr)
        if pool is None:
            continue
        gk = grad_kt_epoch[addr]
        post = [s for s in pool.swaps if s.knowable_at >= gk]
        if len(post) < min_post_grad_swaps:
            continue
        post.sort(key=lambda s: s.event_time)  # forward path is event-time order
        cohort.append(
            GradCohortPool(
                pool_address=addr,
                base_mint=base_mint,
                transition=transition,
                grad_knowable_at=gk,
                swaps=post,
            )
        )
    return cohort


def accumulator_attempts(pool: GradCohortPool, cfg: AccumulatorLabel) -> list[Attempt]:
    """One accumulator-labelled trial per wallet's first post-graduation buy in this pool."""
    forward = [
        PricePoint(event_time=s.event_time, knowable_at=s.knowable_at, price=s.price_usd)
        for s in pool.swaps
    ]
    first_buy: dict[str, SwapRow] = {}
    for s in pool.swaps:  # already event-time ascending
        if s.side == "buy" and s.signer and s.price_usd > 0 and s.signer not in first_buy:
            first_buy[s.signer] = s

    attempts: list[Attempt] = []
    for wallet, entry in first_buy.items():
        outcome = label_accumulator_entry(
            entry_price=entry.price_usd,
            entry_event_time=entry.event_time,
            entry_knowable_at=entry.knowable_at,
            forward=forward,
            cfg=cfg,
        )
        attempts.append(
            Attempt(
                wallet=wallet,
                resolution_knowable=outcome.resolution_knowable,
                success=outcome.success,
            )
        )
    return attempts


def _now_ts(store: EventStore) -> float:
    """The latest `knowable_at` in the store — the most recent moment anything could be known.

    This is the honest evaluation "now": a trial counts as resolved only if its horizon elapsed
    by here, and base rates / scores are read at this T under the usual knowable-at gate.
    """
    row = store.con.execute("SELECT max(knowable_at) FROM events").fetchone()
    return row[0].timestamp() if row and row[0] is not None else 0.0


def build_accumulator_book(
    store: EventStore,
    *,
    label_cfg: AccumulatorLabel | None = None,
    score_cfg: AttributionConfig | None = None,
    min_lag_s: float = 120.0,
) -> tuple[WalletScoreBook, AccumulatorBookStats, list[Attempt]]:
    """Build the accumulator WalletScoreBook over the graduated cohort, with ripening stats.

    Returns the point-in-time book, a stats record (resolved-vs-pending, so ripening is visible),
    and the raw trials. `score_cfg` supplies the Beta-Binomial shrink knobs (`prior_strength`,
    `prior_base_rate`) and `min_attempts` (the resolved-trial threshold for a wallet to be
    scorable); `label_cfg` is the survive-and-appreciate definition.
    """
    label_cfg = label_cfg or AccumulatorLabel()
    score_cfg = score_cfg or AttributionConfig()
    census = detect_graduations(store, min_lag_s=min_lag_s)
    cohort = load_graduated_cohort(store, min_lag_s=min_lag_s)

    all_attempts: list[Attempt] = []
    n_pools_with_attempts = 0
    for pool in cohort:
        atts = accumulator_attempts(pool, label_cfg)
        if atts:
            n_pools_with_attempts += 1
        all_attempts.extend(atts)

    book = WalletScoreBook.from_attempts(all_attempts, score_cfg)
    now_ts = _now_ts(store)

    n_resolved = sum(1 for a in all_attempts if a.resolution_knowable <= now_ts)
    n_resolved_successes = sum(
        1 for a in all_attempts if a.resolution_knowable <= now_ts and a.success
    )
    # A wallet is scorable now iff it has ≥ min_attempts trials RESOLVED by now (same gate the
    # signal uses), so this counts the cohort the operator could actually act on today.
    resolved_per_wallet: dict[str, int] = {}
    for a in all_attempts:
        if a.resolution_knowable <= now_ts:
            resolved_per_wallet[a.wallet] = resolved_per_wallet.get(a.wallet, 0) + 1
    n_scorable = sum(1 for c in resolved_per_wallet.values() if c >= score_cfg.min_attempts)

    stats = AccumulatorBookStats(
        n_genuine_graduations=census.n_genuine,
        n_cohort_pools=len(cohort),
        n_pools_with_attempts=n_pools_with_attempts,
        n_attempts=len(all_attempts),
        n_wallets=book.n_wallets,
        n_resolved=n_resolved,
        n_resolved_successes=n_resolved_successes,
        n_scorable_wallets=n_scorable,
        base_rate_now=book.base_rate_at(now_ts),
        now_ts=now_ts,
        horizon_days=label_cfg.n_days,
    )
    return book, stats, all_attempts


def top_accumulator_wallets(
    book: WalletScoreBook, attempts: list[Attempt], now_ts: float, *, limit: int = 20
) -> list[tuple[str, object]]:
    """Scorable wallets (≥ min_attempts resolved) ranked by demonstrated-lead lift, as of now.

    Returns (wallet, WalletScore) pairs. Empty until the cohort ripens — by design.
    """
    scored = []
    for wallet in {a.wallet for a in attempts}:
        sc = book.score_at(wallet, now_ts)
        if sc.attempts >= book.cfg.min_attempts:
            scored.append((wallet, sc))
    scored.sort(key=lambda ws: ws[1].lift, reverse=True)  # type: ignore[attr-defined]
    return scored[:limit]


def render_markdown(stats: AccumulatorBookStats, top: list[tuple[str, object]]) -> str:
    """Evidence doc for the accumulator book (regenerate via `autocrypt grad-walletbook`)."""
    s = stats
    pct = (s.n_resolved_successes / s.n_resolved) if s.n_resolved else 0.0
    lines: list[str] = ["# G1 — Accumulator wallet-attribution book (graduated cohort)\n"]
    lines.append(
        f"- Success label: survive-AND-appreciate over **{s.horizon_days:g} days** "
        f"(resolves at the horizon; a moon-then-rug is a failure).\n"
        f"- Universe: **{s.n_genuine_graduations:,}** genuine graduations; "
        f"**{s.n_cohort_pools:,}** have ≥1 post-graduation swap "
        f"({s.n_pools_with_attempts:,} produced ≥1 wallet trial).\n"
        f"- Trials (wallet-pool): **{s.n_attempts:,}** across **{s.n_wallets:,}** wallets.\n"
    )
    lines.append("\n## Ripening (point-in-time, no look-ahead)\n")
    lines.append("| metric | value |")
    lines.append("|---|---:|")
    lines.append(f"| trials RESOLVED (horizon elapsed) | {s.n_resolved:,} / {s.n_attempts:,} |")
    lines.append(f"| resolved successes | {s.n_resolved_successes:,} ({pct:.1%}) |")
    lines.append(f"| population accumulator base rate | {s.base_rate_now:.2%} |")
    lines.append(f"| **scorable wallets (≥min_attempts resolved)** | **{s.n_scorable_wallets:,}** |")
    if not s.ripened:
        lines.append(
            "\n> **NOT YET RIPENED.** No wallet has enough *resolved* multi-day trials to be "
            "scored. This is the honest data-gated state — the collector needs more uptime for "
            "post-graduation arcs to reach the horizon. Re-run as the cohort accrues.\n"
        )
        return "\n".join(lines) + "\n"
    lines.append(f"\n## Top accumulator wallets (lift over base, as of now; n={len(top)})\n")
    lines.append("| wallet | attempts | leads | posterior | lift |")
    lines.append("|---|---:|---:|---:|---:|")
    for wallet, sc in top:
        lines.append(
            f"| `{wallet}` | {sc.attempts} | {sc.leads} | "  # type: ignore[attr-defined]
            f"{sc.posterior:.3f} | {sc.lift:+.3f} |"  # type: ignore[attr-defined]
        )
    return "\n".join(lines) + "\n"
