"""File an .xcresult's screenshot attachments into the deck tree `store media push` uploads from.

`shoot` calls `extract_deck()` after every pass. The UI test attaches `NN-Name` (raw, to `.snakelane/<app>/raw/…`) and optionally `NN-Name_framed`
(to `metadata/<platform>/screenshots/<locale>/<device>/`, what ships).
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from ..project import DeckTree
from .media import save_jpeg

# "<NN-Name>[_framed]_<seq>_<UUID>.png" from `xcresulttool export attachments`; `01-Home` -> `ss-01.jpg`.
# Why: docs/design/screenshots.md#shot-names-may-contain-hyphens
NAME_RE = re.compile(r"^([0-9]{2})-[A-Za-z][A-Za-z0-9-]*(_framed)?_\d+_[0-9A-F-]{36}\.png$")


def capture_problem(image: Image.Image, deck: str) -> str | None:
    """Why a capture can't be a screenshot, or None. A passing test can still attach nothing: a Mac
    window on a second display captured as a small white rectangle, and the shoot filed seven of them
    over the previous deck.
    Why: docs/design/screenshots.md#a-blank-capture-fails-the-shoot"""
    low, high = image.convert("L").getextrema()
    if low == high:
        return f"one flat colour ({low}): nothing was captured"
    if deck == "mac" and (image.width < 1280 or image.height < 800):
        return f"{image.width}x{image.height}, under the smallest Mac size App Store Connect takes (1280x800)"
    return None


def stage(attachments_dir: Path, dirs: dict[str, Path], deck: str = "") -> dict[str, int]:
    """Route each attachment into `dirs["raw"]` or `dirs["framed"]` by its `_framed` suffix. Exits,
    before filing anything, when a capture is blank or too small (see `capture_problem`)."""
    stats = {"raw": 0, "framed": 0, "unknown": 0}
    # A retried test leaves both attempts' captures: the newest of each slot is the passing one.
    # Why: docs/design/screenshots.md#a-hung-shot-is-cut-off-and-retried
    latest: dict[tuple[str, str], tuple[float, str]] = {}
    for node in json.loads((attachments_dir / "manifest.json").read_text()):
        for attachment in node.get("attachments", []):
            if not (match := NAME_RE.match(attachment.get("suggestedHumanReadableName", ""))):
                stats["unknown"] += 1
                continue
            slot, when = ("framed" if match[2] else "raw", match[1]), attachment.get("timestamp") or 0.0
            if slot not in latest or when >= latest[slot][0]:
                latest[slot] = (when, attachment["exportedFileName"])
    problems = []
    for (kind, number), (_, exported) in sorted(latest.items()):
        with Image.open(attachments_dir / exported) as image:
            if problem := capture_problem(image, deck):
                problems.append(f"  ss-{number} ({kind}): {problem}")
    if problems:
        raise SystemExit("the test passed but its captures can't be screenshots:\n" + "\n".join(problems)
                         + ("\n  a Mac window on a second display captures blank: open it on the primary one"
                            " (the skill's ScreenshotWindowSizer does)" if deck == "mac" else ""))
    for (kind, number), (_, exported) in latest.items():
        # JPEG, not the PNG it arrived as: ASC rejects the alpha channel captures carry.
        # Named by slot only: docs/design/screenshots.md#files-are-named-by-slot-only
        with Image.open(attachments_dir / exported) as image:
            save_jpeg(image, dirs[kind] / f"ss-{number}.jpg")
        stats[kind] += 1
    return stats


def extract_deck(xcresult: Path, tree: DeckTree, locale: str = "en-US", label: str = "") -> dict[str, int]:
    """Export one bundle's shots into `tree` and print a summary; exit when it held none
    (an empty folder handed to the push would delete the live sets)."""
    if not xcresult.exists():
        raise SystemExit(f"xcresult not found at {xcresult}")
    with tempfile.TemporaryDirectory(prefix="snakelane-shots-") as tmpdir:
        out = Path(tmpdir) / "attachments"
        out.mkdir(parents=True)
        subprocess.run(["xcrun", "xcresulttool", "export", "attachments", "--path", str(xcresult),
                        "--output-path", str(out)], check=True)
        stats = stage(out, {"raw": tree.raw(locale), "framed": tree.framed(locale)}, tree.deck)
    print(f"[{label or xcresult.stem}] raw={stats['raw']} framed={stats['framed']} "
          f"unknown={stats['unknown']} → {tree.framed(locale)}")
    if stats["raw"] + stats["framed"] == 0:
        raise SystemExit(f"no NN-Name attachments in {xcresult} — did the screenshot test run, "
                         "and does it name its attachments `NN-Name` / `NN-Name_framed`?")
    return stats

