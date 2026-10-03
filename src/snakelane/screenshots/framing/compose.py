"""One framed shot: the capture placed by the layout, the caption drawn over or beside it.

    full-bleed  capture fills the canvas, caption over it (the app keeps that strip empty); `bias` moves the crop
    stacked     caption beside the capture, scaled to fit (fit: scale) or filling the width (fit: crop)
    device      the capture as a rounded card on the theme's background, clear of the caption
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from ...project import App
from .draw import callout_layer, caption_band, card, flipped, ink_of, paint, px, with_shadow
from .style import Style

CROP_WARN = 0.04  # share of either axis lost to a centre crop before we say so


def resize_to(im, target: tuple[int, int], pad: bool, ink: tuple[int, int, int]):
    """Bring a capture to exactly `target`, and say what that cost."""
    tw, th = target
    if (im.width, im.height) == target:
        return im, "native"
    scale_cover = max(tw / im.width, th / im.height)
    scale = min(tw / im.width, th / im.height) if pad else scale_cover
    w, h = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    scaled = im.resize((w, h), Image.LANCZOS)
    note = f"from {im.width}x{im.height}" + ("  UPSCALED, will look soft" if scale_cover > 1 else "")
    if pad:
        out = Image.new("RGB", target, ink)
        out.paste(scaled, ((tw - w) // 2, (th - h) // 2))
        return out, note + (f"  padded {abs(tw - w)}x{abs(th - h)}px" if (w, h) != target else "")
    if (lost := max((w - tw) / w if w > tw else 0.0, (h - th) / h if h > th else 0.0)) > 0:
        note += f"  cropped {lost:.1%}"
        if lost > CROP_WARN:
            note += " — check nothing important is at the edges, or set fit: scale"
    left, top = (w - tw) // 2, (h - th) // 2
    return scaled.crop((left, top, left + tw, top + th)), note


def open_capture(src: Path, style: Style):
    # Upright first, so `rotate` counts from what a viewer sees (XCUIScreen turns via EXIF).
    shot = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if style.rotate:
        shot = shot.rotate(style.rotate, expand=True)  # anticlockwise, as Pillow and the docs count
    return shot


def compose(app: App, style: Style, src: Path, caption: str, target: tuple[int, int] | None):
    """The framed shot, a note for the log, and the capture's box on the canvas as (x, y, width,
    height); with a bleeding device card the box runs past the canvas edge."""
    shot = open_capture(src, style)
    tw, th = target = target or (shot.width, shot.height)
    if (shot.width > shot.height) != (tw > th) and shot.width != shot.height:
        raise SystemExit(
            f"  {src.name}: {shot.width}x{shot.height} is "
            f"{'landscape' if shot.width > shot.height else 'portrait'}, and the deck is "
            f"{'landscape' if tw > th else 'portrait'}. Turn it with the slot's `rotate`, or re-shoot.")
    theme, bottom = style.theme, style.bottom
    ink = ink_of(app, theme)
    callout = style.caption.shape == "callout"
    band, depth = (None, 0) if callout else caption_band(app, style, caption, tw, th, ink)
    start = 0 if bottom else depth  # where the capture's share of the canvas begins
    if style.layout == "full-bleed" and style.bias is not None:
        # Cover, with the vertical crop biased (0 top … 1 bottom): key art's interest is often low.
        scale = max(tw / shot.width, th / shot.height)
        resized = shot.resize((round(shot.width * scale), round(shot.height * scale)), Image.LANCZOS)
        top, left = round((resized.height - th) * style.bias), (resized.width - tw) // 2
        canvas = resized.crop((left, top, left + tw, top + th)).convert("RGBA")
        note = f"cover from {shot.width}x{shot.height}"
        box = (-left, -top, resized.width, resized.height)
    elif style.layout == "full-bleed":
        resized, note = resize_to(shot, target, style.fit == "scale", ink)
        canvas = resized.convert("RGBA")
        box = (0, 0, tw, th)
    elif style.layout == "stacked" and style.fit == "crop":
        # Fill the width and crop the end away from the caption.
        # Why: docs/design/framing.md#fill-width-crops-the-far-end
        board = shot.resize((tw, round(shot.height * tw / shot.width)), Image.LANCZOS)
        board = board.crop((0, 0, tw, min(board.height, th - depth)))
        canvas = paint(app, theme.background, target, ink).convert("RGBA")
        canvas.alpha_composite(board.convert("RGBA"), (0, start))
        note = f"fill-width from {shot.width}x{shot.height}"
        box = (0, start, board.width, board.height)
    elif style.layout == "stacked":  # scaled into the rest, so the caption covers no content
        resized, note = resize_to(shot, (tw, th - depth), True, ink)
        canvas = paint(app, theme.background, target, ink).convert("RGBA")
        canvas.alpha_composite(resized.convert("RGBA"), ((tw - resized.width) // 2, start))
        box = ((tw - resized.width) // 2, start, resized.width, resized.height)
    else:
        canvas, note, box = device(app, style, shot, target, depth, ink)
    if callout:
        with_shadow(app, style.caption.callout.get("shadow", theme.shadow), canvas,
                    callout_layer(app, style, caption, target, ink))
        note += "  callout"
    else:
        # A headline is bare type; its shadow is the theme's text_shadow, not the band's.
        shadow = None if style.caption.shape == "headline" else theme.shadow
        with_shadow(app, flipped(shadow) if bottom else shadow, canvas, band,
                    (0, th - band.height) if bottom else (0, 0))
    out = canvas.convert("RGB")
    assert out.size == target, (out.size, target)
    return out, note, box


def device(app: App, style: Style, shot, target: tuple[int, int], depth: int, ink):
    """The capture as a card in the canvas the caption leaves: with `bleed` it keeps its width and
    runs off the far edge; without, it shrinks to fit."""
    tw, th = target
    settings, bleed = style.device, style.device.get("bleed")
    gap = px(settings.get("gap", 0.02), th)
    area = th - depth - 2 * gap
    width = round(tw * float(settings.get("width", 0.84)))
    height = round(shot.height * width / shot.width)
    if not bleed and height > area:
        width, height = round(width * area / height), area
    scaled = shot.resize((width, height), Image.LANCZOS)
    x = (tw - width) // 2
    if bleed:
        y = th - depth - gap - height if style.bottom else depth + gap
    else:
        y = (0 if style.bottom else depth) + gap + (area - height) // 2
    canvas = paint(app, style.theme.background, target, ink).convert("RGBA")
    layer = card(app, style, scaled, th)
    box = (x, y, width, height)
    if y < 0:  # bleeding off the top: only the visible part, so its cut edge stays straight
        layer, y = layer.crop((0, -y, width, height)), 0
    with_shadow(app, style.theme.shadow, canvas, layer, (x, y))
    return canvas, f"device {width}x{height} from {shot.width}x{shot.height}", box
