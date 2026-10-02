"""Small builders shared by the tests: a repo with a snakelane.yml and metadata/, listing files, real images."""

from __future__ import annotations

from pathlib import Path

from snakelane import project

ROOT = Path(__file__).resolve().parents[1]  # the repo


def make_app(root: Path, **config: object) -> project.App:
    """A repo at `root` with a snakelane.yml of `config` over sensible defaults, and its
    metadata/ folder."""
    defaults = {"name": "Example", "bundle_id": "com.example.app", "locales": ["en-US"], "platforms": ["ios"]}
    (root / "metadata" / "default").mkdir(parents=True, exist_ok=True)
    (root / project.CONFIG_NAME).write_text(project.dump_yaml({**defaults, **config}))
    return project.resolve_app(None, root=root)


def write(app: project.App, locale: str, field: str, text: str, platform: str | None = None) -> Path:
    """A listing file: shared (metadata/<locale>/) unless `platform` names an override."""
    path = (app.folder / platform if platform else app.folder) / locale / f"{field}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def image(path: Path, width: int, height: int) -> Path:
    """A real, solid-colour image of that size, PNG or JPEG by suffix: a few KB, whatever the
    dimensions."""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (width, height), "white").save(path)
    return path
