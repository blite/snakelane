"""Regenerate the command output in docs/assets/terminal/ (and docs/assets/gallery.png).

    uv run python scripts/terminal_shots.py            # everything
    uv run python scripts/terminal_shots.py lint gallery   # only these (names as in SHOTS)

Each capture is a real `snakelane` run against a copy of examples/trailhead or examples/two-apps,
saved as plain text that the docs include in a code block, so it stays readable and searchable. Only commands that stay offline are used, and HOME points at an empty
temporary folder while they run, so no API key can be found and nothing can reach App Store
Connect even by mistake. The copy lives in a temporary folder, so the examples are never
touched.

The lint and translations shots run against a copy with a few problems planted in it (an
over-long subtitle, Android named in the German promotional text, an English description
changed after its German translation was marked), because a clean run makes a dull picture.

The gallery screenshot needs Google Chrome in /Applications; it is skipped without it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from rich.text import Text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "terminal"
EXAMPLES = ROOT / "examples"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
WIDTH = 124

# name → (args after `snakelane`, which copy to run in: "clean" or "flawed" trailhead, or "two-apps")
SHOTS: dict[str, tuple[list[str], str]] = {
    "help": (["--help"], "clean"),
    "lint": (["lint"], "flawed"),
    "store-push-dry-run": (["store", "push", "--app", "pro", "--dry-run"], "two-apps"),
    "screenshots-push-dry-run": (["store", "screenshots", "push", "--dry-run"], "clean"),
    "translations-status": (["translations", "status"], "flawed"),
    "frame-list-themes": (["frame", "--list-themes"], "clean"),
    "bump-post-action": (["bump", "--post-action"], "clean"),
}


def plant_problems(repo: Path) -> None:
    """Things lint and translations should catch."""
    default = repo / "metadata" / "default"
    (default / "subtitle.txt").write_text("Hike logs, offline maps and trail notes\n")
    (repo / "metadata" / "de-DE" / "promotional_text.txt").write_text(
        "Neu: Höhenprofile für jede Wanderung. Bald auch für Android.\n")
    # The English source moves on after the German translation was marked.
    description = default / "description.txt"
    description.write_text(description.read_text().replace(
        "Mark water, campsites and viewpoints as you go",
        "Mark water, campsites, huts and viewpoints as you go"))


def run(args: list[str], cwd: Path, home: Path) -> str:
    env = {**os.environ, "HOME": str(home), "FORCE_COLOR": "1", "COLUMNS": str(WIDTH),
           "TERM": "xterm-256color"}
    env.pop("NO_COLOR", None)
    result = subprocess.run(["uv", "run", "--project", str(ROOT), "snakelane", *args], cwd=cwd,
                            env=env, capture_output=True, text=True, timeout=120)
    return result.stdout + result.stderr


def render(name: str, args: list[str], output: str) -> Path:
    path = OUT / f"{name}.txt"
    lines = [line.rstrip() for line in Text.from_ansi(output.rstrip("\n")).plain.splitlines()]
    path.write_text("\n".join([f"$ snakelane {' '.join(args)}", *lines]) + "\n")
    return path


def gallery(clean: Path, home: Path, scratch: Path) -> None:
    if not CHROME.exists():
        print("skipped gallery.png: no Google Chrome in /Applications")
        return
    bundle = scratch / "gallery"
    print(run(["gallery", "--bundle", str(bundle)], clean, home).strip())
    shot = scratch / "gallery.png"
    chrome = subprocess.Popen(
        [str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,1600",
         f"--user-data-dir={scratch / 'chrome'}", f"--screenshot={shot}", (bundle / "index.html").as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        chrome.wait(timeout=60)  # headless Chrome sometimes writes the file and never exits
    except subprocess.TimeoutExpired:
        chrome.kill()
    if not shot.exists():
        print("skipped gallery.png: Chrome wrote no screenshot")
        return
    from PIL import Image

    # The top of the page (the en-US mocks and the iPad deck), trimmed to its content, halved.
    target = ROOT / "docs" / "assets" / "gallery.png"
    trimmed(Image.open(shot).convert("RGB").crop((0, 0, 1280, 1120)), 2).save(target, optimize=True)
    print(f"wrote {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)")


def trimmed(image, shrink: int = 1):
    """`image` without the page background around its content (plus a small margin)."""
    from PIL import Image, ImageChops

    # Content is anything that is neither the page background nor a card's white.
    mask = None
    for colour in (image.getpixel((2, image.height - 2)), (255, 255, 255)):
        diff = ImageChops.difference(image, Image.new("RGB", image.size, colour)).convert("L").point(lambda v: 255 * (v > 12))
        mask = diff if mask is None else ImageChops.darker(mask, diff)
    box = mask.getbbox()
    if box:
        image = image.crop((max(0, box[0] - 16), max(0, box[1] - 16), min(image.width, box[2] + 16),
                            min(image.height, box[3] + 16)))
    return image.resize((image.width // shrink, image.height // shrink), Image.LANCZOS)


def main(only: list[str]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="snakelane-shots-") as tmp:
        scratch = Path(tmp)
        home = scratch / "home"
        home.mkdir()
        repos = {"clean": scratch / "trailhead", "flawed": scratch / "flawed" / "trailhead",
                 "two-apps": scratch / "two-apps"}
        for repo in repos.values():
            shutil.copytree(EXAMPLES / repo.name, repo)
        plant_problems(repos["flawed"])
        for name, (args, repo) in SHOTS.items():
            if only and name not in only:
                continue
            output = run(args, repos[repo], home)
            # A temp path in the output would change on every run.
            output = output.replace(str(repos[repo].resolve()), f"~/{repos[repo].name}")
            output = output.replace(str(repos[repo]), f"~/{repos[repo].name}")
            if "auth setup" in output and "dry-run" not in output:
                sys.exit(f"{name}: wanted an API key, so it isn't offline:\n{output}")
            print(f"wrote {render(name, args, output).relative_to(ROOT)}")
        if not only or "gallery" in only:
            gallery(repos["clean"], home, scratch)


if __name__ == "__main__":
    main(sys.argv[1:])
