"""Composition: an ordered, immutable stack of steps.

This is the "layering" the design brief asked for. A Pipeline is a value,
and every mutator returns a new one, so a strategy can be adapted at the
call site without any risk of the change escaping into the shared
pre-composed constant it was derived from:

    from wnba_engine.features import strategies
    base = strategies.team_form_pipeline(source)
    cheap = base.without("rolling_form")             # a new Pipeline
    heavy = base.with_step(my_step)                  # another new one
    swapped = base.replace_step("rest_days", other)  # and another

`base` is unchanged by all three. That property is what makes it safe to
expose strategies as module-level constants/factories.

The guard is a field, not an optional argument to run(): making it a
parameter would mean every call site gets to decide whether
point-in-time correctness is checked this time, and the answer under
deadline pressure is always "not this time".
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from wnba_engine.features.context import FeatureContext
from wnba_engine.features.errors import FeatureError
from wnba_engine.features.frame import FeatureFrame
from wnba_engine.features.guard import DEFAULT_GUARD, LeakageGuard
from wnba_engine.features.step import PreprocessingStep


@dataclass(frozen=True, slots=True)
class Pipeline:
    """An ordered stack of steps plus the guard that polices them."""

    name: str
    steps: tuple[PreprocessingStep, ...]
    guard: LeakageGuard = DEFAULT_GUARD

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for step in self.steps:
            if step.name in seen:
                raise FeatureError(
                    f"pipeline {self.name!r} has two steps named {step.name!r}; step "
                    "names are the handle without()/replace_step() address, so they "
                    "must be unique"
                )
            seen.add(step.name)

    @property
    def step_names(self) -> tuple[str, ...]:
        return tuple(step.name for step in self.steps)

    def run(
        self, frame: FeatureFrame | None = None, *, context: FeatureContext
    ) -> FeatureFrame:
        """Fold the steps in order, guarding after each.

        Starts from an empty frame by default so the common case reads as
        "the strategy IS the pipeline" -- the first step is a loader that
        creates the rows. Passing a frame in supports the other case:
        re-running a tail of steps over a frame that was materialised
        earlier.
        """
        current = frame if frame is not None else FeatureFrame.empty()
        for step in self.steps:
            provenance = step.provenance
            produced = step.apply(current, context)
            self.guard.check(
                step_name=step.name,
                kind=provenance.kind,
                declared_columns=provenance.adds_columns,
                before=current,
                after=produced,
                context=context,
            )
            current = produced
        return current

    def with_step(self, step: PreprocessingStep) -> Pipeline:
        """Append one step."""
        return replace(self, steps=self.steps + (step,))

    def with_steps(self, steps: tuple[PreprocessingStep, ...]) -> Pipeline:
        return replace(self, steps=self.steps + steps)

    def insert_after(self, name: str, step: PreprocessingStep) -> Pipeline:
        """Insert directly after the named step.

        Order matters more here than in most pipelines -- a windowed step
        placed before the filter that removes preseason games computes
        rest days across exhibition fixtures -- so positional insertion is
        a first-class operation rather than something callers rebuild the
        tuple to achieve.
        """
        index = self._index_of(name)
        return replace(self, steps=self.steps[: index + 1] + (step,) + self.steps[index + 1 :])

    def without(self, name: str) -> Pipeline:
        """Drop the named step."""
        index = self._index_of(name)
        return replace(self, steps=self.steps[:index] + self.steps[index + 1 :])

    def replace_step(self, name: str, step: PreprocessingStep) -> Pipeline:
        """Swap the named step for another, keeping its position."""
        index = self._index_of(name)
        return replace(self, steps=self.steps[:index] + (step,) + self.steps[index + 1 :])

    def renamed(self, name: str) -> Pipeline:
        return replace(self, name=name)

    def with_guard(self, guard: LeakageGuard) -> Pipeline:
        return replace(self, guard=guard)

    def _index_of(self, name: str) -> int:
        for index, step in enumerate(self.steps):
            if step.name == name:
                return index
        raise FeatureError(
            f"pipeline {self.name!r} has no step named {name!r}; steps are "
            f"{list(self.step_names)}"
        )
