"""`framing.decorate`: the app's own code drawing over its framed shots.

    screenshots:
      framing:
        decorate: tools/screenshot_decorate.py      # repo-relative

The file defines `decorate(image, shot)`. snakelane calls it once per framed shot, after the
caption is drawn and before the JPEG is written, with the RGB canvas and a `Shot`; it returns
the image to save (the same size), or `None` to leave the shot as it was. It runs in
snakelane's Python, so it can use the standard library and Pillow and nothing else.

This is for art that belongs to one app and no other — badge cards, a sticker, an arrow at a
control — so it lives in that app's repo instead of becoming a theme option here.
Why: docs/design/framing.md#app-art-is-the-apps-code
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from ...project import App
from .draw import rgb
from .style import Theme


@dataclass(frozen=True)
class Shot:
    """What the hook knows about the shot it's decorating. Sizes are canvas pixels."""

    slot: int                        # the shot's number, ss-NN
    locale: str                      # the ASC locale being framed, e.g. "de-DE"
    deck: str                        # "iphone", "ipad" or "mac"
    size: tuple[int, int]            # the canvas, width x height
    capture: tuple[int, int, int, int]   # (x, y, width, height) of the capture on the canvas; a
                                     # bleeding device card's box runs past the bottom edge
    caption: str                     # the caption as written, marks and all
    colors: dict[str, tuple[int, int, int]] = field(default_factory=dict)  # text, accent, plus the theme's named colours
    font: str | None = None          # the theme's font file, when it sets one
    root: Path = Path(".")           # the app repo, for the hook's own assets


Hook = Callable[[Any, Shot], Any]


def load(app: App, cfg: dict[str, Any]) -> Hook | None:
    """The configured hook, or None. Fails loudly: a hook that silently didn't run ships a deck
    without the art the app expected."""
    if not (rel := cfg.get("decorate")):
        return None
    path = app.root / str(rel)
    if not path.is_file():
        raise SystemExit(f'snakelane.yml "screenshots.framing.decorate": {path} does not exist')
    spec = importlib.util.spec_from_file_location(f"snakelane_decorate_{path.stem}", path)
    module: ModuleType = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    hook = getattr(module, "decorate", None)
    if not callable(hook):
        raise SystemExit(f"{path}: define decorate(image, shot) for framing.decorate")
    return hook


def shot_for(app: App, theme: Theme, **kwargs: Any) -> Shot:
    colors = {name: rgb(app, value) for name, value in (theme.colors or {}).items()}
    colors["text"] = rgb(app, theme.text)
    colors["accent"] = rgb(app, theme.accent if theme.accent is not None else theme.text)
    return Shot(colors=colors, font=theme.font, root=app.root, **kwargs)


def apply(hook: Hook | None, image: Any, shot: Shot, source: str) -> Any:
    """Run the hook on one framed image; `source` names the hook in errors."""
    if hook is None:
        return image
    out = hook(image, shot)
    if out is None:
        return image
    if getattr(out, "size", None) != image.size:
        raise SystemExit(f"{source}: decorate() returned {getattr(out, 'size', type(out).__name__)} "
                         f"for ss-{shot.slot:02d} ({shot.deck}, {shot.locale}); it must keep {image.size}")
    return out.convert("RGB")
