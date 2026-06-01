# Phase 2 — Frequency-vs-Expectancy Profile (KILL-GATE output)

- Universe (survivorship-complete, created pools w/ swaps): **80** pools; used (enough history): **57**
- Hold horizon: **60s**; position size: **$250**; costs: fees + own price impact (constant-product) on both legs
- Eligible pool-minutes: **224.0**; scored fires (blind): **95**, censored: **26**


## Frequency-vs-expectancy curve

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| blind | 83 | 23 | 0.371 | 33.7% | -12.07% | -8.17% | +7.58% | +19.65% | -24.97% / +3.28% | 12 | 26 |
| -2.454 | 83 | 23 | 0.371 | 33.7% | -12.07% | -8.17% | +7.58% | +19.65% | -24.97% / +3.28% | 12 | 25 |
| -0.836 | 63 | 19 | 0.281 | 36.5% | -11.52% | -6.66% | +9.26% | +20.78% | -23.75% / +3.67% | 8 | 20 |
| 0.000 | 41 | 19 | 0.183 | 31.7% | -11.34% | -7.09% | +13.35% | +24.69% | -25.23% / +2.24% | 7 | 13 |
| 0.605 | 19 | 13 | 0.085 | 47.4% | +6.93% | -0.03% | +28.26% | +21.33% | -17.33% / +23.31% | 5 | 7 |
| 1.597 | 9 | 7 | 0.040 | 55.6% | +3.57% | +12.83% | +19.92% | +16.35% | -11.53% / +25.16% | 1 | 3 |
| 2.217 | 4 | 4 | 0.018 | 50.0% | +5.42% | +8.63% | +17.77% | +12.34% | -16.33% / +30.39% | 1 | 2 |
| 4.535 | 1 | 1 | 0.004 | 100.0% | +35.16% | +35.16% | +47.89% | +12.73% | +35.16% / +35.16% | 0 | 1 |

## Blind baseline by hold horizon

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h=30s | 166 | 29 | 0.741 | 22.9% | -15.29% | -8.68% | +4.55% | +19.84% | -23.71% / -0.61% | 20 | 23 |
| h=60s | 83 | 23 | 0.371 | 33.7% | -12.07% | -8.17% | +7.58% | +19.65% | -24.97% / +3.28% | 12 | 26 |
| h=120s | 40 | 19 | 0.179 | 47.5% | +0.62% | -1.05% | +19.25% | +18.63% | -20.97% / +22.59% | 8 | 29 |

## Depth-assumption sensitivity (blind expectancy)

Depth is the biggest modelling assumption (estimated from observed impact). If the sign of expectancy flips across this sweep, the verdict is fragile.

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| depth x0.5 | 83 | 23 | 0.371 | 25.3% | -19.05% | -15.28% | +7.58% | +26.63% | -34.24% / +0.04% | 12 | 26 |
| depth x1 | 83 | 23 | 0.371 | 33.7% | -12.07% | -8.17% | +7.58% | +19.65% | -24.97% / +3.28% | 12 | 26 |
| depth x2 | 83 | 23 | 0.371 | 39.8% | -7.57% | -5.27% | +7.58% | +15.15% | -18.82% / +4.70% | 12 | 26 |

## Rug gate on/off (blind)

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rug ON | 83 | 23 | 0.371 | 33.7% | -12.07% | -8.17% | +7.58% | +19.65% | -24.97% / +3.28% | 12 | 26 |
| rug OFF | 95 | 28 | 0.424 | 29.5% | -16.13% | -12.88% | +6.38% | +22.51% | -28.29% / +1.77% | 0 | 26 |

## Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net return >= the signal's subset). Low p ⇒ the signal selected better-than-random entries — a stricter bar than beating blind entry. Note multiple thresholds are tested, so apply a multiple-comparison discount.

| threshold | n | mean net | p(random >= obs) |
|---|---|---|---|
| -0.836 | 63 | -11.52% | 0.411 |
| 0.000 | 41 | -11.34% | 0.428 |
| 0.605 | 19 | +6.93% | 0.007 |
| 1.597 | 9 | +3.57% | 0.097 |

## Signal-value distribution (composite score)

| quantile | p0 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| value | -2.454 | -0.836 | 0.000 | 0.605 | 1.597 | 2.217 | 4.535 |
