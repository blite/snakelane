"""`ship release`'s release settings and `snakelane status`, against a fake client."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from snakelane import project
from snakelane.release import ship, status

from .fakes import FakeClient
from .helpers import make_app

VERSION = {"id": "v1", "attributes": {"releaseType": "AFTER_APPROVAL", "earliestReleaseDate": None}}


def app_with(tmp_path: Path, release: dict) -> project.App:
    return make_app(tmp_path, release=release)


def test_release_settings_are_validated_before_anything_runs(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="unknown key"):
        ship.release_settings(app_with(tmp_path, {"phase": True}))
    with pytest.raises(SystemExit, match="scheduled needs a date"):
        ship.release_settings(app_with(tmp_path, {"type": "scheduled"}))
    with pytest.raises(SystemExit, match="timezone"):
        app = app_with(tmp_path, {"type": "scheduled"})
        app.config["release"]["date"] = dt.datetime(2026, 11, 3, 9)  # what YAML gives for a bare timestamp
        ship.release_settings(app)
    assert ship.release_settings(app_with(tmp_path, {})) == {"type": None, "date": None, "phased": None}


def test_scheduled_phased_release_writes_only_what_differs(tmp_path: Path) -> None:
    app = app_with(tmp_path, {"type": "scheduled", "date": "2026-11-03T09:00:00-08:00", "phased": True})
    client = FakeClient()
    ship.apply_release_settings(client, VERSION, ship.release_settings(app))
    (m1, p1, body1), (m2, p2, body2) = client.writes
    assert (m1, p1) == ("PATCH", "/v1/appStoreVersions/v1")
    assert body1["data"]["attributes"] == {"releaseType": "SCHEDULED", "earliestReleaseDate": "2026-11-03T09:00:00-08:00"}
    assert (m2, p2) == ("POST", "/v1/appStoreVersionPhasedReleases")
    assert body2["data"]["attributes"] == {"phasedReleaseState": "INACTIVE"}


def test_turning_phased_off_deletes_it_and_matching_settings_write_nothing(tmp_path: Path) -> None:
    client = FakeClient({"/v1/appStoreVersions/v1/appStoreVersionPhasedRelease": {"data": {"id": "p9"}}})
    app = app_with(tmp_path, {"type": "after_approval", "phased": False})
    ship.apply_release_settings(client, VERSION, ship.release_settings(app))
    assert client.writes == [("DELETE", "/v1/appStoreVersionPhasedReleases/p9", None)]


def test_status_shows_live_and_newer_versions_reviews_and_the_latest_build(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(tmp_path)
    monkeypatch.setattr(status, "find_app", lambda client, config: {
        "id": "42", "attributes": {"name": "Example", "primaryLocale": "en-US"}})
    def version(vid, v, state, release="AFTER_APPROVAL"):
        return {"id": vid, "attributes": {"versionString": v, "appStoreState": state, "platform": "IOS",
                                          "releaseType": release}}
    client = FakeClient({
        "/v1/apps/42/appStoreVersions": {"data": [version("v3", "1.3", "WAITING_FOR_REVIEW", "MANUAL"),
                                                  version("v2", "1.2", "READY_FOR_SALE"),
                                                  version("v1", "1.1", "READY_FOR_SALE")]},
        "/v1/appStoreVersions/v3/appStoreVersionPhasedRelease": {"data": {"attributes": {"phasedReleaseState": "INACTIVE"}}},
        "/v1/reviewSubmissions": {"data": [{"attributes": {"state": "WAITING_FOR_REVIEW", "platform": "IOS"}},
                                           {"attributes": {"state": "COMPLETE", "platform": "IOS"}}]},
        "/v1/builds": {"data": [{"attributes": {"version": "57", "processingState": "VALID"}}]},
    })
    result = status.collect(client, app)
    assert [v["version"] for v in result["versions"]["iOS"]] == ["1.3", "1.2"]  # 1.1 is history
    assert result["versions"]["iOS"][0]["phased_release"] == "INACTIVE"
    assert [r["state"] for r in result["reviews_in_progress"]] == ["WAITING_FOR_REVIEW"]
    assert result["latest_build"]["version"] == "57"
    assert status.describe_release(result["versions"]["iOS"][0]) == "manual release, phased (inactive)"


@pytest.mark.parametrize("date", ["not-a-date", "2026-11-03T09:00:00", "2026-11-03"])
def test_a_quoted_date_is_checked_too(tmp_path: Path, date: str) -> None:
    with pytest.raises(SystemExit, match=r"ISO time|timezone"):
        ship.release_settings(app_with(tmp_path, {"type": "scheduled", "date": date}))


def test_a_quoted_date_with_a_timezone_is_kept(tmp_path: Path) -> None:
    settings = ship.release_settings(app_with(tmp_path, {"type": "scheduled", "date": "2026-11-03T09:00:00-08:00"}))
    assert settings["date"] == "2026-11-03T09:00:00-08:00"


def test_the_test_gate_passes_env_to_the_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from snakelane.release import ship

    app = make_app(tmp_path, scheme="Example", test={"env": {"RUN_CONTENT_TESTS": 1, "TEST_RUNNER_X": "y"}})
    (tmp_path / "Example.xcodeproj").mkdir()
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(ship, "run", lambda cmd, env: seen.append(env))
    ship.run_tests(app)
    assert seen == [{"TEST_RUNNER_RUN_CONTENT_TESTS": "1", "TEST_RUNNER_X": "y"}]


def test_the_gate_runs_on_the_simulator_unless_mac_opts_in() -> None:
    from snakelane.release import ship

    def destination(test: dict, platform: str) -> str:
        return ship.test_destination(test, platform)

    assert destination({}, "macos") == "platform=iOS Simulator,name=iPhone 17 Pro Max"
    assert destination({"device": "iPhone Air"}, "ios") == "platform=iOS Simulator,name=iPhone Air"
    assert destination({"mac": {}, "device": "iPhone Air"}, "ios") == "platform=iOS Simulator,name=iPhone Air"
    assert destination({"mac": {}}, "macos") == "platform=macOS,arch=arm64"
    assert destination({"mac": None}, "macos") == "platform=iOS Simulator,name=iPhone 17 Pro Max"
    assert destination({"mac": {"destination": "platform=macOS,arch=x86_64"}}, "macos") == "platform=macOS,arch=x86_64"
    with pytest.raises(SystemExit, match=r"test\.mac is an object"):
        destination({"mac": True}, "macos")


FIRST_EXPORT_OUTPUT = """\
2026-10-03 07:50:35.228 xcodebuild[19059:3379153] [MT] IDEDistribution: Created bundle at path "/tmp/x"
error: exportArchive Cloud signing permission error
error: exportArchive No profiles for 'com.example.app' were found
  Xcode couldn't find any iOS App Store provisioning profiles matching 'com.example.app'.
