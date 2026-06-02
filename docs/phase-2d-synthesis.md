# Phase 2d — Session Synthesis (free-archive adapters + a provider-access reality check)

*Continuation of Phase 2 (THE KILL-GATE). Prior session (2c) chose Flipside-free as the
primary historical archive and Dune as the SQL cross-check. This session built the
adapter — then verification of Flipside's access model forced a pivot. Authoritative
state lives in `Project_spec.md`.*

## Headline (read this first)

1. **Collector still healthy.** `autocrypt collect` (pid 17322) is running; this run
   started 00:40 UTC, 57 ticks over ~83 min, **8,592 net-new swap+wallet rows** on the
   40-pool rolling cohort, 0 retired (no pool has aged past the 24h window yet). Effective
   `event_time` window is still tonight's launch snapshot — wall-clock-bound, doesn't move
   the verdict (exactly as 2c said).
2. **Built the Flipside adapter** (`src/autocrypt/providers/flipside.py`) mirroring the
   Bitquery scaffold: pure, offline-testable mappers + a **key-gated** (free, not
   spend-gated) JSON-RPC network layer. 8 tests, all green.
3. **Verified Flipside access — and it's effectively closed to free self-signup.** The
   operator suspected Flipside had gone invitation-only; research confirmed the substance.
   As of June 2026 Flipside repositioned to an enterprise / "Agents as a Service" model:
   the homepage and the `/api-keys` URL funnel to **"Get a personalized demo" / "Log In"**
   with **no public free-signup CTA**. "Free self-signup" survives only in stale secondary
   sources (the GitHub SDK README — *formerly ShroomDK*, QuickNode's writeup, and docs that
   403 automated fetches). The API surface also appears to have **moved** to a REST
   `api.flipsidecrypto.xyz/public/v3` endpoint (vs the `api-v2…/json-rpc` the adapter
   targets). Honest caveat: I could not read the authoritative docs (persistent 403), so
   the definitive test is whether the operator can still log in / create a key with a
   (possibly legacy) account — but the public site no longer offers it to a new user.
4. **Pivoted to Dune as the PRIMARY free archive (operator-approved).** Dune's free tier
   is open self-signup and was **publicly recommitted in Jan 2026** ("we will keep having a
   generous free plan"). `dex_solana.trades` is decoded + survivorship-complete — same
   property that made Flipside attractive. **Built the Dune adapter**
   (`src/autocrypt/providers/dune.py`) + 8 tests. Flipside adapter stays in the tree as a
   ready swap-in if access reopens.
5. **GO/NO-GO still UNPROVEN.** No key yet → no validation query, no backfill, no profiler
   re-run. Kill-gate verdict unchanged: **CONDITIONAL GO, unproven.** No Phase 3.

## What was built / changed (state of the code)

- **`src/autocrypt/providers/flipside.py`** (NEW) — Flipside Data API adapter. Pure mappers
  (`to_swap` / `to_pool_created` / `swap_to_wallet_event`) for `solana.defi.ez_dex_swaps`;
  key-gated JSON-RPC network layer (create-run → poll → page). `ez_dex_swaps` is
  **directional** (swapper FROM→TO) so buy/sell is exact; it has **no pool-address column**
  so we derive a deterministic surrogate market key per (base, quote, program) and prefer a
  real pool field if one ever appears.
- **`src/autocrypt/providers/dune.py`** (NEW) — Dune Execution API adapter, same canonical
  shape. Maps `dex_solana.trades` rows (token_bought/sold_*) → canonical records;
  key-gated execute → poll → paginate. Same surrogate-pool + directional logic. Ships the
  `DEX_TRADES_SQL` to save as a Dune query (free tier executes **saved queries by ID** with
  `{{since}}`/`{{till}}` params — ad-hoc SQL via API is paid).
- **`tests/test_flipside.py`**, **`tests/test_dune.py`** (NEW) — 8 tests each: buy/sell
  direction, quote↔quote skip, surrogate-vs-real pool key, wallet-event link, pool-created
  proxy, key-gate (no network without a key), normalization of upper-cased keys.
- **`src/autocrypt/schema/events.py`** — added `flipside` + `dune` to the `Source` enum.
- **`src/autocrypt/config.py`** — added `flipside_api_key` + `dune_api_key` (SecretStr,
  optional; read from `.env`, never committed).
- **Tests: 51/51 green** (was 35 + 8 + 8). Ruff clean. No collector/Bitquery changes.

## Key decisions & why

- **Verify access model before depending on a provider.** The 2c plan named Flipside
  primary on the strength of its *data*, but didn't pin down whether a new user can still
  get a free key. Checking first this session caught a closed door before we built a
  backfill on top of it. (Saved as a feedback memory.)
- **Dune over "chase a Flipside key".** Dune removes the blocker entirely: open signup, a
  free plan publicly committed for 2026, and the same decoded/survivorship-complete table.
  The cost of trying Flipside first was a likely dead-end at the sales gate. The adapter is
  provider-agnostic, so the Flipside work isn't wasted — it's a swap-in.
- **Key-gate, not spend-gate.** Both new adapters are FREE, so the guard just enforces "a
  key exists in `.env`" — no `enable_paid` flag (that pattern belongs to Bitquery, which is
  shelved). Pure mappers run offline so tests need no key and no network.
