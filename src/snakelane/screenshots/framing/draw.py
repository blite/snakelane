"""Drawing a caption: colours, type, band (flat or arched), callout, headline and shadows.
Every function returns an RGBA layer; `compose` places it."""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ...project import App
from .style import Style, Theme

DEFAULT_FONT = "/System/Library/Fonts/HelveticaNeue.ttc"
SUPERSAMPLE = 4  # curves and rounded corners are drawn this much larger, then scaled down: antialiasing


def px(value: Any, height: int) -> int:
    """Pixels: a whole number is pixels, a fraction under 1 a share of the canvas height."""
    value = float(value)
    return round(value * height) if 0 < abs(value) < 1 else int(value)


def repo_path(app: App, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else app.root / path


def rgb(app: App, value: Any) -> tuple[int, int, int]:
    """A colour from "#RRGGBB", [r, g, b] or {"colorset": path} in the app's asset catalog."""
    if isinstance(value, str):
        if len(text := value.lstrip("#")) != 6:
            raise SystemExit(f"colour {value!r} is not #RRGGBB")
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(int(v) for v in value)  # type: ignore[return-value]
    if not (isinstance(value, dict) and "colorset" in value):
        raise SystemExit(f"cannot read a colour from {value!r}")
    folder = repo_path(app, value["colorset"])
    folder = folder if folder.suffix == ".colorset" else folder.with_suffix(".colorset")
    try:
        c = json.loads((folder / "Contents.json").read_text())["colors"][0]["color"]["components"]
    except (OSError, KeyError, IndexError) as exc:
        raise SystemExit(f"cannot read a colour from {folder}: {exc}") from exc
    return tuple(int(s, 0) if (s := str(c[k])).startswith("0x") else round(float(s) * 255)
                 for k in ("red", "green", "blue"))  # type: ignore[return-value]


def is_gradient(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and not all(isinstance(v, int) for v in value)


def paint(app: App, value: Any, size: tuple[int, int], ink: tuple[int, int, int]):
    """`size` filled with a colour, or a [top, bottom] vertical gradient; `ink` when unset."""
    if not is_gradient(value):
        return Image.new("RGB", size, rgb(app, value) if value is not None else ink)
    top, bottom = rgb(app, value[0]), rgb(app, value[1])
    h = size[1]
    column = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1) if h > 1 else 0
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True)))
    return column.resize(size, Image.NEAREST)


def ink_of(app: App, theme: Theme) -> tuple[int, int, int]:
    """The fill's colour; a gradient's lower colour, the one that meets the capture."""
    if theme.fill is None:
        return (0, 0, 0)
    return rgb(app, theme.fill[1] if is_gradient(theme.fill) else theme.fill)


def load_face(app: App, font: str | None, face: str, size: int, strict: bool = True):
    """`face` of `font` (default Helvetica Neue); `strict` refuses a face the font lacks."""
    path = str(repo_path(app, font)) if font else DEFAULT_FONT
    if not Path(path).exists():
        raise SystemExit(f"frame: no font at {path}")
    return open_face(path, face, size, strict)


@functools.lru_cache(maxsize=1024)
def open_face(path: str, face: str, size: int, strict: bool):
    """Cached: fitting asks for a few faces at dozens of sizes. A .ttc is searched by face name (its
    order isn't documented); a variable font (SF, New York) by instance name."""
    found = []
    if path.lower().endswith(".ttc"):
        for index in range(32):
            try:
                f = ImageFont.truetype(path, size, index=index)
            except OSError:
                break
            if f.getname()[1] == face:
                return f
            found.append(f.getname()[1])
    font_file = ImageFont.truetype(path, size)
    try:
        names = [n.decode() for n in font_file.get_variation_names()]
    except OSError:
        names = []  # not a variable font
    if face in names:
        font_file.set_variation_by_name(face)
        return font_file
    if strict and (found or names):
        raise SystemExit(f"frame: {Path(path).name} has no {face!r} face; it has {', '.join(found or names)}")
    return font_file


