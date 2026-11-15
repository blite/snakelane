"""`shoot --shots`: only the named shots' test methods run, and only their files are replaced."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from snakelane import project
from snakelane.screenshots import shoot

from .helpers import make_app
from .test_shoot_failure import deck, snapshot

TEST_SOURCE = """
final class ExampleScreenshots: XCTestCase {
    @MainActor func test01Table() {}
    #if os(iOS)
        func test04Layout() {}
    #else
        func test04OnTop() {}
    #endif
    func test05Win() { win(launch("win"), "05-Win") }
    func testHelperIsNotAShot() {}
}
"""


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    (tmp_path / "Example.xcodeproj").mkdir()
    app = make_app(tmp_path, project="Example.xcodeproj", scheme="Example",
                   screenshots={"test": "ExampleUITests/ExampleScreenshots", "mac": {}})
    (tmp_path / "UITests").mkdir()
    (tmp_path / "UITests" / "ExampleScreenshots.swift").write_text(TEST_SOURCE)
    (tmp_path / "UITests" / "Other.swift").write_text("final class Other: XCTestCase { func test09Elsewhere() {} }")
    (tmp_path / "DerivedData").mkdir()
    (tmp_path / "DerivedData" / "Copy.swift").write_text("class ExampleScreenshots { func test07Stale() {} }")
    return app


def test_a_shot_is_named_by_its_number() -> None:
    assert [shoot.slot_number(text) for text in ("5", "05", "ss-05", " SS-12 ")] == ["05", "05", "05", "12"]
    for text in ("", "x", "0", "100", "ss-"):
        with pytest.raises(SystemExit, match="is not a shot"):
            shoot.slot_number(text)


def test_methods_are_found_by_number_in_the_test_classs_source(app: project.App) -> None:
    assert shoot.numbered_tests(app, "ExampleUITests/ExampleScreenshots") == {
        "01": ["test01Table"], "04": ["test04Layout", "test04OnTop"], "05": ["test05Win"]}


def test_every_platforms_method_for_a_slot_is_asked_for(app: project.App) -> None:
    config = shoot.load_config(app)
    assert shoot.tests_for_shots(app, config, config.test, ["04", "05"]) == [
        "ExampleUITests/ExampleScreenshots/test04Layout", "ExampleUITests/ExampleScreenshots/test04OnTop",
        "ExampleUITests/ExampleScreenshots/test05Win"]


def test_the_config_names_a_method_the_convention_cannot(tmp_path: Path) -> None:
    app = make_app(tmp_path, project="Example.xcodeproj", scheme="Example", screenshots={
        "test": "ExampleUITests/ExampleScreenshots", "shot_tests": {"3": "testThemes", "ss-06": ["testA", "testB"]}})
    config = shoot.load_config(app)
    assert shoot.tests_for_shots(app, config, config.test, ["03", "06"]) == [
        "ExampleUITests/ExampleScreenshots/testThemes", "ExampleUITests/ExampleScreenshots/testA",
        "ExampleUITests/ExampleScreenshots/testB"]


def test_a_shot_with_no_method_stops_before_anything_runs(app: project.App) -> None:
    config = shoot.load_config(app)
    with pytest.raises(SystemExit, match=r"no test method for shot 07.*it has 01, 04, 05"):
        shoot.tests_for_shots(app, config, config.test, ["07"])
    with pytest.raises(SystemExit, match=r"must name one as <Target>/<Class>"):
        shoot.tests_for_shots(app, config, None, ["01"])


def test_only_the_named_shots_are_cleared(app: project.App) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    deck(tree, "en-US", ["ss-01.jpg", "ss-05.jpg", "ss-15.jpg"], "shot")
    (tree.raw("en-US") / "_ss-05.png").write_text("the capture before its crop")
    (tree.framed("en-US") / "ap-01.m4v").write_text("preview")
    stale = {p.relative_to(app.root).as_posix() for p in shoot.stale_files(tree, ["en-US"], None, ["05"])}
    assert stale == {
        "metadata/ios/screenshots/en-US/iphone/ss-05.jpg",
        f".snakelane/{app.slug}/raw/ios/en-US/iphone/ss-05.jpg",
        f".snakelane/{app.slug}/raw/ios/en-US/iphone/_ss-05.png",
    }


def test_a_failed_single_shot_leaves_the_whole_deck_as_it_was(app: project.App) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    deck(tree, "en-US", ["ss-01.jpg", "ss-05.jpg"], "old")
    before = snapshot(app)
    with pytest.raises(SystemExit), shoot.PreviousDeck([(tree, None)], ["en-US"], ["05"]):
        assert (tree.framed("en-US") / "ss-01.jpg").exists(), "the other shots never leave the deck"
        assert not (tree.framed("en-US") / "ss-05.jpg").exists()
        deck(tree, "en-US", ["ss-05.jpg"], "new, but the next locale failed")
        raise SystemExit("shoot failed")
    assert snapshot(app) == before


def test_the_plan_runs_only_those_methods_and_touches_only_its_locales(app: project.App) -> None:
    config = shoot.load_config(app)
    args = SimpleNamespace(platform="macos", device=None, locales=None, shots="ss-05, 4", dry_run=True)
    plan = shoot.make_plan(app, config, args)
    assert plan.shots == ["04", "05"]
    assert plan.clear_locales == ["en-US"], "never every locale folder: no pass refills the others"
    cmd = plan.passes[0].cmd
    only = [cmd[i + 1].rsplit("/", 1)[-1] for i, word in enumerate(cmd) if word == "-only-testing"]
    assert only == ["test04Layout", "test04OnTop", "test05Win"]


def test_a_whole_shoot_is_unchanged(app: project.App) -> None:
    config = shoot.load_config(app)
    plan = shoot.make_plan(app, config, SimpleNamespace(platform="macos", device=None, locales=None, dry_run=True))
    cmd = plan.passes[0].cmd
    assert plan.shots is None and plan.clear_locales is None
    assert cmd[cmd.index("-only-testing") + 1] == "ExampleUITests/ExampleScreenshots" and cmd.count("-only-testing") == 1


def test_a_shot_that_did_not_come_back_is_missing(app: project.App) -> None:
    tree = project.DeckTree(app, "macos")
    deck(tree, "en-US", ["ss-05.jpg"], "new")
    assert shoot.missing_shots(tree, "en-US", ["04", "05"]) == ["04"]
