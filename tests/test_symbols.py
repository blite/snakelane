"""dSYMs to Sentry after a ship: the `sentry` block, the preflight, and a failure that only warns."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from snakelane.release import ship, symbols

from .helpers import make_app

SENTRY = {"org": "example-org", "project": "example-app"}


def archive_with_dsyms(tmp_path: Path, name: str = "Example-ios.xcarchive") -> Path:
    (dsym := tmp_path / "build" / name / "dSYMs" / "Example.app.dSYM").mkdir(parents=True)
    return dsym.parent.parent


def test_the_sentry_block_is_optional_and_checked(tmp_path: Path) -> None:
    assert symbols.sentry_config(make_app(tmp_path)) is None
    assert symbols.sentry_config(make_app(tmp_path, sentry=SENTRY)) == SENTRY
    with pytest.raises(SystemExit, match="unknown key token"):
        symbols.sentry_config(make_app(tmp_path, sentry={**SENTRY, "token": "x"}))
    with pytest.raises(SystemExit, match='missing "project"'):
        symbols.sentry_config(make_app(tmp_path, sentry={"org": "example-org"}))
    with pytest.raises(SystemExit, match="is an object"):
        symbols.sentry_config(make_app(tmp_path, sentry="example-org/example-app"))


def test_the_upload_names_org_project_and_the_archives_dsyms(tmp_path: Path) -> None:
    archive = tmp_path / "Example-ios.xcarchive"
    assert symbols.upload_command(SENTRY, archive) == [
        "sentry-cli", "debug-files", "upload", "--org", "example-org", "--project", "example-app",
        str(archive / "dSYMs")]
    self_hosted = symbols.upload_command({**SENTRY, "url": "https://sentry.example.com"}, archive)
    assert self_hosted[:3] == ["sentry-cli", "--url", "https://sentry.example.com"]


def test_without_a_sentry_block_nothing_is_checked_or_sent(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(symbols.shutil, "which", lambda name: pytest.fail("looked for sentry-cli"))
    monkeypatch.setattr(symbols, "run", lambda cmd: pytest.fail("ran sentry-cli"))
    app = make_app(tmp_path)
    symbols.preflight(app)
    assert symbols.upload(app, archive_with_dsyms(tmp_path), "ios") is None


def test_preflight_stops_before_the_archive_without_sentry_cli_or_a_sign_in(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(tmp_path, sentry=SENTRY)
    monkeypatch.setattr(symbols.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="brew install getsentry/tools/sentry-cli"):
        symbols.preflight(app)

    monkeypatch.setattr(symbols.shutil, "which", lambda name: "/opt/homebrew/bin/sentry-cli")
    seen: list[list[str]] = []

    def info(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(symbols.subprocess, "run", info)
    with pytest.raises(SystemExit, match="sentry-cli login"):
        symbols.preflight(app)
    assert seen == [["sentry-cli", "info", "--no-defaults"]]  # the token only, never passed by snakelane


def test_a_failed_upload_is_reported_with_the_retry_not_raised(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = make_app(tmp_path, sentry=SENTRY)
    archive = archive_with_dsyms(tmp_path, "Example-macos.xcarchive")

    def failing(cmd: list[str]) -> None:
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(symbols, "run", failing)
    problem = symbols.upload(app, archive, "macos")
    assert problem is not None
    assert "snakelane ship symbols --platform macos" in problem

    sent: list[list[str]] = []
    monkeypatch.setattr(symbols, "run", sent.append)
    assert symbols.upload(app, archive, "macos") is None
    assert sent == [symbols.upload_command(SENTRY, archive)]


def test_an_archive_without_dsyms_says_which_setting_to_check(tmp_path: Path) -> None:
    app = make_app(tmp_path, sentry=SENTRY)
    (archive := tmp_path / "build" / "Example-ios.xcarchive").mkdir(parents=True)
    assert "dwarf-with-dsym" in (symbols.upload(app, archive, "ios") or "")


def test_ship_symbols_needs_a_sentry_block_and_an_archive(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    make_app(tmp_path, scheme="Example", team_id="TEAM")
    with pytest.raises(SystemExit, match='no "sentry" block'):
        ship.send_symbols()
    make_app(tmp_path, scheme="Example", team_id="TEAM", sentry=SENTRY)
    with pytest.raises(SystemExit, match="ship beta"):
        ship.send_symbols()