def largest(app: App, theme: Theme, size: int, step: int, floor: int, fits) -> Type:
    """The theme's type at the largest size, down from `size` by `step` to `floor`, where `fits(type)`."""
    type_ = Type(app, theme, size)
    while type_.size > floor and not fits(type_):
        type_ = Type(app, theme, type_.size - step)
    return type_


@dataclass
class Type:
    """A theme's faces at one size (open_face caches the loading)."""

    app: App
    theme: Theme
    size: int

    @property
    def base(self):
        return self.font(False, False)

    def font(self, bold: bool, italic: bool):
        t = self.theme
        if not italic:
            return (load_face(self.app, t.font, t.bold_face or t.font_face, self.size) if bold
                    else load_face(self.app, t.font, t.font_face, self.size, strict=False))
        face = (t.bold_italic_face if bold else None) or t.italic_face
        if face is None and t.font is None:
            face = "Bold Italic"  # the default Helvetica Neue's
        if face is None:
            raise SystemExit("frame: this theme has no italic, so a caption can't use *italic*. Set the "
                             "theme's italic_face (and italic_font, if the italic is a separate file), "
                             "or use ==word== for the accent colour.")
        return load_face(self.app, t.italic_font or t.font, face, self.size)

    def width(self, measure, runs: list[Run]) -> float:
        if plain(runs):  # measured whole, as before marks existed, so kerning is unchanged
            return measure.textlength("".join(r.text for r in runs), font=self.base)
        return sum(measure.textlength(r.text, font=self.font(r.bold, r.italic)) for r in runs)

    def bbox(self, measure, runs: list[Run]) -> tuple[float, float, float, float]:
        if plain(runs):
            return measure.textbbox((0, 0), "".join(r.text for r in runs), font=self.base)
        x, box = 0.0, None
        for r in runs:
            f = self.font(r.bold, r.italic)
            b = measure.textbbox((x, self.base.getmetrics()[0] - f.getmetrics()[0]), r.text, font=f)
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
            x += measure.textlength(r.text, font=f)
        return box or (0, 0, 0, 0)


def colour_of(app: App, theme: Theme, run: Run) -> tuple[int, int, int]:
    if run.colour is None:
        return rgb(app, theme.text)
    if run.colour == "accent":
        return rgb(app, theme.accent or theme.text)
    if (named := (theme.colors or {}).get(run.colour)) is not None:
        return rgb(app, named)
    if not str(run.colour).startswith("#"):
        raise SystemExit(f"frame: no colour {run.colour!r} in the theme's colors "
                         f"({', '.join(theme.colors or {}) or 'none set'}); use a name from there or #RRGGBB")
    return rgb(app, run.colour)


def lip_of(app: App, theme: Theme, canvas_h: int, height: Any = None):
    """(height in px, dark, light) of the theme's lip, or None."""
    if not theme.lip:
        return None
    dark = rgb(app, theme.lip.get("color", "#BF8F2E"))
    light = rgb(app, theme.lip["highlight"]) if theme.lip.get("highlight") else dark
    return px(theme.lip.get("height", 0) if height is None else height, canvas_h), dark, light


def smooth_mask(size: tuple[int, int], draw) -> Any:
    """An antialiased L mask of `size`: `draw(ImageDraw, k)` paints it at `k` times the size."""
    k = SUPERSAMPLE
    big = Image.new("L", (size[0] * k, size[1] * k), 0)
    draw(ImageDraw.Draw(big), k)
    return big.resize(size, Image.LANCZOS)


def offset_of(spec: dict) -> tuple[Any, Any]:
    """A shadow's (dx, dy): `offset` is [dx, dy], or one number for straight down."""
    offset = spec.get("offset", [0, 16])
    return (0, offset) if isinstance(offset, (int, float)) else tuple(offset)


