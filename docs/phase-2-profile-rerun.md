# Phase 2 — Frequency-vs-Expectancy Profile (KILL-GATE output)

- Universe (survivorship-complete, created pools w/ swaps): **90** pools; used (enough history): **57**
- Hold horizon: **60s**; position size: **$250**; costs: fees + own price impact (constant-product) on both legs
- Eligible pool-minutes: **224.0**; scored fires (blind): **95**, censored: **26**


## Frequency-vs-expectancy curve

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| blind | 83 | 23 | 0.371 | 33.7% | -12.36% | -7.24% | +6.91% | +19.27% | -25.59% / +2.53% | 12 | 26 |
| -2.454 | 83 | 23 | 0.371 | 33.7% | -12.36% | -7.24% | +6.91% | +19.27% | -25.59% / +2.53% | 12 | 25 |
| -0.836 | 63 | 19 | 0.281 | 36.5% | -11.91% | -6.13% | +8.36% | +20.28% | -25.06% / +2.97% | 8 | 20 |
| 0.000 | 42 | 19 | 0.188 | 31.0% | -11.58% | -6.41% | +11.91% | +23.49% | -25.06% / +2.03% | 7 | 13 |
| 0.605 | 19 | 13 | 0.085 | 47.4% | +6.80% | -1.39% | +26.41% | +19.61% | -18.71% / +23.71% | 5 | 7 |
| 1.597 | 9 | 7 | 0.040 | 44.4% | +2.73% | -1.39% | +15.99% | +13.26% | -11.20% / +26.72% | 1 | 3 |
| 2.204 | 4 | 4 | 0.018 | 50.0% | +4.94% | +8.07% | +17.77% | +12.82% | -16.33% / +29.34% | 1 | 2 |
| 4.535 | 1 | 1 | 0.004 | 100.0% | +35.33% | +35.33% | +47.89% | +12.56% | +35.33% / +35.33% | 0 | 1 |

## Blind baseline by hold horizon

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h=30s | 166 | 29 | 0.741 | 23.5% | -15.37% | -8.01% | +4.19% | +19.55% | -22.94% / -0.67% | 20 | 23 |
| h=60s | 83 | 23 | 0.371 | 33.7% | -12.36% | -7.24% | +6.91% | +19.27% | -25.59% / +2.53% | 12 | 26 |
| h=120s | 40 | 19 | 0.179 | 47.5% | +0.25% | -0.78% | +18.89% | +18.64% | -20.60% / +16.00% | 8 | 29 |

## Depth-assumption sensitivity (blind expectancy)

Depth is the biggest modelling assumption (estimated from observed impact). If the sign of expectancy flips across this sweep, the verdict is fragile.

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| depth x0.5 | 83 | 23 | 0.371 | 24.1% | -19.19% | -14.84% | +6.91% | +26.11% | -34.69% / -0.54% | 12 | 26 |
| depth x1 | 83 | 23 | 0.371 | 33.7% | -12.36% | -7.24% | +6.91% | +19.27% | -25.59% / +2.53% | 12 | 26 |
| depth x2 | 83 | 23 | 0.371 | 39.8% | -7.97% | -5.25% | +6.91% | +14.88% | -20.27% / +3.91% | 12 | 26 |

## Rug gate on/off (blind)

| threshold | fires | pools | fires/pool·min | hit | **expectancy** | median | marked | cost drag | p25/p75 | rug-blk | censored |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rug ON | 83 | 23 | 0.371 | 33.7% | -12.36% | -7.24% | +6.91% | +19.27% | -25.59% / +2.53% | 12 | 26 |
| rug OFF | 95 | 28 | 0.424 | 29.5% | -16.49% | -11.24% | +5.81% | +22.30% | -29.14% / +1.39% | 0 | 26 |

## Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net return >= the signal's subset). Low p ⇒ the signal selected better-than-random entries — a stricter bar than beating blind entry. Note multiple thresholds are tested, so apply a multiple-comparison discount.

| threshold | n | mean net | p(random >= obs) |
|---|---|---|---|
| -0.836 | 63 | -11.91% | 0.430 |
| 0.000 | 42 | -11.58% | 0.430 |
| 0.605 | 19 | +6.80% | 0.008 |
| 1.597 | 9 | +2.73% | 0.108 |

## Signal-value distribution (composite score)

| quantile | p0 | p25 | p50 | p75 | p90 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| value | -2.454 | -0.836 | 0.000 | 0.605 | 1.597 | 2.204 | 4.535 |