- **Surrogate pool key, stated loudly.** Neither warehouse table carries a pool address;
  grouping swaps by (base, quote, program) is the honest creation-proxy unit. Documented as
  an open item a real pool column / dim-pool join can replace.

## Open questions / forks for the human

- **Dune free key (next first step).** Sign up at dune.com (free), create an API key →
  `.env` as `DUNE_API_KEY` (never commit). Also save `DEX_TRADES_SQL` as a Dune query with
  `since`/`till` TIMESTAMP params and note its numeric `query_id`. Then I run the validation
  query.
- **Dune free-tier credit cap (the validation unknown).** Free is credit-metered (~2,500
  credits/mo from 2c research). A full 14d SOL+USDC pull may exceed it → the ONE validation
  execution must measure real cost/row-count and we scope/paginate or accept a modest
  overage honestly. (CoinGecko Analyst $129/mo remains the only paid fallback — YELLOW.)
- **GO/NO-GO re-confirmation — still PENDING the real-data curve.** Unchanged. No Phase 3
  until the profiler runs on a trustworthy multi-day dataset with explicit sign-off.
- **Flipside salvage (optional).** If the operator has/obtains a Flipside key, the adapter's
  network layer likely needs porting from `api-v2…/json-rpc` to the `public/v3` REST
  endpoint; the pure mappers are unaffected. Low priority given Dune is primary.
- **Profiler vs the writer lock (unchanged from 2c).** `collect` holds DuckDB's single
  writer lock. Re-running `autocrypt profile` on the backfill needs either a brief
  authorized stop+restart of `collect` (idempotent, survivorship-safe) or pointing the
  profiler at a separate backfilled DB. Decide when we get there.
- **Collector durability (operational, unanswered this session).** Still a `nohup` process
  → survives the session but not a reboot/sleep. A launchd KeepAlive job is the durable
  form; not installed (writes to `~/Library/LaunchAgents`). Lower stakes now that Dune is
  the primary archive. One-liner in the kickoff if wanted.

## Honesty log (what was caught / corrected this session)

- **Could not read Flipside's authoritative docs** (persistent HTTP 403 on
  docs.flipsidecrypto.com). The "self-signup closed" conclusion rests on the live homepage
  + `/api-keys` page + the absence of any free-signup CTA, cross-checked against stale
  secondary sources — not on the docs themselves. Flagged so the operator's own login
  attempt is the tiebreaker.
- **Field paths are documented-but-unvalidated** for BOTH adapters — no live response has
  confirmed `ez_dex_swaps` / `dex_solana.trades` column names against a real pull. The
  mappers are defensive (lower-case normalization, candidate pool fields) and the first
  validation query is the source of truth, exactly as the Bitquery scaffold was treated.
- **Surrogate pool key is not an on-chain address** — said plainly; it groups a launch's
  swaps into one unit and is replaceable.
- **No profiler re-run, no GO change** — there is no new real data, so the verdict is
  unchanged rather than dressed up.

## Suggested commit plan (human runs git — see CLAUDE.md §4)

