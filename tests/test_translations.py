"""`snakelane translations`: stale / unreviewed / current / untracked."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane import project
from snakelane.listing import translations

from .helpers import make_app, write


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return make_app(tmp_path, locales=["en-US", "en-AU", "de-DE", "ja"])


def status(app: project.App) -> dict[str, dict[str, str]]:
    return translations.statuses(app.folder, app.config["locales"])


def test_lifecycle(app: project.App) -> None:
    write(app, "default", "subtitle", "Plan your week")
    write(app, "de-DE", "subtitle", "Plane deine Woche")
    write(app, "ja", "subtitle", "一週間を計画")
    assert status(app)["de-DE"] == {"subtitle": "untracked"}
    assert status(app)["en-AU"] == {"subtitle": "default"}, "inheriting the default is not a gap"

    translations.cmd_mark(app, ["de-DE", "ja"], ["subtitle"], reviewed=False)
    assert status(app)["de-DE"] == {"subtitle": "unreviewed"}

    write(app, "de-DE", "subtitle", "Plane deine Woche.")  # a hand edit is the review signal
    assert status(app)["de-DE"] == {"subtitle": "current"}
    translations.cmd_mark(app, ["ja"], ["subtitle"], reviewed=True)
    assert status(app)["ja"] == {"subtitle": "current"}

    write(app, "default", "subtitle", "Plan your month")  # the source moved on
    assert status(app)["de-DE"] == {"subtitle": "stale"}
    assert status(app)["ja"] == {"subtitle": "stale"}


def test_mark_refuses_unknown_locales_and_empty_work(app: project.App) -> None:
    with pytest.raises(SystemExit, match=r"not in snakelane\.yml"):
        translations.cmd_mark(app, ["fr-FR"], ["name"], reviewed=False)
    with pytest.raises(SystemExit, match="nothing to mark"):
        translations.cmd_mark(app, ["de-DE"], ["name"], reviewed=False)


def test_push_warning_only_once_tracking_starts(app: project.App, capsys: pytest.CaptureFixture[str]) -> None:
    write(app, "default", "name", "Example")
    write(app, "de-DE", "name", "Beispiel")
    translations.warn_stale(app.folder, app.config["locales"])
    assert capsys.readouterr().out == ""
    translations.cmd_mark(app, ["de-DE"], ["name"], reviewed=False)
    capsys.readouterr()
    translations.warn_stale(app.folder, app.config["locales"])
    assert "0 stale and 1 unreviewed" in capsys.readouterr().out
