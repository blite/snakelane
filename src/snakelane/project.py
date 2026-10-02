"""Find the app repo snakelane is acting on, and the app inside it.

The repo is the nearest folder at or above the working directory holding a config, the way git
finds `.git`; `-C <dir>` or `--config <file>` override the walk.
Why: docs/design/foundations.md#find-the-repo-from-the-working-directory

Config: `snakelane.yml` for a repo with one app, `snakelane.<name>.yml` per app otherwise; pick one
with `--app <name|alias>` or `--config <file>`. Keys this module owns:

    "metadata"  the app's metadata folder, relative to the repo root (default "metadata")
    "name"      display name for log lines (default: the file's <name>)
    "project"   the .xcodeproj, relative to the repo root; optional when the root holds just one
    "scheme"    the app scheme, for test/archive
    "aliases"   extra names `--app` accepts (the file's <name> always works)

YAML is 1.2 (only `true`/`false` are booleans) and decimals stay text: `9.90` is "9.90", not 9.9.
Why: docs/design/foundations.md#decimals-stay-text-in-yaml
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.constructor import SafeConstructor

CONFIG_NAME = "snakelane.yml"
CONFIG_PATTERN = re.compile(r"snakelane(?:\.([A-Za-z0-9_-]+))?\.yml")
# Captures read may be PNG; every uploaded screenshot is JPEG. Why: docs/adr/0002-jpeg-only-screenshot-decks.md
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
DECK_SUFFIXES = (".jpg", ".jpeg")

# `--config <file>` (cli.py) sets this; it wins over discovery.
config_override: Path | None = None


class _TextDecimalConstructor(SafeConstructor):  # YAML 1.2 safe loading, decimals kept as written
    pass


_TextDecimalConstructor.add_constructor("tag:yaml.org,2002:float", lambda loader, node: loader.construct_scalar(node))


def dump_yaml(data: Any, header: str = "") -> str:
    yaml = YAML()  # round-trip: block style, keys in the order given, comments kept
    yaml.width = 100
    yaml.indent(mapping=2, sequence=4, offset=2)
    out = io.StringIO()
    yaml.dump(data, out)
    return header + out.getvalue()


def load_yaml(path: Path) -> Any:
    yaml = YAML(typ="safe", pure=True)
    yaml.Constructor = _TextDecimalConstructor
    try:
        return yaml.load(path.read_text())
    except Exception as error:  # ruamel's error types vary by version; all mean "bad file"
        raise SystemExit(f"{path}: not valid YAML — {error}") from None


def set_yaml_section(path: Path, key: str, value: Any, header: str = "") -> None:
    """Replace one top-level section, keeping the rest of the file and its comments."""
    if path.exists() and (data := YAML().load(path.read_text())) is not None:
        data[key] = value
        path.write_text(dump_yaml(data))
    else:
        path.write_text(dump_yaml({key: value}, header))


def configs_in(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("snakelane*.yml") if CONFIG_PATTERN.fullmatch(p.name))


def find_root(start: Path | None = None) -> Path:
    """`--config`'s folder, else the nearest folder at or above `start` with a config."""
    if config_override is not None:
        return config_override.resolve().parent
    here = (start or Path.cwd()).resolve()
    if found := next((c for c in (here, *here.parents) if configs_in(c)), None):
        return found
    raise SystemExit(f"no {CONFIG_NAME} (or snakelane.<app>.yml) at or above {here} — run snakelane from inside "
                     "an app repo, or pass -C <repo> or --config <file>")


