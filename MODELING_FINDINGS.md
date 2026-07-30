# Modeling findings

What has been tried against this data, and what it returned. Kept so the
same negative results are not rediscovered at cost, and so any future
positive claim has a baseline to beat.

Every number here is **one bet per game** (never one per book -- see
[The correlation trap](#the-correlation-trap)) and, where a holdout is
stated, fit on earlier seasons and evaluated on later ones.

## Summary

**No profitable, reliable backtest has been produced from this data.**
Ten hypotheses across player props, totals and spreads; the best
survivor was +3.08% with t=0.55 and a confidence interval spanning
-7.8% to +14.0%.

## What was tested

| # | Hypothesis | Result |
|---|---|---|
| 1 | Static prop sides (always over / always under) | -2.05% to -10.68% |
| 2 | Line shopping best price across books | -0.25% at best |
| 3 | Rolling-mean predictor, bucketed by disagreement | +14% (2023) decaying to -5% (2026) |
| 4 | Follow the line move / fade the line move | -14.25% / -0.61% |
| 5 | Teammate absence (usage redistribution) | no monotonic signal |
| 6 | Bet the book that deviates most from consensus | -0.57% at best |
| 7 | +EV vs peer consensus, threshold swept | every CI spans zero |
| 8 | Use the sharpest book as fair value | **no sharp book exists** -- see below |
| 9 | Totals: rolling-mean disagreement | "t=3.35" collapsed to t=0.81 |
| 10 | Spreads: rolling-margin disagreement | significantly **negative** (t=-2.62) |
| 11 | Multi-feature ridge / gradient boosting on totals | worse than naive on holdout |

## The three findings that explain the rest

**Props are priced as coin flips.** Brier scores across all nine books
with meaningful volume fall between 0.24614 and 0.24961. A constant 0.5
forecast scores 0.25. The line is chosen so both sides are near
even-money, which is why no book can serve as a "sharp" benchmark and why
de-vigged consensus carries so little information.

**The market's whole informational advantage is 0.76%.** A 60-day rolling
mean scores MAE 3.0538 on player props; the closing line scores 3.0305.
That gap is real and consistent -- and far smaller than the ~4.5% vig.
Beating the line by a little is not enough; the house takes more than the
line is worth.

**More model made it worse.** On a 2022-2024 fit and a 2025-2026 holdout
of team totals:

| Predictor | Holdout MAE |
|---|---:|
| naive average of recent totals | 14.733 |
| ridge, 8 features | 14.872 |
| gradient boosting | 16.019 |
| **the closing line** | **14.234** |

Betting the holdout produced significant NEGATIVE ROI for ridge and naive
(t = -2.48, -2.47). Gradient boosting showed +1.82% above a disagreement
threshold at t=0.29 -- while having the worst prediction error of the
three. A model that forecasts badly and "profits" on a subset is noise by
definition, and is exactly the result that would look like success if
reported without the accuracy column next to it.

## The correlation trap

The totals disagreement test initially reported **+12.72% at t=3.35**,
which is significant at p<0.001 and would have been a publishable-looking
edge.

It was 610 rows -- and **65 distinct games**. The same game appears once
per book, and up to 22 books quote it. Treating those as independent
observations inflated the sample by ~9x and the t-statistic by ~3x.
Collapsed to one bet per game the same strategy gives +9.70% at **t=0.81**,
with seasons alternating +17.8 / +2.8 / +11.1 / -2.5.

Any future backtest must collapse to one bet per game before computing a
statistic. This is the single easiest way to manufacture a false positive
here.

## Ideas that are algebraically inert

**Rate x minutes.** Predicting per-minute rate and projected minutes
separately, then multiplying, sounds structurally better than a rolling
mean of the raw stat -- it separates "playing more" from "scoring more".

Measured: MAE 3.0537 against the naive 3.0538. Identical, because
`rate x average_minutes` reduces to `average_stat` when minutes are just
their own history. The decomposition only pays with **forward-looking**
minutes -- lineup news, injury impact, blowout risk -- which this repo
does not have.

(A first attempt scored 8.0045 by averaging ratios rather than taking a
ratio of sums; `avg(stat/minutes)` is biased upward by low-minute games
with noisy rates.)

## What would change the answer

None of these is a modeling problem:

- **Projected minutes and lineup news.** The single biggest prop driver,
  and the input that makes the rate decomposition non-trivial.
- **Speed on injury news.** Untestable historically -- injury history is
  daily-resolution Wayback data. The 30-minute off-box capture makes it
  measurable going forward.
- **Access to soft books at low limits**, where mechanical edges persist.

## Reproducing

Modeling dependencies are optional and not required for ingestion:

```bash
uv sync --extra modeling
```
