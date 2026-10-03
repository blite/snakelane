"""`snakelane frame`: caption and frame raw captures outside the UI test.

    snakelane frame [--locale en-US] [--deck ipad] [--theme felt] [--list-themes]

Reads .snakelane/<app>/raw/<platform>/<locale>/<device>/*, writes
metadata/<platform>/screenshots/<locale>/<device>/ss-NN.jpg. Settings: snakelane.yml's
`screenshots.framing` (keys: docs/reference/framing.md; reasons: docs/design/framing.md).
A raw file's slot is its `ss-NN` name; a capture without a caption is an error. `framing.captions`
is one {slot: caption} map for every locale, or {locale: {slot: caption}}; a locale without an
entry gets the primary locale's.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import typer

from ..args import AppOption, PlatformOption, command_app, resolve_platform, run
from ..project import IMAGE_SUFFIXES, App, DeckTree, resolve_app
from .framing.draw import caption_band, ink_of, parse_caption
from .framing.style import DECKS, check_framing, style_for, theme_of
from .framing.themes import THEMES
from .media import deck_files, save_jpeg

# The canvas when "targets" names none: 6.5" iPhone, 13" iPad, the Mac. Only the handoff needs it.
DECK_CANVAS = {"iphone": (1284, 2778), "ipad": (2064, 2752), "mac": (2880, 1800)}
CAPTIONS = 'snakelane.yml "framing.captions"'
PLATFORM_DECKS = {"ios": ("iphone", "ipad"), "macos": ("mac",)}
OLD_ACCENT = re.compile(r"(?<![*\\])\*(?!\*)[^*\n]+(?<![*\\])\*(?!\*)")


def framing(app: App) -> dict[str, Any]:
    check_framing(cfg := (app.config.get("screenshots") or {}).get("framing") or {})
    return cfg


def slots_of(cfg: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(k): v or {} for k, v in (cfg.get("slots") or {}).items()}


def is_slot_key(key: Any) -> bool:
    return isinstance(key, int) or (isinstance(key, str) and key.isdigit())


def slot_map(where: str, source: dict[Any, Any]) -> dict[int, str]:
    if bad := [str(k) for k in source if not is_slot_key(k)]:
        raise SystemExit(f"{where}: {', '.join(bad)} is not a shot number")
    return {int(k): "\n".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in source.items()}


def caption_sets(cfg: dict[str, Any]) -> dict[str | None, dict[int, str]]:
    """Every caption map in framing.captions: {None: map} for the one-map form, else by locale.
    Slot keys are numbers, locale keys are not; that is how the two forms are told apart."""
    if not isinstance(source := cfg.get("captions"), dict):
        raise SystemExit('frame: set "framing.captions" in snakelane.yml: {"1": "Caption", …}')
    source = {k: v for k, v in source.items() if k != "_comment"}
    slot_keys = [k for k in source if is_slot_key(k)]
    if len(slot_keys) == len(source):
        return {None: slot_map(CAPTIONS, source)}
    if slot_keys:
        raise SystemExit(f"{CAPTIONS} mixes shot numbers ({', '.join(map(str, slot_keys))}) with locales; use "
                         'one form: {"1": "Caption", …} for every locale, or {"en-US": {"1": "Caption", …}, …}')
    sets: dict[str | None, dict[int, str]] = {}
    for locale, entry in source.items():
        if not isinstance(entry, dict):
            raise SystemExit(f'{CAPTIONS}.{locale} must map shot numbers to captions: {{"1": "Caption", …}}')
        sets[str(locale)] = slot_map(f"{CAPTIONS}.{locale}", entry)
    return sets


def captions_source(app: App, cfg: dict[str, Any], locale: str | None) -> str | None:
    """Whose captions `locale` gets: its own, else the primary locale's; None for the one-map form."""
    sets = caption_sets(cfg)
    if None in sets:
        return None
    if locale is not None and locale in sets:
        return locale
    if (primary := app.primary_locale) in sets:
        return primary
    raise SystemExit(f"{CAPTIONS} has no captions for {locale or 'the primary locale'}, nor for the primary "
                     f"locale {primary}; add a {locale or primary} entry")