Work branch: **`Phase2`** (or the current phase branch). Suggested logical commits:

1. **feat(providers): free Dune `dex_solana.trades` adapter (Phase 2c primary archive)**
   — `src/autocrypt/providers/dune.py`, `tests/test_dune.py`.
2. **feat(providers): free Flipside `ez_dex_swaps` adapter (swap-in / cross-check)**
   — `src/autocrypt/providers/flipside.py`, `tests/test_flipside.py`.
3. **feat(schema,config): add flipside/dune sources + API-key settings**
   — `src/autocrypt/schema/events.py`, `src/autocrypt/config.py`.
4. **docs(phase-2): Flipside-access finding → pivot to Dune-primary; 2d synthesis + spec**
   — `docs/provider-evaluation.md`, `docs/phase-2d-synthesis.md`, `Project_spec.md`.

Do **not** commit `data/` (store, `*.log`). Note: prior-session code (collector, Bitquery
scaffold) + earlier synthesis docs may still be uncommitted on this branch — check
`git status`; they carry their own plans in `docs/phase-2b-synthesis.md` /
`docs/phase-2c-synthesis.md`.

---

## ▶ Kickoff prompt for the next session — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then docs/phase-2d-synthesis.md, then
docs/provider-evaluation.md (the "Phase 2d addendum"). Skim docs/event-schema.md +
docs/data-dictionary.md. Confirm back to me in 3-4 sentences where we are and this
session's goal before doing anything else.

CONTEXT: Phase 2 (KILL-GATE). Profiler built; CONDITIONAL GO stands but UNPROVEN (curve
still on a ~3-hr launch snapshot: blind -12%, signal +6.8% net over 19 fires, p=0.008).
LAST SESSION: Flipside-free self-signup turned out to be effectively CLOSED (enterprise/
demo model as of 2026), so we PIVOTED to DUNE as the primary free archive (open signup,
free plan publicly committed for 2026; dex_solana.trades is decoded + survivorship-
complete). Built provider-agnostic Dune AND Flipside adapters with pure tested mappers
(51/51 tests green). Flipside stays as a swap-in if access reopens.

GOAL THIS SESSION (all $0 / GREEN unless noted):
  1. Confirm `autocrypt collect` is still running (ps / data/collect.log); report window.
     Restart if dead. (Optional, ask first: launchd job for reboot-survival.)
  2. PREREQ (operator action): a free Dune API key in .env as DUNE_API_KEY (dune.com →
     Settings → API), AND the DEX_TRADES_SQL from src/autocrypt/providers/dune.py saved as
     a Dune query with `since`/`till` TIMESTAMP params — give me its numeric query_id.
  3. Run ONE free validation execution via the Dune adapter: confirm field paths against a
     real pull, measure free-tier CREDIT COST + row caps for a small window, and confirm
     survivorship (dead/rugged tokens present). Report caps honestly.
  4. If caps allow, backfill the ~14d SOL+USDC enumerate-by-(first-trade) universe via Dune,
     `autocrypt qc` it, then RE-RUN `autocrypt profile` on it and present the UPDATED
     frequency-vs-expectancy curve + permutation p. That curve is the GO/NO-GO instrument.
     Watch: horizon-censoring vs real pool deaths/rugs (mark-to-rug, don't drop); depth
     still estimated; signal holding out-of-window; surrogate pool key groups by
     (base,quote,project). Re-confirm GO / start Phase 3 ONLY with explicit human sign-off.

NOTE: running `autocrypt profile` needs the DuckDB writer lock, which `collect` holds —
briefly pause collect (ask me; idempotent + survivorship-safe) or point the profiler at a
separate backfilled DB.

Autonomy: GREEN for all read-only/simulated/backtest/code work (collector, profiler, Dune
+ Flipside adapters and free validation queries, free signups). YELLOW: any PAID tier
(e.g. CoinGecko Analyst $129/mo if Dune free credits are too tight — needs an explicit
cap), and the GO/NO-GO re-confirmation before Phase 3. RED unchanged (no keys/funds/
live/safety-bypass).

First concrete step: report collect status; if the Dune key + query_id are in, run the
validation execution; otherwise build/refine whatever is $0 and tell me exactly what you
need from me to proceed.
```
