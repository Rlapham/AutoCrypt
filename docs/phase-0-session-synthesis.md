# Phase 0 — Session Synthesis (Planning & Scaffolding)

*This is the synthesis of the planning conversation that originated the project. It captures how we got to the current decisions so future sessions understand the "why," not just the "what." For authoritative current state, see `Project_spec.md`.*

## What this session did

A multi-step brainstorming session that took a vague idea ("use Claude Code to help trade crypto by finding pre-run-up patterns, maybe via social chatter") and narrowed it, decision by decision, into a concrete, validated-by-design project shape. Then scaffolded the repo for handoff to Claude Code.

## The reasoning chain (decisions and why)

1. **Where's the edge?** Raw social chatter is not an edge — it's lagging and partly manufactured by holders, i.e. the exit-liquidity mechanism aimed at naive "chatter → buy" bots. The edge candidates are: the *derivative* of mentions (not the level), *source/wallet attribution* (lead-lag), and *on-chain data* (which leads social). Reframe: social-chatter *peak* is better as an **exit/crowding** signal than an entry.

2. **Public-only operator.** No private group access ⇒ the edge must come from **on-chain data**, not social. The most defensible asset is a **wallet-attribution model**: weight wallets by their demonstrated historical *lead* on run-ups. Express features as **derivatives** (rate-of-change), not levels.

3. **Autonomous vs manual.** Chose **autonomous where safe** (Tier 1, on-chain). Autonomy's real payoff for a public-only operator is **running a processing edge 24/7 without emotional error** — NOT winning the millisecond latency race (a Python bot on a cheap VPS loses that race to co-located capital). So we explicitly *avoid* betting the system on speed-racing (e.g. CEX listing snipes), and instead run a processing/attribution edge continuously.

4. **Chain.** **Solana to start** (highest opportunity density + sub-cent fees = the "many small trades" economics that high-ROI low-cap strategies need). **Base** as pre-committed fallback. **Ethereum L1 ruled out** as execution venue (fees kill high-frequency low-cap). The tension: Solana has the *most opportunities* but the *noisiest* version of the attribution signal (smart-money labels are deeper on ETH). Resolved by making it a testable hypothesis for Phase 2.

5. **Frequency reframed as the pivotal variable.** Signal frequency is a **threshold dial**, not a chain property — Solana can fire several/minute or a few/week depending on threshold. But high-frequency and low-frequency are **two different edges** (statistical vs judgmental), and conflating them is the trap. This is *measurable*, so the first concrete deliverable became a **signal-frequency-and-expectancy profiler** that decides the project's shape with evidence.

6. **Validation-first ordering.** The build sequence puts **data ingestion (Phase 1)** then a **survivorship-proof backtest / profiler (Phase 2)** *before* any execution code — Phase 2 is a kill-gate. Most people build execution first and validate never; we do the opposite. Brakes (risk layer, kill switches) are built before the engine.

7. **Workflow & autonomy handoff.** Phases tackled one-per-session; end-of-session wrap-up writes a synthesis doc + updates the spec + emits the next-session kickoff prompt. Autonomy is **maximal for safe (read-only/simulated/paper) work** and **hard-gated for anything touching keys, real funds, going live, or weakening a safety control** (see `CLAUDE.md` §3). Implemented via Claude Code **auto mode** + `.claude/settings.json` allow/deny rules (deny blocks reads of secrets and destructive commands).

## Key constraints established (full list in `Project_spec.md` §4)
Survivorship-proof backtest universe · no look-ahead (point-in-time) · realistic execution sim incl. own price impact · mandatory rug filters · custody discipline / never commit secrets · circuit breakers + kill switch before live · paper before capital, small before scale · no geo-evasion. Plus the honest framing: this is statistically-losing-by-default; the project is a bet that a specific edge survives realistic costs, and Phase 2 may say it doesn't.

## State of the code
None yet. Repo contains: `CLAUDE.md`, `Project_spec.md`, this synthesis, `.claude/settings.json` (autonomy rules), `.gitignore`, `README.md`. Phase 1 starts the actual build.

## Why we stopped here
Natural handoff point: planning is converged, the repo is scaffolded. Phase 1 (data ingestion) is a clean, self-contained, fully-GREEN-autonomy unit of work.

---

## ▶ Kickoff prompt for the next session (Phase 1) — paste into a fresh Claude Code terminal

```text
Read CLAUDE.md, then Project_spec.md, then this file (docs/phase-0-session-synthesis.md). Confirm back to me, in 3–4 sentences, which phase we're in and the goal of this session before doing anything else.

We are starting PHASE 1: Data ingestion + historical backfill for Solana, read-only. This phase is fully GREEN autonomy — build, run, install packages, write helper scripts freely; do not stop to ask permission for routine work. The only checkpoints are YELLOW items: pause and ask before signing up for any PAID API tier (propose it + state the price), and pause to get my sign-off on the canonical event schema before you build the rest of the pipeline on it (later phases depend on it).

Goals for this phase:
1. Stand up the Python project (venv, requirements, repo layout, .env handling — secrets via env vars only, never committed).
2. Design and propose the canonical, point-in-time-correct event schema for Solana token/liquidity/wallet events (new pools, swaps, liquidity changes, holder snapshots, tracked-wallet activity). CRITICAL: every record is stamped with the time it COULD HAVE BEEN KNOWN, not fetch time — no look-ahead. Pause here for my sign-off (YELLOW).
3. Build read-only ingestion in three modes: live streaming, periodic polling, and historical backfill. Evaluate free tiers first (Bitquery, Birdeye, DexPaprika/GeckoTerminal); only propose a paid tier if a free one can't cover the need (YELLOW).
4. Backfill a defined historical window into a local store (pick a sensible window and token universe — and remember the universe MUST include tokens that went nowhere or rugged, not just survivors, or Phase 2's backtest is invalid).
5. Add basic data-quality checks (gaps, dupes, timestamp sanity) and a short data dictionary in docs/.

Do NOT do anything from the RED list (no keys to funded wallets, no real transactions, no funds, no disabling safety controls). No trading logic in this phase — data only.

When the phase is done, run the end-of-session wrap-up from CLAUDE.md §2: write docs/phase-1-synthesis.md, update Project_spec.md and CLAUDE.md, emit the Phase 2 kickoff prompt, commit on a phase-1 branch, and print the kickoff prompt last.
```
