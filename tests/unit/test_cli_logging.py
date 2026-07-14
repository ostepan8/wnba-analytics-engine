"""Regression test: httpx's own request logger must never be left at INFO.

httpx logs "HTTP Request: GET <full url incl. query string>" at INFO for
every request. Discovered live (2026-07-09): running `wnba-engine
snapshot-odds-api` printed the-odds-api's real API key in cleartext to
stdout via this exact log line, bypassing our own JsonHttpClient's
redact_query_param_keys entirely (a completely separate logging code
path). The cli() group callback must silence it as a global,
defense-in-depth fix -- see wnba_engine/cli/main.py.
"""

from __future__ import annotations

import logging

from wnba_engine.cli.main import cli


def test_cli_group_silences_httpx_info_logging():
    # `--help` short-circuits before Click invokes the group callback, so
    # exercise the callback directly -- it's the same function every real
    # subcommand invocation runs first.
    logging.getLogger("httpx").setLevel(logging.NOTSET)  # reset in case another test set it
    cli.callback()
    assert logging.getLogger("httpx").level == logging.WARNING
