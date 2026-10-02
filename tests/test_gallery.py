"""`snakelane gallery` builds a review page from the metadata tree. Offline: the live comparison
is fed App Store Connect-shaped data, and git runs against a throwaway repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from snakelane import project
from snakelane.screenshots import gallery

from .helpers import image, make_app, write


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    app = make_app(tmp_path, locales=["en-US", "en-AU"])
    write(app, "default", "name", "Example <App>")
    write(app, "default", "subtitle", "Plan your week")
    write(app, "default", "description", "Line one.\nLine two.\nLine three.\nLine four.")
    write(app, "default", "promotional_text", "Now with widgets")
    deck = app.folder / "ios" / "screenshots" / "en-US" / "iphone"
    for n in range(1, 12):
        image(deck / f"ss-{n:02}.jpg", 1284, 2778)
    image(deck / "_ss-99.jpg", 1284, 2778)
    return app


def test_page_lists_decks_inheritance_limits_and_listing(app: project.App) -> None:
    page = gallery.build(app)
    assert "Example &lt;App&gt;" in page, "listing text is escaped"
    assert "ss-01.jpg" in page and "_ss-99.jpg" not in page, "excluded shots are not shown"
    assert "11 shots, over the limit of 10" in page
    assert "no deck — shows en-US&#x27;s" in page
    assert page.count(">Search result<") == 2 and page.count(">Product page<") == 2
    assert "Now with widgets" in page and "Line four." in page
    assert "placeholder" in page, "no icon in this repo, so a lettered placeholder"
    assert "en-US · primary" in page


def test_review_panel_shows_lint_and_translations(app: project.App) -> None:
    write(app, "default", "keywords", "plan, week")
    write(app, "en-AU", "subtitle", "Plan your fortnight")
    page = gallery.build(app)
    assert "keyword-format" in page
    assert "subtitle: untracked" in page


def test_primary_locale_and_unlisted_decks(app: project.App) -> None:
    app.config["primary_locale"] = "en-AU"
    image(app.folder / "ios" / "screenshots" / "ja" / "ss-01.jpg", 1284, 2778)
    page = gallery.build(app)
    assert "en-AU · primary" in page
    assert "Not in snakelane.yml — never pushed" in page and 'href="#unlisted"' in page


def test_bundle_copies_images_and_links_relatively(app: project.App, tmp_path: Path) -> None:
    bundle = tmp_path / "out"
    page = gallery.build(app, assets=gallery.Assets(bundle))
    assert "file://" not in page
    copied = list((bundle / "img").glob("*-ss-01.jpg"))
    assert len(copied) == 1 and f'src="img/{copied[0].name}"' in page


def test_icon_from_config(app: project.App) -> None:
    icon = app.root / "icon.png"
    image(icon, 1024, 1024)
    app.config["gallery"] = {"icon": "icon.png"}
    assert gallery.find_icon(app) == icon
    assert icon.as_uri() in gallery.build(app)


def test_live_comparison_matches_by_type_order_and_upload_checksum(app: project.App) -> None:
    deck = gallery.local_decks(app, "en-US")[0]
    shots = deck.shots
    remote = [
        {"fileName": "ss-01.jpg", "sourceFileChecksum": gallery.upload_checksum(shots[0].path),
         "imageAsset": {"templateUrl": "https://cdn/x/{w}x{h}bb.{f}", "width": 1284, "height": 2778}},
        {"fileName": "ss-02.jpg", "sourceFileChecksum": "0" * 32,
         "imageAsset": {"templateUrl": "https://cdn/y/{w}x{h}bb.{f}", "width": 1284, "height": 2778}},
    ]
    gallery.compare_live([deck], {"APP_IPHONE_65": remote}, "ios")
    assert [s.status for s in shots[:3]] == ["unchanged", "changed", "new"]
    assert shots[1].before == "https://cdn/y/400x865bb.jpg"


def test_live_comparison_reports_what_the_push_would_delete(app: project.App) -> None:
    deck = gallery.local_decks(app, "en-US")[0]
    remote = [{"fileName": f"old-{n}.jpg", "sourceFileChecksum": "x", "imageAsset": {}} for n in range(12)]
    gallery.compare_live([deck], {"APP_IPHONE_65": remote}, "ios")
    assert [label for label, _ in deck.removed] == ["old-11.jpg (APP_IPHONE_65)"]


def test_git_comparison(app: project.App) -> None:
    run = lambda *a: subprocess.run(["git", "-C", str(app.root), *a], check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "deck")
    folder = app.folder / "ios" / "screenshots" / "en-US" / "iphone"
    image(folder / "ss-02.jpg", 1320, 2868)       # changed
    (folder / "ss-11.jpg").unlink()              # removed
    image(folder / "ss-12.jpg", 1284, 2778)       # new
    page = gallery.build(app, compare_git_head=True)
    assert "compared with git HEAD" in page
    for status in ("changed", "new", "removed", "unchanged"):
        assert f'<span class="badge {status}">' in page


def test_empty_deck_folder_is_shown_as_a_deletion(app: project.App) -> None:
    (app.folder / "ios" / "screenshots" / "en-AU").mkdir()
    page = gallery.build(app)
    assert "empty folder: the push deletes this locale's live screenshots" in page
