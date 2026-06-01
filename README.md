# AutoCrypt

A research-first project to test whether **on-chain signals reliably precede large low-cap Solana run-ups**, and — only if that edge proves real under honest testing — to act on it autonomously with tight risk controls.

> **Status:** Phase 0 (scaffolding) complete. Phase 1 (data ingestion) is next. No code, no funds, no keys yet.
>
> **Reality check:** low-cap Solana speculation is statistically a losing game for most participants. This project is a bet that one specific, *measurable* edge survives realistic costs. **Phase 2 is a kill-gate** — if the backtest doesn't show a profitable operating point honestly, the project stops or pivots. This is not financial or legal advice; you are responsible for your own tax/regulatory compliance.

## Repo map

| File | Purpose |
|------|---------|
| `Project_spec.md` | **Authoritative** state: goals, decisions, constraints, architecture, tooling, phase plan. Start here. |
| `CLAUDE.md` | Light per-session instructions for Claude Code: workflow + autonomy policy. Read every session. |
| `docs/phase-*-synthesis.md` | One synthesis per phase. The latest holds current state + the next-session kickoff prompt. |
| `.claude/settings.json` | Permission rules (allow dev commands; deny secret reads + destructive commands). |
| `.gitignore` | Blocks secrets/keys/wallets from ever being committed. |

## How to run a session

1. Open Claude Code in this repo. **Use auto mode** for hands-off-but-safe execution:
   ```bash
   claude --permission-mode auto
   ```
   (Auto mode runs without permission prompts but applies a background safety classifier and the allow/deny rules above. Do **not** use `--dangerously-skip-permissions` outside an isolated container — it has no prompt-injection protection.)
2. Paste the kickoff prompt from the **latest** `docs/phase-*-synthesis.md` (the Phase 1 prompt is in `docs/phase-0-session-synthesis.md`).
3. Let it run the phase to completion. It only pauses for **YELLOW** checkpoints (paid APIs, schema sign-off, phase gates) and never auto-performs **RED** actions (keys, real funds, going live, disabling safety controls) — see `CLAUDE.md` §3.
4. At the end it writes the next synthesis doc, updates the spec, and prints the next kickoff prompt to copy.

## Setup notes

- Python 3.11+, virtualenv, secrets in `.env` only (git-ignored, read via env vars — never hardcoded).
- Make this a git repo: `git init && git add . && git commit -m "Phase 0: project scaffolding"`. Work happens on `phase-N` branches; you merge to `main`.
