"""Offline checks on `gamecenter images`: reading a .gamekit, validating its images, and the
new/changed/unchanged plan against a stand-in App Store Connect."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image as PILImage

from snakelane.connect import asc
from snakelane.gamecenter import gamekit, images

from .helpers import image, make_app

ACH, LB, ACT = "grp.game.ach.win-one", "grp.game.lb.wins", "grp.game.activity.main"


def make_bundle(folder: Path, extra_images: dict[str, Any] | None = None) -> Path:
    """A .gamekit as Xcode writes it: escaped slashes, an achievement whose id has a hyphen, a
    leaderboard and an activity."""
    folder.mkdir(parents=True, exist_ok=True)
    resources = {
        "achievementImages": {f"{ACH}-en-US": [{"localID": f"{ACH}-en-US", "url": f"en-US/A-{ACH}.png"}],
                              **(extra_images or {})},
        "achievementLocalizations": {ACH: [{"locale": "en-US", "localID": f"{ACH}-en-US", "name": "Win"}]},
        "leaderboardImages": {f"{LB}-de-DE": [{"localID": f"{LB}-de-DE", "url": f"de-DE/L-{LB}.png"}]},
        "leaderboardLocalizations": {LB: [{"locale": "de-DE", "localID": f"{LB}-de-DE", "name": "Siege"}]},
        "gameActivityDefaultImages": {ACT: {"localID": ACT, "url": f"G-{ACT}.png"}},
    }
    (folder / gamekit.RESOURCES).write_text(json.dumps({"resources": resources}).replace("/", "\\/"))
    image(folder / "en-US" / f"A-{ACH}.png", 1024, 1024)
    image(folder / "de-DE" / f"L-{LB}.png", 1024, 1024)
    image(folder / f"G-{ACT}.png", 3840, 2160)
    return folder


def test_bundle_maps_images_to_record_and_locale_through_the_localizations(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path / "G.gamekit")
    found, problems = gamekit.read_bundle(bundle)
    assert problems == []
    assert {(i.kind, i.vendor_id, i.locale, i.path.relative_to(bundle).as_posix()) for i in found} == {
        ("achievement", ACH, "en-US", f"en-US/A-{ACH}.png"),
        ("leaderboard", LB, "de-DE", f"de-DE/L-{LB}.png"),
        ("activity", ACT, None, f"G-{ACT}.png"),
    }


def test_an_image_with_no_localization_is_a_problem(tmp_path: Path) -> None:
    bundle = make_bundle(tmp_path / "G.gamekit", {"x-en-US": [{"localID": "x-en-US", "url": "en-US/x.png"}]})
    _, [problem] = gamekit.read_bundle(bundle)
    assert "'x-en-US' has no achievement localization" in problem


def test_the_repo_s_only_gamekit_is_found_and_build_output_is_skipped(tmp_path: Path) -> None:
    make_bundle(tmp_path / "App" / "GC.gamekit")
    make_bundle(tmp_path / "DerivedData" / "Old.gamekit")
    make_bundle(tmp_path / ".git" / "Stale.gamekit")
    assert gamekit.find_bundle(tmp_path) == tmp_path / "App" / "GC.gamekit"


def test_none_or_several_gamekits_need_the_config_key(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"no \*\.gamekit"):
        gamekit.find_bundle(tmp_path)
    make_bundle(tmp_path / "A.gamekit")
    make_bundle(tmp_path / "B.gamekit")
    with pytest.raises(SystemExit, match=r"2 \*\.gamekit folders.*A\.gamekit, B\.gamekit"):
        gamekit.find_bundle(tmp_path)
    assert gamekit.find_bundle(tmp_path, "B.gamekit") == tmp_path / "B.gamekit"
    with pytest.raises(SystemExit, match=r"no gameCenterResources\.json"):
        gamekit.find_bundle(tmp_path, "C.gamekit")


def test_the_config_key_names_the_bundle(tmp_path: Path) -> None:
    make_bundle(tmp_path / "A.gamekit")
    make_bundle(tmp_path / "B.gamekit")
    app = make_app(tmp_path, gamecenter={"gamekit": "B.gamekit"})
    assert all(tmp_path / "B.gamekit" in i.path.parents for i in images.local_images(app))


@pytest.mark.parametrize("kind, size, mode, problem", [
    ("achievement", (1024, 1024), "RGB", None),
    ("leaderboard", (1024, 1024), "P", None),
    ("activity", (3840, 2160), "RGB", None),
    ("achievement", (512, 512), "RGB", "must be 1024×1024"),
    ("activity", (1920, 1080), "RGB", "must be 3840×2160"),
    ("achievement", (1024, 1024), "RGBA", "alpha channel"),
    ("leaderboard", (1024, 1024), "CMYK", "wants RGB"),
])
def test_images_are_checked_against_apple_s_spec(tmp_path: Path, kind: str, size: tuple[int, int], mode: str,
                                                 problem: str | None) -> None:
    path = tmp_path / ("x.jpg" if mode == "CMYK" else "x.png")
    PILImage.new(mode, size).save(path)
    found = gamekit.image_problem(gamekit.Image(kind, "id", "en-US", path))
    assert found is None if problem is None else problem in found


def test_a_bad_image_stops_before_app_store_connect_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = make_bundle(tmp_path / "G.gamekit")
    PILImage.new("RGBA", (1024, 1024)).save(bundle / "en-US" / f"A-{ACH}.png")
    make_app(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(asc, "Client", lambda **_: pytest.fail("App Store Connect was read"))
    with pytest.raises(SystemExit, match=r"fix the \.gamekit images"):
        images.cmd_push(SimpleNamespace(app=None, dry_run=False, yes=True, new_version=False))


def test_pixels_are_compared_not_bytes(tmp_path: Path) -> None:
    local = tmp_path / "a.png"
    PILImage.new("RGB", (8, 8), (10, 20, 30)).save(local)
    assert gamekit.same_pixels(local, PILImage.new("RGBA", (8, 8), (10, 20, 30, 255)))  # ASC's re-encode
    assert not gamekit.same_pixels(local, PILImage.new("RGB", (8, 8), (10, 20, 31)))
    assert not gamekit.same_pixels(local, PILImage.new("RGB", (16, 16), (10, 20, 30)))


def test_status_and_version_rules() -> None:
    assert images.status_for(None, None) == "new"
    assert images.status_for({"id": "i"}, True) == "unchanged"
    assert images.status_for({"id": "i"}, False) == "changed"
    assert images.status_for({"id": "i"}, None) == "changed"  # failed processing: nothing to compare
    version = lambda n, state: {"id": f"v{n}", "attributes": {"version": n, "state": state}}  # noqa: E731
    assert images.newest([version(1, "LIVE"), version(2, "PREPARE_FOR_SUBMISSION")])["id"] == "v2"
    assert images.version_problem(version(1, "PREPARE_FOR_SUBMISSION"), False) == (None, False)
    live, needs = images.version_problem(version(1, "LIVE"), False)
    assert "--new-version" in live and not needs
    assert images.version_problem(version(1, "LIVE"), True) == (None, True)
    assert "IN_REVIEW" in images.version_problem(version(3, "IN_REVIEW"), True)[0]


class Live(asc.Client):
    """A real client (so the dry run is the client's) whose reads come from `LIVE_GETS`, never the network."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(asc.Credentials("K", "I"), **kwargs)

    def _get(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        path = url.removeprefix(asc.BASE_URL)
        if path not in LIVE_GETS:
            raise asc.ASCError(f"GET {path} → HTTP 404", status=404)
        return {"data": LIVE_GETS[path]}

    def _write(self, verb: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if not self.dry_run:
            pytest.fail(f"a real {verb.upper()} {url}")
        return super()._write(verb, url, **kwargs)


def rec(id_: str, vendor_id: str) -> dict[str, Any]:
    return {"id": id_, "attributes": {"vendorIdentifier": vendor_id}}


def version(id_: str, n: int, state: str) -> dict[str, Any]:
    return {"id": id_, "attributes": {"version": n, "state": state}}


def asset(id_: str) -> dict[str, Any]:
    return {"id": id_, "attributes": {"imageAsset": {"templateUrl": f"https://cdn/{id_}/{{w}}x{{h}}bb.{{f}}",
                                                     "width": 8, "height": 8}}}


GROUP = "/v1/gameCenterGroups/G"
LIVE_GETS = {
    "/v1/apps": [{"id": "1", "attributes": {"bundleId": "com.example.app"}}],
    "/v1/apps/1/gameCenterDetail": {"id": "D"},
    "/v1/gameCenterDetails/D/gameCenterGroup": {"id": "G", "attributes": {"referenceName": "game"}},
    f"{GROUP}/gameCenterAchievementsV2": [rec("A", ACH)],
    f"{GROUP}/gameCenterLeaderboardsV2": [rec("L", LB)],
    f"{GROUP}/gameCenterActivities": [],  # not synced yet
    "/v2/gameCenterAchievements/A/versions": [version("AV", 1, "LIVE")],
    "/v2/gameCenterAchievementVersions/AV/localizations": [{"id": "AL", "attributes": {"locale": "en-US"}}],
    "/v2/gameCenterAchievementLocalizations/AL/image": asset("old"),
    "/v2/gameCenterLeaderboards/L/versions": [version("LV1", 1, "LIVE"), version("LV2", 2, "PREPARE_FOR_SUBMISSION")],
    "/v2/gameCenterLeaderboardVersions/LV2/localizations": [{"id": "LL", "attributes": {"locale": "de-DE"}}],
}


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The example bundle in an app repo, against LIVE_GETS: the live achievement image differs."""
    make_bundle(tmp_path / "App" / "G.gamekit")
    make_app(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(asc, "Client", Live)
    monkeypatch.setattr(asc.Credentials, "available", staticmethod(lambda: True))
    monkeypatch.setattr(images, "fetch_image_asset", lambda attrs: PILImage.new("RGB", (1024, 1024), "black"))
    return tmp_path


def by_label(targets: list[images.Target]) -> dict[str, images.Target]:
    return {t.image.label: t for t in targets}


def test_plan_reads_the_group_and_the_newest_version(live: Path) -> None:
    app = make_app(live)
    found = images.local_images(app)
    targets, holder = images.plan(Live(), app.config, found, allow_new_version=False)
    plan = by_label(targets)
    assert holder == "Game Center group 'game'"
    assert plan[f"achievement {ACH} [en-US]"].status == "skip"
    assert "changed, not uploaded: version 1 is LIVE" in plan[f"achievement {ACH} [en-US]"].reason
    assert plan[f"leaderboard {LB} [de-DE]"].status == "new"
    assert plan[f"leaderboard {LB} [de-DE]"].version["id"] == "LV2"
    assert plan[f"activity {ACT}"].status == "skip"
    assert "no such activity on App Store Connect yet" in plan[f"activity {ACT}"].reason

    targets, _ = images.plan(Live(), app.config, found, allow_new_version=True)
    achievement = by_label(targets)[f"achievement {ACH} [en-US]"]
    assert (achievement.status, achievement.new_version) == ("changed", True)


def test_unchanged_pixels_are_left_alone(live: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images, "fetch_image_asset", lambda attrs: PILImage.new("RGB", (1024, 1024), "white"))
    app = make_app(live)
    targets, _ = images.plan(Live(), app.config, images.local_images(app), allow_new_version=True)
    assert by_label(targets)[f"achievement {ACH} [en-US]"].status == "unchanged"


def test_a_dry_run_plans_every_write_and_sends_none(live: Path, capsys: pytest.CaptureFixture) -> None:
    images.cmd_push(SimpleNamespace(app=None, dry_run=True, yes=False, new_version=True))
    out = capsys.readouterr().out
    assert "would POST /v2/gameCenterAchievementVersions  achievement→A" in out
    assert "would POST /v2/gameCenterLeaderboardImages" in out and "localization→LL" in out
    assert "would PATCH /v2/gameCenterLeaderboardImages/planned-2  uploaded=True" in out
    assert "nothing was written" in out and "✓ " not in out


def test_a_push_without_a_terminal_needs_yes(live: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit, match="pass --yes"):
        images.cmd_push(SimpleNamespace(app=None, dry_run=False, yes=False, new_version=False))


def test_a_replacement_deletes_then_uploads_and_shouts_if_the_upload_fails(
        live: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    calls: list[str] = []
    app = make_app(live)
    targets, _ = images.plan(Live(), app.config, images.local_images(app), allow_new_version=False)
    target = by_label(targets)[f"leaderboard {LB} [de-DE]"]
    target.live = {"id": "old"}
    client = SimpleNamespace(dry_run=False, report=print, delete=lambda path: calls.append(f"DELETE {path}"))

    def upload(*args: Any, **kwargs: Any) -> str:
        calls.append(f"UPLOAD api={kwargs['api']} checksum={kwargs['checksum']}")
        raise asc.ASCError("boom")

    monkeypatch.setattr(images, "upload_asset_resource", upload)
    with pytest.raises(asc.ASCError):
        images.push_one(client, target)  # type: ignore[arg-type]
    assert calls == ["DELETE /v2/gameCenterLeaderboardImages/old", "UPLOAD api=v2 checksum=False"]
    assert "old image was DELETED and the upload FAILED" in capsys.readouterr().out
