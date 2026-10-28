"""Offline checks on how `store screenshots push` reads a deck."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane.screenshots import media

from .helpers import image


@pytest.mark.parametrize(
    "size", [(1260, 2736), (1290, 2796), (1320, 2868), (2796, 1290)],
)
def test_every_accepted_69_inch_size_maps(tmp_path: Path, size: tuple[int, int]) -> None:
    assert media.display_type_for(image(tmp_path / "ss-01.png", *size)) == "APP_IPHONE_67"


@pytest.mark.parametrize("size", [(1179, 2556), (1206, 2622), (2622, 1206)])
def test_every_accepted_63_inch_size_maps(tmp_path: Path, size: tuple[int, int]) -> None:
    assert media.display_type_for(image(tmp_path / "ss-01.png", *size)) == "APP_IPHONE_61"


@pytest.mark.parametrize("size", [(1398, 2034), (2034, 1398), (2007, 2853), (2853, 2007)])
def test_both_iphone_duo_displays_map_to_its_slot(tmp_path: Path, size: tuple[int, int]) -> None:
    assert media.display_type_for(image(tmp_path / "ss-01.png", *size)) == "APP_IPHONE_DUO"


def test_a_duo_size_is_not_a_size_warning() -> None:
    assert media.size_warnings([(1398, 2034), (2007, 2853)]) == []


@pytest.mark.parametrize("name, deck", [
    ("iPhone 17 Pro", "iphone"), ("iPad Pro 13-inch (M5)", "ipad"),
    ("iPhone Duo", "duo"), ("iPhone Duo — Play", "duo"),
])
def test_a_simulator_files_into_its_deck_by_name(name: str, deck: str) -> None:
    from snakelane.project import device_deck

    assert device_deck(name) == deck


def test_unknown_size_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="unknown screenshot pixel size"):
        media.display_type_for(image(tmp_path / "ss-01.png", 1668, 2420))


def test_sets_over_ten_are_reported_per_locale_and_type() -> None:
    shots = [Path(f"ss-{n:02}.jpg") for n in range(1, 12)]
    plan = {
        "en-US": {"APP_IPHONE_67": shots, "APP_IPAD_PRO_3GEN_129": shots[:10]},
        "ja": None,
    }
    [problem] = media.oversized_sets(plan)
    assert problem.startswith("en-US/APP_IPHONE_67: 11 screenshots (limit 10)")
    assert "ss-11.jpg" in problem
    assert media.oversized_sets({"en-US": {"APP_IPHONE_67": shots[:10]}}) == []


def test_default_sizes_raise_no_warning() -> None:
    assert media.size_warnings([(1206, 2622), (1179, 2556), (2064, 2752), (2880, 1800)]) == []


def test_other_accepted_sizes_warn_but_still_map(tmp_path: Path) -> None:
    files = [image(tmp_path / f"{n}.png", 1284, 2778) for n in range(3)]
    files.append(image(tmp_path / "ipad.png", 2048, 2732))
    warnings = media.size_warnings([media.screenshot_dimensions(f) for f in files])
    assert warnings == [
        '1 iPad screenshot(s) at 2048x2732, not the 13" snakelane defaults to'
        ' — 12.9" is the legacy size; re-shoot on iPad Pro 13-inch (M5)',
        '3 iPhone screenshot(s) at 1284x2778, not the 6.3" snakelane defaults to'
        ' — ASC will show the 6.3" slot, the one it requires, dimmed; re-shoot on iPhone 17 Pro',
    ]
    assert {media.display_type_for(f) for f in files} == {"APP_IPHONE_65", "APP_IPAD_PRO_3GEN_129"}


def test_a_rejected_screenshot_is_retried_into_its_own_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every locale has an ss-01.jpg: the retry must follow the resource id, not the name."""
    from snakelane.screenshots import upload

    from .fakes import FakeClient

    en, de = tmp_path / "en" / "ss-01.jpg", tmp_path / "de" / "ss-01.jpg"
    uploads = [
        {"id": "en-1", "path": en, "relationships": {"set": "EN"}, "label": "en-US/APP_IPHONE_65/ss-01.jpg"},
        {"id": "de-1", "path": de, "relationships": {"set": "DE"}, "label": "de-DE/APP_IPHONE_65/ss-01.jpg"},
    ]
    rounds = iter([([], [("en-US/APP_IPHONE_65/ss-01.jpg", "en-1", "IMAGE_TOO_LARGE")], []),
                   (["en-US/APP_IPHONE_65/ss-01.jpg"], [], [])])
    monkeypatch.setattr(upload, "wait_for_asset_processing", lambda client, kind, pending: next(rounds))
    reuploaded = []
    monkeypatch.setattr(upload, "upload_asset_resource",
                        lambda client, kind, path, rel: reuploaded.append((path, rel)) or "en-2")
    client = FakeClient()
    assert upload.verify_screenshot_processing(client, uploads)
    assert client.writes == [("DELETE", "/v1/appScreenshots/en-1", None)]
    assert reuploaded == [(en, {"set": "EN"})]


