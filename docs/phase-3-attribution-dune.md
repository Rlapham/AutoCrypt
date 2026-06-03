# Phase 3 — Wallet-Attribution Signal Profile (on the kill-gate harness)

Profiles the **lead-weighted wallet-attribution** signal (Project_spec §2 — the claimed *defensible edge*) on the exact same survivorship-complete, point-in-time profiler as the Phase-2 derivative kill-gate, so the two are directly comparable. The signal fires when wallets with a **demonstrated historical lead on run-ups** (scored only from trials resolved before the decision) are buying the pool now.

- Universe (survivorship-complete, created pools w/ swaps): **812** pools; used (enough history): **617**
- Hold horizon: **60s**; position size: **$250**; costs: fees + own price impact (constant-product) on both legs
- Eligible pool-minutes: **6470.3**; scored fires (blind): **1201**, censored: **205**

- Attribution book: **32,475** wallets / **59,597** resolved entry-trials over **3,625** pools; final population lead rate **20.3%** (run-up = +100% within window). 'blind' here = fire whenever the attribution signal is *defined* (>=1 recent buyer with track record), so it already conditions on smart-money presence.


## Frequency-vs-expectancy curve

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| blind | 995 | 262 | 0.154 | 15.3% | -28.12% | -19.38% | -0.03% | +28.09% | -45.16% / -5.84% | 206 | 205 |
| -0.138 | 995 | 262 | 0.154 | 15.3% | -28.12% | -19.38% | -0.03% | +28.09% | -45.16% / -5.84% | 206 | 204 |
| -0.035 | 728 | 228 | 0.113 | 18.1% | -27.28% | -19.90% | -0.26% | +27.02% | -48.44% / -3.76% | 173 | 153 |
| -0.001 | 459 | 188 | 0.071 | 17.2% | -31.30% | -25.12% | -0.68% | +30.62% | -62.52% / -6.66% | 142 | 128 |
| 0.040 | 190 | 104 | 0.029 | 18.9% | -42.41% | -46.28% | -0.41% | +42.00% | -85.32% / -8.89% | 111 | 99 |
| 0.159 | 51 | 30 | 0.008 | 2.0% | -82.09% | -87.82% | -8.66% | +73.43% | -94.57% / -78.45% | 70 | 53 |
| 0.188 | 28 | 14 | 0.004 | 0.0% | -79.69% | -84.22% | -13.34% | +66.35% | -93.99% / -76.79% | 33 | 22 |
| 0.229 | 10 | 5 | 0.002 | 0.0% | -72.32% | -74.06% | +6.09% | +78.42% | -86.48% / -55.06% | 3 | 4 |

## Blind baseline by hold horizon

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h=30s | 1756 | 285 | 0.271 | 11.9% | -27.68% | -17.98% | -0.01% | +27.67% | -38.28% / -7.14% | 350 | 200 |
| h=60s | 995 | 262 | 0.154 | 15.3% | -28.12% | -19.38% | -0.03% | +28.09% | -45.16% / -5.84% | 206 | 205 |
| h=120s | 562 | 226 | 0.087 | 19.4% | -30.14% | -22.98% | -0.07% | +30.06% | -61.51% / -5.57% | 130 | 224 |

## Depth-assumption sensitivity (blind expectancy)

Depth is the biggest modelling assumption (estimated from observed impact). If the sign of expectancy flips across this sweep, the verdict is fragile.

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| depth x0.5 | 995 | 262 | 0.154 | 9.8% | -36.84% | -30.14% | -0.03% | +36.80% | -56.74% / -13.50% | 206 | 205 |
| depth x1 | 995 | 262 | 0.154 | 15.3% | -28.12% | -19.38% | -0.03% | +28.09% | -45.16% / -5.84% | 206 | 205 |
| depth x2 | 995 | 262 | 0.154 | 22.9% | -21.66% | -12.38% | -0.03% | +21.63% | -37.38% / -1.15% | 206 | 205 |

## Rug gate on/off (blind)

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rug ON | 995 | 262 | 0.154 | 15.3% | -28.12% | -19.38% | -0.03% | +28.09% | -45.16% / -5.84% | 206 | 205 |
| rug OFF | 1201 | 301 | 0.186 | 13.9% | -32.68% | -22.96% | +1.71% | +34.39% | -63.05% / -6.81% | 0 | 205 |

## Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net return >= the signal's subset). Low p ⇒ the signal selected better-than-random entries — a stricter bar than beating blind entry. Note multiple thresholds are tested, so apply a multiple-comparison discount.

| threshold | n | mean net | p(random >= obs) |
|---|---|---|---|
| -0.035 | 728 | -27.28% | 0.117 |
| -0.001 | 459 | -31.30% | 0.993 |
| 0.040 | 190 | -42.41% | 1.000 |
| 0.159 | 51 | -82.09% | 1.000 |
| 0.188 | 28 | -79.69% | 1.000 |
| 0.229 | 10 | -72.32% | 1.000 |

## Signal-value distribution (attribution lift)

| quantile | p0 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| value | -0.138 | -0.035 | -0.001 | 0.040 | 0.159 | 0.188 | 0.229 |
