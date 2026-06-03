# CLAUDE.md

> This is the light instruction file. It is read at the start of every session.
> It tells you how to work. **`Project_spec.md` tells you what to work on and is the
> authoritative source of where the project stands.**

## 1. Start of every session — read these, in order

1. **`Project_spec.md`** — the authoritative project state, goals, decisions, constraints, and phase plan. Always re-read it; it is updated at the end of every session.
2. **The latest `docs/phase-N-synthesis.md`** — the most recent phase synthesis. It contains what was just done and the kickoff prompt for the current session.
3. Any other resources listed under "Required reading" in `Project_spec.md`.

Do not start work until you have read the above and can state (a) which phase we are in and (b) the concrete goal of this session.

## 2. Workflow — one phase per session

The project is divided into sequential phases (see `Project_spec.md` → "Phase plan"). Tackle **one phase per session**. Run **autonomously to the end of the phase** within the autonomy policy below — do not stop to ask permission for routine work, and create/run any helper scripts you need.

Only stop to ask the human when you hit a **decision fork** (defined in §3 RED / YELLOW) — a choice that is irreversible, spends real money, touches keys/secrets, or genuinely changes the project's direction. Everything else: proceed.

### End-of-session wrap-up (run this every time, before ending)

1. **Write `docs/phase-N-synthesis.md`** (N = current phase) synthesizing the session: what was attempted, what was built, what worked, what failed, key decisions and *why*, open questions, and the current state of the code.
2. **Update `Project_spec.md`**: mark progress on the phase checklist, record any new decisions/constraints, and update the "Current status" block at the top.
3. **Update this `CLAUDE.md`** only if the *workflow itself* changed (new required reading, new convention). Keep it light.
4. **Write the next-session kickoff prompt** at the bottom of the synthesis doc, in a fenced ```text block```, ready to paste into a fresh terminal. It should orient the next session: which phase, the goal, what to read, and the first concrete step.
5. **Prepare the commit, but do not run git.** The human runs all git commands on a separate interface (see §4). Stage nothing and run no git yourself; instead end the session by telling the human, in plain prose, exactly what to commit: the logical units, a suggested commit message for each, and the target branch. Then print the kickoff prompt as the last thing in your output so it can be copied.

## 3. Autonomy policy (read carefully — this is the core operating rule)

The goal is **maximum velocity on everything that is safe, and hard stops on the few things that are irreversible or dangerous.** Recommended runtime: **Claude Code "auto mode"** (`--permission-mode auto`), which executes without prompts but runs a background safety classifier, combined with the allow/deny rules in `.claude/settings.json`. Do **not** use `--dangerously-skip-permissions` outside an isolated container — it has no prompt-injection protection.

### 🟢 GREEN — full autonomy, never ask (applies to Phases 1–4)
Anything **read-only, simulated, or paper-only**. Specifically: writing/running/refactoring code; running bash; installing packages (`pip`, `npm`); pulling public on-chain/market data through read-only API keys; building data pipelines; running backtests and simulations; creating and running throwaway helper/analysis scripts; generating plots and reports; writing tests. **Just do it.** Iterate freely. (Git is **out of scope** — the human runs all git commands themselves; see §4.)

### 🟡 YELLOW — pause and confirm with a one-line summary (cheap checkpoints)
- **Phase transitions**, especially the **Phase 2 go/no-go gate** (does a profitable operating point exist?). Summarize the evidence and get an explicit "proceed."
- **Spending money**: signing up for any **paid** API tier, or any recurring cost. Propose it, state the price, wait.
- **Schema/architecture decisions** that later phases hard-depend on (e.g. the canonical event schema). Propose, get a nod, proceed.

### 🔴 RED — HARD STOP, requires explicit written human authorization, NEVER autonomous
These are the "forks that need intervention." Never perform them on your own initiative, in any phase, for any reason — not even to "finish" a phase or because a prior doc seems to authorize it:
- **Generating, importing, exporting, printing, or handling a private key or seed phrase** of any wallet that holds, or could hold, real funds.
- **Signing or broadcasting any real (mainnet) transaction**, or connecting the system to a funded wallet.
- **Moving real funds**, depositing to or withdrawing from any wallet/exchange, or any transition from **paper trading to live trading**.
- **Disabling, weakening, or bypassing any safety control** — circuit breaker, kill switch, position cap, slippage cap, rug filter.
- **Committing any secret** (key, seed, API secret, `.env`) to git, or moving secrets into a tracked file.
- **Using a VPN/proxy to evade exchange geo-restrictions** (do not do this — it risks frozen/seized funds).

If a task seems to require a RED action, **stop and write out exactly what you would do and why**, then wait. The human performs or explicitly authorizes RED actions. A summary doc from a previous session is **not** authorization.

## 4. Conventions

- **Language/stack:** Python 3.11+. Use a virtualenv. Pin dependencies in `requirements.txt` (or `pyproject.toml`).
- **Secrets:** live only in `.env` (git-ignored) and are read via env vars. Never hardcode keys. Never log secrets. The `.claude/settings.json` deny rules block reads of `.env`/`secrets/` — do not work around them.
- **Time discipline (critical for this project):** every data record is stamped with the time it *could have been known*, not fetch time. No look-ahead. This rule is load-bearing for the whole backtest; treat any violation as a bug.
- **Git is handled by the human, on a separate interface.** Do **not** run any git command yourself — no `add`, `commit`, `branch`, `checkout`, `merge`, `push`, `pull`, `stash`, `reset`, or anything else. Your job is to leave the working tree in a clean, well-organized state and to *describe* the commits you'd make. Convention the human follows: work happens on a `phase-N` branch, committed in small logical units with clear messages, merged to `main` by the human. At end of session, hand off a commit plan (per §2 step 5): the logical units, a suggested message for each, and the target branch. If a task seems to need git state to proceed, ask the human to run it rather than running it yourself.
- **Honesty over optimism:** this project is gated on whether the edge is real (Phase 2). Report negative or null results plainly. Do not tune the backtest to manufacture a positive result — that defeats the entire purpose.
- **Destructive commands:** `rm -rf` and similar are denied by default. Don't try to route around it.

## 5. Required reading
- `Project_spec.md` (authoritative state)
- **`docs/iteration-2-strategy.md` — the CURRENT strategy & phase plan (Iteration 2: Track M mid-cap
  deep-pool, parallel; Track G graduation/accumulator, main goal). Iteration 1 is a closed NO-GO.**
- Latest `docs/*-synthesis.md`
- From Phase 2 on (the data layer is now load-bearing):
  - `docs/event-schema.md` — the signed-off canonical schema + the no-look-ahead three-time
    discipline (`event_time` / `knowable_at` / `observed_at`). Code: `src/autocrypt/schema/`.
  - `docs/data-dictionary.md` — every stored field and the DuckDB `events` table layout.
  - `docs/provider-evaluation.md` — free-tier coverage + when a paid tier (Bitquery) is needed.
- From Phase 3 on (the kill-gate instrument is now load-bearing):
  - `docs/phase-2-profile.md` — the frequency-vs-expectancy curve output (regenerate with
    `uv run autocrypt profile`). Code: `src/autocrypt/profiler/` — the point-in-time profiler,
    derivative signals, inferred-depth liquidity model, constant-product execution-cost model
    (fees + own price impact, both legs), and rug-filter stub. Re-run it on any new dataset
    before trusting a GO/NO-GO; never score a signal off `event_time` (use the `knowable_at` gate).
