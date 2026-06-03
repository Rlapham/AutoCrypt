"""Run the profiler and render the frequency-vs-expectancy report (the kill-gate output).

Produces, on a survivorship-complete point-in-time universe:
  * the frequency-vs-expectancy curve (adaptive thresholds from the signal distribution),
  * a BLIND baseline (fire on every defined signal) — the signal must beat this to matter,
  * sensitivity sweeps over depth assumption, hold horizon, and the rug gate,
so the human can judge GO/NO-GO honestly rather than from a single tuned number.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from autocrypt.attribution.signal import AttributionSignalConfig
from autocrypt.attribution.wallet_book import AttributionConfig, WalletScoreBook
from autocrypt.profiler.dataset import load_pools
from autocrypt.profiler.profiler import (
    Profiler,
    ProfilerConfig,
    ThresholdResult,
    Trade,
    summarize_threshold,
)
from autocrypt.storage.store import EventStore

NEG_INF = float("-inf")


@dataclass(slots=True)
class SignificancePoint:
    """Permutation test of one threshold's edge vs random subsets of the same size."""

    threshold: float
    n: int
    mean_net: float
    p_value: float  # P(random subset of size n has mean >= observed)


@dataclass(slots=True)
class ProfileReport:
    universe_pools: int
    pools_used: int
    blind: ThresholdResult
    curve: list[ThresholdResult]
    horizon_sweep: dict[float, ThresholdResult]  # horizon_s -> blind result
    depth_sweep: dict[float, ThresholdResult]  # depth_mult -> blind result
    rug_off_blind: ThresholdResult
    meta: dict[str, float]
    signal_quantiles: dict[str, float]
    significance: list[SignificancePoint]
    signal_field: str = "score"  # "score" (derivative) | "attr_score" (attribution)
    book_meta: dict[str, float] = None  # type: ignore[assignment]  # attribution book stats


def _quantiles_from(vals: list[float]) -> tuple[list[float], dict[str, float]]:
    """Signal-value quantiles → curve thresholds (dedup, ascending) + a labelled dict."""
    vals = sorted(vals)
    if not vals:
        return [], {}

    def q(p: float) -> float:
        idx = p * (len(vals) - 1)
        lo = int(idx)
        hi = min(lo + 1, len(vals) - 1)
        return vals[lo] + (idx - lo) * (vals[hi] - vals[lo])

    qs = {f"p{int(p * 100)}": q(p) for p in (0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)}
    return sorted(set(qs.values())), qs


def _permutation_test(
    passed: list[Trade], thresholds: list[float], n_resamples: int = 20_000, min_n: int = 8
) -> list[SignificancePoint]:
    """For each threshold, is the selected subset's mean better than a random subset?

    The null is "the signal carries no information": a same-size random draw from ALL
    fired trades. A low p means the signal selected better-than-random entries — a
    stricter bar than merely beating blind entry. Seeded for reproducibility.
    """
    rng = random.Random(1234)
    nets = [t.net_return for t in passed]
    out: list[SignificancePoint] = []
    for thr in thresholds:
        subset = [t.net_return for t in passed if t.signal_value >= thr]
        k = len(subset)
        if k < min_n or k == len(nets):
            continue
        obs = sum(subset) / k
        hits = sum(
            1 for _ in range(n_resamples) if sum(rng.sample(nets, k)) / k >= obs
        )
        out.append(SignificancePoint(thr, k, obs, hits / n_resamples))
    return out


