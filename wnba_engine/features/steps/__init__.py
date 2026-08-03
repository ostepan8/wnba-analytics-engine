"""Concrete preprocessing steps, one module per family.

- `loading`    -- the only modules that bring rows in from Postgres.
- `cleaning`   -- null policy, type coercion, duplicate handling.
- `filtering`  -- row selection (franchise, season type, minimum minutes).
- `derivation` -- situational features; every cross-row one is windowed.
- `form_steps` -- multi-window team form: expanding and exponential
  levels, dispersion, trend, home/road splits, streaks, margin profile.
- `matchup_steps` -- features of the RELATIONSHIP between two teams:
  rest advantage, pace interaction, head-to-head record.
- `player_steps` -- player rates and role. Every one is a ratio, and all
  three shapes take the ratio of SUMS rather than a mean of ratios.
- `_windowing` -- shared plumbing for windowed steps. `trailing_walk`
  encodes the append-AFTER-summarise invariant once, so the six steps in
  `form_steps` and the four in `derivation` cannot each get it subtly
  wrong.
- `encoding`   -- categorical encoding and scaling.

Split by what a step DOES rather than by grain, because the swap a caller
usually wants is "same pipeline, different cleaning policy" -- not "same
cleaning, different table".
"""

from __future__ import annotations
