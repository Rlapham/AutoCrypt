# AutoCrypt

A **research-first** project to test whether on-chain signals reliably precede sustained Solana
price moves — and, *only if* such an edge survives honest, cost-realistic, survivorship-safe
testing, to act on it autonomously with tight risk controls. The discipline is the point: every
strategy passes through a **kill-gate** that must show a profitable operating point on
point-in-time data, or it is reported as a NO-GO and shelved. We do not tune backtests to
manufacture a positive.

> **Status (2026-06-08):** Two strategy iterations tested. **Iteration 1 (short-hold low-cap) —
> conclusive NO-GO. Iteration 2 / Track M (daily mid-cap price signals) — NO-GO, closed.**
> **Iteration 2 / Track G (graduation accumulator) — the main goal: fully built and armed,
> now DATA-GATED** — a durable collector is accruing a survivorship-complete dataset; the
> go/no-go test runs once it ripens (~weeks out). No funds, no keys, no live trading — paper/
> research only.
>
> **Reality check:** low-cap Solana speculation is statistically a losing game for most
> participants. This project is a bet that one specific, *measurable* edge survives realistic
> costs — and so far the data has killed every edge we've tested except the one still accruing.
> This is not financial or legal advice; you are responsible for your own tax/regulatory compliance.

## What we're testing, and what we've found

The core instrument is a **kill-gate profiler**: it replays history under a strict no-look-ahead
gate (`knowable_at <= T`), measures outcomes from `event_time`, prices trades with realistic
execution costs (fees + own price impact, both legs), keeps dead/rugged pools in the denominator
(survivorship-safe), and only passes a signal that beats both a blind baseline and a random
permutation after a multiple-comparison discount. Strategies are run through it stage by stage.

### Iteration 1 — short-hold low-cap Solana → **conclusive NO-GO (shelved)**
Tested both a derivative-composite price signal and the project's claimed defensible edge —
**lead-weighted wallet attribution** — on real, survivorship-complete on-chain data. Both lose
badly (blind ≈ −28%; tightening toward "smart money" makes it *worse*, → −82%, i.e. it
anti-predicts — you become exit liquidity). The cause is **structural, not tunable**: mean
~60-second drift ≈ 0%, while round-trip costs on thin fresh-launch pools are ~20–28%. No entry
signal can clear that.

### Iteration 2, Track M — mid-cap deep-pool, daily signals → **NO-GO, closed**
Built a free, survivorship-aware mid-cap universe (n=113 deep-pool names) and re-ran the gate.
- **Key positive finding:** in deep pools, round-trip friction collapses to **~0.8–0.9%** (vs
  20–28%) — the cost wall that killed Iteration 1 is *not* universal; the binding constraint
  becomes capacity, not cost.
- **But** a transparent daily price-signal battery (TS/XS momentum, mean-reversion, volume-gated
  breakout) is a NO-GO: none beats random after discounting; cost drag still slightly exceeds the
  marked drift at tradeable size. The gate closed on its own statistics, not on survivorship bias.
  *(Caveat: only daily, price-only signals were tested — not intraday or richer liquidity/flow features.)*

### Iteration 2, Track G — graduation accumulator → **THE MAIN GOAL, in progress, DATA-GATED**
Thesis: enter tokens *after they graduate* (bonding-curve → deep AMM pool, e.g.
pump.fun → pumpswap) and ride a multi-day "accumulator" arc — a longer horizon in deeper
liquidity that sidesteps the cost wall. Every component is now built and tested:
- **Graduation detection** — point-in-time, survivorship-complete; genuine graduation rate
  **~1.67%**, dominated by pump.fun → pumpswap (Meteora co-launch artifacts are flagged & excluded).
- **Accumulator success label** — within N days the token must both appreciate AND survive
  (a moon-then-rug is a *failure*); resolves at the horizon, no early resolution.
- **Wallet-attribution book** over the graduated cohort — surfaces a *followable* accumulator
  cohort, reusing the same point-in-time scoring machinery; survivorship-safe by construction.
- **Durable collection** — a launchd-managed forward collector accrues the cohort survivorship-
  completely and now survives reboot/crash (the durability gap that previously cost days is closed).

**Current state:** the collector is healthy and capturing the right deep pools richly, but the
strategy is **not yet testable** — the multi-day horizon means *zero trials have resolved* on the
young dataset (latest poll: 231 genuine graduations, 15 cohort pools, 1,085 wallet trials, **0
resolved → "not ripened"**). The Track-G go/no-go is gated purely on **uptime** now (~1–3 weeks),
not on any remaining build work.

