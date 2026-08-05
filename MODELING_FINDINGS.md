# Modeling findings

What has been tried against this data, and what it returned. Kept so the
same negative results are not rediscovered at cost, and so any future
positive claim has a baseline to beat.

Every number here is **one bet per game** (never one per book -- see
[The correlation trap](#the-correlation-trap)) and, where a holdout is
stated, fit on earlier seasons and evaluated on later ones.

## Summary

**No profitable, reliable backtest has been produced from this data.**
That statement has survived every attempt to overturn it, including one
result that appeared to overturn it and did not (see the
[props retraction](#player-props-the-unders-bias-is-real-and-the-edge-was-a-grading-bug)
-- +2.27% at t=+3.65 became +0.66% at t=+1.10 once the bet was graded as
a bet that could actually be placed).

**One lead is genuinely open and is the best thing here:** cross-venue
divergence between the sportsbooks and Polymarket's vig-free price is
worth **+1.07 points of CLV over a matched control, t = +7.77**, and it is
the only candidate that strengthened rather than weakened as controls were
added. It is a lead and not a strategy: realised profit is unproven at
n=398, and executability cannot be tested until the two-minute capture has
run for a season. See
[Cross-venue divergence](#cross-venue-divergence-the-first-thing-that-survives).

**Read the file with its own multiplicity in mind.** Across 126 features,
four prop markets, both venues and every slice tried, this project has run
well over 200 hypothesis tests. At that count roughly 10 results with
|t| > 2 are expected from noise alone. Nothing found here has cleared the
bar that number implies, and any future candidate needs to clear it too --
a single t = +2.5 is not evidence in a search this wide. The pattern of
every result that *did* look promising is the same: it shrank toward zero
as the controls got stricter, and the last control to be applied was
usually the one that mattered.

The four controls that have killed something real, in order of how often:
grading at real prices instead of flat -110; clustering on the correct
independent unit; requiring monotonicity in effect size; and requiring the
bet to be placeable at a single counterparty.

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
| 5 | Teammate absence (usage redistribution) | no monotonic signal (re-tested 2026-08-05 on point-in-time injury data, same answer) |
| 6 | Bet the book that deviates most from consensus | -0.57% at best |
| 7 | +EV vs peer consensus, threshold swept | every CI spans zero |
| 8 | Use the sharpest book as fair value | **no sharp book exists** -- see below |
| 9 | Totals: rolling-mean disagreement | "t=3.35" collapsed to t=0.81 |
| 10 | Spreads: rolling-margin disagreement | significantly **negative** (t=-2.62) |
| 11 | Multi-feature ridge / gradient boosting on totals | worse than naive on holdout |
| 12 | Unders at the best of eleven books | **+0.66%, t=+1.10** -- the +2.27% was a grading bug, see retraction |
| 13 | Prop shopping by market thinness / book disagreement | no residual edge once graded at one book |
| 14 | **Cross-venue divergence (book vs Polymarket fair price)** | **+1.07 pts CLV over matched control, t=+7.77** -- survives every control; profit unproven |

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
Polymarket when it disagrees with the books" appeared to return +15.34% on
96 games (t=1.60) -- a figure computed at a flat -110 and therefore
overstated, see the pricing correction below -- but its threshold profile
INVERTED -- +16.1% at >=0.0075, +5.7%
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

## Methodological correction: flat -110 overstates every moneyline result

**Several ROI figures recorded earlier on 2026-08-04 assumed a flat -110
price. That is wrong for a moneyline and it inflates in one direction.**
A -110 payout is 0.909 per unit; a real favourite at -180 pays 0.556 and a
real dog at +160 pays 1.60. Any strategy that leans toward favourites gets
systematically overpaid by the assumption.

Measured against the best available closing price per side, 1,278 games:

| strategy | flat -110 | **best real price** |
|---|---:|---:|
| bet the home team every game | +3.48% | **-4.17%** (t = -1.30) |
| "follow Kalshi when it disagrees with the books" | +21.91% | **+3.66%** (t = +0.51) |
| same, divergence >= 1pt | +36.36% | **+7.74%** (t = +0.94) |
| same, divergence >= 2pt | +44.63% | **+9.73%** (t = +0.78) |

The Kalshi result had looked like the strongest finding in this file --
63.9% at z=+3.57, rising monotonically to 75.8%. It was three artefacts
stacked:

1. **Flat -110 pricing.** "Follow Kalshi" picks the HOME side on 71% of
   games, because Kalshi sits +0.74 points higher on home systematically.
   Home teams are usually favourites, so the assumption overpaid nearly
   every bet.
2. **A home-heavy sample.** Home teams won 57.3% of the 178 Kalshi-covered
   games against a 54.2% long-run rate. Betting home BLIND in that sample
   "returned" +12.71% under the same flat pricing -- no model required.
   The control is what exposed it.
3. **One partial season.** Every Kalshi bar is 2026-05 onward. No
   out-of-sample year exists.

Any future ROI in this file must use `analysis/clv.american_to_profit`
against a real quoted price. A win RATE may be compared to a break-even
threshold; a RETURN may not be computed from one.

### Out-of-sample confirmation: the Kalshi result was a home-bias proxy (2026-08-04)

The 2026-only caveat on the Kalshi result is gone, because the missing
season was never missing -- it was behind a different API tier.

Kalshi partitions exchange data at a cutoff (`GET /historical/cutoff`,
2026-06-05). Markets settled earlier are served ONLY from `/historical/*`
and are invisible to `/markets`. For KXWNBAGAME that is 364 markets from
2026-05-22 against **760 from 2025-05-23**. Candlesticks 404 for those, but
`/historical/trades` returns timestamped prints: 536,844 trades across 593
markets and 297 games of the 2025 season, now in `kalshi_trades` (0027).

Re-running "follow Kalshi when it disagrees with the books" on 2025, at
best real prices:

| | 2025 (out of sample) | 2026 (in sample) |
|---|---:|---:|
| follow Kalshi | +9.40% (t=+1.33) | +3.66% (t=+0.51) |
| **bet HOME every game** | **+9.25% (t=+1.15)** | +12.71%* |
| paired difference | **+0.15%, t = +0.02** | -- |
| strategy picks home | 72% of games | 71% |
| season home win rate | 56.9% | 57.3% |

\* the 2026 control figure is at flat -110; see the pricing correction above.

**The paired difference is +0.15% at t = +0.02.** Following Kalshi adds
nothing measurable over a blind home bet, in either season independently.
Both seasons had home teams above the 54.2% long-run rate, which is what
made the blind bet look good -- and over 1,278 games at real prices,
betting home is **-4.17%**.

So the diagnosis holds, now with a genuine out-of-sample season rather than
an argument. Worth stating what actually settled it: not a statistic, but
running the dumbest available control and pairing against it.

### Favourite-longshot bias: present in shape, absent in significance

Bucketing every side bet by its de-vigged probability, at best real prices:

| fair P(side) | n | ROI | t | win% |
|---|---:|---:|---:|---:|
| 0.00-0.35 | 777 | +3.44% | +0.47 | 23.4% |
| 0.35-0.45 | 357 | +3.68% | +0.56 | 41.5% |
| 0.45-0.55 | 288 | -1.72% | -0.30 | 50.0% |
| 0.55-0.65 | 357 | -5.12% | -1.21 | 58.5% |
| 0.65-1.00 | 777 | -3.57% | -1.82 | 76.6% |

The gradient runs the textbook direction -- dogs less bad than favourites
-- but no bucket reaches \|t\| = 2, the two extreme buckets break
monotonicity against each other, and "bet every away team" (+3.30%,
t=+0.79) is negative in two of five seasons. Consistent with the vig being
distributed slightly unevenly, not with an exploitable bias.

## The residual test, re-run against every feature (2026-08-04)

The "decisive test" above predates the 99 features added in August 2026
(multi-window form, matchup, player rates, style, market). Re-running it
across all of them, on 2,528 team-game rows carrying a de-vigged closing
price:

**First it found a leak, not an edge.** The top of the table was:

| feature | r vs market residual | t |
|---|---:|---:|
| `offensive_rating` | **+0.431** | +23.9 |
| `efg` | **+0.393** | +21.4 |
| `tov_ratio` | -0.112 | -5.7 |

Those are the row's OWN game's advanced stats. `load_team_games` selects
thirteen columns from `team_advanced_stats` for the game being predicted,
and `TARGET_COLUMNS` -- the list whose docstring says "named here so a
caller can drop them in one line before training" -- listed only the four
scoring columns. A caller who followed that advice exactly would have kept
all thirteen and produced a spectacular backtest built on knowing the box
score of the game it was forecasting.

**The leakage guard cannot catch this.** These are row-local source
columns, exactly like `points_scored`; nothing about their timestamp is
wrong. Only their meaning is. Fixed by completing `TARGET_COLUMNS` (now 17
columns) and adding `derivation.drop_targets`, so the one-line drop the
docstring promises actually exists.

**With those excluded, nothing survives.** 110 genuine backward-looking
features:

| | |
|---|---:|
| features with \|t\| > 1.96 | **5** |
| expected by chance at 5% | **5.5** |
| surviving Bonferroni (\|t\| > 3.51) | 1 |
| best \|r\| among genuine features | 0.073 (0.53% of residual variance) |

The count of "significant" features is indistinguishable from noise.

### The one survivor, and why it is not one either

`pace_gap` (difference in the two teams' rolling pace) reached r = -0.073,
t = -3.66, and a betting test looked monotonic and profitable: +3.50% at
1sd, **+10.18% at 1.5sd**, +12.50% at 2sd. (Those returns assume a flat
-110 and are overstated for the same reason the Kalshi result was; the
collapse below does not depend on them.)

It does not survive the check this file already documents. **A team-game
frame holds two rows per game, and `pace_gap` is exactly antisymmetric
between them -- verified on 1,288 of 1,288 games.** The two rows are one
observation. Collapsing to the home row alone:

| | doubled | independent |
|---|---:|---:|
| n | 2,522 | 1,261 |
| t | -3.66 | **-2.61** |

Precisely the sqrt(2) inflation, and -2.61 no longer clears the
Bonferroni threshold for having searched 110 features. Per season the
effect is significant in none of the five, and **2023 carries the opposite
sign** (r = +0.034). The betting z-scores fall to +2.04 at 1.5sd (n=175)
and +1.34 at 2sd (n=56), after an in-sample threshold search.

So the answer stands, and now stands on a much wider base: **across 110
features spanning form, matchup, style, rest, pace and player role,
nothing holds information the closing line has not already priced.**

## Player props: the unders bias is real, and the edge was a grading bug
## (2026-08-04, RETRACTED 2026-08-05)

> **RETRACTION.** This section originally reported +2.27% (t = +3.65) for
> betting unders at the best of eleven books, and called it the first
> result in this file to survive every control. It does not survive. The
> bet as graded was not placeable: win/loss was settled against the
> **consensus** line while the payout came from whichever book offered the
> best under **odds** -- two different books, and systematically the two
> that disagree most. Graded honestly (one book: its line settles, its
> odds pay) the same strategy returns **+0.66%, t = +1.10**, with a
> player-clustered bootstrap P(ROI <= 0) = 0.134 and a 95% CI of -0.52% to
> +1.91%. See [the corrected numbers](#the-corrected-numbers) below. The
> unders-bias measurement itself (next two paragraphs) is unaffected.

The largest sample in this file -- **24,011 graded (line, outcome) pairs**
across points, rebounds, assists and threes, 2023-2026.

**Prop lines carry no discriminating skill, by construction.** Brier
0.243-0.249, skill 0.002-0.017. That is not a criticism: a prop line is
SET to make over/under a coin flip, so measuring its resolution is
measuring the wrong thing.

**Unders win more than the price implies.** De-vigged fair over price
against realised over rate, all four markets in the same direction:

| prop | n | fair over | realised | gap |
|---|---:|---:|---:|---:|
| points | 8,362 | 0.497 | 0.473 | -2.4 pts |
| rebounds | 6,793 | 0.491 | 0.463 | -2.8 pts |
| assists | 4,379 | 0.485 | 0.469 | -1.6 pts |
| threes | 4,476 | 0.471 | 0.446 | -2.5 pts |

That gap is a real property of the market. It is not a bet.

### The corrected numbers

Every strategy below settles and pays at **the same book**, which is the
only way a prop bet exists. The line you are graded against is the line you
took.

| strategy (under side) | n | ROI | t |
|---|---:|---:|---:|
| best LINE (highest under number) | 24,096 | **+0.66%** | +1.10 |
| best ODDS, at that book's own line | 24,096 | -0.21% | -0.33 |
| median line | 24,096 | -1.77% | -2.99 |
| worst line (control) | 24,096 | -4.27% | -7.16 |
| *consensus line + best odds (the retracted bug)* | *24,011* | *+2.27%* | *+3.65* |

The ladder from worst line to best line is clean and monotonic and worth
about **5 points**, which is the one durable fact here: shopping props is
worth roughly 5 points of ROI, more than the ~3 points it is worth on
moneylines, because prop lines disagree across books more than game lines
do. But 5 points of shopping against a 6.75% prop vig lands you at
**breakeven, not profit**. Recovering the vig is not beating it.

Season stability confirms it: +1.78%, +2.17%, +0.79%, **-1.46%** for
2023-2026. The most recent season is negative.

**Why the bug flattered the result so specifically.** The book with the
best under odds is disproportionately the book with the *lowest* under
line -- that is what it is being paid for. Settling that bet against the
higher consensus line credits wins that the actual ticket lost. The error
is largest exactly where books disagree most, which is why the
disagreement slice looked strongest (+8.04%) before correction and
vanished after (+0.35% at 1.0-1.5 apart).

The lesson is now a rule for this repo: **a backtest that draws the line
from one source and the price from another is not measuring a bet.**

## Cross-venue divergence: the first thing that survives (2026-08-05)

**The strongest result in this file, and the only one that got STRONGER as
the controls got stricter rather than weaker.** It is not yet a
demonstrated profit -- see the limits at the bottom -- but it is the first
lead here that has earned further work.

The idea is structural rather than predictive, which is why it is worth
something: every other section of this file failed at forecasting, while
execution kept being where the value was. Polymarket has no bookmaker vig,
so its price is a fair probability rather than a padded one. The question
is not whether Polymarket *predicts* the books (that is the lead-lag
section, and it is weak) but whether the two venues simply **disagree at
the same moment** by more than the cost of crossing. That needs no
forecasting skill at all.

Method: for each pre-tip sportsbook quote, a size-weighted Polymarket
price over the preceding 10 minutes, requiring >= $1,000 of Polymarket
volume in that window. A divergence is when the best book price for one
side, vig included, is still cheaper than Polymarket's fair price for it.

**It passes the monotonicity tests.** Arb rate rises with Polymarket
liquidity -- 12.2% of moments at any volume, 13.2% above $1,000, 16.9%
above $5,000, **31.0% above $20,000**. That direction is the whole reason
to believe it: dust-trade noise produces *more* fake divergence at *low*
liquidity, not less. The early version of this test was in fact ruined by
exactly that artifact -- $6 and $10 fills sitting at p=0.500 on untraded
markets while the book had the game at 29%, which is an uninitialised
Polymarket market rather than a mispriced book.

**And it passes the control that killed the props finding.** Selecting the
cheapest book price at a moment makes it revert toward the close all by
itself, so the comparison has to be against that, not against zero:

| | n | CLV | t |
|---|---:|---:|---:|
| divergence bets | 398 | **+1.15 pts** | +8.52 |
| best book price, no Polymarket test | 6,052 | +0.15 pts | +5.74 |
| same moments, Polymarket says NO divergence | 5,654 | +0.08 pts | +3.07 |
| **difference vs matched control** | | **+1.07 pts** | **+7.77** |

Price reversion explains 0.08 of the 1.15. Polymarket carries about **1.07
points of information the books have not yet priced**, and t = +7.77
clears a Bonferroni threshold for the 200+ tests in this file (|t| ~ 3.5),
which no previous candidate did. CLV also rises with the size of the
divergence (+1.00, +1.07, +1.26 pts across 0-0.5%, 0.5-1%, 1-2% buckets).

### What it is not

**It is not a demonstrated profit.** Realised ROI is -4.66% at t = -0.56
on 398 bets, with a game-clustered 95% CI of -34.55% to +33.32% and
P(ROI<=0) = 0.612. That interval is useless in both directions: the sample
proves nothing about profit either way. The mean divergence is only
0.5-0.7%, so the theoretical edge is thin and needs a lot of bets. 2026 is
weaker than 2025 (11.3% vs 16.0% arb rate).

**Executability is unproven and is the real question.** The book price
moved against us by the next capture in 303 of 384 cases -- which is the
*good* reading (it is what positive CLV means) but also means the window
is short. Our historical captures are ~60 minutes apart, so every
divergence in this dataset was observed up to an hour late. Whether the
price is still there when you can act on it is exactly the open question,
and it cannot be answered from this data.

**This is what the two-minute focused capture is for.** As of 2026-08-05
that agent is fixed and running at a resolution that can measure it; the
answer needs a season of accumulation. Until then this is a strong lead
and not a strategy, and the distinction matters -- the retracted props
finding in this file is what happens when that line gets blurred.

## Injury-driven usage: refuted again, on better data (2026-08-05)

This re-tests hypothesis **#5** in the table above, which the first pass
recorded as "no monotonic signal". The re-test uses point-in-time injury
reports rather than roster inference, sizes each absence by the absent
player's prior scoring, and grades at one book. Same answer.

The mechanism is the most strongly motivated one left: when a high-usage
teammate is out, the remaining players absorb the vacated production, so
overs on teammates of absent stars should beat the line if the market
under-adjusts.

Absences from 13,334 point-in-time `Out` reports (filed before tip,
within 4 days), each absent player's prior production measured strictly
from earlier games in the same season, aggregated to 6,271 (game, team)
pairs. Overs graded at the best available line, same book.

| vacated prior PPG | n | over ROI | t |
|---|---:|---:|---:|
| none out | 15,414 | -8.56% | -10.93 |
| 0-8 pts out | 3,113 | -10.03% | -5.75 |
| 8-15 pts out | 2,250 | -5.70% | -2.78 |
| 15+ pts out | 3,319 | -8.15% | -4.82 |

**No gradient.** Overs lose about the same in every bucket including
"nobody out", which is just the vig plus the unders bias. The unders
mirror shows no gradient either (+0.41%, +2.60%, -1.48%, +1.44% -- not
monotonic, none significant). By prop type at 15+ vacated points, overs
run -2.74% to -8.59%, all negative. The market prices injuries.

## Shot quality vs shot making, and a prop hypothesis that failed (2026-08-05)

The first test built on stats.wnba.com's 164,143 shot locations, and the
one hypothesis this file has had that was grounded in a measured property
of the sport rather than in a market pattern.

**The decomposition works and is worth keeping on its own.** Splitting each
attempt into where it was taken (league expected points for that zone) and
whether it went in:

| | game-to-game autocorrelation |
|---|---:|
| shot QUALITY -- where a player shoots | **0.325** |
| shot MAKING -- whether it went in | **0.048** |

Shot selection is a stable player property; game-level shooting above or
below expectation is very close to pure noise. The zone efficiencies that
fall out are textbook: restricted area 1.260 points per attempt, corner
threes 1.107, above-the-break threes 1.020, mid-range worst at 0.746.

**The hypothesis:** if a prop line moves on recent shot MAKING, it is
chasing noise, and the under should be profitable on players who have
recently shot above expectation.

**It does not survive.** 8,258 points props with five prior shot-games,
under at the best of eleven books, split by the player's recent making:

| tercile | n | mean making | ROI | t |
|---|---:|---:|---:|---:|
| cold | 2,752 | -0.187 | -0.92% | -0.50 |
| **middle** | 2,752 | +0.018 | **+3.56%** | +1.93 |
| hot | 2,754 | +0.229 | +3.17% | +1.72 |

The middle tercile beats the hot one, so the ordering is wrong: a real
overreaction would make the effect increase through the hot bucket, not
peak in the middle. Hot minus cold is +4.09% at t = +1.57, and 2026 returns
-2.60%. What survives is the base unders bias already recorded above, not
anything shot-making adds to it.

Worth noting what this rules out. The market prices a player's scoring
without being fooled by a five-game hot streak, on a quantity the data
shows is 95% noise. That is a more specific and more impressive statement
about prop pricing than "the closing line is efficient".

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
