# Phase M3 — Mid-cap deep-pool KILL-GATE (signal battery)

- Universe (in-band, speculative-only): **92** pools, source `coingecko_mcap_ranked` — **survivorship-BIASED** (today's survivors). A positive is an UPPER BOUND; ceiling on this control is **NO-GO/"unproven"**, never a GO.
- Hold horizon **5 bars (days)**; lookback **10**; position = min($10,000, 0.4% x reserve) [M2 capacity rule]; cost = fees 30bps/leg + own impact (both legs), depth = 0.5xreserve.
- Decisions are point-in-time (`knowable_at ≤ T`); entry close[i] → exit close[i+H]; one position per pool at a time (cooldown = horizon); censored trades reported.


## Verdict summary

| signal | scored | blind exp. | best exp. | verdict |
|---|---|---|---|---|
| `ts_mom` | 2855 | -0.78% | +2.13% | NO-GO — not better than random (discounted p=0.522) |
| `xs_mom` | 2814 | -0.71% | +2.32% | NO-GO — not better than random (discounted p=0.581) |
| `mean_rev` | 2855 | -0.78% | +11.01% | NO-GO — not better than random (discounted p=0.223) |
| `breakout` | 1807 | -0.25% | -0.25% | NO-GO — best net expectancy -0.25% not profitable after cost |

---

## `ts_mom` — Time-series momentum — buy when the trailing L-bar return is high (trend).

Pools used **92/92**; scored fires **2855**, censored **92**. Verdict: **NO-GO — not better than random (discounted p=0.522)**


### Frequency-vs-expectancy curve

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| blind | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| -0.944 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| -0.104 | 2141 | 92 | 0.75 | 30.3% | **-1.37%** | -2.33% | +0.64% | +2.00% | -7.45% / +1.41% |
| -0.015 | 1428 | 91 | 0.50 | 31.0% | **-0.73%** | -2.14% | +1.30% | +2.03% | -7.20% / +1.50% |
| 0.050 | 714 | 85 | 0.25 | 36.8% | **-0.26%** | -3.15% | +1.84% | +2.09% | -9.90% / +4.16% |
| 0.183 | 286 | 64 | 0.10 | 42.0% | **-0.28%** | -3.26% | +1.89% | +2.17% | -14.49% / +7.21% |
| 0.352 | 143 | 48 | 0.05 | 42.0% | **+2.13%** | -3.82% | +4.48% | +2.34% | -15.84% / +8.08% |

### Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net ≥ the signal's). Apply a multiple-comparison discount (several thresholds tested).

| threshold | n | mean net | p(random ≥ obs) |
|---|---|---|---|
| -0.104 | 2141 | -1.37% | 0.830 |
| -0.015 | 1428 | -0.73% | 0.489 |
| 0.050 | 714 | -0.26% | 0.312 |
| 0.183 | 286 | -0.28% | 0.240 |
| 0.352 | 143 | +2.13% | 0.104 |

### Robustness sweeps (blind expectancy)

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| horizon=3d | 4718 | 92 | 1.00 | 30.0% | **-1.31%** | -2.29% | +0.69% | +2.00% | -6.88% / +1.16% |
| horizon=5d | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| horizon=10d | 1422 | 90 | 1.00 | 32.7% | **-0.73%** | -3.18% | +1.33% | +2.06% | -12.62% / +3.33% |
| depthx0.5 | 2855 | 92 | 1.00 | 25.2% | **-2.15%** | -3.93% | +1.25% | +3.40% | -9.72% / +0.06% |
| depthx1 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| depthx2 | 2855 | 92 | 1.00 | 33.4% | **-0.08%** | -1.88% | +1.25% | +1.33% | -7.84% / +2.17% |
| lookback=5 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| lookback=10 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| lookback=20 | 2673 | 90 | 1.00 | 30.9% | **-0.70%** | -2.50% | +1.33% | +2.03% | -8.47% / +1.55% |
| window=early | 1484 | 89 | 1.00 | 28.6% | **-1.69%** | -3.32% | +0.31% | +1.99% | -9.64% / +1.01% |
| window=late | 1371 | 91 | 1.00 | 32.7% | **+0.20%** | -2.14% | +2.27% | +2.07% | -7.23% / +1.89% |

---

## `xs_mom` — Cross-sectional momentum — buy the universe's strongest trailing performers (percentile rank across all pools on the decision date).

Pools used **92/92**; scored fires **2814**, censored **92**. Verdict: **NO-GO — not better than random (discounted p=0.581)**


### Frequency-vs-expectancy curve

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| blind | 2814 | 92 | 1.00 | 30.7% | **-0.71%** | -2.56% | +1.32% | +2.04% | -8.49% / +1.46% |
| 0.000 | 2814 | 92 | 1.00 | 30.7% | **-0.71%** | -2.56% | +1.32% | +2.04% | -8.49% / +1.46% |
| 0.241 | 2111 | 91 | 0.75 | 29.7% | **-1.74%** | -2.47% | +0.25% | +2.00% | -8.23% / +1.25% |
| 0.500 | 1415 | 91 | 0.50 | 30.7% | **-1.44%** | -2.50% | +0.58% | +2.02% | -8.48% / +1.58% |
| 0.756 | 705 | 89 | 0.25 | 35.2% | **+0.09%** | -2.37% | +2.18% | +2.09% | -9.83% / +4.29% |
| 0.906 | 286 | 75 | 0.10 | 41.3% | **+2.32%** | -2.56% | +4.57% | +2.25% | -13.71% / +7.06% |
| 0.959 | 141 | 51 | 0.05 | 40.4% | **+1.54%** | -3.77% | +3.80% | +2.27% | -15.77% / +7.51% |

### Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net ≥ the signal's). Apply a multiple-comparison discount (several thresholds tested).

| threshold | n | mean net | p(random ≥ obs) |
|---|---|---|---|
| 0.241 | 2111 | -1.74% | 0.961 |
| 0.500 | 1415 | -1.44% | 0.747 |
| 0.756 | 705 | +0.09% | 0.278 |
| 0.906 | 286 | +2.32% | 0.116 |
| 0.959 | 141 | +1.54% | 0.121 |

### Robustness sweeps (blind expectancy)

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| horizon=3d | 4653 | 92 | 1.00 | 30.1% | **-1.24%** | -2.29% | +0.77% | +2.01% | -6.92% / +1.19% |
| horizon=5d | 2814 | 92 | 1.00 | 30.7% | **-0.71%** | -2.56% | +1.32% | +2.04% | -8.49% / +1.46% |
| horizon=10d | 1401 | 90 | 1.00 | 32.8% | **-0.02%** | -3.15% | +2.08% | +2.10% | -12.81% / +3.44% |
| depthx0.5 | 2814 | 92 | 1.00 | 25.3% | **-2.09%** | -3.92% | +1.32% | +3.42% | -9.81% / +0.08% |
| depthx1 | 2814 | 92 | 1.00 | 30.7% | **-0.71%** | -2.56% | +1.32% | +2.04% | -8.49% / +1.46% |
| depthx2 | 2814 | 92 | 1.00 | 33.5% | **-0.01%** | -1.87% | +1.32% | +1.33% | -7.87% / +2.23% |
| lookback=5 | 2818 | 92 | 1.00 | 30.7% | **-1.00%** | -2.58% | +1.03% | +2.03% | -8.49% / +1.46% |
| lookback=10 | 2814 | 92 | 1.00 | 30.7% | **-0.71%** | -2.56% | +1.32% | +2.04% | -8.49% / +1.46% |
| lookback=20 | 2636 | 90 | 1.00 | 31.1% | **-0.64%** | -2.49% | +1.40% | +2.04% | -8.48% / +1.58% |
| window=early | 1444 | 89 | 1.00 | 28.9% | **-1.59%** | -3.34% | +0.42% | +2.01% | -9.78% / +1.03% |
| window=late | 1370 | 91 | 1.00 | 32.6% | **+0.21%** | -2.10% | +2.28% | +2.07% | -7.24% / +1.91% |

---

## `mean_rev` — Mean-reversion — buy oversold names (negative z-score vs the trailing mean).

Pools used **92/92**; scored fires **2855**, censored **92**. Verdict: **NO-GO — not better than random (discounted p=0.223)**


### Frequency-vs-expectancy curve

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| blind | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| -43.549 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| -0.745 | 2141 | 92 | 0.75 | 29.3% | **-1.27%** | -2.77% | +0.74% | +2.00% | -8.76% / +1.11% |
| 0.431 | 1428 | 91 | 0.50 | 29.3% | **-0.67%** | -2.98% | +1.36% | +2.03% | -8.88% / +1.13% |
| 1.250 | 714 | 88 | 0.25 | 25.5% | **-0.84%** | -3.35% | +1.19% | +2.03% | -9.63% / +0.26% |
| 1.987 | 286 | 88 | 0.10 | 25.9% | **+3.88%** | -3.33% | +6.04% | +2.16% | -9.42% / +0.56% |
| 2.480 | 143 | 76 | 0.05 | 25.2% | **+11.01%** | -3.33% | +13.38% | +2.36% | -9.37% / -0.00% |

### Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net ≥ the signal's). Apply a multiple-comparison discount (several thresholds tested).

| threshold | n | mean net | p(random ≥ obs) |
|---|---|---|---|
| -0.745 | 2141 | -1.27% | 0.791 |
| 0.431 | 1428 | -0.67% | 0.473 |
| 1.250 | 714 | -0.84% | 0.409 |
| 1.987 | 286 | +3.88% | 0.096 |
| 2.480 | 143 | +11.01% | 0.045 |

### Robustness sweeps (blind expectancy)

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| horizon=3d | 4718 | 92 | 1.00 | 30.0% | **-1.31%** | -2.29% | +0.69% | +2.00% | -6.88% / +1.16% |
| horizon=5d | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| horizon=10d | 1422 | 90 | 1.00 | 32.7% | **-0.73%** | -3.18% | +1.33% | +2.06% | -12.62% / +3.33% |
| depthx0.5 | 2855 | 92 | 1.00 | 25.2% | **-2.15%** | -3.93% | +1.25% | +3.40% | -9.72% / +0.06% |
| depthx1 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| depthx2 | 2855 | 92 | 1.00 | 33.4% | **-0.08%** | -1.88% | +1.25% | +1.33% | -7.84% / +2.17% |
| lookback=5 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| lookback=10 | 2855 | 92 | 1.00 | 30.6% | **-0.78%** | -2.57% | +1.25% | +2.03% | -8.48% / +1.43% |
| lookback=20 | 2673 | 90 | 1.00 | 30.9% | **-0.70%** | -2.50% | +1.33% | +2.03% | -8.47% / +1.55% |
| window=early | 1484 | 89 | 1.00 | 28.6% | **-1.69%** | -3.32% | +0.31% | +1.99% | -9.64% / +1.01% |
| window=late | 1371 | 91 | 1.00 | 32.7% | **+0.20%** | -2.14% | +2.27% | +2.07% | -7.23% / +1.89% |

---

## `breakout` — Breakout — buy a close above the prior L-bar high, gated on volume expansion.

Pools used **90/92**; scored fires **1807**, censored **74**. Verdict: **NO-GO — best net expectancy -0.25% not profitable after cost**


### Frequency-vs-expectancy curve

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| blind | 1807 | 90 | 1.00 | 31.4% | **-0.25%** | -2.72% | +1.79% | +2.05% | -8.85% / +2.18% |
| -0.951 | 1807 | 90 | 1.00 | 31.4% | **-0.25%** | -2.72% | +1.79% | +2.05% | -8.85% / +2.18% |
| -0.178 | 1355 | 90 | 0.75 | 29.7% | **-1.08%** | -2.53% | +0.94% | +2.02% | -7.65% / +1.50% |
| -0.094 | 904 | 89 | 0.50 | 27.8% | **-1.22%** | -2.30% | +0.78% | +2.00% | -6.94% / +0.93% |
| -0.027 | 452 | 88 | 0.25 | 22.8% | **-0.99%** | -2.19% | +0.99% | +1.98% | -6.76% / -0.52% |
| 0.004 | 181 | 75 | 0.10 | 25.4% | **-1.32%** | -5.30% | +0.75% | +2.08% | -11.58% / +0.11% |
| 0.031 | 91 | 50 | 0.05 | 30.8% | **-0.93%** | -7.27% | +1.22% | +2.15% | -15.97% / +5.99% |

### Significance — does the signal beat RANDOM selection?

Permutation test (20k resamples, seeded): P(a random subset of the same size has mean net ≥ the signal's). Apply a multiple-comparison discount (several thresholds tested).

| threshold | n | mean net | p(random ≥ obs) |
|---|---|---|---|
| -0.178 | 1355 | -1.08% | 0.917 |
| -0.094 | 904 | -1.22% | 0.820 |
| -0.027 | 452 | -0.99% | 0.599 |
| 0.004 | 181 | -1.32% | 0.551 |
| 0.031 | 91 | -0.93% | 0.429 |

### Robustness sweeps (blind expectancy)

| threshold | fires | pools | fire-frac | hit | **expectancy** | median | marked | cost drag | p25/p75 |
|---|---|---|---|---|---|---|---|---|---|
| horizon=3d | 2515 | 91 | 1.00 | 30.1% | **-0.80%** | -2.40% | +1.22% | +2.02% | -7.38% / +1.27% |
| horizon=5d | 1807 | 90 | 1.00 | 31.4% | **-0.25%** | -2.72% | +1.79% | +2.05% | -8.85% / +2.18% |
| horizon=10d | 1041 | 90 | 1.00 | 33.6% | **+0.09%** | -3.23% | +2.18% | +2.10% | -12.51% / +2.90% |
| depthx0.5 | 1807 | 90 | 1.00 | 27.1% | **-1.64%** | -4.04% | +1.79% | +3.43% | -10.04% / +0.91% |
| depthx1 | 1807 | 90 | 1.00 | 31.4% | **-0.25%** | -2.72% | +1.79% | +2.05% | -8.85% / +2.18% |
| depthx2 | 1807 | 90 | 1.00 | 34.4% | **+0.45%** | -2.04% | +1.79% | +1.34% | -8.25% / +2.93% |
| lookback=5 | 2001 | 90 | 1.00 | 32.4% | **+0.02%** | -2.46% | +2.07% | +2.05% | -8.38% / +2.31% |
| lookback=10 | 1807 | 90 | 1.00 | 31.4% | **-0.25%** | -2.72% | +1.79% | +2.05% | -8.85% / +2.18% |
| lookback=20 | 1545 | 90 | 1.00 | 32.0% | **-0.45%** | -2.65% | +1.61% | +2.06% | -8.98% / +2.20% |
| window=early | 918 | 89 | 1.00 | 30.1% | **-1.60%** | -3.21% | +0.39% | +1.99% | -9.97% / +1.82% |
| window=late | 889 | 88 | 1.00 | 32.8% | **+1.13%** | -2.38% | +3.24% | +2.11% | -7.68% / +2.74% |
