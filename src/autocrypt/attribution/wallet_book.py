"""Lead-weighted wallet-attribution — the project's claimed *defensible edge*.

Project_spec §2: "label wallets by their demonstrated historical lead on run-ups (which
addresses reliably buy *before* moves), and weight 'this wallet is buying' by that
demonstrated lead." The kill-gate so far only tested the *derivative composite* signal;
this module builds the attribution model the thesis actually rests on, so the profiler can
score it on the same survivorship-complete, point-in-time harness.

THE DISCIPLINE THAT MAKES THIS HONEST (no look-ahead):

  * An **attempt** is one wallet's *first buy* in a pool (one Bernoulli trial per
    wallet-pool). It is a **success** if the pool's price reaches `entry_price *
    (1 + runup_pct)` within `runup_window_s` *after that entry* — measuring from the
    wallet's own entry price makes "led the run-up" intrinsic, not relative to some
    external level.
  * Each trial's outcome becomes **knowable** at a specific wall-clock: the price-crossing
    swap's `knowable_at` (success) or `entry_knowable + runup_window_s` (failure — we only
    know it *didn't* run up once the window has elapsed). A wallet's score at decision time
    T may use ONLY trials resolved at knowable <= T. This is the same `knowable_at` gate the
    rest of the profiler uses, applied to a wallet's track record.
  * The universe of attempts includes pools that died / rugged (they are the failures in
    the denominator), so the score is survivorship-safe by construction.

The score is a Beta-Binomial-shrunk hit rate expressed as **lift** over the point-in-time
global base rate: a wallet with few trials shrinks toward the population, so a 1-for-1
wallet does not masquerade as a genius.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from autocrypt.profiler.dataset import PoolData, SwapRow


@dataclass(slots=True)
class AttributionConfig:
    """Knobs for run-up labelling and wallet-score shrinkage."""

    runup_pct: float = 1.0  # a "run-up" = price reaches entry*(1+this) (+100% default)
    runup_window_s: float = 300.0  # ...within this many seconds of the wallet's entry
    min_attempts: int = 3  # a wallet needs >= this many RESOLVED trials to be scored
    prior_strength: float = 20.0  # Beta-Binomial pseudo-count (shrink toward base rate)
    prior_base_rate: float = 0.05  # fallback population lead rate before any trial resolves


@dataclass(slots=True)
class WalletScore:
    """A wallet's demonstrated-lead score as of some decision time (all point-in-time)."""

    attempts: int  # resolved trials knowable by T
    leads: int  # of those, how many preceded a run-up
    posterior: float  # Beta-Binomial posterior mean P(entry precedes run-up)
    lift: float  # posterior - base_rate (>0 = better than the crowd)
    base_rate: float  # the point-in-time population rate it is measured against


@dataclass(slots=True)
class Attempt:
    """One resolved Bernoulli trial for a wallet: did its first buy precede a 'success'?

    A trial is venue/label-agnostic — the *definition* of success and the resolution time live
    in whatever produced it (the fast-pump run-up label in `_pool_attempts`, or Track G's
    survive-AND-appreciate accumulator label). `WalletScoreBook.from_attempts` consumes these
    directly, so a different cohort/label reuses the identical point-in-time scoring machinery.
    """

    wallet: str
    resolution_knowable: float  # earliest wall-clock the outcome could be known
    success: bool