def with_shadow(app: App, spec: dict | None, canvas, layer, at: tuple[int, int] = (0, 0)) -> None:
    """Composite `layer` onto `canvas` at `at`, over its drop shadow when `spec` is set."""
    if spec:
        h = canvas.size[1]
        dx, dy = offset_of(spec)
        alpha = Image.new("L", canvas.size, 0)
        alpha.paste(layer.getchannel("A"), (at[0] + px(dx, h), at[1] + px(dy, h)))
        alpha = alpha.filter(ImageFilter.GaussianBlur(px(spec.get("blur", 60), h) / 3))
        opacity = float(spec.get("opacity", 0.55))
        shade = Image.new("RGBA", canvas.size, (*rgb(app, spec.get("color", "#000000")), 255))
        shade.putalpha(alpha.point(lambda v: round(v * opacity)))
        canvas.alpha_composite(shade)
    canvas.alpha_composite(layer, at)


def flipped(spec: dict | None) -> dict | None:
    """The shadow falling the other way: a bottom band's falls up, onto the capture."""
    if not spec:
        return spec
    dx, dy = offset_of(spec)
    return {**spec, "offset": [dx, -dy]}


# A caption is Markdown-like: **bold**, *italic*, ==accent==, [words]{colour or name}, a line break at
# \n or <br>. Marks don't span lines; an unclosed one is an error; a backslash escapes a mark character.


@dataclass(frozen=True)
class Run:
    text: str
    bold: bool = False
    italic: bool = False
    colour: Any = None  # None: the theme's text colour; "accent"; or a colour name or #RRGGBB


Placed = list[tuple[float, float, list[Run]]]  # (x, y of the line box's top, runs) per line

# An escape, **, *, ==, the "[" of "[words]{colour}" (its colour read ahead), or the span's "]{colour}".
MARK = re.compile(r"\\(.)|\*\*|\*|==|\[(?=[^\[\]]*\]\{([^}]*)\})|\]\{[^}]*\}")


def plain(runs: list[Run]) -> bool:
    return not any(r.bold or r.italic for r in runs)


def parse_line(theme: Theme, line: str) -> list[Run]:
    runs: list[Run] = []
    on = {"**": False, "*": False, "==": False}  # bold, italic, accent
    colours: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if text := "".join(buf):
            runs.append(Run(text.upper() if theme.case == "upper" else text, on["**"], on["*"],
                            colours[-1] if colours else ("accent" if on["=="] else None)))
        buf.clear()

    at = 0
    for m in MARK.finditer(line):
        buf.append(line[at:m.start()])
        at, token = m.end(), m.group(0)
        if m.group(1) is not None or (token.startswith("]") and not colours):
            buf.append(m.group(1) if m.group(1) is not None else token)  # an escape, or a stray close
            continue
        flush()
        if token in on:
            on[token] = not on[token]
        elif token == "[":
            colours.append(m.group(2).strip())
        else:
            colours.pop()
    buf.append(line[at:])
    flush()
    if unclosed := [mark for mark, open_ in on.items() if open_]:
        raise SystemExit(f"frame: caption line {line!r} leaves {' and '.join(unclosed)} unclosed "
                         "(a literal asterisk or equals sign is written \\* or \\=)")
    return runs


def parse_caption(theme: Theme, text: str) -> list[list[Run]]:
    return [parse_line(theme, line) for line in text.replace("<br>", "\n").split("\n")]


def draw_runs(app: App, theme: Theme, d, x: float, y: float, runs: list[Run], type_: Type) -> None:
    """One line; `y` is the regular face's line-box top, and every face shares its baseline."""
    ascent = type_.base.getmetrics()[0]
    for r in runs:
        font = type_.font(r.bold, r.italic)
        d.text((x, y + ascent - font.getmetrics()[0]), r.text, font=font, fill=(*colour_of(app, theme, r), 255))
        x += d.textlength(r.text, font=font)


