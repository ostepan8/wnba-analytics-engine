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

The one structural question left open is LEAD-LAG, and as of 2026-08-03 it
is half-answered. Cross-venue (Polymarket -> books) now measures a weak
effect in the predicted direction and at the predicted horizon, which
survives a game-clustered bootstrap at one of two a-priori lags and not
the other. Book-to-book remains untestable. Both are limited by the same
thing: our sportsbook captures are 60 minutes apart and the phenomenon is
15-30 minutes wide.

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

## The decisive test: residual modeling

The standard technique for an efficient market is not to predict the
outcome from scratch -- it is to predict the LINE'S ERROR. The line is
the best available forecast, so a model can only add value by learning
where it is systematically wrong. Every other test here compared a model
AGAINST the line; this one uses the line as an input and learns the
residual.

Trained on 2022-2024, evaluated on a 2025-2026 holdout:

| | corr(predicted residual, actual residual) |
|---|---:|
| ridge | **-0.031** |
| gradient boosting | **-0.041** |

Zero, and if anything slightly negative. Betting the holdout at every
disagreement threshold returned negative ROI on both models, several
significantly (t = -2.85, -2.06).

The line's errors are unpredictable from anything in this dataset. That
is what market efficiency means operationally, and it is the strongest
negative result here: not "our model was not good enough" but "there is
no structure in the residual for a better model to find".

## A different lens: microstructure, not prediction

Every result above shares one frame -- forecast the outcome, compare to
the line, bet the gap. Twelve variations of one idea is not twelve ideas.
Changing the target variable entirely gives a different answer.

**Books follow each other, and quickly.** Across 46,401 observed price
moves on 10 books, when one book repriced a prop, others moved the SAME
direction within 6 hours **72-80% of the time**, at a mean lag of
**16-29 minutes**:

| Leading book | n | followed | mean lag |
|---|---:|---:|---:|
| fanatics | 4,131 | 79.7% | 0.37h |
| bovada | 5,186 | 79.0% | 0.27h |
| williamhill_us | 9,920 | 78.5% | 0.27h |
| betonlineag | 9,265 | 77.1% | 0.37h |
| fanduel | 13,913 | 74.0% | 0.41h |
| draftkings | 5,787 | 72.6% | 0.48h |

That is real structure, and it requires forecasting nothing. If a
follower's price is genuinely stale in the window after a leader moves,
it is bettable without any view on the game.

**But this data cannot test it.** Betting the "stale" book returned
-5.03% (t=-2.72, negative in all four seasons) -- and that number is
meaningless, because of the sampling resolution:

| | |
|---|---:|
| lead-lag window | 16-29 min |
| **median gap between our captures of the same prop at the same book** | **60.3 min** |
| mean gap | 394 min |
| consecutive captures within 30 min | **4.5%** |

We sample an order of magnitude slower than the phenomenon. When the data
shows "A moved and B has not", B has very likely already moved and we
have simply not observed it yet. Those prices are not stale, they are
UNSAMPLED, and the -5.03% is measuring bets placed after both books
adjusted.

**This is the open question in this file.** Every other result is a
negative finding about the market. This is a negative finding about our
instrumentation, and it is fixable: testing it needs sub-10-minute
capture on a subset of props, which is an infrastructure change rather
than a modelling one. The off-box capture host already runs every 30
minutes and could run a narrow high-frequency sweep alongside it.

Until that exists, treat BOOK-TO-BOOK lead-lag as UNTESTED, not as
refuted. Nothing below changes that; the next section tests a different
pair of venues.

### Cross-venue: does Polymarket lead the books? (2026-08-03)

A separate question from the one above, and one the data can now partly
answer. `polymarket_trades` carries exact fill timestamps, so one side of
this comparison is no longer sampling-limited:

| | median gap between consecutive observations, pre-tip |
|---|---:|
| Polymarket fills | **1.7 min** (75.7% within 10 min) |
| sportsbook quotes, per book | **60.1 min** (0.2% within 10 min) |

`uv run wnba-engine lead-lag-report`, 202 games with both venues, 2025-26,
de-vigged consensus P(home) against trade-implied P(home), first
differences on a 5-minute grid, fifteen symmetric lags:

| lag | r (poly -> books) | n | t |
|---:|---:|---:|---:|
| +10m | +0.033 | 760 | +0.91 |
| **+15m** | **+0.095** | 746 | +2.61 |
| **+20m** | **+0.102** | 756 | +2.82 |
| +30m | -0.013 | 750 | -0.34 |

The reverse direction agrees: books-follow-Polymarket peaks at -15m
(r=+0.075), which is the same claim read backwards, while
books-LEAD-Polymarket at +15/+20m is flat (r=+0.021/+0.009). So the
asymmetry is in the direction the hypothesis predicts, and it lands in the
16-29 minute band the book-to-book section measured independently.

**And it is still not enough to act on.** Three reasons, in order of
weight:

1. **The pooled t is inflated by clustering** -- the same trap this file
   documents above. 756 paired observations come from 193 games. A
   game-clustered block bootstrap (`analysis/lead_lag.bootstrap_by_game`,
   2,000 resamples) gives P(r <= 0) = **0.0285** at +20m and **0.14** at
   +15m. One of two a-priori lags is marginally significant; the other is
   not.
2. **r = 0.10 explains 1% of variance.** Fifteen lags were examined, and
   the peak moved between runs as the backfill added rows -- consistent
   with a noise-dominated maximum rather than a stable one.