def captions(app: App, cfg: dict[str, Any], locale: str | None = None) -> dict[int, str]:
    """Slot -> caption for `locale` from snakelane.yml's framing.captions (a list is the caption's
    lines): the one map, or the locale's own, falling back to the primary locale's."""
    return caption_sets(cfg)[captions_source(app, cfg, locale)]


def fallback_note(app: App, cfg: dict[str, Any], locale: str) -> str | None:
    """One line when `locale` borrows another locale's captions."""
    source = captions_source(app, cfg, locale)
    return None if source in (None, locale) else f"captions: {locale} has none in {CAPTIONS}; using {source}'s"


def slot_of(path: Path) -> int | None:
    return int(m.group(1)) if (m := re.fullmatch(r"ss-(\d+)", path.stem)) else None


def banner_handoff(app: App, deck: str, locale: str | None = None) -> dict[str, Any]:
    """Per slot, what the app leaves empty for the caption (`depth`: share of height, lip and rule
    included); the top-level pair is the commonest. Why: docs/design/framing.md#the-banner-handoff"""
    cfg = framing(app)
    width, height = tuple((cfg.get("targets") or {}).get(deck) or DECK_CANVAS[deck])
    slots, handed = slots_of(cfg), {}
    for n, text in sorted(captions(app, cfg, locale).items()):
        style = style_for(cfg, slots.get(n, {}), deck)
        if not style.caption_over_capture:
            handed[str(n)] = {"position": "none", "depth": 0}
            continue
        _, depth = caption_band(app, style, text, width, height, ink_of(app, style.theme))
        handed[str(n)] = {"position": style.caption.position, "depth": round(depth / height, 4)}
    values = [tuple(v.items()) for v in handed.values()]
    common = dict(max(values, key=values.count)) if values else {"position": "none", "depth": 0}
    return {"version": 1, "deck": deck, **common, "slots": handed}


def frame_deck(app: App, locale: str = "en-US", decks: list[str] | None = None, theme: str | None = None) -> int:
    """Frame `locale`'s raw captures in `decks` (default: all with raws); return the count.
    With `theme`, output goes to .snakelane/, not the deck."""
    from .framing.compose import compose

    cfg = framing(app)
    if theme is not None:
        overrides = cfg.get("theme") if isinstance(cfg.get("theme"), dict) else {}
        check_framing(cfg := {**cfg, "theme": {**overrides, "base": theme}})
    deck = captions(app, cfg, locale)
    if note := fallback_note(app, cfg, locale):
        print(f"  {note}")
    # Every locale's marks are checked, not just this one's: a broken translation fails the first run.
    texts = [t for s in caption_sets(cfg).values() for t in s.values()]
    the_theme = theme_of(cfg.get("theme"))
    for text in texts:
        parse_caption(the_theme, text)
    # `*word*` meant the accent until 2026-10-02 and is now italic: warn a theme that has an accent.
    if the_theme.accent and any(map(OLD_ACCENT.search, texts)) and not any("==" in t for t in texts):
        print(f"  note: captions in {CAPTIONS} use *word*, which is italic; the accent colour is ==word==")
    targets = {k: tuple(v) for k, v in (cfg.get("targets") or {}).items()}
    slots, produced, total = slots_of(cfg), set(), 0
    for platform in decks or DECKS:
        tree = DeckTree.for_deck(app, platform)
        raw = tree.raw(locale)
        framed = app.work_dir / "themes" / theme / platform / locale if theme else tree.framed(locale)
        # The deck is exactly the `ss-NN` files (an `unused-06-alt.png` kept beside them is not).
        shots = [p for p in deck_files([raw], IMAGE_SUFFIXES, "raw", quiet=True) if slot_of(p) is not None] \
            if raw.is_dir() else []
        if not shots:
            if decks:
                print(f"{platform:7s} no captures in {raw}")
            continue
        target = targets.get(platform)
        print(f"{platform:7s} -> " + (f"{target[0]}x{target[1]}" if target else "native size"))
        for src in shots:
            if (n := slot_of(src)) not in deck:
                raise SystemExit(f"{src.name}: no caption for shot {n} in {CAPTIONS}")
            style = style_for(cfg, slots.get(n, {}), platform)
            image, note = compose(app, style, src, deck[n], target)
            dst = framed / f"ss-{n:02d}.jpg"
            save_jpeg(image, dst)  # the extraction's writer, so the two decks match
            print(f"          {dst.name:<34s} {note:<48s} “{deck[n]}”")
            total += 1
            produced.add(n)
        print(f"          written to {framed}")
    if not total:
        raise SystemExit(f"nothing framed — put captures in raw/{locale}/ as ss-01.png .. or run `snakelane shoot`")
    # Across platforms: an iPad deck may omit a phone-only shot.
    # Why: docs/design/framing.md#a-missing-captioned-shot-fails-the-run
    if missing := sorted(set(deck) - produced):
        raise SystemExit(f"captioned shot(s) {', '.join(map(str, missing))} in {CAPTIONS} have no capture "
                         f"in any deck for {locale}; shoot them, or drop their captions")
    print(f"\n{total} framed.")
    return total


