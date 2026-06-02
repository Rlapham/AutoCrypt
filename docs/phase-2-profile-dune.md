# Phase 2 — Frequency-vs-Expectancy Profile (KILL-GATE output)

- Universe (survivorship-complete, created pools w/ swaps): **812** pools; used (enough history): **616**
- Hold horizon: **60s**; position size: **$250**; costs: fees + own price impact (constant-product) on both legs
- Eligible pool-minutes: **6470.3**; scored fires (blind): **2017**, censored: **196**


## Frequency-vs-expectancy curve

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| blind | 1763 | 259 | 0.272 | 23.3% | -15.99% | -8.21% | +0.43% | +16.41% | -26.13% / -0.61% | 254 | 196 |
| -3.400 | 1763 | 259 | 0.272 | 23.3% | -15.99% | -8.21% | +0.43% | +16.41% | -26.13% / -0.61% | 254 | 196 |
| -0.343 | 1347 | 211 | 0.208 | 25.8% | -15.16% | -6.50% | +0.63% | +15.79% | -25.45% / +0.24% | 166 | 117 |
| 0.009 | 888 | 197 | 0.137 | 25.5% | -16.06% | -7.33% | +0.68% | +16.74% | -27.31% / +0.11% | 121 | 78 |
| 0.394 | 416 | 176 | 0.064 | 19.2% | -20.84% | -14.43% | +0.60% | +21.44% | -33.93% / -2.30% | 89 | 39 |
| 1.500 | 170 | 111 | 0.026 | 21.2% | -22.33% | -15.82% | +2.27% | +24.60% | -40.24% / -2.37% | 33 | 17 |
| 2.885 | 87 | 69 | 0.013 | 20.7% | -24.98% | -19.27% | +2.80% | +27.78% | -42.68% / -4.06% | 14 | 8 |
| 19.008 | 21 | 20 | 0.003 | 28.6% | -33.45% | -37.94% | +3.06% | +36.51% | -64.60% / +6.90% | 0 | 2 |

## Blind baseline by hold horizon

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h=30s | 3363 | 282 | 0.520 | 16.3% | -16.35% | -8.33% | +0.32% | +16.67% | -22.74% / -2.04% | 451 | 193 |
| h=60s | 1763 | 259 | 0.272 | 23.3% | -15.99% | -8.21% | +0.43% | +16.41% | -26.13% / -0.61% | 254 | 196 |
| h=120s | 904 | 227 | 0.140 | 28.7% | -16.42% | -8.74% | +0.54% | +16.96% | -30.32% / +2.01% | 143 | 217 |

## Depth-assumption sensitivity (blind expectancy)

Depth is the biggest modelling assumption (estimated from observed impact). If the sign of expectancy flips across this sweep, the verdict is fragile.

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| depth x0.5 | 1763 | 259 | 0.272 | 15.1% | -22.58% | -13.86% | +0.43% | +23.01% | -35.30% / -3.10% | 254 | 196 |
| depth x1 | 1763 | 259 | 0.272 | 23.3% | -15.99% | -8.21% | +0.43% | +16.41% | -26.13% / -0.61% | 254 | 196 |
| depth x2 | 1763 | 259 | 0.272 | 30.5% | -11.39% | -4.66% | +0.43% | +11.82% | -19.07% / +1.66% | 254 | 196 |

## Rug gate on/off (blind)

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rug ON | 1763 | 259 | 0.272 | 23.3% | -15.99% | -8.21% | +0.43% | +16.41% | -26.13% / -0.61% | 254 | 196 |
| rug OFF | 2017 | 289 | 0.312 | 21.7% | -19.16% | -9.78% | +1.51% | +20.67% | -30.53% / -0.99% | 0 | 196 |

## Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net return >= the signal's subset). Low p ⇒ the signal selected better-than-random entries — a stricter bar than beating blind entry. Note multiple thresholds are tested, so apply a multiple-comparison discount.

| threshold | n | mean net | p(random >= obs) |
|---|---|---|---|
| -0.343 | 1347 | -15.16% | 0.022 |
| 0.009 | 888 | -16.06% | 0.540 |
| 0.394 | 416 | -20.84% | 1.000 |
| 1.500 | 170 | -22.33% | 0.998 |
| 2.885 | 87 | -24.98% | 0.997 |
| 19.008 | 21 | -33.45% | 0.993 |

## Signal-value distribution (composite score)

| quantile | p0 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| value | -3.400 | -0.343 | 0.009 | 0.394 | 1.500 | 2.885 | 19.008 |