** EXPORT FAILED **
"""


def test_a_first_export_that_cannot_sign_says_how_to_get_past_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from snakelane.connect import asc
    from snakelane.release import ship

    app = make_app(tmp_path, scheme="Example", team_id="TEAM", bundle_id="com.example.app")
    monkeypatch.setattr(asc.Credentials, "load", staticmethod(lambda: asc.Credentials(
        key_id="K", issuer_id="I")))

    def failing_export(cmd: list[str], env: dict[str, str]) -> str:
        raise subprocess.CalledProcessError(70, cmd, output=FIRST_EXPORT_OUTPUT)

    monkeypatch.setattr(ship, "run_logged", failing_export)
    archive = tmp_path / "build" / "Example-ios.xcarchive"
    with pytest.raises(SystemExit) as stopped:
        ship.upload(app, archive)
    message = str(stopped.value)
    assert "com.example.app has no App Store provisioning profile" in message
    assert f"open {archive}" in message
    assert "Admin role" in message


def test_any_other_export_failure_still_raises_as_it_was(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from snakelane.connect import asc
    from snakelane.release import ship

    app = make_app(tmp_path, scheme="Example", team_id="TEAM", bundle_id="com.example.app")
    monkeypatch.setattr(asc.Credentials, "load", staticmethod(lambda: asc.Credentials(
        key_id="K", issuer_id="I")))

    def failing_export(cmd: list[str], env: dict[str, str]) -> str:
        raise subprocess.CalledProcessError(70, cmd, output="error: Copy failed\n")

    monkeypatch.setattr(ship, "run_logged", failing_export)
    with pytest.raises(subprocess.CalledProcessError):
        ship.upload(app, tmp_path / "Example-ios.xcarchive")
    assert not ship.needs_first_store_profile("error: Copy failed")