def build_report(
    store: EventStore,
    horizon_s: float = 60.0,
    position_size_usd: float = 250.0,
    min_swaps: int = 10,
    signal_field: str = "score",
    attr_cfg: AttributionConfig | None = None,
) -> ProfileReport:
    """Build the frequency-vs-expectancy report for the chosen signal.

    `signal_field="score"` profiles the derivative composite (the Phase-2 kill-gate);
    `signal_field="attr_score"` profiles the Phase-3 wallet-attribution signal on the SAME
    harness (costs, censoring, depth/horizon/rug sweeps, permutation test). In attribution
    mode a `WalletScoreBook` is built once from the FULL universe (min_swaps=1, so wallet
    track records use every entry) while trades are still scored on the min_swaps universe.
    """
    pools = load_pools(store, min_swaps=min_swaps)

    book: WalletScoreBook | None = None
    book_meta: dict[str, float] = {}
    sig_cfg = AttributionSignalConfig(attribution=attr_cfg or AttributionConfig())
    if signal_field.startswith("attr"):
        full_pools = load_pools(store, min_swaps=1)  # maximal wallet history
        book = WalletScoreBook.build(full_pools, sig_cfg.attribution)
        base = book.base_rate_at(float("inf"))  # final population rate (report only)
        book_meta = {
            "book_pools": float(len(full_pools)),
            "book_wallets": float(book.n_wallets),
            "book_attempts": float(book.n_attempts),
            "book_final_base_rate": base,
            "runup_pct_x100": sig_cfg.attribution.runup_pct * 100.0,
        }

    def _profiler(cfg: ProfilerConfig) -> Profiler:
        return Profiler(cfg, book=book)

    def _cfg(**kw: object) -> ProfilerConfig:
        params: dict[str, object] = {
            "horizon_s": horizon_s,
            "position_size_usd": position_size_usd,
            "signal_field": signal_field,
            "attribution": sig_cfg,
        }
        params.update(kw)  # caller overrides (horizon_s / depth_multiplier / use_rug_filter)
        return ProfilerConfig(**params)  # type: ignore[arg-type]

    # Single point-in-time pass: all downstream curve points filter these trades.
    scored, censored, minutes, used = _profiler(_cfg()).run(pools)
    thresholds, qs = _quantiles_from([t.signal_value for t in scored])

    blind = summarize_threshold(NEG_INF, scored, censored, minutes)
    curve = [summarize_threshold(thr, scored, censored, minutes) for thr in thresholds]
    meta = {
        "n_pools_in_universe": float(len(pools)),
        "n_pools_used": float(used),
        "total_scored_fires_at_min_threshold": float(len(scored)),
        "total_censored_at_min_threshold": float(len(censored)),
        "total_eligible_pool_minutes": minutes,
    }
    passed = [t for t in scored if not t.rug_blocked]
    significance = _permutation_test(passed, thresholds)

    # Horizon sweep (blind expectancy at each horizon).
    horizon_sweep: dict[float, ThresholdResult] = {}
    for h in (30.0, 60.0, 120.0):
        s, c, m, _ = _profiler(_cfg(horizon_s=h)).run(pools)
        horizon_sweep[h] = summarize_threshold(NEG_INF, s, c, m)

    # Depth-sensitivity sweep (blind expectancy at each depth multiplier).
    depth_sweep: dict[float, ThresholdResult] = {}
    for dm in (0.5, 1.0, 2.0):
        s, c, m, _ = _profiler(_cfg(depth_multiplier=dm)).run(pools)
        depth_sweep[dm] = summarize_threshold(NEG_INF, s, c, m)

    # Rug gate OFF (blind), to show how the gate changes the firing universe.
    s, c, m, _ = _profiler(_cfg(use_rug_filter=False)).run(pools)
    rug_off_blind = summarize_threshold(NEG_INF, s, c, m)

    return ProfileReport(
        universe_pools=len(pools),
        pools_used=int(meta["n_pools_used"]),
        blind=blind,
        curve=curve,
        horizon_sweep=horizon_sweep,
        depth_sweep=depth_sweep,
        rug_off_blind=rug_off_blind,
        meta=meta,
        signal_quantiles=qs,
        significance=significance,
        signal_field=signal_field,
        book_meta=book_meta,
    )


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def render_markdown(rep: ProfileReport, horizon_s: float, position_size_usd: float) -> str:
    is_attr = rep.signal_field.startswith("attr")
    L: list[str] = []
    if is_attr:
        L.append("# Phase 3 — Wallet-Attribution Signal Profile (on the kill-gate harness)\n")
        L.append(
            "Profiles the **lead-weighted wallet-attribution** signal (Project_spec §2 — the "
            "claimed *defensible edge*) on the exact same survivorship-complete, point-in-time "
            "profiler as the Phase-2 derivative kill-gate, so the two are directly comparable. "
            "The signal fires when wallets with a **demonstrated historical lead on run-ups** "
            "(scored only from trials resolved before the decision) are buying the pool now.\n"
        )
    else:
        L.append("# Phase 2 — Frequency-vs-Expectancy Profile (KILL-GATE output)\n")
    L.append(
        f"- Universe (survivorship-complete, created pools w/ swaps): **{rep.universe_pools}** "
        f"pools; used (enough history): **{rep.pools_used}**\n"
        f"- Hold horizon: **{horizon_s:.0f}s**; position size: **${position_size_usd:.0f}**; "
        f"costs: fees + own price impact (constant-product) on both legs\n"
        f"- Eligible pool-minutes: **{rep.meta.get('total_eligible_pool_minutes', 0):.1f}**; "
        f"scored fires (blind): **{int(rep.meta.get('total_scored_fires_at_min_threshold', 0))}**, "
        f"censored: **{int(rep.meta.get('total_censored_at_min_threshold', 0))}**\n"
    )
    if is_attr and rep.book_meta:
        bm = rep.book_meta
        L.append(
            f"- Attribution book: **{int(bm.get('book_wallets', 0)):,}** wallets / "
            f"**{int(bm.get('book_attempts', 0)):,}** resolved entry-trials over "
            f"**{int(bm.get('book_pools', 0)):,}** pools; final population lead rate "
            f"**{bm.get('book_final_base_rate', 0) * 100:.1f}%** (run-up = "
            f"+{int(rep.book_meta.get('runup_pct_x100', 100))}% within window). 'blind' here = "
            f"fire whenever the attribution signal is *defined* (>=1 recent buyer with track "
            f"record), so it already conditions on smart-money presence.\n"
        )

    def row(r: ThresholdResult) -> str:
        thr = "blind" if r.threshold == NEG_INF else f"{r.threshold:.3f}"
        return (
            f"| {thr} | {r.n_fires} | {r.n_pools_fired} | {r.fire_rate_per_pool_min:.3f} | "
            f"{r.hit_rate * 100:.1f}% | {_pct(r.expectancy)} | {_pct(r.median_net)} | "
            f"{_pct(r.mean_marked)} | {_pct(r.mean_cost_drag)} | "
            f"{_pct(r.p25_net)} / {_pct(r.p75_net)} | {r.n_rug_blocked} | {r.n_censored} |"
        )

    hdr = (
        "| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | "
        "marked | cost drag | p25/p75 | rug-blk | censored |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|"
    )

    L.append("\n## Frequency-vs-expectancy curve\n")
    L.append(hdr)
    L.append(row(rep.blind))
    for r in rep.curve:
        L.append(row(r))

    L.append("\n## Blind baseline by hold horizon\n")
    L.append(hdr)
    for h, r in sorted(rep.horizon_sweep.items()):
        L.append(row(r).replace("| blind |", f"| h={h:.0f}s |"))

    L.append("\n## Depth-assumption sensitivity (blind expectancy)\n")
    L.append(
        "Depth is the biggest modelling assumption (estimated from observed impact). "
        "If the sign of expectancy flips across this sweep, the verdict is fragile.\n"
    )
    L.append(hdr)
    for dm, r in sorted(rep.depth_sweep.items()):
        L.append(row(r).replace("| blind |", f"| depth x{dm:g} |"))

    L.append("\n## Rug gate on/off (blind)\n")
    L.append(hdr)
    L.append(row(rep.blind).replace("| blind |", "| rug ON |"))
    L.append(row(rep.rug_off_blind).replace("| blind |", "| rug OFF |"))

    if rep.significance:
        L.append("\n## Significance — does the signal beat RANDOM selection?\n")
        L.append(
            "Permutation test (20k resamples, seeded): P(a random subset of the same size "
            "has mean net return >= the signal's subset). Low p ⇒ the signal selected "
            "better-than-random entries — a stricter bar than beating blind entry. "
            "Note multiple thresholds are tested, so apply a multiple-comparison discount.\n"
        )
        L.append("| threshold | n | mean net | p(random >= obs) |")
        L.append("|---|---|---|---|")
        for s in rep.significance:
            L.append(f"| {s.threshold:.3f} | {s.n} | {_pct(s.mean_net)} | {s.p_value:.3f} |")

    dist_label = "attribution lift" if is_attr else "composite score"
    L.append(f"\n## Signal-value distribution ({dist_label})\n")
    L.append("| quantile | " + " | ".join(rep.signal_quantiles.keys()) + " |")
    L.append("|---|" + "---|" * len(rep.signal_quantiles))
    L.append("| value | " + " | ".join(f"{v:.3f}" for v in rep.signal_quantiles.values()) + " |")

    return "\n".join(L) + "\n"