class _SparseMax:
    """O(n log n)-build / O(1)-query range-maximum (sparse table) over a fixed array."""

    __slots__ = ("_log", "_table")

    def __init__(self, arr: list[float]) -> None:
        n = len(arr)
        self._log = [0] * (n + 1)
        for i in range(2, n + 1):
            self._log[i] = self._log[i // 2] + 1
        self._table: list[list[float]] = [arr[:]]
        k = 1
        while (1 << k) <= n:
            prev = self._table[k - 1]
            step = 1 << (k - 1)
            self._table.append([max(prev[i], prev[i + step]) for i in range(n - (1 << k) + 1)])
            k += 1

    def query(self, lo: int, hi: int) -> float:
        """Max over inclusive [lo, hi] (assumes lo <= hi)."""
        k = self._log[hi - lo + 1]
        return max(self._table[k][lo], self._table[k][hi - (1 << k) + 1])


# Above this pool size, build a sparse table so a failed trial (price never reaches target —
# the common case for dead launches) is decided in O(1) instead of scanning the whole window.
_RMQ_MIN_N = 64


def _pool_attempts(pool: PoolData, cfg: AttributionConfig) -> list[Attempt]:
    """Each wallet's first-buy trial in this pool, with its point-in-time resolution time.

    Forward price path is read in EVENT-TIME order (the on-chain truth), but the trial's
    *resolution_knowable* is a `knowable_at`, so downstream scoring never sees an outcome
    before it could have been known.
    """
    swaps: list[SwapRow] = sorted(pool.swaps, key=lambda s: s.event_time)
    n = len(swaps)
    if n == 0:
        return []
    prices = [s.price_usd for s in swaps]
    ets = [s.event_time for s in swaps]
    kts = [s.knowable_at for s in swaps]

    # window_end[i] = last index whose event_time is within runup_window_s of i (two-pointer,
    # monotonic non-decreasing since event_times are sorted).
    window_end = [0] * n
    j = 0
    for i in range(n):
        if j < i:
            j = i
        limit = ets[i] + cfg.runup_window_s
        while j + 1 < n and ets[j + 1] <= limit:
            j += 1
        window_end[i] = j

    rmq = _SparseMax(prices) if n > _RMQ_MIN_N else None

    first_buy: dict[str, int] = {}
    for i, s in enumerate(swaps):
        if s.side == "buy" and s.signer and s.price_usd > 0 and s.signer not in first_buy:
            first_buy[s.signer] = i

    attempts: list[Attempt] = []
    for wallet, i in first_buy.items():
        lo, hi = i + 1, window_end[i]
        target = prices[i] * (1.0 + cfg.runup_pct)
        success = False
        res_kt = kts[i] + cfg.runup_window_s  # failure: knowable once the window elapses
        if lo <= hi and not (rmq is not None and rmq.query(lo, hi) < target):
            for k in range(lo, hi + 1):  # find the first crossing (success only pays this)
                if prices[k] >= target:
                    success = True
                    res_kt = kts[k]  # success: knowable when the crossing print lands
                    break
        attempts.append(Attempt(wallet=wallet, resolution_knowable=res_kt, success=success))
    return attempts


@dataclass(slots=True)
class _WalletTimeline:
    """Sorted resolution times + prefix lead counts for one wallet (bisect-queried)."""

    res_times: list[float]
    cum_leads: list[int]  # cum_leads[k] = leads among the first k resolved trials


class WalletScoreBook:
    """Point-in-time book of wallet lead-scores, built once from the full universe.

    `score_at(wallet, T)` and `base_rate_at(T)` both honour the `knowable_at <= T` gate via
    binary search over resolution times — so the same book serves every decision time in a
    single profiler pass without leaking the future.
    """

    def __init__(
        self,
        wallets: dict[str, _WalletTimeline],
        global_res_times: list[float],
        global_cum_leads: list[int],
        cfg: AttributionConfig,
    ) -> None:
        self._wallets = wallets
        self._g_times = global_res_times
        self._g_leads = global_cum_leads
        self.cfg = cfg

    @classmethod
    def build(cls, pools: list[PoolData], cfg: AttributionConfig) -> WalletScoreBook:
        """Build from the fast-pump run-up label over a pool universe (Iteration-1 / Track-M)."""
        all_attempts: list[Attempt] = []
        for pool in pools:
            all_attempts.extend(_pool_attempts(pool, cfg))
        return cls.from_attempts(all_attempts, cfg)

    @classmethod
    def from_attempts(cls, attempts: list[Attempt], cfg: AttributionConfig) -> WalletScoreBook:
        """Build directly from pre-labelled trials — label/cohort-agnostic.

        Separated from `build` so a different success definition (e.g. Track G's days-horizon
        survive-AND-appreciate accumulator label) can feed the IDENTICAL point-in-time scoring:
        per-wallet and global resolution-time timelines with prefix lead counts, queried under
        the `knowable_at <= T` gate. `cfg` supplies only the Beta-Binomial shrink knobs here
        (`prior_strength`, `prior_base_rate`); the run-up knobs are irrelevant to scoring.
        """
        per_wallet: dict[str, list[Attempt]] = {}
        for a in attempts:
            per_wallet.setdefault(a.wallet, []).append(a)

        wallets: dict[str, _WalletTimeline] = {}
        for wallet, atts in per_wallet.items():
            atts.sort(key=lambda a: a.resolution_knowable)
            res_times = [a.resolution_knowable for a in atts]
            cum_leads = [0] * (len(atts) + 1)
            for k, a in enumerate(atts):
                cum_leads[k + 1] = cum_leads[k] + (1 if a.success else 0)
            wallets[wallet] = _WalletTimeline(res_times=res_times, cum_leads=cum_leads)

        all_sorted = sorted(attempts, key=lambda a: a.resolution_knowable)
        g_times = [a.resolution_knowable for a in all_sorted]
        g_cum = [0] * (len(all_sorted) + 1)
        for k, a in enumerate(all_sorted):
            g_cum[k + 1] = g_cum[k] + (1 if a.success else 0)

        return cls(wallets, g_times, g_cum, cfg)

    @property
    def n_attempts(self) -> int:
        return len(self._g_times)

    @property
    def n_wallets(self) -> int:
        return len(self._wallets)

    def base_rate_at(self, t: float) -> float:
        """Point-in-time population lead rate (trials resolved by `t`)."""
        idx = bisect_right(self._g_times, t)
        if idx == 0:
            return self.cfg.prior_base_rate
        return self._g_leads[idx] / idx

    def score_at(self, wallet: str, t: float) -> WalletScore:
        """A wallet's demonstrated-lead score using only trials knowable by `t`."""
        base = self.base_rate_at(t)
        tl = self._wallets.get(wallet)
        if tl is None:
            return WalletScore(0, 0, base, 0.0, base)
        idx = bisect_right(tl.res_times, t)
        attempts = idx
        leads = tl.cum_leads[idx]
        if attempts == 0:
            return WalletScore(0, 0, base, 0.0, base)
        k = self.cfg.prior_strength
        posterior = (leads + k * base) / (attempts + k)
        return WalletScore(attempts, leads, posterior, posterior - base, base)