See `Project_spec.md` for the authoritative, detailed state and the full phase checklist.

## Repo map

| Path | Purpose |
|------|---------|
| `Project_spec.md` | **Authoritative** state: goals, decisions, constraints, architecture, per-stage findings, phase plan. Start here. |
| `CLAUDE.md` | Light per-session instructions for Claude Code: workflow + autonomy policy (GREEN/YELLOW/RED). Read every session. |
| `docs/iteration-2-strategy.md` | The current strategy & phase plan (Track M + Track G). |
| `docs/phase-*-synthesis.md` | One synthesis per stage; the latest holds current state + the next-session kickoff prompt. |
| `docs/event-schema.md`, `docs/data-dictionary.md` | The signed-off canonical event schema + the three-time no-look-ahead discipline (`event_time`/`knowable_at`/`observed_at`) and stored fields. |
| `docs/phase-2-profile.md`, `docs/phase-M*-*.md`, `docs/phase-G*-*.md` | Kill-gate outputs and the per-stage GO/NO-GO evidence. |
| `src/autocrypt/` | The package: `schema/`, `storage/` (DuckDB), `providers/`, `ingestion/` (the collector), `profiler/` (the kill-gate), `attribution/`, `midcap/` (Track M), `grad/` (Track G). |
| `tests/` | Unit tests pinning the no-look-ahead / survivorship discipline (127 passing). |
| `.claude/settings.json` | Permission rules (allow dev commands; deny secret reads + destructive commands). |
| `.gitignore` | Blocks secrets/keys/wallets from ever being committed. |

## Tooling

Python 3.11+, managed with [`uv`](https://docs.astral.sh/uv/). The CLI entry point is `autocrypt`:

```bash
uv run autocrypt stats                 # what's in the store
uv run autocrypt qc                    # data-quality / no-look-ahead checks
uv run autocrypt collect               # forward collector (run durably under launchd; see below)
uv run autocrypt profile               # the kill-gate frequency-vs-expectancy curve
uv run autocrypt grad-detect           # Track G: graduation census (read-only)
uv run autocrypt grad-walletbook       # Track G: accumulator wallet book + ripening report
uv run autocrypt midcap-killgate       # Track M: signal battery through the gate
```

Data lives in DuckDB stores under `data/` (`autocrypt_graduation.duckdb` for Track G,
`autocrypt_midcap.duckdb` for Track M). **The live collector holds a single-writer lock**, so run
analytics against a *snapshot copy*:

```bash
cp data/autocrypt_graduation.duckdb /tmp/grad_snap.duckdb
DB_URL=duckdb:///tmp/grad_snap.duckdb uv run autocrypt grad-walletbook
```

The Track-G collector runs durably as a launchd LaunchAgent (`com.autocrypt.collector`,
`RunAtLoad`+`KeepAlive`) so it survives reboot and crash. Health check:

```bash
launchctl print "gui/$(id -u)/com.autocrypt.collector" | grep "state ="
```

## How to run a session

1. Open Claude Code in this repo. **Use auto mode** for hands-off-but-safe execution:
   ```bash
   claude --permission-mode auto
   ```
   (Auto mode runs without permission prompts but applies a background safety classifier and the
   allow/deny rules above. Do **not** use `--dangerously-skip-permissions` outside an isolated
   container — it has no prompt-injection protection.)
2. Read `Project_spec.md` and the latest `docs/*-synthesis.md`, then paste that synthesis's
   kickoff prompt to orient the session.
3. Let it run the stage to completion. It only pauses for **YELLOW** checkpoints (paid APIs, schema
   sign-off, phase/strategy gates, collector-policy changes) and never auto-performs **RED** actions
   (keys, real funds, going live, disabling safety controls) — see `CLAUDE.md` §3.
4. At the end it writes the next synthesis doc, updates the spec, and hands off a commit plan.

## Setup notes

- Python 3.11+, `uv` for env + deps; secrets in `.env` only (git-ignored, read via env vars —
  never hardcoded). The `.claude/settings.json` deny rules block reads of `.env`/`secrets/`.
- **Time discipline (load-bearing):** every record is stamped with the time it *could have been
  known* (`knowable_at`), never fetch time. No look-ahead — treat any violation as a bug.
- **Git is run by the human**, on a separate interface. Work happens on `phase-N` branches and is
  merged to `main`; sessions leave a clean tree and a described commit plan rather than running git.
