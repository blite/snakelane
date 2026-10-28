"""What a deck is made of: image/video sizes, the App Store slot each fills, and which files count."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def _both_ways(sizes: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Portrait and landscape."""
    return [size for w, h in sizes for size in ((w, h), (h, w))]


# The pixels alone decide the slot, never a config key; ASC's media page is the arbiter.
# Why: docs/design/screenshots.md#the-display-type-table
# Each iOS slot, the display App Store Connect names it by (the gallery's label), and its sizes.
IOS_SLOTS = [
    # Apple's one required iPhone class ("Dynamic Island, medium display"): 15 / 16 / 15 Pro, then 16 Pro / 17 / 17 Pro.
    ("APP_IPHONE_61", '6.3"', [(1179, 2556), (1206, 2622)]),
    ("APP_IPHONE_65", '6.5"', [(1242, 2688), (1284, 2778)]),  # 11 Pro Max / XS Max, 14 Plus / 13 Pro Max
    # Plus the physically 6.5" iPhone Air (1260x2736), which files here.
    ("APP_IPHONE_67", '6.9"', [(1260, 2736), (1290, 2796), (1320, 2868)]),
    # iPhone Duo, outer (closed) and inner (open) display. Not in Apple's OpenAPI (4.5.1, 2026-10);
    # App-Store-Connect-CLI#2926 created the set and uploaded the outer size. Required from April 2027
    # for apps built with the iOS 27.1 SDK.
    ("APP_IPHONE_DUO", "Duo", [(1398, 2034), (2007, 2853)]),
    ("APP_IPAD_PRO_3GEN_129", '13"', [(2064, 2752)]),  # required
    ("APP_IPAD_PRO_3GEN_129", '12.9"', [(2048, 2732)]),  # legacy, same slot
]
SCREEN_SIZES = {size: inches for _, inches, sizes in IOS_SLOTS for size in _both_ways(sizes)}
SCREENSHOT_DISPLAY_TYPES = {
    **{size: slot for slot, _, sizes in IOS_SLOTS for size in _both_ways(sizes)},
    **{size: "APP_DESKTOP" for size in [(1280, 800), (1440, 900), (2560, 1600), (2880, 1800)]},  # 16:10 only
}

# The sizes snakelane shoots by default; any other accepted size uploads with a warning.
# Why: docs/design/screenshots.md#non-default-sizes-are-a-warning
DISPLAY_TYPE_FAMILY = {"APP_IPHONE_61": "iPhone", "APP_IPHONE_65": "iPhone", "APP_IPHONE_67": "iPhone",
                       "APP_IPHONE_DUO": "iPhone Duo",
                       "APP_IPAD_PRO_3GEN_129": "iPad", "APP_DESKTOP": "Mac"}
PREFERRED_SIZES = {  # family -> (label, sizes, advice)
    "iPhone": ('6.3"', {d for d, t in SCREENSHOT_DISPLAY_TYPES.items() if t == "APP_IPHONE_61"},
               'ASC will show the 6.3" slot, the one it requires, dimmed; re-shoot on iPhone 17 Pro'),
    "iPad": ('13"', {(2064, 2752), (2752, 2064)}, '12.9" is the legacy size; re-shoot on iPad Pro 13-inch (M5)'),
}

