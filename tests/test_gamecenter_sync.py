"""Offline checks on `gamecenter sync`: the .gamekit's text and images against a stand-in App Store
Connect, a new version only where the newest is LIVE, and the draft review submission."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from snakelane.gamecenter import gamekit, sync

from . import test_gamecenter as gc
from .test_gamecenter import ACH, ACT, GROUP, LB, live  # noqa: F401  (live is a fixture)


def args(**kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(**{"app": None, "platform": None, "dry_run": True, "yes": False,
                              "without_version": False, **kwargs})


@pytest.fixture
def connect(live: Path, monkeypatch: pytest.MonkeyPatch) -> Path:  # noqa: F811
    """What the review half reads too: no draft yet, 1.0 being prepared, no sets or challenges."""
    for path, data in {
        f"{GROUP}/gameCenterLeaderboardSetsV2": [],
        f"{GROUP}/gameCenterChallenges": [],
        "/v1/apps/1/reviewSubmissions": [],
        "/v1/apps/1/appStoreVersions": [{"id": "V", "attributes": {"versionString": "1.0",
                                                                   "appStoreState": "PREPARE_FOR_SUBMISSION"}}],
    }.items():
        monkeypatch.setitem(gc.LIVE_GETS, path, data)
    return live


def test_texts_leave_out_archived_records_and_blank_fields(tmp_path: Path) -> None:
    bundle = gc.make_bundle(tmp_path / "G.gamekit")
    data = json.loads((bundle / gamekit.RESOURCES).read_text())
    data["resources"]["achievements"] = [{"vendorIdentifier": "gone", "archived": True}]
    data["resources"]["achievementLocalizations"]["gone"] = [{"locale": "en-US", "localID": "g", "name": "Old"}]
    data["resources"]["leaderboardLocalizations"][LB][0].update(formatterOverride=None, formatterSuffix="")
    (bundle / gamekit.RESOURCES).write_text(json.dumps(data))
    assert {(t.kind, t.vendor_id, t.locale, t.fields) for t in gamekit.read_texts(bundle)} == {
        ("achievement", ACH, "en-US", (("name", "Win"),)),
        ("leaderboard", LB, "de-DE", (("name", "Siege"),)),
    }


def test_a_new_locale_sends_every_field_and_a_held_one_only_what_differs() -> None:
    text = lambda locale: gamekit.Text("achievement", ACH, locale, (("name", "Win"), ("afterEarnedDescription", "Won")))  # noqa: E731
    held = {"en-US": {"id": "L", "attributes": {"locale": "en-US", "name": "Win", "afterEarnedDescription": "Did"}}}
    new, changed = sync.diff([text("de-DE"), text("en-US")], held)
    assert (new.locale, new.fields, new.live) == ("de-DE", {"name": "Win", "afterEarnedDescription": "Won"}, None)
    assert (changed.locale, changed.fields, changed.live["id"]) == ("en-US", {"afterEarnedDescription": "Won"}, "L")
    assert sync.diff([text("en-US")], {"en-US": {"id": "L", "attributes": {
        "name": "Win", "afterEarnedDescription": "Won"}}}) == []


def test_a_dry_run_writes_text_and_images_then_fills_a_new_draft(connect: Path,
                                                                 capsys: pytest.CaptureFixture) -> None:
    sync.cmd_sync(args())
    out = capsys.readouterr().out
    # The achievement's newest version is LIVE: a new version, the text on its copies.
    assert f"~ achievement {ACH}" in out and "→ new version 2" in out
    assert "would POST /v2/gameCenterAchievementVersions  achievement→A" in out
    assert "would PATCH /v2/gameCenterAchievementLocalizations/AL  name='Win'" in out
    # The leaderboard's version 2 is editable: written in place, no new version.
    assert "would PATCH /v2/gameCenterLeaderboardLocalizations/LL  name='Siege'" in out
    assert "would POST /v2/gameCenterLeaderboardVersions" not in out
    assert "localization→LL" in out
    # Not on App Store Connect: Xcode creates records.
    assert f"✗ activity {ACT}: no such activity on App Store Connect yet" in out
    # No draft yet: one is created, with the app version and both records.
    assert "would POST /v1/reviewSubmissions" in out
    assert "would add app version 1.0" in out
    assert f"would add achievement {ACH}" in out and f"would add leaderboard {LB}" in out
    assert "nothing was written" in out


def test_without_a_terminal_sync_needs_yes(connect: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit, match="pass --yes"):
        sync.cmd_sync(args(dry_run=False))


def test_an_achievement_language_without_a_picture_gets_the_primary_locale_s(tmp_path: Path) -> None:
    en, fr = tmp_path / "en.png", tmp_path / "fr.png"
    text = lambda vendor, locale, kind="achievement": gamekit.Text(kind, vendor, locale, (("name", "x"),))  # noqa: E731
    pictures = [gamekit.Image("achievement", ACH, "fr-FR", fr), gamekit.Image("achievement", ACH, "en-US", en),
                gamekit.Image("achievement", "lone", "fr-FR", fr)]
    filled = sync.fill_achievement_images(
        [text(ACH, "en-US"), text(ACH, "de-DE"), text(ACH, "fr-FR"), text("lone", "ko"),
         text("bare", "de-DE"), text(LB, "de-DE", "leaderboard")], pictures, "en-US")
    # de-DE takes en-US's; a record without the primary's takes the one it has; a record with no
    # picture at all, and a leaderboard, are left alone.
    assert {(i.vendor_id, i.locale, i.path) for i in filled} == {(ACH, "de-DE", en), ("lone", "ko", fr)}


def test_a_dry_run_gives_a_new_achievement_language_the_en_us_picture(connect: Path,
                                                                     capsys: pytest.CaptureFixture) -> None:
    resources = connect / "App" / "G.gamekit" / gamekit.RESOURCES
    data = json.loads(resources.read_text())
    data["resources"]["achievementLocalizations"][ACH].append({"locale": "de-DE", "localID": f"{ACH}-de-DE",
                                                               "name": "Sieg"})
    resources.write_text(json.dumps(data))
    sync.cmd_sync(args())
    out = capsys.readouterr().out
    assert "+ de-DE: name" in out and "+ image [de-DE]" in out
