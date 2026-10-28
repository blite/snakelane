"""Where each kind of file lives in an app's metadata folder, in either of its two layouts.

Kind first (a `listing/` folder exists), since 2026-10-28:

    listing/default/<field>.txt              the primary locale's text, and review_notes.txt
    listing/locales/<locale>/<field>.txt     each translation
    listing/<platform>/default/, …/locales/  platform overrides, the same shape
    listing/copyright.txt                    one per version; listing/<platform>/copyright.txt overrides
    purchases/iap.yml                        the catalogue; review screenshots relative to purchases/
    screenshots/<platform>/<locale>/         the decks
    creative/[<platform>/]<locale|default>/  in-app event and product page art
    release/asset_packs.json                 the asset pack record

The review contact is snakelane.yml's `review.contact`, not files.

Flat, before it: `<locale>/` and `default/` at the top, `<platform>/screenshots/`, `<platform>/<locale>/`
overrides, `review/` and `<platform>/review/`, `iap.yml` with screenshots relative to the folder.
`snakelane migrate-layout` moves a flat folder to kind first.

Code passes a `platform_dir` (`<metadata>/<platform>`) as the handle for "this app, this platform"; in
the kind-first layout that folder need not exist, and these functions turn it into real paths.
Why: docs/design/foundations.md#metadata-is-sorted-by-kind
"""

from __future__ import annotations

from pathlib import Path

LISTING = "listing"
REVIEW_NOTES = "review_notes.txt"


def kind_first(folder: Path) -> bool:
    return (folder / LISTING).is_dir()


def split(platform_dir: Path) -> tuple[Path, str]:
    return platform_dir.parent, platform_dir.name


def locale_dir(base: Path, locale: str, kind: bool) -> Path:
    """`base/default`, or a locale's folder: `base/locales/<locale>` kind first, `base/<locale>` flat."""
    if locale == "default":
        return base / "default"
    return base / "locales" / locale if kind else base / locale


def listing_bases(platform_dir: Path) -> tuple[Path, Path, bool]:
    """(the platform's override base, the shared base, kind first?)."""
    folder, platform = split(platform_dir)
    kind = kind_first(folder)
    shared = folder / LISTING if kind else folder
    return shared / platform, shared, kind


def text_candidates(platform_dir: Path, locale: str, name: str) -> list[Path]:
    """<platform> <locale>, <platform> default, shared <locale>, shared default — most specific first."""
    own, shared, kind = listing_bases(platform_dir)
    return [locale_dir(own, locale, kind) / name, own / "default" / name,
            locale_dir(shared, locale, kind) / name, shared / "default" / name]


def copyright_candidates(platform_dir: Path) -> list[Path]:
    own, shared, _ = listing_bases(platform_dir)
    return [own / "copyright.txt", shared / "copyright.txt"]


def review_dirs(platform_dir: Path) -> list[Path]:
    """Flat only: `<platform>/review/` then `review/`."""
    return [platform_dir / "review", platform_dir.parent / "review"]


def review_notes_candidates(platform_dir: Path) -> list[Path]:
    """Kind first: the platform's default/review_notes.txt, then the shared one."""
    own, shared, _ = listing_bases(platform_dir)
    return [own / "default" / REVIEW_NOTES, shared / "default" / REVIEW_NOTES]


def stray_review_notes(platform_dir: Path) -> list[Path]:
    """review_notes.txt under a locale: App Store Connect keeps one note per version, not per language."""
    own, shared, _ = listing_bases(platform_dir)
    return sorted(p for base in (own, shared) for p in (base / "locales").glob(f"*/{REVIEW_NOTES}"))


def screenshots_dir(platform_dir: Path) -> Path:
    """The folder holding a platform's `<locale>/` decks."""
    folder, platform = split(platform_dir)
    return folder / "screenshots" / platform if kind_first(folder) else platform_dir / "screenshots"


def purchases_dir(platform_dir: Path) -> Path:
    """Where iap.yml lives, and what its review screenshot paths are relative to."""
    folder = platform_dir.parent
    return folder / "purchases" if kind_first(folder) else folder


def creative_candidates(platform_dir: Path, locale: str) -> list[Path]:
    folder, platform = split(platform_dir)
    if kind_first(folder):
        base = folder / "creative"
        return [base / platform / locale, base / platform / "default", base / locale, base / "default"]
    return [platform_dir / "creative" / locale, platform_dir / "creative" / "default",
            folder / "creative" / locale, folder / "creative" / "default"]


def asset_pack_record(folder: Path) -> str:
    """The record's default path, relative to the metadata folder."""
    return "release/asset_packs.json" if kind_first(folder) else "ios/asset_packs.json"


def translations_base(folder: Path) -> tuple[Path, bool]:
    """Where `default/` and the locales sit for translation tracking (shared listing only)."""
    kind = kind_first(folder)
    return (folder / LISTING if kind else folder), kind
