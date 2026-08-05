"""The recurring ESPN sweep has to cover games that have not happened yet.

`sync-recent` swept only backwards, so the `games` table never extended
much past today. That is invisible until something needs a game BEFORE it
is played -- which the focused odds capture does: an odds row for a game
missing from `games` is unresolved and dropped, silently, with a WARNING
that a launchd log nobody reads is the only record of.

Observed live on 2026-08-05: two events (Fever/Aces, Fire/Tempo) lost 5
odds rows each because the schedule stopped at 2026-08-06.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from wnba_engine.cli.main import cli


@pytest.fixture
def captured_window(monkeypatch) -> dict[str, date]:
    """Record the (since, until) the command asks the backfill for."""
    seen: dict[str, date] = {}

    def _fake_backfill(db, client, since, until):
        del db, client
        seen["since"], seen["until"] = since, until
        return "backfill: 0 game(s)"

    monkeypatch.setattr("wnba_engine.cli.main.backfill", _fake_backfill)
    monkeypatch.setattr("wnba_engine.cli.main.Database", lambda url: _NullDb())
    monkeypatch.setattr("wnba_engine.cli.main.EspnClient", lambda settings: _NullClient())
    return seen


class _NullDb:
    def close(self) -> None:
        return None


class _NullClient:
    def __enter__(self) -> _NullClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_sync_recent_reaches_past_today(captured_window) -> None:
    """The regression. `until` must lead today, not equal it."""
    result = CliRunner().invoke(cli, ["sync-recent"])
    assert result.exit_code == 0, result.output
    assert captured_window["until"] > date.today(), (
        "sync-recent still stops at today; scheduled games stay unknown "
        "until the day they are played and their odds rows are dropped"
    )


def test_the_forward_window_is_configurable(captured_window) -> None:
    result = CliRunner().invoke(cli, ["sync-recent", "--days", "2", "--days-ahead", "10"])
    assert result.exit_code == 0, result.output
    assert captured_window["since"] == date.today() - timedelta(days=2)
    assert captured_window["until"] == date.today() + timedelta(days=10)


def test_the_forward_window_can_be_switched_off(captured_window) -> None:
    """Zero has to mean today, not 'ignore the flag' -- a backfill of a
    date range that ends before it starts is not a no-op, it is a bug.
    """
    result = CliRunner().invoke(cli, ["sync-recent", "--days-ahead", "0"])
    assert result.exit_code == 0, result.output
    assert captured_window["until"] == date.today()
