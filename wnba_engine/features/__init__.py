"""Composable, point-in-time-correct feature preprocessing.

See README.md in this package for the architecture, how to add a step or
a strategy, and the leakage contract. The short version:

    context  = FeatureContext(as_of=..., seasons=(2025,))
    source   = PostgresRowSource(conn)
    pipeline = strategies.build("team_form", source)
    frame    = pipeline.run(context=context)

Every step in that pipeline is checked, after it runs, against the
boundary in `context` and against each row's own tip-off. A step that
cannot prove where its data came from is refused rather than trusted.
"""

from __future__ import annotations

from wnba_engine.features.context import DEFAULT_SEASON_TYPES, FeatureContext
from wnba_engine.features.errors import (
    FeatureError,
    LeakageError,
    StepContractError,
    UndeclaredProvenanceError,
)
from wnba_engine.features.frame import FeatureFrame, Row
from wnba_engine.features.guard import DEFAULT_GUARD, LeakageGuard
from wnba_engine.features.pipeline import Pipeline
from wnba_engine.features.provenance import StepKind, StepProvenance
from wnba_engine.features.source import (
    FeatureRowSource,
    PostgresRowSource,
    StaticRowSource,
)
from wnba_engine.features.step import (
    AsOfJoinStep,
    FilterStep,
    FittedStep,
    PreprocessingStep,
    RowMapStep,
    SourceStep,
    TimeInvariantJoinStep,
    WindowedStep,
)

__all__ = [
    "DEFAULT_GUARD",
    "DEFAULT_SEASON_TYPES",
    "FeatureContext",
    "FeatureError",
    "FeatureFrame",
    "FeatureRowSource",
    "FilterStep",
    "FittedStep",
    "AsOfJoinStep",
    "LeakageError",
    "LeakageGuard",
    "Pipeline",
    "PostgresRowSource",
    "PreprocessingStep",
    "Row",
    "RowMapStep",
    "SourceStep",
    "StaticRowSource",
    "StepContractError",
    "StepKind",
    "StepProvenance",
    "TimeInvariantJoinStep",
    "UndeclaredProvenanceError",
    "WindowedStep",
]