def test_unreadable_images_fail_clearly(tmp_path: Path) -> None:
    broken = tmp_path / "ss-01.png"
    broken.write_bytes(b"\x89PNG\r\n\x1a\ntruncated")
    with pytest.raises(ValueError, match="not an image"):
        media.screenshot_dimensions(broken)


def test_jpeg_dimensions(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "ss-01.jpg"
    Image.new("RGB", (1284, 2778), "white").save(path, "JPEG")
    assert media.screenshot_dimensions(path) == (1284, 2778)


def test_extraction_files_attachments_as_rgb_jpegs(tmp_path: Path) -> None:
    import json

    from PIL import Image

    from snakelane.screenshots import extract

    attachments = tmp_path / "attachments"
    attachments.mkdir()
    uuid = "0123ABCD-0000-0000-0000-000000000000"
    manifest = []
    for name, file in (("01-Home", "a.png"), ("01-Home_framed", "b.png"), ("Screenshot", "c.png")):
        Image.new("RGBA", (1284, 2778), (20, 40, 60, 255)).save(attachments / file)
        manifest.append({"attachments": [{"suggestedHumanReadableName": f"{name}_0_{uuid}.png",
                                          "exportedFileName": file}]})
    (attachments / "manifest.json").write_text(json.dumps(manifest))
    dirs = {"raw": tmp_path / "raw", "framed": tmp_path / "framed"}
    stats = extract.stage(attachments, dirs)
    assert stats == {"raw": 1, "framed": 1, "unknown": 1}
    with Image.open(dirs["framed"] / "ss-01.jpg") as image:
        assert image.format == "JPEG" and image.mode == "RGB" and image.size == (1284, 2778)


def test_a_retried_shot_keeps_the_passing_attempt(tmp_path: Path) -> None:
    import json

    from PIL import Image

    from snakelane.screenshots import extract

    attachments = tmp_path / "attachments"
    attachments.mkdir()
    manifest = []
    # The passing retry is listed first; the hung first attempt's capture is older.
    for file, colour, when in (("retry.png", (0, 200, 0, 255), 200.0), ("hung.png", (200, 0, 0, 255), 100.0)):
        Image.new("RGBA", (1206, 2622), colour).save(attachments / file)
        manifest.append({"attachments": [{"suggestedHumanReadableName":
                                          f"01-Home_0_0123ABCD-0000-0000-0000-00000000000{len(manifest)}.png",
                                          "exportedFileName": file, "timestamp": when}]})
    (attachments / "manifest.json").write_text(json.dumps(manifest))
    dirs = {"raw": tmp_path / "raw", "framed": tmp_path / "framed"}
    for d in dirs.values():
        d.mkdir()
    assert extract.stage(attachments, dirs) == {"raw": 1, "framed": 0, "unknown": 0}
    with Image.open(dirs["raw"] / "ss-01.jpg") as image:
        assert image.getpixel((10, 10))[1] > 150


def test_a_png_in_a_deck_is_refused_not_skipped(tmp_path: Path) -> None:
    image(tmp_path / "ss-01.jpg", 1284, 2778)
    image(tmp_path / "_ss-02.png", 1284, 2778)  # excluded files may be anything
    media.refuse_png_in_deck([tmp_path])
    image(tmp_path / "ss-03.png", 1284, 2778)
    with pytest.raises(SystemExit, match="JPEG only"):
        media.refuse_png_in_deck([tmp_path])


@pytest.fixture
def media_run(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`store media push` with each kind's plan and push stubbed; returns the steps in the order they ran."""
    from snakelane.connect import asc
    from snakelane.screenshots import creative, upload

    steps: list[str] = []
    monkeypatch.setattr(upload, "media_app", lambda args, media: (Path("metadata"), {}, "ios"))
    deck = {"en-US": {"slot": [Path("file")]}}
    monkeypatch.setattr(upload, "screenshots_plan", lambda *a, **k: steps.append("plan screenshots") or deck)
    monkeypatch.setattr(upload, "previews_plan", lambda *a: steps.append("plan previews") or (deck, {}))
    monkeypatch.setattr(creative, "creative_plan", lambda *a: steps.append("plan creative") or {"en-US": {}})
    monkeypatch.setattr(creative, "check_plan", lambda *a: steps.append("check creative"))
    monkeypatch.setattr(upload, "push_screenshots", lambda *a: steps.append("push screenshots"))
    monkeypatch.setattr(upload, "push_previews", lambda *a: steps.append("push previews"))
    monkeypatch.setattr(creative, "push_creative", lambda *a: steps.append("push creative"))
    monkeypatch.setattr(asc.Credentials, "available", staticmethod(lambda: True))
    monkeypatch.setattr(asc, "Client", lambda dry_run=False: object())
    return steps


def run_media(only: list[str] | None = None) -> None:
    from types import SimpleNamespace

    from snakelane.screenshots import upload

    upload.cmd_media_push(SimpleNamespace(app=None, platform=None, only=only, dry_run=False,
                                          allow_developer_chrome=False))


def test_media_push_plans_and_checks_everything_before_the_first_write(media_run: list[str]) -> None:
    run_media()
    assert media_run == ["plan screenshots", "plan previews", "plan creative", "check creative",
                         "push screenshots", "push previews", "push creative"]


def test_media_push_only_runs_the_kinds_asked_for_in_push_order(media_run: list[str]) -> None:
    run_media(["creative", "previews"])
    assert media_run == ["plan previews", "plan creative", "check creative", "push previews", "push creative"]


def test_a_failed_media_push_names_what_was_not_pushed(media_run: list[str], monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture) -> None:
    from snakelane.screenshots import upload

    def fail(*args: object) -> None:
        raise SystemExit("Screenshots push finished WITH FAILURES — see above.")

    monkeypatch.setattr(upload, "push_screenshots", fail)
    with pytest.raises(SystemExit):
        run_media()
    assert "push previews" not in media_run
    assert "snakelane store media push --only previews --only creative" in capsys.readouterr().err


def test_a_default_media_push_leaves_a_kind_with_no_files_anywhere_alone(
        media_run: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from snakelane.screenshots import upload

    shots = {"en-US": {"APP_IPHONE_61": [Path("ss-01.jpg")]}, "de-DE": None}
    monkeypatch.setattr(upload, "screenshots_plan", lambda *a, **k: shots)
    monkeypatch.setattr(upload, "previews_plan", lambda *a: ({"en-US": {}, "de-DE": None}, {}))
    run_media()
    assert "push screenshots" in media_run and "push previews" not in media_run
    assert "no previews in any deck, so the live ones stay" in capsys.readouterr().out
    media_run.clear()
    run_media(["previews"])
    assert media_run == ["push previews"], "named, an empty deck is mirrored (and deletes what's live)"
