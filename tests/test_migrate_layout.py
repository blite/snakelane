"""`migrate-layout`: a flat metadata folder moved to the kind-first one reads back exactly as it did."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from snakelane import layout, migrate, project
from snakelane.listing import fields
from snakelane.purchases.catalogue import catalogue_path
from snakelane.screenshots import media

from .helpers import image, make_app, write

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
                          env=GIT_ENV).stdout


def flat_app(root: Path) -> project.App:
    """Every kind of file the flat layout holds, committed, with a gitignored deck."""
    app = make_app(root, locales=["en-US", "de-DE"], platforms=["ios", "macos"])
    write(app, "default", "description", "Shared.")
    write(app, "default", "name", "Trailhead")
    write(app, "de-DE", "description", "Geteilt.")
    write(app, "default", "description", "Mac.", platform="macos")
    write(app, "de-DE", "release_notes", "Mac auf Deutsch.", platform="macos")
    (app.folder / "copyright.txt").write_text("2026 Example")
    review = app.folder / "review"
    review.mkdir()
    for stem, value in (("first_name", "Ada"), ("last_name", "Lovelace"), ("email_address", "ada@example.com"),
                        ("phone_number", "+1 555 123 4567"), ("notes", "Shared notes.")):
        (review / f"{stem}.txt").write_text(value)
    (app.folder / "macos" / "review").mkdir(parents=True)
    (app.folder / "macos" / "review" / "notes.txt").write_text("Mac notes.")
    (app.folder / "iap.yml").write_text("products:\n  - product_id: com.example.vip\n"
                                        "    review_screenshot: iap/vip.jpg\n")
    image(app.folder / "iap" / "vip.jpg", 640, 920)
    (app.folder / "ios").mkdir(exist_ok=True)
    (app.folder / "ios" / "asset_packs.json").write_text("{}\n")
    (app.folder / "translations.json").write_text("{}\n")
    (app.folder / "README.md").write_text("notes\n")
    (root / ".gitignore").write_text("metadata/*/screenshots/\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "flat")
    image(app.folder / "ios" / "screenshots" / "en-US" / "iphone" / "ss-01.jpg", 1206, 2622)
    (app.folder / "ios" / "screenshots" / "de-DE").mkdir(parents=True)  # empty: "delete what's live"
    return app


def reads(app: project.App) -> dict[str, Any]:
    """Everything the commands read, by platform."""
    out: dict[str, Any] = {}
    for platform in ("ios", "macos"):
        pd = app.folder / platform
        out[platform] = {
            "listing": fields.read_listing(pd, app.locales),
            "copyright": fields.read_copyright(pd, app.config),
            "review": fields.read_review(pd, app.config),
            "decks": {loc: [str(p.relative_to(layout.screenshots_dir(pd))) for p in media.deck_dirs(pd, loc)]
                      for loc in app.locales},
        }
    out["catalogue"] = catalogue_path(app.folder / "ios").read_text().replace("iap/", "")
    out["shot"] = (layout.purchases_dir(app.folder / "ios") / ("iap/vip.jpg" if not layout.kind_first(app.folder)
                                                                else "vip.jpg")).is_file()
    out["record"] = (app.folder / layout.asset_pack_record(app.folder)).read_text()
    return out


def migrated(app: project.App) -> project.App:
    migrate.execute(app, migrate.build_plan(app))
    return project.resolve_app(None, root=app.root)


@pytest.fixture
def app(tmp_path: Path) -> project.App:
    return flat_app(tmp_path)


def test_everything_reads_back_the_same(app: project.App) -> None:
    before = reads(app)
    after_app = migrated(app)
    assert layout.kind_first(after_app.folder)
    assert reads(after_app) == before


def test_files_land_where_the_layout_says(app: project.App) -> None:
    folder = migrated(app).folder
    for rel in ("listing/default/description.txt", "listing/locales/de-DE/description.txt",
                "listing/macos/default/description.txt", "listing/macos/locales/de-DE/release_notes.txt",
                "listing/default/review_notes.txt", "listing/macos/default/review_notes.txt",
                "listing/translations.json", "purchases/iap.yml", "purchases/vip.jpg",
                "release/asset_packs.json", "screenshots/ios/en-US/iphone/ss-01.jpg", "README.md"):
        assert (folder / rel).is_file(), rel
    assert (folder / "screenshots/ios/de-DE").is_dir()  # the empty deck folder survives
    for gone in ("default", "de-DE", "review", "iap", "iap.yml", "ios", "macos", "copyright.txt"):
        assert not (folder / gone).exists(), gone


def test_tracked_files_move_as_renames_and_the_contact_goes_to_the_config(app: project.App) -> None:
    after = migrated(app)
    git(after.root, "add", "-A")
    status = git(after.root, "status", "--porcelain")
    assert "R  metadata/default/description.txt -> metadata/listing/default/description.txt" in status
    assert "D  metadata/review/first_name.txt" in status
    assert after.config["review"]["contact"] == {"first_name": "Ada", "last_name": "Lovelace",
                                                 "email": "ada@example.com", "phone": "+1 555 123 4567"}
    assert after.config["copyright"] == "2026 Example"
    assert "review_screenshot: vip.jpg" in (after.folder / "purchases/iap.yml").read_text()
    assert (after.root / ".gitignore").read_text() == "metadata/screenshots/\n"


def test_a_platform_contact_that_differs_stops_the_move(app: project.App) -> None:
    (app.folder / "macos" / "review" / "email_address.txt").write_text("mac@example.com")
    with pytest.raises(SystemExit, match="differs from the shared"):
        _run(app)
    assert (app.folder / "default").is_dir()


def _run(app: project.App) -> None:
    plan = migrate.build_plan(app)
    if plan.problems:
        raise SystemExit("\n".join(plan.problems))
    migrate.execute(app, plan)


def test_a_second_run_refuses(app: project.App) -> None:
    after = migrated(app)
    with pytest.raises(SystemExit, match="already has listing/"):
        migrate.build_plan(after)


def test_review_notes_under_a_locale_are_refused(app: project.App) -> None:
    after = migrated(app)
    stray = after.folder / "listing/locales/de-DE/review_notes.txt"
    stray.write_text("Notizen.")
    with pytest.raises(SystemExit, match="one review note per version"):
        fields.read_review(after.folder / "ios", after.config)


def test_an_app_level_field_override_names_the_shared_file(app: project.App) -> None:
    after = migrated(app)
    own = after.folder / "listing/macos/default/name.txt"
    own.write_text("Trailhead for Mac")
    with pytest.raises(SystemExit, match=r"listing/default/name\.txt"):
        fields.read_field(after.folder / "macos", "en-US", "name")


def test_the_config_contact_wins_over_flat_files(tmp_path: Path) -> None:
    app = make_app(tmp_path, review={"contact": {"email": "new@example.com"}})
    (app.folder / "review").mkdir()
    (app.folder / "review" / "email_address.txt").write_text("old@example.com")
    assert fields.read_review(app.folder / "ios", app.config)["email_address"] == "new@example.com"


def test_a_folder_moved_before_copyright_joined_the_config_moves_just_that(app: project.App) -> None:
    after = migrated(app)
    leftover = after.folder / "listing/copyright.txt"
    leftover.write_text("2026 Example")
    config = after.config_path.read_text()
    after.config_path.write_text(config.replace('copyright: "2026 Example"\n', ""))
    after = project.resolve_app(None, root=after.root)
    assert fields.read_copyright(after.folder / "ios", after.config) == "2026 Example"  # still read
    final = migrated(after)
    assert not leftover.exists()
    assert final.config["copyright"] == "2026 Example"
    assert fields.read_copyright(final.folder / "ios", final.config) == "2026 Example"


def test_copyright_in_both_the_config_and_a_shared_file_is_refused(app: project.App) -> None:
    after = migrated(app)
    (after.folder / "listing/copyright.txt").write_text("2025 Someone Else")
    with pytest.raises(SystemExit, match=r"also in snakelane\.yml"):
        fields.read_copyright(after.folder / "ios", after.config)


def test_a_platform_copyright_file_still_overrides_the_config(app: project.App) -> None:
    after = migrated(app)
    (after.folder / "listing/macos").mkdir(parents=True, exist_ok=True)
    (after.folder / "listing/macos/copyright.txt").write_text("2026 Example (Mac)")
    assert fields.read_copyright(after.folder / "macos", after.config) == "2026 Example (Mac)"
    assert fields.read_copyright(after.folder / "ios", after.config) == "2026 Example"


def test_a_short_folder_without_listing_text_is_not_a_locale(app: project.App) -> None:
    image(app.folder / "ppo" / "search-result.jpg", 1206, 2622)  # product page art, not a language
    plan = migrate.build_plan(app)
    assert app.folder / "ppo" in plan.left
    assert not any("ppo" in str(dst) for _, dst in plan.moves)


def test_an_asset_pack_record_named_in_the_config_follows_the_file(app: project.App) -> None:
    app.config_path.write_text(app.config_path.read_text() + "asset_packs:\n  record: ios/asset_packs.json  # kept\n")
    git(app.root, "commit", "-qam", "record")
    after = migrated(project.load_app(app.config_path))
    assert after.config["asset_packs"]["record"] == "release/asset_packs.json"
    assert "# kept" in after.config_path.read_text()
