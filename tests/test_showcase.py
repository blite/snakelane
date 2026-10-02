"""Every theme renders with every layout and caption shape; with SNAKELANE_WRITE_SHOWCASE=1 the
same renders become the docs' showcase images (docs/assets/framing/)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from snakelane import project
from snakelane.screenshots import frame
from snakelane.screenshots.framing.style import LAYOUTS, SHAPES
from snakelane.screenshots.framing.themes import THEMES, VARIATIONS

from .helpers import ROOT, make_app

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

SIZE = (642, 1389)  # half a 6.5" iPhone shot: quick, and the proportions are the real ones
SHOWCASE = ROOT / "docs" / "assets" / "framing"
WRITE = os.environ.get("SNAKELANE_WRITE_SHOWCASE") == "1"

# Each theme in the layout and caption its app used. Docs: docs/reference/framing.md.
PAIRINGS: dict[str, dict] = {
    "felt": {"layout": "full-bleed", "caption": {"shape": "arch", "depth": 0.158}},
    "ruby": {"layout": "full-bleed", "caption": {"shape": "arch", "depth": 0.158}},
    "evergreen": {"layout": "full-bleed", "caption": {"depth": 0.11}},
    "coral": {"layout": "full-bleed", "caption": {"shape": "arch", "depth": 0.154, "arch": 0.02}},
    "walnut": {"layout": "full-bleed", "caption": {"depth": 0.12}},
    "moss": {"layout": "full-bleed", "caption": {"depth": 0.10}},
    "parchment": {"layout": "full-bleed", "caption": {"shape": "arch", "depth": 0.17, "arch": -0.03}},
    "indigo": {"layout": "stacked", "caption": {"depth": 0.10}},
    "campfire": {"layout": "stacked", "fit": "crop", "caption": {"depth": 0.08, "align": "left", "margin": 50}},
    "azure": {"layout": "device", "caption": {"depth": 0.24}},
    "dusk": {"layout": "device", "device": {"bleed": True, "width": 0.86},
             "caption": {"depth": 0.17, "align": "left", "margin": 56}},
}
CAPTION = "Every ==hike==,\nlogged"


def fake_screen(path: Path, landscape: bool = False) -> None:
    """A stand-in app screen: a title bar and cards, so a layout's crop shows."""
    im = Image.new("RGB", SIZE, "#EEF1F5")
    d = ImageDraw.Draw(im)
    w, h = SIZE
    d.rectangle((0, 0, w, round(h * 0.06)), fill="#D9DEE6")
    for i in range(5):
        top = round(h * (0.14 + i * 0.15))
        d.rounded_rectangle((40, top, w - 40, top + round(h * 0.12)), 24, fill="#FFFFFF", outline="#C8CFDA", width=3)
        d.rounded_rectangle((70, top + 30, 70 + round(h * 0.06), top + 30 + round(h * 0.06)), 14, fill="#4F8A5B")
    if landscape:  # a wide layout: a row of tall cards and a side bar, as a landscape app draws
        w, h = SIZE[1], SIZE[0]
        im = Image.new("RGB", (w, h), "#EEF1F5")
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, round(w * 0.08), h), fill="#D9DEE6")
        for i in range(6):
            left = round(w * (0.12 + i * 0.145))
            d.rounded_rectangle((left, 60, left + round(w * 0.12), h - 60), 24, fill="#FFFFFF", outline="#C8CFDA", width=3)
            d.rounded_rectangle((left + 24, 90, left + 24 + round(w * 0.05), 90 + round(w * 0.05)), 14, fill="#4F8A5B")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def key_art(path: Path) -> None:
    """Stand-in key art: a sky over hills, with its subject low in the frame."""
    w, h = SIZE[0] * 2, SIZE[1]
    im = Image.new("RGB", (w, h), "#8EC5F2")
    d = ImageDraw.Draw(im)
    for i, colour in enumerate(("#6FA86B", "#4F8A5B", "#3B6E47")):
        top = round(h * (0.55 + i * 0.1))
        d.ellipse((-w // 2 + i * w // 3, top, w + i * w // 4, top + h), fill=colour)
    d.ellipse((w // 2 - 90, round(h * 0.62), w // 2 + 90, round(h * 0.62) + 180), fill="#F2B544")
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def render(tmp_path: Path, name: str, framing: dict, landscape: bool = False, art: bool = False) -> Image.Image:
    app = make_app(tmp_path / name, screenshots={"frame": "snakelane",
                                                 "framing": {"captions": {"1": CAPTION}, **framing}})
    raw = project.DeckTree.for_deck(app, "iphone").raw("en-US") / "ss-01.png"
    if art:
        key_art(raw)
    else:
        fake_screen(raw, landscape)
    frame.frame_deck(app, "en-US")
    with Image.open(project.DeckTree.for_deck(app, "iphone").framed("en-US") / "ss-01.jpg") as out:
        assert out.size == SIZE
        return out.copy()


def save(image: Image.Image, name: str, full_size: bool = False) -> None:
    """A showcase image, at half the render's size unless it's a sheet."""
    SHOWCASE.mkdir(parents=True, exist_ok=True)
    if not full_size:
        image = image.resize((image.width // 2, image.height // 2), Image.LANCZOS)
    image.save(SHOWCASE / name, quality=85, optimize=True)


def sheet(images: list[Image.Image], columns: int, labels: list[str]) -> Image.Image:
    thumb = (214, 463)
    rows = -(-len(images) // columns)
    out = Image.new("RGB", (columns * (thumb[0] + 16) + 16, rows * (thumb[1] + 56) + 16), "#FFFFFF")
    d = ImageDraw.Draw(out)
    for i, (im, label) in enumerate(zip(images, labels, strict=True)):
        x, y = 16 + (i % columns) * (thumb[0] + 16), 16 + (i // columns) * (thumb[1] + 56)
        out.paste(im.resize(thumb, Image.LANCZOS), (x, y))
        d.text((x, y + thumb[1] + 8), label, fill="#222222", font_size=20)
    return out


def test_every_theme_and_variation_in_its_pairing(tmp_path: Path) -> None:
    looks = {**{name: name for name in THEMES}, **VARIATIONS}
    assert set(PAIRINGS) == set(looks), "every theme and variation has a showcase pairing"
    for name, theme in looks.items():
        image = render(tmp_path, name, {**PAIRINGS[name], "theme": theme})
        if WRITE:
            save(image, f"theme-{name}.jpg")


def test_themes_use_different_type() -> None:
    fonts = [(t["font"], t["font_face"]) for name, t in THEMES.items() if name != "ruby"]  # ruby: felt's colourway
    assert len(set(fonts)) == len(fonts), "a theme that only recolours another belongs in VARIATIONS"


def test_every_layout_takes_every_caption_shape(tmp_path: Path) -> None:
    images, labels = [], []
    for layout in LAYOUTS:
        for shape in SHAPES:
            caption = {"shape": shape, "depth": 0.14}
            if shape == "callout":
                caption["callout"] = {"centre": 0.5}
            images.append(render(tmp_path, f"{layout}-{shape}", {"layout": layout, "theme": "felt", "caption": caption}))
            labels.append(f"{layout} · {shape}")
            if WRITE:
                save(images[-1], f"layout-{layout}-{shape}.jpg")
    if WRITE:
        save(sheet(images, len(SHAPES), labels), "layouts.jpg", full_size=True)


EXTRAS = {
    "bottom-band": ({"layout": "full-bleed", "theme": "evergreen", "caption": {"position": "bottom", "depth": 0.11}}, False),
    "bottom-arch": ({"layout": "full-bleed", "theme": "felt", "caption": {"position": "bottom", "shape": "arch",
                                                                          "depth": 0.158}}, False),
    "landscape-callout": ({"layout": "full-bleed", "theme": "felt",
                           "slots": {"1": {"rotate": 90, "caption": {"shape": "callout"}}}}, True),
    "device-bottom": ({"layout": "device", "theme": "azure", "caption": {"position": "bottom", "depth": 0.2}}, False),
    "inline-marks": ({"layout": "stacked", "theme": {"base": "parchment", "colors": {"moss": "#4F7A3A"}},
                      "captions": {"1": ["**Every** *hike*,", "==logged== [offline]{moss}"]}, "caption": {"depth": 0.17}},
                     False),
    "key-art": ({"layout": "full-bleed", "theme": "campfire", "targets": {"iphone": list(SIZE)}, "caption": {"depth": 0.08, "align": "left", "margin": 50},
                 "slots": {"1": {"bias": 0.62}}}, False),
}


def test_bottom_captions_and_turned_captures(tmp_path: Path) -> None:
    for name, (framing, landscape) in EXTRAS.items():
        image = render(tmp_path, name, framing, landscape, art=name == "key-art")
        if WRITE:
            save(image, f"extra-{name}.jpg")


def test_the_showcase_page_shows_every_image() -> None:
    import re

    page = (ROOT / "docs" / "showcase.md").read_text()
    shown = set(re.findall(r"assets/framing/([\w.-]+\.jpg)", page))
    expected = ({f"theme-{n}.jpg" for n in PAIRINGS} | {f"extra-{n}.jpg" for n in EXTRAS}
                | {f"layout-{layout}-{shape}.jpg" for layout in LAYOUTS for shape in SHAPES})
    assert shown == expected, (sorted(expected - shown), sorted(shown - expected))
    on_disk = {p.name for p in SHOWCASE.glob("*.jpg")} - {"layouts.jpg"}
    assert on_disk == expected, "regenerate with SNAKELANE_WRITE_SHOWCASE=1 uv run --group dev pytest tests/test_showcase.py"


def test_a_theme_preview_leaves_the_deck_alone(tmp_path: Path) -> None:
    app = make_app(tmp_path, screenshots={"frame": "snakelane", "framing": {"captions": {"1": "One"}}})
    fake_screen(project.DeckTree.for_deck(app, "iphone").raw("en-US") / "ss-01.png")
    frame.frame_deck(app, "en-US", theme="dusk")
    assert not project.DeckTree.for_deck(app, "iphone").framed("en-US").exists()
    assert (app.work_dir / "themes" / "dusk" / "iphone" / "en-US" / "ss-01.jpg").exists()


def test_a_theme_is_overridden_key_by_key(tmp_path: Path) -> None:
    from snakelane.screenshots.framing.style import theme_of

    theme = theme_of({"base": "felt", "fill": "#123456"})
    assert theme.fill == "#123456" and theme.lip == THEMES["felt"]["lip"] and theme.case == "upper"


def test_a_device_card_bleeds_off_the_bottom(tmp_path: Path) -> None:
    out = render(tmp_path, "bleed", {"layout": "device", "theme": "dusk", "caption": {"depth": 0.17},
                                     "device": {"bleed": True, "width": 0.86}})
    bottom_middle = out.getpixel((SIZE[0] // 2, SIZE[1] - 3))
    assert sum(bottom_middle) > 600, "the card's light screen reaches the bottom edge"

