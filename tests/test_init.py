"""`snakelane init` reads an Xcode project and writes a config the rest of snakelane accepts."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane import init, project
from snakelane.listing import lint

PBXPROJ = """
        A1 = { buildSettings = { PRODUCT_BUNDLE_IDENTIFIER = com.example.trail; DEVELOPMENT_TEAM = ABCDE12345;
                SUPPORTED_PLATFORMS = "iphoneos iphonesimulator macosx"; }; };
        A2 = { buildSettings = { PRODUCT_BUNDLE_IDENTIFIER = "com.example.trail.widget"; DEVELOPMENT_TEAM = ABCDE12345; }; };
        A3 = { buildSettings = { PRODUCT_BUNDLE_IDENTIFIER = com.example.trailTests; SDKROOT = iphoneos; }; };
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    proj = tmp_path / "Trail.xcodeproj"
    (proj / "xcshareddata" / "xcschemes").mkdir(parents=True)
    (proj / "project.pbxproj").write_text(PBXPROJ)
    for scheme in ("Trail", "TrailTests", "Debug (Sample Data)"):
        (proj / "xcshareddata" / "xcschemes" / f"{scheme}.xcscheme").write_text("<Scheme/>")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_writes_a_config_snakelane_reads(repo: Path) -> None:
    init.main([])
    app = project.resolve_app(None, root=repo)
    assert app.config["bundle_id"] == "com.example.trail"
    assert app.config["scheme"] == "Trail"
    assert app.config["team_id"] == "ABCDE12345"
    assert app.config["platforms"] == ["ios", "macos"]
    assert (repo / "metadata" / "default" / "name.txt").read_text().strip() == "Trail"


def test_placeholders_cannot_be_pushed_and_nothing_is_overwritten(repo: Path) -> None:
    init.main([])
    app = project.resolve_app(None, root=repo)
    assert any(f.rule == "placeholder" for f in lint.run(app, "ios"))
    with pytest.raises(SystemExit, match="already exists"):
        init.main([])
    (repo / "metadata" / "default" / "subtitle.txt").write_text("Hike logs\n")
    init.main(["--force"])
    assert (repo / "metadata" / "default" / "subtitle.txt").read_text() == "Hike logs\n"
