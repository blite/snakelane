"""`snakelane bump`: stamping (iOS and macOS archive layouts), archive verification, both scopes
and repo discovery from Xcode's $PROJECT_DIR, on a synthetic project."""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from snakelane import project
from snakelane.release import bump

PBXPROJ = """// !$*UTF8*$!
{ objects = {
\tAA01 /* Debug */ = {isa = XCBuildConfiguration; buildSettings = {CURRENT_PROJECT_VERSION = 7; MARKETING_VERSION = 1.2;
\t\tPRODUCT_BUNDLE_IDENTIFIER = com.example.app; OTHER = "${SRCROOT}/x";}; name = Debug;};
\tAA02 /* Debug */ = {isa = XCBuildConfiguration; buildSettings = {CURRENT_PROJECT_VERSION = 7;
\t\tPRODUCT_BUNDLE_IDENTIFIER = "com.example.app.widget";}; name = Debug;};
\tBB01 /* Debug */ = {isa = XCBuildConfiguration; buildSettings = {CURRENT_PROJECT_VERSION = 40;
\t\tPRODUCT_BUNDLE_IDENTIFIER = com.example.other;}; name = Debug;};
}; }
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for key in ("PROJECT_DIR", "SRCROOT"):
        monkeypatch.delenv(key, raising=False)
    repo = tmp_path / "Repo"
    (repo / "metadata").mkdir(parents=True)
    (repo / "Example.xcodeproj").mkdir()
    (repo / "Example.xcodeproj" / "project.pbxproj").write_text(PBXPROJ)
    (repo / project.CONFIG_NAME).write_text("bundle_id: com.example.app\nscheme: Example\n")
    monkeypatch.chdir(tmp_path)  # no config above the working directory
    return repo


def test_the_post_action_finds_the_repo_through_project_dir(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(repo))
    assert bump.locate_app(None).root == repo.resolve()
    monkeypatch.delenv("PROJECT_DIR")
    with pytest.raises(SystemExit):
        bump.locate_app(None)


def test_project_and_app_scopes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(repo))
    app = bump.locate_app(None)
    assert bump.committed_build(app) == 40, "project scope reads every configuration"
    assert bump.next_build(app, check_testflight=False) == 41
    app.config.update(build_number_scope="app", extension_bundle_ids=["com.example.app.widget"])
    assert bump.committed_build(app) == 7, "app scope ignores the other app"
    assert bump.write_pbxproj(app, 8) == 2
    text = app.pbxproj.read_text()
    assert text.count("CURRENT_PROJECT_VERSION = 8;") == 2 and "= 40;" in text
    app.config["build_number_scope"] = "project"
    assert bump.write_pbxproj(app, 41) == 3


@pytest.mark.parametrize("layout", ["ios", "macos"])
def test_stamping_and_verifying_an_archive(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           layout: str) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(repo))
    app = bump.locate_app(None)
    bump.write_pbxproj(app, 41)
    archive = tmp_path / f"{layout}.xcarchive"
    bundle = archive / "Products" / "Applications" / "App.app"
    contents = bundle / "Contents" if layout == "macos" else bundle
    appex = contents / ("PlugIns" if layout == "macos" else "Extensions") / "Widget.appex"
    ext_plist = (appex / "Contents" if layout == "macos" else appex) / "Info.plist"
    plists = [contents / "Info.plist", ext_plist]
    for path in plists:
        bump._dump(path, {"CFBundleVersion": "1", "CFBundleShortVersionString": "1.2"})
    bump._dump(archive / "Info.plist", {"ApplicationProperties": {"CFBundleVersion": "1"}})
    with pytest.raises(SystemExit):
        bump.verify_archive(app, archive, before=40)  # not stamped yet
    bump.stamp_archive(archive, 41)
    bump.stamp_archive(archive, 41)  # idempotent
    assert all(plistlib.loads(p.read_bytes())["CFBundleVersion"] == "41" for p in plists)
    assert bump._load(archive / "Info.plist")["ApplicationProperties"]["CFBundleVersion"] == "41"
    assert bump.verify_archive(app, archive, before=40) == 41
    with pytest.raises(SystemExit):
        bump.verify_archive(app, archive, before=41)  # the number didn't move
    bump._dump(ext_plist, {"CFBundleVersion": "4"})
    with pytest.raises(SystemExit):
        bump.verify_archive(app, archive, before=40)  # a mismatched extension
    assert bump.archived_versions(archive) == ("1.2", "41")
