"""Refuse a screenshot that was shot from a developer build.

    snakelane check                          # every framed deck of the app
    snakelane check <file-or-directory>...
    snakelane check --quiet <paths>          # exit code only

Exit 0 clean, 1 developer chrome, 2 unreadable, 3 Vision (pyobjc, the `snakelane[check]` extra) missing:
then it refuses rather than passes. The push runs it first. By default it OCRs the bottom-right corner for
SpriteKit's DEBUG `nodes:<count>` / `<n> fps` HUD; why, and why such a shot is re-shot rather than cropped:
docs/design/screenshots.md#the-developer-chrome-check. An app with another tell sets snakelane.yml
"screenshots": {"check": {...}}:
    "patterns":     regexes, case-insensitive          default the HUD's
    "corner":       [width, height] bottom-right crop, fractions   default [0.45, 0.06]
    "upscale":      enlargement before OCR             default 3
    "custom_words": Vision's custom words              default ["nodes", "fps"]
    "advice":       printed when a shot fails          default re-shoot from a Release build
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer

from ..args import AppOption, command_app
from ..args import run as run_cli
from ..project import IMAGE_SUFFIXES, resolve_app

# `nodes:107` is the reliable half; Vision misreads `fps` over busy artwork. Both allow the space
# Vision inserts after the colon.
HUD_PATTERNS = (r"nodes\s*[:.]?\s*\d+", r"\d+(\.\d+)?\s*fps\b")

DEFAULT_ADVICE = (
    "These were shot from a DEBUG build, so they also carry any developer buttons and were laid out "
    "around them. Cropping does not fix that — re-shoot from a Release build (snakelane.yml's "
    "\"screenshots.scheme\" should name a scheme that builds Release); see metadata/SCREENSHOTS.md."
)

INSTALL_HINT = (
    "snakelane check needs macOS's Vision framework (pyobjc). Install the extra:\n"
    "    uv tool install --editable <snakelane checkout> "
    "--with pyobjc-framework-Vision --with pyobjc-framework-Quartz\n"
    "or depend on snakelane[check]."
)


def _patterns(sources) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in sources]


@dataclass
class Settings:
    patterns: list[re.Pattern] = field(default_factory=lambda: _patterns(HUD_PATTERNS))
    # Both load-bearing: a wider crop at 1x missed known-bad shots.
    # Why: docs/design/screenshots.md#it-reads-only-an-enlarged-corner
    corner: tuple[float, float] = (0.45, 0.06)
    upscale: int = 3
    custom_words: list[str] = field(default_factory=lambda: ["nodes", "fps"])
    advice: str = DEFAULT_ADVICE

    @classmethod
    def from_config(cls, cfg: dict[str, Any] | None) -> Settings:
        cfg = cfg or {}
        if unknown := set(cfg) - {"patterns", "corner", "upscale", "custom_words", "advice", "_comment"}:
            raise SystemExit(f'unknown key(s) in snakelane.yml "screenshots.check": {", ".join(sorted(unknown))}')
        def corner(value: Any) -> tuple[float, float]:
            w, h = value
            return float(w), float(h)

        convert = {"patterns": _patterns, "corner": corner, "upscale": int, "custom_words": list, "advice": str}
        return cls(**{key: convert[key](value) for key, value in cfg.items() if key in convert})


class UnreadableImage(RuntimeError):
    pass


def hud_text_in(path: Path, settings: Settings | None = None) -> list[str]:
    """The developer-chrome strings found in the corner of `path`."""
    settings = settings or Settings()
    try:  # imported here so `--help` works anywhere
        import Quartz
        import Vision
    except ImportError as exc:  # pragma: no cover - platform guard
        # 3, not 1 or 2: those mean "developer chrome found" and "unreadable file".
        print(f"{INSTALL_HINT}\n({exc})", file=sys.stderr)
        raise SystemExit(3) from exc
    from Foundation import NSURL

    source = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(path)), None)
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None) \
        if source is not None and Quartz.CGImageSourceGetCount(source) else None
    if image is None:
        raise UnreadableImage(f"not a readable image: {path}")
    width, height = Quartz.CGImageGetWidth(image), Quartz.CGImageGetHeight(image)
    cw, ch = max(1, int(width * settings.corner[0])), max(1, int(height * settings.corner[1]))
    # CGImage's origin is top-left.
    corner = Quartz.CGImageCreateWithImageInRect(image, Quartz.CGRectMake(width - cw, height - ch, cw, ch))
    if corner is None:
        raise UnreadableImage(f"could not crop: {path}")
    zw, zh = cw * settings.upscale, ch * settings.upscale  # enough pixels per glyph for Vision
    context = Quartz.CGBitmapContextCreate(None, zw, zh, 8, 0, Quartz.CGColorSpaceCreateDeviceRGB(),
                                           Quartz.kCGImageAlphaPremultipliedLast)
    if context is None:
        raise UnreadableImage(f"could not enlarge: {path}")
    Quartz.CGContextSetInterpolationQuality(context, Quartz.kCGInterpolationHigh)
    Quartz.CGContextDrawImage(context, Quartz.CGRectMake(0, 0, zw, zh), corner)
    if (corner := Quartz.CGBitmapContextCreateImage(context)) is None:
        raise UnreadableImage(f"could not enlarge: {path}")
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(corner, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)  # it turns `nodes:107` into prose
    request.setCustomWords_(settings.custom_words)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise UnreadableImage(f"text recognition failed on {path}: {error}")
    texts = [str(c[0].string()) for o in (request.results() or []) if (c := o.topCandidates_(1))]
    return [t.strip() for t in texts if any(p.search(t) for p in settings.patterns)]


def check(paths: list[Path], quiet: bool = False, settings: Settings | None = None) -> int:
    """0 clean, 1 developer chrome found, 2 unreadable; `settings` from `settings_for(app)`."""
    settings = settings or Settings()
    images = [p for path in paths for p in (sorted(path.rglob("*")) if path.is_dir() else [path])
              if p.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        if not quiet:
            print("no images to check")
        return 0
    dirty: list[tuple[Path, list[str]]] = []
    unreadable: list[str] = []
    for image in images:
        try:
            if hits := hud_text_in(image, settings):
                dirty.append((image, hits))
        except UnreadableImage as exc:
            unreadable.append(str(exc))
    if not quiet:
        print(f"checked {len(images)} image(s): {len(images) - len(dirty) - len(unreadable)} clean, "
              f"{len(dirty)} with developer chrome")
        for image, hits in dirty:
            print(f"  {image}: {', '.join(repr(h) for h in hits)}")
        for message in unreadable:
            print(f"  {message}")
    if unreadable:
        return 2
    if dirty and not quiet:
        print(f"\n{settings.advice}")
    return 1 if dirty else 0


def settings_for(app) -> Settings:
    return Settings.from_config((app.config.get("screenshots") or {}).get("check"))


def framed_decks(app, locales: list[str] | None = None) -> list[Path]:
    """What the push would upload, by the push's own rules."""
    from .media import DECK_SUFFIXES, deck_dirs, deck_files
    return [
        p
        for platform_dir in sorted(p.parent for p in app.folder.glob("*/screenshots"))
        for locale in locales or sorted(p.name for p in (platform_dir / "screenshots").iterdir() if p.is_dir())
        for p in deck_files(deck_dirs(platform_dir, locale), DECK_SUFFIXES, "screenshot", quiet=True)
    ]


cli = command_app("OCR a deck for developer overlays (debug HUDs) before upload. "
                  "Exit 0 clean, 1 developer chrome found, 2 unreadable, 3 Vision not installed.")


@cli.command()
def check_command(
    paths: Annotated[list[Path] | None, typer.Argument(help=(
        "image files, or directories to search (default: every deck of the app, as the push would upload it)"
    ), show_default=False)] = None,
    app: AppOption = None,
    locale: Annotated[list[str] | None, typer.Option(
        "--locale", help="default-deck mode: only this locale (repeatable)")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", help="say nothing; report through the exit code")] = False,
) -> None:
    # Outside an app repo, a check of explicit paths runs on the defaults.
    settings, resolved = Settings(), None
    try:
        resolved = resolve_app(app)
        settings = settings_for(resolved)
    except SystemExit:
        if not paths:
            raise
    raise SystemExit(check(paths or framed_decks(resolved, locale), quiet=quiet, settings=settings))


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane check")
