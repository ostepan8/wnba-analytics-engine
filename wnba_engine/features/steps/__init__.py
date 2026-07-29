"""Concrete preprocessing steps, one module per family.

- `loading`    -- the only modules that bring rows in from Postgres.
- `cleaning`   -- null policy, type coercion, duplicate handling.
- `filtering`  -- row selection (franchise, season type, minimum minutes).
- `derivation` -- situational features; every cross-row one is windowed.
- `encoding`   -- categorical encoding and scaling.

Split by what a step DOES rather than by grain, because the swap a caller
usually wants is "same pipeline, different cleaning policy" -- not "same
cleaning, different table".
"""

from __future__ import annotations
