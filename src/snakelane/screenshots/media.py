"""What a deck is made of: image/video sizes, the App Store slot each fills, and which files count."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

from .. import project
from ..project import (  # noqa: F401  (the deck's users import them from here)
    DECK_SUFFIXES,
    IMAGE_SUFFIXES,
)

PREVIEW_SUFFIXES = (".m4v", ".mp4", ".mov")
JPEG_QUALITY = 90
# ASC's per-set limit, checked locally: Apple refusing the 11th file comes after the live set is deleted.
MAX_SCREENSHOTS_PER_SET = 10


def _both_ways(sizes: list[tuple[int, int]], display_type: str) -> dict[tuple[int, int], str]:
    return {size: display_type for w, h in sizes for size in ((w, h), (h, w))}


# The pixels alone decide the slot, never a config key; ASC's media page is the arbiter.
# Why: docs/design/screenshots.md#the-display-type-table
SCREENSHOT_DISPLAY_TYPES = {
    **_both_ways([(1242, 2688), (1284, 2778)], "APP_IPHONE_65"),  # 11 Pro Max / XS Max, 14 Plus / 13 Pro Max
    # 6.9", plus the physically 6.5" iPhone Air (1260x2736), which files here.
    **_both_ways([(1260, 2736), (1290, 2796), (1320, 2868)], "APP_IPHONE_67"),
    **_both_ways([(2064, 2752), (2048, 2732)], "APP_IPAD_PRO_3GEN_129"),  # 13" (required), legacy 12.9"
    **{size: "APP_DESKTOP" for size in [(1280, 800), (1440, 900), (2560, 1600), (2880, 1800)]},  # 16:10 only
}

# The sizes snakelane shoots by default; any other accepted size uploads with a warning.
# Why: docs/design/screenshots.md#non-default-sizes-are-a-warning
DISPLAY_TYPE_FAMILY = {"APP_IPHONE_65": "iPhone", "APP_IPHONE_67": "iPhone",
                       "APP_IPAD_PRO_3GEN_129": "iPad", "APP_DESKTOP": "Mac"}
PREFERRED_SIZES = {  # family -> (label, sizes, advice)
    "iPhone": ('6.5"', {d for d, t in SCREENSHOT_DISPLAY_TYPES.items() if t == "APP_IPHONE_65"},
               'ASC will show the 6.5" slot dimmed'),
    "iPad": ('13"', {(2064, 2752), (2752, 2064)}, '12.9" is the legacy size; re-shoot on iPad Pro 13-inch (M5)'),
}

# Accepted App Preview sizes per slot, a local pre-check of Apple's app-preview-specifications page.
# Keys are previewType values (no APP_ prefix: ASC 409s on it). 886x1920 fits both iPhone slots,
# so the slot comes from the shots beside a video, not this table.
# Why: docs/design/screenshots.md#an-app-previews-slot-comes-from-the-screenshots-beside-it
ACCEPTED_PREVIEW_SIZES = {
    "IPHONE_65": {(886, 1920), (1920, 886)},
    "IPHONE_67": {(886, 1920), (1920, 886)},
    "IPAD_PRO_3GEN_129": {(1200, 1600), (1600, 1200)},  # not 900x1200: that is the 2nd-gen 12.9"'s
}


def size_advice(dimensions: tuple[int, int]) -> str | None:
    """Why an accepted size isn't the default one, or None when it is (or has no default)."""
    preferred = PREFERRED_SIZES.get(DISPLAY_TYPE_FAMILY.get(SCREENSHOT_DISPLAY_TYPES.get(dimensions, ""), ""))
    return None if preferred is None or dimensions in preferred[1] else preferred[2]


def size_warnings(dimensions: list[tuple[int, int]]) -> list[str]:
    """One line per non-default size in a deck, with its count. Advice: the push goes ahead."""
    counts = Counter(d for d in dimensions if size_advice(d))
    found = sorted(((DISPLAY_TYPE_FAMILY[SCREENSHOT_DISPLAY_TYPES[d]], d), n) for d, n in counts.items())
    return [f"{n} {family} screenshot(s) at {w}x{h}, not the {PREFERRED_SIZES[family][0]} snakelane defaults to "
            f"— {PREFERRED_SIZES[family][2]}" for (family, (w, h)), n in found]


def oversized_sets(plan: dict[str, dict[str, list[Path]] | None]) -> list[str]:
    return [
        f"{locale}/{display_type}: {len(files)} screenshots (limit {MAX_SCREENSHOTS_PER_SET}) — "
        + ", ".join(f.name for f in files[MAX_SCREENSHOTS_PER_SET:]) + " would not fit"
        for locale, by_type in plan.items() for display_type, files in (by_type or {}).items()
        if len(files) > MAX_SCREENSHOTS_PER_SET
    ]


def screenshot_dimensions(path: Path) -> tuple[int, int]:
    """(width, height) from the header, without decoding the pixels."""
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, SyntaxError) as error:  # UnidentifiedImageError is an OSError
        raise ValueError(f"{path}: not an image snakelane can read ({error})") from None


