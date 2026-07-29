"""Unit tests for individually-acknowledged known-benign violations.

The point of the mechanism is that it mutes exactly one violation and
nothing else, so most of these tests are about what still FAILS.
"""

from __future__ import annotations

import pytest

from wnba_engine.models.validation import CheckResult
from wnba_engine.validation import acknowledged as ack
from wnba_engine.validation._shared import build_check_result
from wnba_engine.validation.crosswalk_checks import _duplicate_mapping_key
from wnba_engine.validation.runner import find_stale_acknowledgements

CHECK = "some_check"


def _entry(key: str) -> ack.Acknowledgement:
    return ack.Acknowledgement(
        check_name=CHECK, key=key, reason="verified benign", verified_on="2026-07-29"
    )


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch):
    """Swap the real registry for a one-entry fake, so these tests don't
    break every time a real acknowledgement is added or removed.
    """
    monkeypatch.setattr(ack, "ACKNOWLEDGEMENTS", (_entry("row-1"),))


def _build(rows: list[tuple[object, ...]], *, keyed: bool = True) -> CheckResult:
    return build_check_result(
        name=CHECK,
        description="test check",
        rows=rows,
        formatter=lambda r: f"row={r[0]}",
        key_fn=(lambda r: str(r[0])) if keyed else None,
    )


def test_acknowledged_violation_does_not_fail_the_check(registry):
    result = _build([("row-1",)])

    assert result.passed
    assert result.acknowledged_count == 1
    assert result.unacknowledged_count == 0
    # Still counted and still reported -- muted, not hidden.
    assert result.violation_count == 1
    assert "verified benign" in result.sample_acknowledged[0]


def test_unacknowledged_violation_still_fails(registry):
    result = _build([("row-2",)])

    assert not result.passed
    assert result.acknowledged_count == 0
    assert result.unacknowledged_count == 1


def test_new_violation_alongside_an_acknowledged_one_still_fails(registry):
    """The regression the whole design exists to prevent: a permanently
    red check hiding a genuinely new problem."""
    result = _build([("row-1",), ("row-2",)])

    assert not result.passed
    assert result.violation_count == 2
    assert result.acknowledged_count == 1
    assert result.sample_violations == ("row=row-2",)


def test_no_key_fn_means_nothing_can_be_acknowledged(registry):
    """A check with no known-benign cases keeps its original behaviour."""
    result = _build([("row-1",)], keyed=False)

    assert not result.passed
    assert result.acknowledged_count == 0
    assert result.sample_acknowledged == ()


def test_clean_check_passes_with_no_acknowledgements(registry):
    result = _build([])

    assert result.passed
    assert result.violation_count == 0
    assert result.acknowledged_count == 0


def test_duplicate_mapping_key_includes_external_ids():
    """A third external_id must change the key, so an acknowledged pair
    growing into a triple re-fails instead of riding in on the old entry.
    """
    pair = _duplicate_mapping_key(("balldontlie", "player", 284, ["67134", "80698"]))
    triple = _duplicate_mapping_key(("balldontlie", "player", 284, ["67134", "80698", "99999"]))

    assert pair == "balldontlie/player/284:67134,80698"
    assert pair != triple


def test_stale_acknowledgement_is_reported(registry):
    """An entry matching nothing this run is dead weight and gets called
    out rather than silently persisting."""
    clean_run = _build([])

    assert find_stale_acknowledgements((clean_run,)) == (f"{CHECK}: row-1 (verified benign)",)


def test_matched_acknowledgement_is_not_stale(registry):
    matched = _build([("row-1",)])

    assert find_stale_acknowledgements((matched,)) == ()


def test_registry_keys_are_unique():
    """Two entries with the same key means one is unreachable and its
    stated reason is a lie about what got verified."""
    keys = [(entry.check_name, entry.key) for entry in ack.ACKNOWLEDGEMENTS]

    assert len(keys) == len(set(keys))


def test_registry_entries_carry_evidence():
    """An acknowledgement without a reason and a date is just a
    suppression, which is the thing this mechanism refuses to be."""
    for entry in ack.ACKNOWLEDGEMENTS:
        assert entry.reason.strip(), f"{entry.key} has no reason"
        assert entry.verified_on.strip(), f"{entry.key} has no verified_on date"
        assert entry.check_name.strip(), f"{entry.key} has no check_name"
