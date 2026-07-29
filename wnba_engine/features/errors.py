"""Feature-layer exception types.

Every one of these is a LEAKAGE failure or a step-contract failure -- the
two things this subsystem exists to make impossible. They deliberately do
NOT subclass ProviderValidationError: nothing here is about a malformed
upstream payload, it is about this repo's own code trying to look at data
it must not see.

They all fail LOUDLY (raise, never warn/skip). A preprocessing layer that
quietly drops a leaky row is worse than one that has no guard at all --
the resulting model looks honest and is not.
"""

from __future__ import annotations

from datetime import datetime

from wnba_engine.errors import WnbaEngineError


class FeatureError(WnbaEngineError):
    """Base class for feature-layer failures."""


class LeakageError(FeatureError):
    """Data from at-or-after the point-in-time boundary reached a feature.

    Carries the step, column, and both timestamps, because the first
    question on seeing this is always "how far past the boundary, and
    which source?" -- a bare "leakage detected" sends you reading SQL.
    """

    def __init__(
        self,
        *,
        step: str,
        column: str,
        observed: datetime,
        boundary: datetime,
        detail: str,
    ) -> None:
        self.step = step
        self.column = column
        self.observed = observed
        self.boundary = boundary
        super().__init__(
            f"step {step!r} produced a row whose {column}={observed.isoformat()} "
            f"is not before the {detail} boundary {boundary.isoformat()}"
        )


class UndeclaredProvenanceError(FeatureError):
    """A step produced rows it cannot prove are point-in-time safe.

    This is the "silence is not consent" rule: a step that declares no
    as-of anchor for the rows it emits is rejected rather than trusted.
    Without it, the cheapest way to defeat the guard would be to simply
    not mention where the data came from.
    """


class StepContractError(FeatureError):
    """A step violated the structural contract of its own StepKind --
    added an undeclared column, invented rows in a filter, and so on.

    Structural, not statistical: these are the invariants that make the
    leakage checks meaningful. A step that can silently add a column can
    silently add a leaky one.
    """