def save_jpeg(image: Image.Image, path: Path, quality: int = JPEG_QUALITY) -> None:
    """Every JPEG snakelane writes: RGB, no chroma subsampling so caption text stays sharp."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "JPEG", quality=quality, subsampling=0, optimize=True)


def refuse_png_in_deck(dirs: list[Path]) -> None:
    """Exit if a deck holds a PNG (ADR 0002): skipping it would delete it from the store."""
    if pngs := [p for d in dirs for p in d.iterdir() if p.suffix.lower() == ".png" and not p.name.startswith("_")]:
        raise SystemExit(
            "screenshot decks are JPEG only, and these are PNG:\n" + "".join(f"  {p}\n" for p in pngs)
            + "Re-run `snakelane frame` or `snakelane shoot`, which write JPEG, or convert them "
            "yourself (an alpha channel must be flattened: App Store Connect rejects it)."
        )


def display_type_for(path: Path, dimensions: tuple[int, int] | None = None) -> str:
    """The slot a screenshot fills; pass `dimensions` when they have already been read."""
    dimensions = dimensions or screenshot_dimensions(path)
    if (display_type := SCREENSHOT_DISPLAY_TYPES.get(dimensions)) is None:
        raise SystemExit(
            f"unknown screenshot pixel size {dimensions} for {path} — add it to SCREENSHOT_DISPLAY_TYPES in "
            "snakelane's screenshots/media.py if this is a new device class App Store Connect accepts (check "
            "the app's media page in ASC), or re-shoot on a device whose size is listed there"
        )
    return display_type


def read_mp4_dimensions(path: Path) -> tuple[int, int]:
    """Display size from the first video track's `moov > trak > tkhd` box (no ffprobe needed).

    Width and height are 16.16 fixed point; an audio track's are zero, which skips it."""

    def walk(data: bytes, offset: int, end: int) -> tuple[int, int] | None:
        while offset + 8 <= end:
            size, kind, body = int.from_bytes(data[offset:offset + 4], "big"), data[offset + 4:offset + 8], offset + 8
            if size == 0:
                size = end - offset
            elif size == 1:  # 64-bit `largesize` follows the header
                size = int.from_bytes(data[offset + 8:offset + 16], "big")
            if size < 8 or offset + size > end:
                return None
            if kind in (b"moov", b"trak", b"mdia"):
                if found := walk(data, body, offset + size):
                    return found
            elif kind == b"tkhd":
                # Version 1 widens creation/modification/duration to 64 bits: 12 more bytes.
                matrix_end = body + (32 if data[body] == 0 else 44) + 8 + 36
                if matrix_end + 8 > end:
                    return None
                width, height = (int.from_bytes(data[i:i + 4], "big") / 65536 for i in (matrix_end, matrix_end + 4))
                if width and height:
                    return round(width), round(height)
            offset += size
        return None

    data = path.read_bytes()
    if (dimensions := walk(data, 0, len(data))) is None:
        raise ValueError(f"{path} has no readable video track")
    return dimensions


def preview_type_for(path: Path, deck: Path) -> str:
    """A video's App Preview slot, read off the screenshots beside it, then its size checked against it.

    Why: docs/design/screenshots.md#an-app-previews-slot-comes-from-the-screenshots-beside-it"""
    if not (shots := deck_files([deck], DECK_SUFFIXES, "screenshot", quiet=True)):
        raise SystemExit(
            f"{path.name} has no screenshots beside it in {deck}, so there is nothing to tell a 6.5\" preview "
            "from a 6.9\" one — Apple accepts 886x1920 for both. Shoot the deck first, or upload this preview "
            "by hand."
        )
    display_type = display_type_for(shots[0])
    preview_type = display_type.removeprefix("APP_")
    if (accepted := ACCEPTED_PREVIEW_SIZES.get(preview_type)) is None:
        raise SystemExit(
            f"{path.name} sits in a {display_type} deck, which has no App Preview slot in ACCEPTED_PREVIEW_SIZES. "
            "Add it, checking Apple's app preview specifications for the accepted resolutions."
        )
    if (dimensions := read_mp4_dimensions(path)) not in accepted:
        try:
            root = project.find_root()
        except SystemExit:
            root = None
        script = next(iter(sorted(root.glob("[Ss]cripts/**/encode_app_preview.sh"))), None) if root else None
        hint = (f"Re-encode with {script.relative_to(root)}." if script else
                "Re-encode it first: see App Previews in the snakelane skill's references/gotchas.md.")
        raise SystemExit(f"{path.name} is {dimensions[0]}x{dimensions[1]}, which {preview_type} does not accept "
                         f"({', '.join(f'{w}x{h}' for w, h in sorted(accepted))}). {hint}")
    return preview_type


def deck_dirs(platform_dir: Path, locale: str) -> list[Path]:
    """`<platform>/screenshots/<locale>/` and its device folders (which only keep same-named shots apart).

    [] when the locale has no folder (no opinion); an empty folder means "delete what's live"."""
    root = platform_dir / "screenshots" / locale
    if not root.is_dir():
        return []
    return [root, *sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))]


def deck_files(dirs: list[Path], suffixes: tuple[str, ...], kind: str, quiet: bool = False) -> list[Path]:
    """Files with `suffixes` in `dirs`, name-sorted (the upload order ASC keeps), minus `_`-excluded ones.

    An excluded file is removed from ASC on the next push, so each skip is printed."""
    candidates = sorted((p for d in dirs for p in d.iterdir() if p.suffix.lower() in suffixes), key=lambda p: p.name)
    for skipped in (p for p in candidates if p.name.startswith("_") and not quiet):
        print(f"  (skipping {kind} {skipped.name} — leading underscore excludes it)")
    return [p for p in candidates if not p.name.startswith("_")]
