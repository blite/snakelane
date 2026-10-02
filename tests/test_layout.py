"""The metadata layout: one shared listing, platform folders for what differs."""

from __future__ import annotations

from pathlib import Path

import pytest

from snakelane import project
from snakelane.listing import fields
from snakelane.screenshots import media

from .helpers import image, make_app, write


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return make_app(tmp_path, locales=["en-US", "de-DE"], platforms=["ios", "macos"])


def test_text_resolves_most_specific_first(app: project.App) -> None:
    write(app, "default", "description", "Shared.")
    write(app, "de-DE", "description", "Geteilt.")
    write(app, "default", "description", "Mac.", platform="macos")
    write(app, "de-DE", "description", "Mac auf Deutsch.", platform="macos")
    ios, mac = app.folder / "ios", app.folder / "macos"
    assert fields.read_field(ios, "en-US", "description") == "Shared."
    assert fields.read_field(ios, "de-DE", "description") == "Geteilt."
    assert fields.read_field(mac, "en-US", "description") == "Mac."
    assert fields.read_field(mac, "de-DE", "description") == "Mac auf Deutsch."


def test_app_level_fields_cannot_differ_by_platform(app: project.App) -> None:
    write(app, "default", "name", "Trailhead")
    assert fields.read_field(app.folder / "macos", "en-US", "name") == "Trailhead"
    write(app, "default", "name", "Trailhead for Mac", platform="macos")
    with pytest.raises(SystemExit, match="same on every platform"):
        fields.read_field(app.folder / "macos", "en-US", "name")


def test_copyright_and_review_fall_back_to_the_shared_copy(app: project.App) -> None:
    (app.folder / "copyright.txt").write_text("2026 Example")
    (app.folder / "review").mkdir()
    (app.folder / "review" / "email_address.txt").write_text("review@example.com")
    (app.folder / "review" / "notes.txt").write_text("Shared notes.")
    (app.folder / "macos" / "review").mkdir(parents=True)
    (app.folder / "macos" / "review" / "notes.txt").write_text("Mac notes.")
    assert fields.read_copyright(app.folder / "ios") == "2026 Example"
    review = fields.read_review(app.folder / "macos")
    assert review["notes"] == "Mac notes." and review["email_address"] == "review@example.com"


def test_a_deck_is_the_locale_folder_and_its_device_folders(app: project.App) -> None:
    ios = app.folder / "ios"
    assert media.deck_dirs(ios, "en-US") == []  # no folder: no opinion
    image(ios / "screenshots" / "en-US" / "iphone" / "ss-01.jpg", 1284, 2778)
    image(ios / "screenshots" / "en-US" / "ipad" / "ss-01.jpg", 2064, 2752)
    dirs = media.deck_dirs(ios, "en-US")
    assert [d.name for d in dirs] == ["en-US", "ipad", "iphone"]
    files = media.deck_files(dirs, media.IMAGE_SUFFIXES, "screenshot", quiet=True)
    assert sorted(media.display_type_for(f) for f in files) == ["APP_IPAD_PRO_3GEN_129", "APP_IPHONE_65"]


def test_raw_captures_live_outside_metadata(app: project.App) -> None:
    tree = project.DeckTree(app, "ios", "iphone")
    assert app.folder not in tree.raw("en-US").parents
    assert tree.raw("en-US") == app.root / ".snakelane" / app.slug / "raw" / "ios" / "en-US" / "iphone"
