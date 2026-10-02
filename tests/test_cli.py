"""Smoke tests: every command routes, imports and prints its help.

Nothing here talks to App Store Connect. The deeper offline checks are the
commands' own `--dry-run` modes, run against real app repos as described in AGENTS.md.
"""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

import snakelane
from snakelane import cli


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "snakelane", *args],
                          capture_output=True, text=True, check=False)


def test_version_matches_package_metadata() -> None:
    from importlib.metadata import version

    assert snakelane.__version__ == version("snakelane")
    assert run("--version").stdout.strip() == snakelane.__version__


def test_help_lists_every_command() -> None:
    out = run("--help").stdout
    for name in cli.COMMANDS:
        assert name in out


def test_unknown_command_fails() -> None:
    assert run("nope").returncode != 0


@pytest.mark.parametrize("module", sorted({m for m, _ in cli.COMMANDS.values()}))
def test_command_module_imports(module: str) -> None:
    assert callable(importlib.import_module(f"snakelane.{module}").main)


@pytest.mark.parametrize("command", sorted(cli.COMMANDS))
def test_command_help(command: str) -> None:
    result = run(command, "--help")
    assert result.returncode == 0, result.stderr


def test_frame_runs_the_reframe_test_when_the_test_draws_captions(tmp_path) -> None:
    from snakelane.screenshots import frame

    from .helpers import make_app

    make_app(tmp_path, scheme="Example", screenshots={"frame": "test"})
    import os
    here = os.getcwd()
    os.chdir(tmp_path)
    try:
        with pytest.raises(SystemExit, match="has no reframe UI test"):
            frame.main([])
    finally:
        os.chdir(here)
