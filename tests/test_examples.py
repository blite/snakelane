"""The examples/ trees stay valid: every offline command runs clean against them."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from snakelane import project
from snakelane.listing import lint, translations
from snakelane.screenshots import gallery

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
TRAILHEAD = EXAMPLES / "trailhead"


def snakelane(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # HOME points somewhere empty so no real API key is found: these must work offline.
    env = {**os.environ, "HOME": str(tmp_path)}
    return subprocess.run([sys.executable, "-m", "snakelane", *args],
                          capture_output=True, text=True, env=env, check=False)


@pytest.mark.parametrize("command", [
    ["store", "push", "--dry-run"],
    ["store", "screenshots", "push", "--dry-run"],
    ["store", "iap", "push", "--dry-run"],
    ["store", "subs", "push", "--dry-run"],
    ["translations", "status"],
])
def test_offline_commands_run_clean(tmp_path: Path, command: list[str]) -> None:
    result = snakelane(tmp_path, "-C", str(TRAILHEAD), *command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "warning" not in result.stdout


def test_listing_passes_lint_and_translations_are_current() -> None:
    app = project.resolve_app(None, root=TRAILHEAD)
    assert lint.run(app, "ios") == []
    states = {s for fields in translations.statuses(app.folder / "ios", app.locales).values()
              for s in fields.values()}
    assert states <= {"current", "default"}


def test_gallery_shows_both_decks_and_inheritance() -> None:
    page = gallery.build(project.resolve_app(None, root=TRAILHEAD))
    assert "no deck — shows en-US&#x27;s" in page  # en-AU
    assert page.count("ss-01.jpg") >= 3             # iPhone en-US, iPad en-US, iPhone de-DE


def test_two_apps_need_a_name_or_a_config(tmp_path: Path) -> None:
    repo = EXAMPLES / "two-apps"
    assert "pass --app" in snakelane(tmp_path, "-C", str(repo), "lint").stderr
    assert project.resolve_app("PRO", root=repo).folder == repo / "metadata" / "pro"
    assert project.resolve_app("free", root=repo).name == "Trailhead"
    result = snakelane(tmp_path, "--config", str(repo / "snakelane.pro.yml"), "lint")
    assert result.returncode == 0, result.stdout + result.stderr
