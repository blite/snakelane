"""A failed shoot leaves the deck exactly as it found it (`shoot.PreviousDeck`)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from snakelane import project
from snakelane.screenshots import shoot

from .helpers import make_app


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return make_app(tmp_path)


def deck(tree: project.DeckTree, locale: str, names: list[str], content: str) -> None:
    for folder in (tree.raw(locale), tree.framed(locale)):
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_text(content)


def snapshot(app: project.App) -> dict[str, str]:
    return {str(p.relative_to(app.root)): p.read_text() for p in sorted(app.root.rglob("*"))
            if p.is_file() and p.name != project.CONFIG_NAME}


def test_failure_restores_the_previous_deck(app: project.App) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    deck(tree, "en-US", ["ss-01.jpg", "ss-02.jpg", "ss-03.jpg"], "old")
    deck(tree, "de-DE", ["ss-01.jpg", "ss-02.jpg", "ss-03.jpg"], "old")
    (tree.framed("en-US") / "ap-01.m4v").write_text("preview")  # not the shoot's to touch
    before = snapshot(app)

    previous = shoot.PreviousDeck([(tree, None)], None)
    previous.stash()
    assert not list(tree.framed("en-US").glob("ss-*")), "old shots are out of the deck"
    assert (tree.framed("en-US") / "ap-01.m4v").exists()
    deck(tree, "en-US", ["ss-01.jpg"], "new, half a shoot")  # the test died after one shot
    previous.restore()

    assert snapshot(app) == before
    assert not app.shoot_stash.exists()


def test_success_discards_the_previous_deck(app: project.App) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    deck(tree, "en-US", ["ss-01.jpg", "ss-02.jpg", "ss-03.jpg"], "old")
    previous = shoot.PreviousDeck([(tree, None)], None)
    previous.stash()
    deck(tree, "en-US", ["ss-01.jpg", "ss-02.jpg"], "new")
    previous.discard()

    assert sorted(p.name for p in tree.framed("en-US").iterdir()) == ["ss-01.jpg", "ss-02.jpg"]
    assert {p.read_text() for p in tree.raw("en-US").iterdir()} == {"new"}
    assert not app.shoot_stash.exists()


def test_a_stash_left_by_a_killed_shoot_is_never_overwritten(app: project.App) -> None:
    app.shoot_stash.mkdir(parents=True)
    with pytest.raises(SystemExit, match="left over from a shoot that was killed"):
        shoot.PreviousDeck([(project.DeckTree(app, "ios", "iphone"), None)], None)


def test_execute_restores_when_a_pass_fails(app: project.App, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    deck(tree, "en-US", ["ss-01.jpg", "ss-02.jpg"], "old")
    before = snapshot(app)
    plan = SimpleNamespace(
        config=SimpleNamespace(frame="test"),
        clear_targets=[(tree, "iPhone 14 Plus")],
        clear_locales=None,
    )

    def failing_passes(plan: object) -> None:
        deck(tree, "en-US", ["ss-01.jpg"], "partial")
        raise SystemExit("shoot failed")

    monkeypatch.setattr(shoot, "run_passes", failing_passes)
    with pytest.raises(SystemExit, match="shoot failed"):
        shoot.execute(plan)  # type: ignore[arg-type]
    assert snapshot(app) == before


def test_the_clear_matches_what_the_push_uploads(app: project.App) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    deck(tree, "en-US", ["ss-01.jpg"], "shot")
    (tree.framed("en-US") / "iPhone 14 Plus-01.jpg").write_text("stray from old naming")
    (tree.raw("en-US") / "unused-02-alt.png").write_text("kept for comparison")
    (tree.framed("en-US") / "ap-01.m4v").write_text("preview")
    stale = {p.relative_to(app.root).as_posix() for p in shoot.stale_files(tree, None, None)}
    assert stale == {
        "metadata/ios/screenshots/en-US/iphone/ss-01.jpg",
        "metadata/ios/screenshots/en-US/iphone/iPhone 14 Plus-01.jpg",
        f".snakelane/{app.slug}/raw/ios/en-US/iphone/ss-01.jpg",
    }


def test_a_mac_deck_has_no_device_folder(app: project.App) -> None:
    mac = project.DeckTree(app, "macos")
    assert mac.framed("ja") == app.folder / "macos" / "screenshots" / "ja"
    assert project.DeckTree(app, "ios", "ipad").framed("ja") == app.folder / "ios" / "screenshots" / "ja" / "ipad"


def test_a_push_refuses_while_a_killed_shoots_stash_exists(app: project.App, tmp_path: Path) -> None:
    import subprocess
    import sys

    app.shoot_stash.mkdir(parents=True)
    result = subprocess.run([sys.executable, "-m", "snakelane", "-C", str(app.root),
                             "store", "screenshots", "push", "--dry-run"],
                            capture_output=True, text=True, check=False, env={"HOME": str(tmp_path), "PATH": ""})
    assert result.returncode != 0 and "left over from a shoot that was killed" in result.stderr


def test_each_pass_gets_the_banner_depth_and_the_file_is_removed(app: project.App, tmp_path: Path,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    app.config["scheme"] = "Example"
    monkeypatch.setattr(shoot, "HANDOFF_DIR", tmp_path)
    app.config["screenshots"] = {"frame": "snakelane", "framing": {"layout": "full-bleed", "captions": {"1": "One"}}}
    config = shoot.load_config(app)
    tree = project.DeckTree(app, "ios", "ipad")
    env = shoot.runner_env(config, "en-US", None, tree, shoot.banner_json(config, tree))
    assert json.loads(env["TEST_RUNNER_SNAKELANE_BANNER"])["deck"] == "ipad"
    seen: list[dict] = []
    monkeypatch.setattr(shoot, "extract_deck", lambda *args: None)
    monkeypatch.setattr(shoot, "run", lambda cmd, env: seen.append(json.loads(shoot.banner_file(app).read_text())))
    plan = shoot.Plan(app, config, "ios", {"en-US": None}, full_locales=True)
    plan.passes.append(shoot.Pass("ipad", tree, "en-US", None, tmp_path / "x.xcresult", ["true"], env))
    shoot.run_passes(plan)
    assert seen[0]["slots"]["1"]["position"] == "top" and seen[0]["depth"] == pytest.approx(0.10, abs=0.002)
    assert not shoot.banner_file(app).exists(), "no stale depth for the next run"