def draw_text(app: App, theme: Theme, layer, placed: Placed, type_: Type) -> None:
    """The caption's lines onto `layer`, over a soft shadow when the theme has one."""
    type_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(type_layer)
    for x, y, runs in placed:
        draw_runs(app, theme, d, x, y, runs, type_)
    if not (spec := theme.text_shadow):
        layer.alpha_composite(type_layer)
        return
    spec = {"color": spec} if isinstance(spec, str) else spec
    size = type_.size
    with_shadow(app, {"color": spec.get("color", "#000000"), "opacity": spec.get("opacity", 0.8),
                      "blur": max(1, round(size * 0.3)), "offset": [0, max(1, round(size * 0.06))]},
                layer, type_layer)


def fit_block(app: App, style: Style, lines: list[list[Run]], width: int, canvas_h: int, crown: int,
              measure) -> tuple[Type, Placed, int]:
    """Font, line positions and band depth for several lines: with caption.size the band grows to
    the type, without, the type shrinks to the band.
    Why: docs/design/framing.md#caption-sizing-follows-solitaires-arch"""
    c = style.caption
    max_w = width - 2 * c.margin if c.size else round(width * 0.88)

    def widest(type_: Type) -> float:
        return max(type_.width(measure, line) for line in lines)

    def ink(type_: Type) -> tuple[float, float]:  # inked top and bottom, from the first line box's top
        return (type_.bbox(measure, lines[0])[1],
                type_.size * 1.04 * (len(lines) - 1) + type_.bbox(measure, lines[-1])[3])

    if c.size:
        font = largest(app, style.theme, int(c.size), 4, c.min_size, lambda t: widest(t) <= max_w)
        band_h = round(font.size * 1.04 * len(lines)) + 2 * c.pad + crown
    else:
        band_h = round(canvas_h * float(c.depth))
    pad = c.pad if c.size else 0
    area = band_h - crown - 2 * pad if pad else (band_h - crown) * 0.94
    def fits(type_: Type) -> bool:
        top, bottom = ink(type_)
        return widest(type_) <= max_w and bottom - top <= area * 0.9

    if not c.size:
        font = largest(app, style.theme, round(area * 0.46), 2, 8, fits)
    size = font.size
    line_h = size * 1.04
    top = pad + (area - line_h * len(lines)) / 2 + size * 0.05
    # Solitaire's placement, unless this font's ink would leave the area: then centre the ink.
    ink_top, ink_bottom = ink(font)
    if top + ink_top < pad or top + ink_bottom > pad + area:
        top = pad + (area - (ink_bottom - ink_top)) / 2 - ink_top
    placed = []
    for line in lines:
        placed.append((c.margin if c.align == "left" else (width - font.width(measure, line)) / 2, top, line))
        top += line_h
    return font, placed, band_h