@dataclass
class App:
    root: Path
    config_path: Path
    config: dict[str, Any] = field(repr=False)

    folder = property(lambda self: self.root / self.config.get("metadata", "metadata"))
    name = property(lambda self: self.config.get("name") or self.key or self.root.name)
    slug = property(lambda self: re.sub(r"[^a-z0-9]+", "-", (self.key or self.name).lower()).strip("-"))
    locales = property(lambda self: list(self.config.get("locales", [])))
    pbxproj = property(lambda self: self.project / "project.pbxproj")
    work_dir = property(lambda self: self.root / ".snakelane" / self.slug)  # gitignored
    # The deck a shoot replaces, kept until every pass succeeds; left over means it was killed.
    shoot_stash = property(lambda self: self.work_dir / "previous-shoot")

    @property
    def key(self) -> str:
        """The `<name>` of snakelane.<name>.yml, or "" for a plain snakelane.yml."""
        match = CONFIG_PATTERN.fullmatch(self.config_path.name)
        return (match.group(1) or "") if match else ""

    @property
    def primary_locale(self) -> str:
        """"primary_locale", else the first of "locales"; deckless locales inherit it."""
        return self.config.get("primary_locale") or (self.locales[0] if self.locales else "en-US")

    @property
    def scheme(self) -> str:
        if scheme := self.config.get("scheme"):
            return scheme
        raise SystemExit(f'{self.config_path} has no "scheme"')

    @property
    def project(self) -> Path:
        """"project", else the repo root's only .xcodeproj (never a guess)."""
        if named := self.config.get("project"):
            if not (path := self.root / named).exists():
                raise SystemExit(f'"project": {named!r} in {self.config_path.name} does not exist at {path}')
            return path
        found = sorted(self.root.glob("*.xcodeproj"))
        if len(found) == 1:
            return found[0]
        raise SystemExit(f'set "project" in {self.config_path} — the repo root holds '
                         f"{len(found)} .xcodeproj bundles ({', '.join(p.name for p in found) or 'none'})")

    def platform_dir(self, platform: str) -> Path:
        return self.folder / platform

    def refuse_if_shoot_was_killed(self) -> None:
        """So a half-shot deck never becomes the record."""
        if self.shoot_stash.exists():
            raise SystemExit(
                f"{self.shoot_stash} is left over from a shoot that was killed, and holds the deck "
                "from before it, mirrored by path from the repo root. Move its files back over the "
                f"current ones (e.g. `rsync -a {self.shoot_stash}/ {self.root}/`) — or delete it if "
                "the current deck is good — then try again.")

    def log_path(self, what: str) -> Path:
        """Fixed, so the bump log is findable after Xcode swallows post-action output."""
        return Path("/tmp") / f"snakelane-{self.slug}-{what}.log"


def runner_vars(env: dict[str, Any]) -> dict[str, str]:
    """Prefixed TEST_RUNNER_ so `xcodebuild test` hands them to the tests (it strips the prefix)."""
    return {k if k.startswith("TEST_RUNNER_") else f"TEST_RUNNER_{k}": str(v) for k, v in env.items()}


@dataclass(frozen=True)
class DeckTree:
    """Where one device class's screenshots live, for one platform.

        framed (what ships)   <metadata>/<platform>/screenshots/<locale>/<device>/
        raw (the captures)    <repo>/.snakelane/<slug>/raw/<platform>/<locale>/<device>/

    `device` is "iphone"/"ipad" for iOS, "" for a Mac deck (in the locale folder itself).
    Why raw is outside metadata/: docs/design/foundations.md#raw-captures-live-outside-metadata
    """

    app: App
    platform: str
    device: str = ""

    framed_base = property(lambda self: self.app.folder / self.platform / "screenshots")
    raw_base = property(lambda self: self.app.work_dir / "raw" / self.platform)
    deck = property(lambda self: self.device or "mac")  # iphone, ipad or mac

    def framed(self, locale: str) -> Path:
        return self.framed_base / locale / self.device

    def raw(self, locale: str) -> Path:
        return self.raw_base / locale / self.device

    def label(self) -> str:
        return f"{self.platform}/{self.device}" if self.device else self.platform

    @classmethod
    def for_deck(cls, app: App, deck: str) -> DeckTree:
        return cls(app, "macos") if deck == "mac" else cls(app, "ios", deck)


def device_deck(device_name: str) -> str:
    return "ipad" if "ipad" in device_name.lower() else "iphone"


def load_app(config_path: Path) -> App:
    if not isinstance(config := load_yaml(config_path) or {}, dict):
        raise SystemExit(f"{config_path}: expected a mapping of settings at the top level")
    return App(root=config_path.resolve().parent, config_path=config_path.resolve(), config=config)


def list_apps(root: Path) -> list[App]:
    return [load_app(path) for path in configs_in(root)]


def resolve_app(app_arg: str | None = None, root: Path | None = None) -> App:
    """The app `--config` or `--app` (a <name> or alias, any case) names, else the only one; never a guess."""
    if config_override is not None and root is None:
        if not config_override.is_file():
            raise SystemExit(f"--config {config_override}: no such file")
        return load_app(config_override)
    apps = list_apps(root or find_root())
    if app_arg is None:
        if len(apps) == 1:
            return apps[0]
        names = ", ".join(a.key or a.config_path.name for a in apps)
        raise SystemExit(f"this repo has {len(apps)} apps; pass --app ({names}) or --config <file>")
    wanted = app_arg.strip().lower()
    for app in apps:
        if wanted in {n.lower() for n in (app.key, app.name, *app.config.get("aliases", [])) if n}:
            return app
    known = sorted({n for a in apps for n in (a.key, *a.config.get("aliases", [])) if n})
    raise SystemExit(f"unknown --app {app_arg!r} — expected one of: {', '.join(known) or '(none named)'}")
