"""`snakelane translations`: which translated listing fields are stale or unreviewed.

    snakelane translations status [--app A] [--json]
    snakelane translations mark ja de-DE [--fields name,subtitle] [--reviewed]

snakelane doesn't translate: `mark` hashes `default/<field>.txt` and `<locale>/<field>.txt` into
`metadata/translations.json` (commit it). `status` reads each override as stale (default changed since),
unreviewed (marked, untouched since), current (`--reviewed` or hand-edited after) or untracked (no entry;
never assumed stale). Locales showing the default text are counted, not flagged.
Why: docs/design/foundations.md#translation-tracking
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

import typer

from .. import project
from ..args import AppOption, command_app, run
from .fields import TEXT_FIELDS, read_text

FIELDS = tuple(TEXT_FIELDS)
MANIFEST = "translations.json"


def digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


def manifest_path(folder: Path) -> Path:
    """Beside the shared listing it tracks; platform overrides are not tracked."""
    return folder / MANIFEST


def load_manifest(folder: Path) -> dict[str, Any]:
    path = manifest_path(folder)
    return json.loads(path.read_text()) if path.exists() else {}


def field_status(folder: Path, manifest: dict[str, Any], locale: str, field: str) -> str | None:
    """stale/unreviewed/current/untracked/default, or None when there is nothing to say."""
    source, translation = read_text(folder / "default" / f"{field}.txt"), read_text(folder / locale / f"{field}.txt")
    if translation is None:
        return "default" if source is not None else None
    if (entry := manifest.get(f"{locale}/{field}")) is None:
        return "untracked"
    if source is not None and digest(source) != entry["source"]:
        return "stale"
    return "current" if entry.get("reviewed") or digest(translation) != entry["translation"] else "unreviewed"


def statuses(folder: Path, locales: list[str]) -> dict[str, dict[str, str]]:
    manifest = load_manifest(folder)
    result: dict[str, dict[str, str]] = {}
    for locale in locales:
        for field in FIELDS:
            if (status := field_status(folder, manifest, locale, field)) is not None:
                result.setdefault(locale, {})[field] = status
    return result


def warn_stale(folder: Path, locales: list[str]) -> None:
    """For `store push`: one line when tracked translations need attention."""
    if not manifest_path(folder).exists():
        return
    flagged = [s for fields in statuses(folder, locales).values() for s in fields.values() if s in ("stale", "unreviewed")]
    if flagged:
        stale = flagged.count("stale")
        print(f"  warning: {stale} stale and {len(flagged) - stale} unreviewed translated field(s) — "
              "`snakelane translations status`")


def cmd_status(app: project.App, as_json: bool = False) -> None:
    locales = app.locales
    table = statuses(app.folder, locales)
    if as_json:
        print(json.dumps({locale: table.get(locale, {}) for locale in locales}, indent=2))
        return
    order = ("stale", "unreviewed", "untracked", "current")
    for locale in locales:
        fields = table.get(locale, {})
        line = ", ".join(f"{field}: {status}" for status in order for field, s in fields.items() if s == status)
        line = line or "no overrides"
        if inherited := [field for field, s in fields.items() if s == "default"]:
            line += f"  (default text: {', '.join(inherited)})"
        print(f"  {locale:8} {line}")
    counts = {s: sum(s == v for f in table.values() for v in f.values()) for s in order}
    print(f"{counts['stale']} stale, {counts['unreviewed']} unreviewed, {counts['untracked']} untracked, "
          f"{counts['current']} current")


def cmd_mark(app: project.App, locales: list[str], fields: list[str], reviewed: bool) -> None:
    folder = app.folder
    if unknown := [locale for locale in locales if locale not in app.locales]:
        raise SystemExit(f"not in snakelane.yml's \"locales\": {', '.join(unknown)}")
    manifest = load_manifest(folder)
    marked = 0
    for locale in locales:
        for field in fields:
            translation, source = read_text(folder / locale / f"{field}.txt"), read_text(folder / "default" / f"{field}.txt")
            if translation is not None and source is not None:
                manifest[f"{locale}/{field}"] = {"source": digest(source), "translation": digest(translation),
                                                 "reviewed": reviewed}
                marked += 1
    if not marked:
        raise SystemExit("nothing to mark: those locales have no override of a field that default/ also has")
    path = manifest_path(folder)
    path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    print(f"marked {marked} field(s) as {'reviewed' if reviewed else 'unreviewed'} in {path}")


cli = command_app("Track which translated listing fields are stale or unreviewed.")


@cli.command()
def status(app: AppOption = None,
           json_output: Annotated[bool, typer.Option("--json", help="print {locale: {field: state}} as JSON")] = False) -> None:
    """Each locale's translated fields: stale, unreviewed, current or untracked."""
    cmd_status(project.resolve_app(app), json_output)


@cli.command()
def mark(
    locales: Annotated[list[str], typer.Argument(help="locales whose overrides were just translated or reviewed")],
    app: AppOption = None,
    fields: Annotated[str, typer.Option("--fields", help="comma-separated fields")] = ",".join(FIELDS),
    reviewed: Annotated[bool, typer.Option("--reviewed", help="a person (or a review pass) has checked them")] = False,
) -> None:
    """Record what these locales' translations were made from."""
    chosen = [f.strip() for f in fields.split(",") if f.strip()]
    if bad := sorted(set(chosen) - set(FIELDS)):
        raise SystemExit(f"untracked field(s) {bad}; tracked: {', '.join(FIELDS)}")
    cmd_mark(project.resolve_app(app), locales, chosen, reviewed)


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane translations")