# Accepted App Preview sizes per slot, a local pre-check of Apple's app-preview-specifications page.
# Keys are previewType values (no APP_ prefix: ASC 409s on it). 886x1920 fits every iPhone slot,
# so the slot comes from the shots beside a video, not this table.
# Why: docs/design/screenshots.md#an-app-previews-slot-comes-from-the-screenshots-beside-it
ACCEPTED_PREVIEW_SIZES = {
    "IPHONE_61": {(886, 1920), (1920, 886)},
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


@dataclass
class Track:
    handler: bytes = b""                    # b"vide" / b"soun"
    dimensions: tuple[int, int] = (0, 0)    # tkhd's display size; zero on an audio track
    seconds: float = 0.0                    # mdhd duration / timescale
    samples: int = 0                        # stts: frames, for a video track
    codec: bytes = b""                      # the first stsd entry's format, e.g. b"avc1", b"mp4a"
    channels: int = 0
    sample_rate: int = 0

    @property
    def fps(self) -> float:
        return self.samples / self.seconds if self.seconds else 0.0


@dataclass
class Movie:
    """What App Store Connect checks about an App Preview, read from the file's own boxes."""

    video: Track
    audio: Track | None
    seconds: float

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.video.dimensions


def read_movie(path: Path) -> Movie:
    """Size, length, frame rate and audio format from the `moov` box, without ffprobe.

    Why hand-rolled: docs/design/screenshots.md#video-dimensions-are-read-without-ffprobe"""
    data = path.read_bytes()
    u32 = lambda at: int.from_bytes(data[at:at + 4], "big")  # noqa: E731
    u64 = lambda at: int.from_bytes(data[at:at + 8], "big")  # noqa: E731
    tracks: list[Track] = []
    movie_seconds = 0.0

    def boxes(offset: int, end: int):
        while offset + 8 <= end:
            size, kind, body = u32(offset), data[offset + 4:offset + 8], offset + 8
            if size == 0:
                size = end - offset
            elif size == 1:  # 64-bit `largesize` follows the header
                size, body = u64(offset + 8), offset + 16
            if size < 8 or offset + size > end:
                return
            yield kind, body, offset + size
            offset += size

    def scaled(body: int) -> float:
        """mvhd/mdhd: a timescale and a duration, 32-bit in version 0 and 64-bit in version 1."""
        if data[body] == 0:
            return u32(body + 16) / (u32(body + 12) or 1)
        return u64(body + 24) / (u32(body + 20) or 1)

    def walk(offset: int, end: int, track: Track | None) -> None:
        nonlocal movie_seconds
        for kind, body, box_end in boxes(offset, end):
            if kind == b"mvhd":
                movie_seconds = scaled(body)
            elif kind == b"trak":
                tracks.append(track := Track())
                walk(body, box_end, track)
            elif kind in (b"mdia", b"minf", b"stbl") and track is not None:
                walk(body, box_end, track)
            elif track is None:
                if kind == b"moov":
                    walk(body, box_end, None)
            elif kind == b"tkhd":
                # Version 1 widens creation/modification/duration to 64 bits: 12 more bytes.
                matrix_end = body + (32 if data[body] == 0 else 44) + 8 + 36
                if matrix_end + 8 <= box_end:
                    track.dimensions = (round(u32(matrix_end) / 65536), round(u32(matrix_end + 4) / 65536))
            elif kind == b"hdlr" and not track.handler:  # a QuickTime minf holds a second, the data handler's
                track.handler = data[body + 8:body + 12]
            elif kind == b"mdhd":
                track.seconds = scaled(body)
            elif kind == b"stts":
                track.samples = sum(u32(body + 8 + 8 * i) for i in range(u32(body + 4)))
            elif kind == b"stsd" and u32(body + 4):
                entry = body + 8
                track.codec = data[entry + 4:entry + 8]
                if track.handler == b"soun":  # AudioSampleEntry: 8 reserved bytes, then the version 0 fields
                    track.channels = int.from_bytes(data[entry + 24:entry + 26], "big")
                    track.sample_rate = u32(entry + 32) >> 16

    walk(0, len(data), None)
    video = next((t for t in tracks if t.handler == b"vide" and all(t.dimensions)), None)
    if video is None:
        raise ValueError(f"{path} has no readable video track")
    return Movie(video, next((t for t in tracks if t.handler == b"soun"), None), movie_seconds or video.seconds)


def read_mp4_dimensions(path: Path) -> tuple[int, int]:
    """Display size of the first video track."""
    return read_movie(path).dimensions


# Apple's App Preview specification, checked here because its ingest rejects a file minutes after a
# "successful" upload, visible only in the web UI.
# Why: docs/design/screenshots.md#a-preview-is-checked-before-it-uploads
PREVIEW_SECONDS = (15.0, 30.0)
PREVIEW_MAX_FPS = 30.0
PREVIEW_AUDIO_RATES = (44100, 48000)


def preview_problems(movie: Movie) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a file against Apple's preview specification, size apart (that is the slot's)."""
    errors, warnings = [], []
    low, high = PREVIEW_SECONDS
    # A clip trimmed to exactly 30 s can come out a frame long; Apple's own check rounds.
    if not low <= round(movie.seconds, 1) <= high:
        errors.append(f"{movie.seconds:.1f}s long; Apple takes {low:.0f}–{high:.0f}s")
    if (fps := movie.video.fps) > PREVIEW_MAX_FPS + 0.05:
        errors.append(f"{fps:.1f} fps; Apple's ceiling is {PREVIEW_MAX_FPS:.0f}")
    if (audio := movie.audio) is None:
        warnings.append("no audio track; Apple has rejected silent previews as \"unsupported or corrupted "
                        "audio\", so a silent stereo track is the safe default")
    elif audio.codec != b"mp4a" or audio.channels != 2 or audio.sample_rate not in PREVIEW_AUDIO_RATES:
        errors.append(f"audio is {audio.codec.decode(errors='replace')} {audio.channels}ch {audio.sample_rate} Hz; "
                      "Apple takes stereo AAC at 44.1 or 48 kHz")
    return errors, warnings


def preview_type_for(path: Path, deck: Path) -> str:
    """A video's App Preview slot, read off the screenshots beside it, then its size checked against it.

    Why: docs/design/screenshots.md#an-app-previews-slot-comes-from-the-screenshots-beside-it"""
    if not (shots := deck_files([deck], DECK_SUFFIXES, "screenshot", quiet=True)):
        raise SystemExit(
            f"{path.name} has no screenshots beside it in {deck}, so there is nothing to tell which iPhone slot "
            "a preview fills — Apple accepts 886x1920 for every one. Shoot the deck first, or upload this preview "
            "by hand."
        )
    display_type = display_type_for(shots[0])
    preview_type = display_type.removeprefix("APP_")
    if (accepted := ACCEPTED_PREVIEW_SIZES.get(preview_type)) is None:
        raise SystemExit(
            f"{path.name} sits in a {display_type} deck, which has no App Preview slot in ACCEPTED_PREVIEW_SIZES. "
            "Add it, checking Apple's app preview specifications for the accepted resolutions."
        )
    movie = read_movie(path)
    errors, warnings = preview_problems(movie)
    if (dimensions := movie.dimensions) not in accepted:
        errors.insert(0, f"{dimensions[0]}x{dimensions[1]}, which {preview_type} does not accept "
                         f"({', '.join(f'{w}x{h}' for w, h in sorted(accepted))})")
    for warning in warnings:
        print(f"  warning: {path.name}: {warning}")
    if errors:
        raise SystemExit(f"{path.name}: {'; '.join(errors)}. {reencode_hint()}")
    return preview_type