cli = command_app("Caption and frame raw captures outside the UI test. Settings: the config's "
                  "screenshots.framing — layout, caption and theme (docs/reference/framing.md).", no_args_is_help=False)


def known_decks(decks: list[str] | None) -> list[str] | None:
    if bad := next((d for d in decks or [] if d not in DECKS), None):
        raise typer.BadParameter(f"{bad!r} is not one of {', '.join(DECKS)}")
    return decks


@cli.command()
def frame_command(
    app: AppOption = None,
    locale: Annotated[str, typer.Option("--locale")] = "en-US",
    deck: Annotated[list[str] | None, typer.Option("--deck", callback=known_decks,
                                                   help="only this deck (repeatable; default: every deck with raws)")] = None,
    theme: Annotated[str | None, typer.Option("--theme", help="try a built-in look; writes to .snakelane/themes/, "
                                              "not the deck")] = None,
    list_themes: Annotated[bool, typer.Option("--list-themes", help="list the built-in themes")] = False,
    device: Annotated[str | None, typer.Option("--device", help="frame: test only: the simulator that hosts the app's "
                                               "reframe test (any will do)")] = None,
    platform: PlatformOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="frame: test only: print what would run")] = False,
) -> None:
    """Caption the deck from its raw captures, without shooting. With `screenshots.frame: snakelane`
    (or no frame setting) snakelane draws the captions; with `frame: test` the app's reframe UI test
    redraws them."""
    if list_themes:
        for name, t in THEMES.items():
            fill = " → ".join(t["fill"]) if isinstance(t.get("fill"), list) else t.get("fill")
            ornaments = [k for k in ("lip", "panel", "rule", "shadow", "text_shadow") if t.get(k)]
            print(f"  {name:<10} {fill or '':<20} {Path(t.get('font', '')).stem} {t.get('font_face', '')}"
                  + (f"  + {', '.join(ornaments)}" if ornaments else ""))
        print("\nUse one with framing.theme: <name>, or {base: <name>, …overrides}; "
              "try one with `snakelane frame --theme <name>`.")
        return
    resolved = resolve_app(app)
    from .shoot import frame_mode, reframe_with_test

    if frame_mode(resolved.config.get("screenshots") or {}) != "snakelane" and not theme:
        reframe_with_test(SimpleNamespace(app=app, locale=locale, device=device, dry_run=dry_run,
                                          platform=resolve_platform(resolved.config, platform)))
        return
    if dry_run:
        raise typer.BadParameter("--dry-run is for frame: test; snakelane's own framing writes nothing outside "
                                 "the deck, so run it and look (or use --theme to write a preview)")
    # --platform narrows the decks; without it every deck with raws is framed, as before.
    # Why: docs/design/framing.md#frame-honours-platform
    if platform is not None and not deck:
        deck = list(PLATFORM_DECKS[resolve_platform(resolved.config, platform)])
    frame_deck(resolved, locale, deck, theme=theme)
    print("A preview: the deck is unchanged. Set framing.theme to keep it." if theme
          else "Upload with:  snakelane store screenshots push")


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane frame")
