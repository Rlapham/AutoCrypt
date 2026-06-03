"""Track M (Iteration 2) — mid-cap deep-pool universe + point-in-time OHLCV.

The verdict machinery (profiler, schema, store) is shared with Iteration 1; only the
cohort changes. The #1 validity risk here is survivorship: the free tiers expose only a
*current* top-pools snapshot, never historical universe membership. See
`docs/phase-M1-synthesis.md` for the empirical finding and the two-mode response:

- `snapshot_universe` (FORWARD, clean): record the enumerated universe now and on a
  schedule, flagging band membership, so a point-in-time survivorship-safe set accrues
  over wall-clock (a pool that later dies is still in earlier snapshots).
- `build_control_dataset` (BIASED, immediate): ingest today's in-band pools' OHLCV as an
  explicitly survivorship-BIASED upper bound. By asymmetry (bias only inflates returns)
  this can yield a decisive NO-GO or "unproven" — never a GO. Never treat it as a pass.
"""