# --- the clip's sidecar ---------------------------------------------------------------------------
# `snakelane preview` writes ap-01.json beside ap-01.m4v: the poster frame it chose and the captions it
# drew. The push sends the poster; the gallery and the search-result check read the captions.

PREVIEW_FPS = 30  # what `snakelane preview` encodes at, and the frame rate of a poster time code
TIME_CODE = re.compile(r"(\d\d):([0-5]\d):([0-5]\d):(\d\d)")


def time_code(seconds: float, fps: int = PREVIEW_FPS) -> str:
    """`previewFrameTimeCode`'s HH:MM:SS:FF (Apple's examples: "00:00:05:00"), rounded to a frame."""
    frames = round(seconds * fps)
    whole, frame = divmod(frames, fps)
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}:{frame:02d}"


def time_code_seconds(code: str, fps: int = PREVIEW_FPS) -> float:
    if not (match := TIME_CODE.fullmatch(code)) or int(match[4]) >= fps:
        raise ValueError(f"{code!r} is not an HH:MM:SS:FF time code at {fps} fps")
    h, m, s, f = map(int, match.groups())
    return h * 3600 + m * 60 + s + f / fps


def preview_sidecar(clip: Path) -> Path:
    return clip.with_suffix(".json")


def preview_info(clip: Path) -> dict[str, Any]:
    """What `snakelane preview` recorded about `clip`: {} for a preview made some other way."""
    if not (path := preview_sidecar(clip)).is_file():
        return {}
    try:
        info = json.loads(path.read_text())
    except ValueError as error:
        raise SystemExit(f"{path}: not JSON ({error}); re-encode with `snakelane preview --encode-only`") from None
    return info if isinstance(info, dict) else {}


def poster_time_code(clip: Path, seconds: float | None = None) -> str | None:
    """The poster frame to send for `clip`, None for Apple's default; refused when it falls outside a
    clip of `seconds` (a sidecar left beside a clip encoded since)."""
    if not (poster := preview_info(clip).get("poster")):
        return None
    code = poster.get("time_code") if isinstance(poster, dict) else None
    try:
        at = time_code_seconds(str(code))
    except ValueError as error:
        raise SystemExit(f"{preview_sidecar(clip)}: poster {error}") from None
    if seconds is not None and at >= seconds:
        raise SystemExit(f"{preview_sidecar(clip)}: the poster is at {code}, past the end of the "
                         f"{seconds:.1f}s {clip.name}; re-encode with `snakelane preview --encode-only`")
    return code


def reencode_hint() -> str:
    try:
        root = project.find_root()
    except SystemExit:
        root = None
    script = next(iter(sorted(root.glob("[Ss]cripts/**/encode_app_preview.sh"))), None) if root else None
    if script:
        return f"Re-encode with {script.relative_to(root)}, or record it with `snakelane preview`."
    return ("Re-encode it with `snakelane preview --encode-only`, or see App Previews in the snakelane skill's "
            "references/gotchas.md.")


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