def caption_band(app: App, style: Style, text: str, width: int, canvas_h: int, ink: tuple[int, int, int]):
    """The band (or arch, or bare headline) as a canvas-wide RGBA layer, and how deep it reaches."""
    c, theme = style.caption, style.theme
    rise = round(canvas_h * float(c.arch)) if c.shape == "arch" else 0
    crown = max(rise, 0)  # the type sits above the band's shallowest point: crown, or a sagging arch's sides
    measure = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    lines = parse_caption(theme, text)
    runs = lines[0]
    if len(lines) > 1:
        f, placed, band_h = fit_block(app, style, lines, width, canvas_h, crown, measure)
    elif c.size:  # type first: shrink until one line fits the margins, then fit the band to it
        f = largest(app, theme, int(c.size), 4, c.min_size, lambda t: t.width(measure, runs) <= width - 2 * c.margin)
        band_h = sum(f.base.getmetrics()) + 2 * c.pad + crown
        placed = [(c.margin if c.align == "left" else (width - f.width(measure, runs)) / 2, c.pad, runs)]
    else:  # band first: a share of the canvas, with the largest type that fits on one line
        band_h = round(canvas_h * float(c.depth))
        max_w, max_h = round(width * 0.88), round((band_h - crown) * 0.52)

        def fits(type_: Type) -> bool:
            l, t, r, b = type_.bbox(measure, runs)
            return r - l <= max_w and b - t <= max_h

        f = largest(app, theme, max_h, 2, 8, fits)
        l, t, r, b = f.bbox(measure, runs)
        placed = [((c.margin if c.align == "left" else (width - (r - l)) / 2) - l,
                   (band_h - crown - (b - t)) / 2 - t, runs)]
    rule_h = px(theme.rule.get("height", 0), canvas_h) if theme.rule and c.shape != "headline" else 0
    if (c.shape != "band" or style.bottom or len(lines) > 1 or theme.lip or theme.panel or theme.text_shadow
            or is_gradient(theme.fill)):
        return styled_band(app, style, placed, f, width, canvas_h, band_h, rise, rule_h, ink)
    # One extra row of band colour keeps reframes byte-identical to PuzzleReef's committed decks.
    # Why: docs/design/framing.md#the-plain-bands-extra-pixel-row
    bleed = 0 if c.size or rule_h else 1
    band = Image.new("RGBA", (width, band_h + rule_h + bleed), (0, 0, 0, 0))
    d = ImageDraw.Draw(band)
    d.rectangle((0, 0, width, band_h - 1 + bleed), fill=(*ink, 255))
    if rule_h:
        d.rectangle((0, band_h, width, band_h + rule_h - 1), fill=(*rgb(app, theme.rule.get("color", "#FFFFFF")), 255))
    draw_runs(app, theme, d, placed[0][0], placed[0][1], runs, f)
    return band, band_h + rule_h


