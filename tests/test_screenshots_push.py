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
    assert media.size_warnings([(1284, 2778), (1242, 2688), (2064, 2752), (2880, 1800)]) == []


def test_other_accepted_sizes_warn_but_still_map(tmp_path: Path) -> None:
    files = [image(tmp_path / f"{n}.png", 1320, 2868) for n in range(3)]
    files.append(image(tmp_path / "ipad.png", 2048, 2732))
    warnings = media.size_warnings([media.screenshot_dimensions(f) for f in files])
    assert warnings == [
        '1 iPad screenshot(s) at 2048x2732, not the 13" snakelane defaults to'
        ' — 12.9" is the legacy size; re-shoot on iPad Pro 13-inch (M5)',
        '3 iPhone screenshot(s) at 1320x2868, not the 6.5" snakelane defaults to'
        ' — ASC will show the 6.5" slot dimmed',
    ]
    assert {media.display_type_for(f) for f in files} == {"APP_IPHONE_67", "APP_IPAD_PRO_3GEN_129"}


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


def test_a_png_in_a_deck_is_refused_not_skipped(tmp_path: Path) -> None:
    image(tmp_path / "ss-01.jpg", 1284, 2778)
    image(tmp_path / "_ss-02.png", 1284, 2778)  # excluded files may be anything
    media.refuse_png_in_deck([tmp_path])
    image(tmp_path / "ss-03.png", 1284, 2778)
    with pytest.raises(SystemExit, match="JPEG only"):
        media.refuse_png_in_deck([tmp_path])