3. **The follower is still sampled hourly.** A 15-20 minute lag sits BELOW
   the books' 60.1-minute resolution, so the lag estimate cannot be
   trusted to that precision even where the direction is real.

**Status: half-instrumented.** The Polymarket side is solved permanently
and cheaply -- fills are recoverable from the chain, no capture host
required. The sportsbook side is unchanged and is now the binding
constraint on both lead-lag questions in this file. Raising odds-api
polling on a subset of games is the single change that would settle it.

A live example from the day this was written, offered as illustration and
not evidence: Polymarket sat at ATL 56.5% while eleven books averaged
52.2%; over the following six hours the books moved to 55.3% and
Polymarket eased to 55.5%. They converged from BOTH directions, which is
what two venues finding the same number looks like -- not what one venue
following the other looks like.

### The economics of the cross-venue lead: too small on average, positive in the tail

Establishing that books FOLLOW Polymarket says nothing about whether the
follow is worth crossing a spread for. That is an arithmetic question and
the data answers it.

Regressing each book price change on the Polymarket move that preceded it
by >=20 minutes, over 1,049 changes:

| | probability points |
|---|---:|
| books recover **60.8%** of a Polymarket move (beta = 0.608) | |
| mean absolute Polymarket move | 1.21 |
| implied book follow-through | **0.74** |
| half the sportsbook overround (1.0465) you must cross | **2.33** |
| **net per bet** | **-1.59** |

**The average move is roughly 3x too small to pay for the spread**, and no
amount of capture speed changes that -- faster sampling captures 0.74
points faster.

It flips in the tail, and unlike every other candidate in this file it
does so MONOTONICALLY, which is what a real effect looks like:

| \|Polymarket move\| >= | n | book follow | net vs vig |
|---|---:|---:|---:|
| any | 1,049 | 0.74p | -1.59p |
| 1.0p | 588 | 1.26p | -1.07p |
| 2.0p | 244 | 2.20p | -0.13p |
| **3.0p** | 123 | 3.14p | **+0.81p** |
| **5.0p** | 35 | 4.40p | **+2.07p** |

Break-even is a Polymarket move of **~3.83 points**, which is 7.3% of
observations -- about 40 opportunities per WNBA season.

Compare that against the false positive rejected the same day: "follow
Polymarket when it disagrees with the books" returned +15.34% on 96 games
(t=1.60) but its threshold profile INVERTED -- +16.1% at >=0.0075, +5.7%
at >=0.015, -4.6% at >=0.02 -- and every game was 2026. Monotonicity is
the difference, and it is a cheaper test than any statistic.

**Three things stand between this and money, and only the first is about
latency:**

1. You would have to act on the tail alone. Betting the average move
   loses 1.59 points a time.
2. **This measures that the book MOVED, not that the old price was still
   available.** Our sportsbook sampling is 60.1 minutes; the follow-through
   could have landed two minutes after Polymarket. The current data
   structurally cannot distinguish those, and that assumption carries the
   entire result.
3. The CLV-without-profit section below is this exact failure mode already
   observed once: 72.6% price-direction accuracy, -1.6% to -7.3% ROI.

And a blunt comparison: on 2026-08-03 the same moneyline ranged -115 to
-130 across eleven books -- **3 points of stake from line shopping alone**,
larger than the +2.07 point edge in the best bucket, with no infrastructure
at all.

**The one experiment worth running** is therefore assumption 2, not a
trading system: raise sportsbook polling to ~5 minutes on the handful of
games where Polymarket has real volume, and measure whether book prices
survive the window. `capture-odds-focused` does exactly that. If they do
not survive, this is dead and it cost a few hundred API calls to learn.

## Predicting price movement: CLV without profit

The second change of lens. Rather than forecasting the game, forecast the
PRICE -- which way will this quote move before it closes? If that is
predictable, a bettor captures closing line value regardless of who wins,
which is the metric the literature treats as the real measure of skill.

**It is predictable.** Logistic regression on five features (current
de-vigged price, deviation from peer books quoted in the prior 90
minutes, peer dispersion, hours to tip, number of peers), trained on
seasons <=2024 and evaluated on 2025-2026:

| Confidence | n | Direction accuracy |
|---|---:|---:|
| all | 17,038 | 59.6% |
| >0.60 | 4,799 | 67.5% |
| >0.65 | 1,978 | 69.8% |
| >0.70 | 632 | **72.6%** |

against a 51.8% majority-class baseline. This is the largest predictive
signal found anywhere in this file.

**And it loses money.** Betting the side the price is predicted to move
toward, one bet per game, on the same holdout:

| Confidence | games | ROI | t |
|---|---:|---:|---:|
| >0.50 | 512 | -4.04% | -3.29 |
| >0.60 | 499 | -1.59% | -0.62 |
| >0.65 | 431 | -7.25% | -1.80 |
| >0.70 | 258 | -4.98% | -0.74 |

The explanation is the useful part. What the model detects is MEAN
REVERSION TO PEER CONSENSUS -- an outlier book drifting back toward where
everyone else already is. The prediction is correct and the CLV is real:
the price genuinely moves toward the bet. But the destination is the
consensus price, which is fair, and reaching fair value costs the vig.

**Positive CLV does not imply profit when the movement being predicted is
convergence to an efficient consensus.** CLV measures whether you beat
the closing price; it says nothing about whether the closing price was
beatable. The widely-repeated claim that positive CLV implies long-term
profit is sportsbook-published rather than peer-reviewed, and this is a
direct counterexample: 72% direction accuracy, negative ROI.

Anything built on CLV as a proxy metric here must be validated against
outcomes as well, not instead.

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