def styled_band(app: App, style: Style, placed: Placed, font, width: int, canvas_h: int, band_h: int,
                rise: int, rule_h: int, ink: tuple[int, int, int]):
    """Layers under one parabolic edge (`band_h` deep at the sides, `rise` less in the middle), lip
    and rule following it. A headline is the type alone."""
    theme = style.theme
    headline = style.caption.shape == "headline"
    lip = None if headline else lip_of(app, theme, canvas_h)
    lip_h = lip[0] if lip else 0
    height = band_h + lip_h + rule_h + max(-rise, 0)  # a sagging arch reaches past band_h
    steps = max(2, width // 8)

    def above(depth: float, middle: float | None = None):
        """A mask above a curve `depth` deep at the sides, `middle` (default: the band's curve) in the middle."""
        middle = depth - rise if middle is None else middle
        edge = [(width * i / steps, depth + (middle - depth) * (1 - (2 * i / steps - 1) ** 2))
                for i in range(steps + 1)]
        return smooth_mask((width, height), lambda d, k: d.polygon(
            [(0, 0), (width * k, 0), *((x * k, y * k) for x, y in reversed(edge))], fill=255))

    band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if not headline:
        if rule_h:
            band.paste((*rgb(app, theme.rule.get("color", "#FFFFFF")), 255), (0, 0), above(band_h + lip_h + rule_h))
        if lip:
            band.paste((*lip[1], 255), (0, 0), above(band_h + lip_h))
            band.paste((*lip[2], 255), (0, 0), above(band_h + round(lip_h * 0.55)))
        # A gradient runs over the body's own depth, not the lip's.
        body = paint(app, theme.fill, (width, band_h if is_gradient(theme.fill) else height), ink)
        band.paste(body.convert("RGBA").crop((0, 0, width, height)), (0, 0), above(band_h))
        if theme.panel:  # a brighter sheet bowing the other way inside the body, for depth
            shape = above(round(band_h * 0.52), round(band_h * 0.64))
            sheet = Image.new("RGBA", (width, height), (*rgb(app, theme.panel.get("color", "#FFFFFF")), 0))
            sheet.putalpha(shape.point(lambda v: round(v * float(theme.panel.get("opacity", 0.55)))))
            band.alpha_composite(sheet)
    if style.bottom:  # mirrored so every layer faces the capture; the type is set upright in the body
        band = ImageOps.flip(band)
        placed = [(x, y + height - band_h + max(rise, 0), line) for x, y, line in placed]
    draw_text(app, theme, band, placed, font)
    return band, height


def callout_layer(app: App, style: Style, text: str, size: tuple[int, int], ink: tuple[int, int, int]):
    """A rounded caption box hanging off one side, as a full-canvas RGBA layer. It runs past its edge
    by twice its radius, so only the inner corners are round."""
    spec, theme = style.caption.callout, style.theme
    if (edge := spec.get("edge", "right")) not in ("left", "right"):
        raise SystemExit(f'framing.caption.callout "edge" must be "left" or "right", not {edge!r}')
    cw, ch = size
    w, h = round(cw * float(spec.get("width", 0.66))), round(ch * float(spec.get("height", 0.115)))
    radius = round(cw * float(spec.get("radius", 0.04)))
    top = round(ch * float(spec.get("centre", 0.6)) - h / 2)
    box = (cw - w, top, cw + 2 * radius, top + h) if edge == "right" else (-2 * radius, top, w, top + h)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lip = lip_of(app, theme, ch, spec.get("lip"))  # a box a third the band's depth wants a thinner lip
    inset = lip[0] if lip else 0
    region = (max(0, box[0]), box[1], min(cw, box[2]), box[3])  # masks cover only the visible part: cheap

    def fill(colour_or_image, inner: int) -> None:
        rect = (box[0] + inner - region[0], inner, box[2] - inner - region[0], box[3] - box[1] - inner)
        mask = smooth_mask((region[2] - region[0], region[3] - region[1]), lambda dr, k: dr.rounded_rectangle(
            tuple(v * k for v in rect), max(0, radius - inner) * k, fill=255))
        layer.paste(colour_or_image, region, mask)

    if lip:
        fill((*lip[1], 255), 0)
        fill((*lip[2], 255), round(inset * 0.45))
    body = (box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset)
    sheet = Image.new("RGBA", (region[2] - region[0], region[3] - region[1]), (0, 0, 0, 0))
    sheet.paste(paint(app, theme.fill, (sheet.width, body[3] - body[1]), ink).convert("RGBA"), (0, inset))
    fill(sheet, inset)
    lines = parse_caption(theme, text)
    visible = (max(0, body[0]), min(cw, body[2]))
    max_w = (visible[1] - visible[0]) - round(w * 0.14)
    body_h = body[3] - body[1]
    font = largest(app, theme, max(8, round(body_h * 0.34)), 2, 8,
                   lambda t: max(t.width(d, line) for line in lines) <= max_w
                   and t.size * 1.04 * len(lines) <= body_h * 0.9)
    line_h = font.size * 1.04
    # Capitals sit high in their line box; the nudge centres the capitals, not the box.
    y = body[1] + (body_h - line_h * len(lines)) / 2 + font.size * 0.05
    placed = []
    for line in lines:
        x = visible[0] + round(w * 0.08) if edge == "right" else visible[1] - round(w * 0.08) - font.width(d, line)
        placed.append((x, y, line))
        y += line_h
    draw_text(app, theme, layer, placed, font)
    return layer


def card(app: App, style: Style, shot, canvas_h: int):
    """The capture as a card: rounded corners and the theme's outline, as an RGBA layer."""
    radius = round(shot.width * float(style.device.get("radius", 0.07)))
    corners = (0, 0, shot.width * SUPERSAMPLE - 1, shot.height * SUPERSAMPLE - 1)
    layer = shot.convert("RGBA")
    layer.putalpha(smooth_mask(shot.size, lambda d, k: d.rounded_rectangle(corners, radius * k, fill=255)))
    if outline := style.theme.outline:
        stroke = px(outline.get("width", 6), canvas_h)
        ring = smooth_mask(shot.size, lambda d, k: d.rounded_rectangle(
            corners, radius * k, outline=255, width=stroke * k))
        layer.paste((*rgb(app, outline.get("color", "#FFFFFF")), 255), (0, 0), ring)
    return layer
