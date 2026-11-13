"""`screenshots.framing` as three independent choices, resolved per slot: layout (full-bleed, stacked,
device), caption (band, arch, callout, headline; top or bottom) and theme (built-in, overridden key by key).
Every key: docs/reference/framing.md."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, replace
from typing import Any

from .themes import SUPPLEMENTAL, THEMES

DECKS = ("iphone", "ipad", "duo", "mac")
LAYOUTS = ("full-bleed", "stacked", "device")
SHAPES = ("band", "arch", "callout", "headline")
FITS = ("scale", "crop")
FRAMING_KEYS = {"captions", "targets", "slots", "layout", "fit", "caption", "theme", "device", "decorate"}
SLOT_KEYS = {"layout", "fit", "caption", "bias", "rotate", "image"}
CALLOUT_KEYS = {"edge", "centre", "width", "height", "radius", "lip", "shadow"}
DEVICE_KEYS = {"width", "radius", "curve", "gap", "bleed"}
# A device card's corners as the hardware draws its screen: `radius` is how far the corner reaches
# along each edge, as a share of the capture's width, and `curve` the superellipse it follows (2 is
# a circle). Measured off the simulators' own screen masks (`simctl io screenshot --mask=alpha`):
# an iPhone's corner is continuous, easing out of the edge, an iPad's a plain arc. The defaults are
# snakelane's default devices, the 6.5" iPhone 14 Plus and the 13" iPad Pro.
# Why: docs/design/framing.md#a-card-has-its-devices-corners
DEVICE_CORNERS = {"iphone": {"radius": 0.139, "curve": 2.26}, "ipad": {"radius": 0.029, "curve": 2.0},
                  "duo": {"radius": 0.016, "curve": 2.0}}


@dataclass(frozen=True)
class Theme:
    """Colours are "#RRGGBB", [r, g, b] or {"colorset": path}; fill and background also take [top, bottom]."""

    fill: Any = None                 # band, arch and callout body; default black
    background: Any = None           # behind a scaled or device capture; default fill
    text: Any = "#FFFFFF"
    accent: Any = None               # `==words==`; default text
    colors: dict | None = None       # named colours for `[words]{name}`
    font: str | None = None          # a path; default Helvetica Neue
    font_face: str = "Bold"          # the face inside a .ttc, or a variable font's weight
    bold_face: str | None = None     # `**words**`; default font_face
    italic_face: str | None = None   # `*words*`; none means the theme has no italic
    italic_font: str | None = None   # where the italic lives, when it's a separate file
    bold_italic_face: str | None = None
    case: str = "as-written"         # or "upper"
    rule: dict | None = None         # {"color", "height"} on the capture side of a band
    lip: dict | None = None          # {"color", "highlight", "height"} a two-tone edge
    panel: dict | None = None        # {"color", "opacity"} a brighter sheet inside an arch
    shadow: dict | None = None       # {"color", "opacity", "blur", "offset"} under band, callout or card
    text_shadow: Any = None          # colour or {"color", "opacity"}
    outline: dict | None = None      # {"color", "width"} round a device card


@dataclass(frozen=True)
class Caption:
    shape: str = "band"
    position: str = "top"
    depth: float = 0.10              # the band's share of the canvas height
    size: int | None = None          # instead of depth: a type size, the band grows to fit
    min_size: int = 52
    pad: int = 30
    margin: int = 110
    align: str = "center"
    arch: float = 0.018              # how far an arch bows, as a share of the canvas height
    callout: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Style:
    layout: str = "stacked"
    fit: str = "scale"
    caption: Caption = field(default_factory=Caption)
    theme: Theme = field(default_factory=Theme)
    device: dict = field(default_factory=dict)
    rotate: int | None = None
    bias: float | None = None        # full-bleed: where a crop falls, 0 top … 1 bottom

    @property
    def bottom(self) -> bool:
        return self.caption.position == "bottom"

    @property
    def caption_over_capture(self) -> bool:
        """Whether the caption lies over an app screen, which the app then keeps clear (the banner handoff)."""
        return (self.layout == "full-bleed" and self.caption.shape != "callout"
                and not self.rotate and self.bias is None)


def check_keys(where: str, entry: dict[str, Any], known: set[str]) -> None:
    """Refuse a misspelt key, which would otherwise be silently ignored."""
    if unknown := set(entry) - known - {"_comment"}:
        raise SystemExit(f'unknown key(s) in snakelane.yml "screenshots.{where}": {", ".join(sorted(unknown))}')


def check_framing(cfg: dict[str, Any]) -> None:
    check_keys("framing", cfg, FRAMING_KEYS)
    for n, slot in (cfg.get("slots") or {}).items():
        check_keys(f"framing.slots.{n}", slot or {}, SLOT_KEYS)
    check_keys("framing.device", cfg.get("device") or {}, DEVICE_KEYS)
    theme_of(cfg.get("theme"))  # an unknown theme or theme key fails before any drawing


def theme_of(value: Any) -> Theme:
    """A built-in theme by name, or overrides on top of one ({"base": name})."""
    if value is None:
        return Theme()
    overrides = {"base": value} if isinstance(value, str) else dict(value)
    if (base := overrides.pop("base", None)) is not None and base not in THEMES:
        raise SystemExit(f"framing.theme: no theme {base!r}; built in: {', '.join(sorted(THEMES))} "
                         "(`snakelane frame --list-themes` shows them)")
    overrides.pop("_comment", None)
    check_keys("framing.theme", overrides, {f.name for f in fields(Theme)})
    theme = Theme(**{**(THEMES[base] if base else {}), **overrides})
    if theme.case not in ("as-written", "upper"):
        raise SystemExit(f'framing.theme.case must be "as-written" or "upper", not {theme.case!r}')
    return theme


# Scripts the built-in themes' Latin fonts have no glyphs for, and the macOS font a caption in one
# switches to, whole (one face per caption keeps its line metrics even). Bold only: these fonts have
# no italic. Pillow without raqm can't shape Arabic or Hebrew, so they have no entry.
SCRIPT_FONTS: list[tuple[re.Pattern[str], dict[str, Any]]] = [
    (re.compile("[\u0E00-\u0E7F]"), {"font": f"{SUPPLEMENTAL}/SukhumvitSet.ttc", "font_face": "Bold"}),  # Thai
]


def for_text(style: Style, text: str | list[str]) -> Style:
    """`style`, with its theme's font swapped for one that has the script `text` is written in."""
    text = "\n".join(text) if isinstance(text, list) else text
    for script, font in SCRIPT_FONTS:
        if script.search(text):
            theme = replace(style.theme, **font, bold_face=None, italic_face=None, italic_font=None,
                            bold_italic_face=None)
            return replace(style, theme=theme)
    return style


def per_deck(where: str, value: Any, deck: str | None) -> Any:
    """A setting given once, or per deck as {iphone: …, mac: …}; None when this deck has no entry."""
    if not isinstance(value, dict):
        return value
    if unknown := set(value) - set(DECKS) - {"_comment"}:
        raise SystemExit(f"{where}: unknown deck(s) {', '.join(sorted(unknown))}; decks are {', '.join(DECKS)}")
    return value.get(deck or "")


def device_for(cfg: dict[str, Any], deck: str | None) -> dict[str, Any]:
    """`framing.device` for one deck: each key a value or a per-deck mapping (a portrait phone's
    corner radius is far too round on a landscape Mac window); a deck without an entry gets the default."""
    resolved = {key: per_deck(f"framing.device.{key}", value, deck)
                for key, value in (cfg.get("device") or {}).items() if key != "_comment"}
    return {**DEVICE_CORNERS.get(deck or "", {}), **{key: value for key, value in resolved.items() if value is not None}}


def style_for(cfg: dict[str, Any], slot: dict[str, Any], deck: str | None) -> Style:
    """One slot's style: the framing's settings, then the slot's."""
    base_caption, slot_caption = cfg.get("caption") or {}, slot.get("caption") or {}
    caption = {**base_caption, **slot_caption,
               "callout": {**(base_caption.get("callout") or {}), **(slot_caption.get("callout") or {})}}
    layout = slot.get("layout", cfg.get("layout", "stacked"))
    if layout not in LAYOUTS:
        raise SystemExit(f"framing.layout must be one of {', '.join(LAYOUTS)}, not {layout!r}")
    # Crop is a full-bleed capture's default (it fills the canvas); scale is the others'.
    fit = slot.get("fit", cfg.get("fit", "crop" if layout == "full-bleed" else "scale"))
    if fit not in FITS:
        raise SystemExit(f'framing.fit must be "scale" or "crop", not {fit!r}')
    if (turn := slot.get("rotate")) is not None and turn not in (90, 180, 270, -90):
        raise SystemExit(f"framing.slots rotate must be 90, 180, 270 or -90, not {turn!r}")
    caption.setdefault("shape", "headline" if layout == "device" else "band")
    check_keys("framing.caption", caption, {f.name for f in fields(Caption)})
    caption.pop("_comment", None)
    position = per_deck("framing.caption.position", caption.get("position", "top"), deck)
    caption["position"] = "top" if position is None else position
    # Sizing can differ per deck too: a Duo's outer display is short and wide, so a caption sized
    # to the band's depth grows to its edges; a fixed type size with padding keeps a gap.
    for key in ("depth", "size", "pad", "margin"):
        if key in caption and (value := per_deck(f"framing.caption.{key}", caption[key], deck)) is None:
            del caption[key]
        elif key in caption:
            caption[key] = value
    c = Caption(**caption)
    if c.shape not in SHAPES:
        raise SystemExit(f"framing.caption.shape must be one of {', '.join(SHAPES)}, not {c.shape!r}")
    if c.position not in ("top", "bottom"):
        raise SystemExit(f'framing.caption.position must be "top" or "bottom", not {c.position!r}')
    check_keys("framing.caption.callout", c.callout, CALLOUT_KEYS)
    # Placement can differ per deck: a landscape shot's bare felt isn't in the same place on a phone
    # and a tablet. A deck left out of a mapping gets the default.
    for key in ("edge", "centre", "width", "height", "radius"):
        if key in c.callout and (value := per_deck(f"framing.caption.callout.{key}", c.callout[key], deck)) is None:
            del c.callout[key]
        elif key in c.callout:
            c.callout[key] = value
    return Style(layout=layout, fit=fit, caption=c, theme=theme_of(cfg.get("theme")),
                 device=device_for(cfg, deck), rotate=turn,
                 bias=None if slot.get("bias") is None else float(slot["bias"]))
