"""`snakelane init [--dry-run] [--pull]`: snakelane.yml and a starter metadata/ for an Xcode project.

Guesses are printed with their source; the bundle id is the shortest non-test PRODUCT_BUNDLE_IDENTIFIER
(extensions append to it). Listing files are TODO placeholders `lint` refuses, so none can be pushed.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer

from . import project
from .args import command_app
from .args import run as run_cli

PLATFORMS = {"iphoneos": "ios", "macosx": "macos"}
PLACEHOLDERS = {
    "subtitle": "TODO: up to 30 characters",
    "description": "TODO: what the app does, for the App Store page.",
    "keywords": "TODO,comma,separated,no,spaces",
    "release_notes": "TODO: what changed in this version.",
    "support_url": "https://example.com/TODO/support",
    "privacy_url": "https://example.com/TODO/privacy",
}


def setting(source: str, key: str) -> list[str]:
    return [v.strip('"') for v in re.findall(rf"\b{key} = (\"[^\"]*\"|[^;]+);", source)]


def guess_bundle_id(source: str) -> str | None:
    ids = {b for b in setting(source, "PRODUCT_BUNDLE_IDENTIFIER") if "test" not in b.lower() and "$(" not in b}
    return min(ids, key=lambda b: (len(b), b), default=None)


def guess_scheme(xcodeproj: Path) -> tuple[str | None, list[str]]:
    schemes = sorted(p.stem for p in (xcodeproj / "xcshareddata" / "xcschemes").glob("*.xcscheme"))
    candidates = [s for s in schemes if "test" not in s.lower() and not s.lower().startswith("debug")]
    squash = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())  # noqa: E731
    match = next((s for s in candidates if squash(s) == squash(xcodeproj.stem)), None)
    return match or next(iter(candidates), None), schemes


def guess_platforms(source: str) -> list[str]:
    found = {PLATFORMS[p] for value in setting(source, "SUPPORTED_PLATFORMS") + setting(source, "SDKROOT")
             for p in value.split() if p in PLATFORMS}
    return sorted(found, key=["ios", "macos"].index) or ["ios"]


def config_text(name: str, bundle_id: str, scheme: str | None, team: str | None,
                platforms: list[str], project_line: str) -> str:
    return f"""# snakelane config — every key: skills/snakelane/references/config.md
# Written by `snakelane init`; check each value, then run `snakelane lint`.

name: {json.dumps(name)}
bundle_id: {json.dumps(bundle_id)}
# The numeric App Store id. Leave it empty until the app record exists; once set, snakelane
# refuses to touch any other app (Apple's bundle-id lookup is a prefix match).
apple_id: ""
scheme: {json.dumps(scheme or "TODO")}
team_id: {json.dumps(team or "TODO")}
{project_line}
locales: [en-US]
platforms: [{", ".join(platforms)}]

# categories:
#   primary: PRODUCTIVITY
#   secondary: UTILITIES

# screenshots:
#   devices: [iPhone 14 Plus, iPad Pro 13-inch (M5)]   # 6.5" iPhone and 13" iPad
"""


cli = command_app("Write snakelane.yml and a starter metadata/ for the repo's Xcode project.")


@cli.command()
def init_command(
    project_path: Annotated[str | None, typer.Option(
        "--project", help="the .xcodeproj to read, when the repo root has several")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="print what was found and would be written")] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite an existing snakelane.yml")] = False,
    pull: Annotated[bool, typer.Option(
        "--pull", help="then fill metadata/ from the live listing (needs the API key)")] = False,
) -> None:
    root = Path.cwd()
    config = root / project.CONFIG_NAME
    if config.exists() and not force:
        raise SystemExit(f"{config} already exists; pass --force to overwrite it")
    all_projects = sorted(root.glob("*.xcodeproj"))
    projects = [root / project_path] if project_path else all_projects
    if len(projects) != 1 or not projects[0].is_dir():
        raise SystemExit(f"need exactly one .xcodeproj at {root} "
                         f"(found: {', '.join(p.name for p in projects) or 'none'}); pass --project")
    xcodeproj = projects[0]
    source = (xcodeproj / "project.pbxproj").read_text()
    if not (bundle_id := guess_bundle_id(source)):
        raise SystemExit(f"no PRODUCT_BUNDLE_IDENTIFIER in {xcodeproj.name} that isn't a test target")
    scheme, schemes = guess_scheme(xcodeproj)
    team = next(iter(Counter(setting(source, "DEVELOPMENT_TEAM")).most_common(1)), (None,))[0]
    platforms = guess_platforms(source)
    name = scheme or xcodeproj.stem
    print(f"project    {xcodeproj.name}")
    print(f"bundle_id  {bundle_id}   (shortest non-test PRODUCT_BUNDLE_IDENTIFIER)")
    print(f"scheme     {scheme or '(none found: set it)'}   (shared schemes: {', '.join(schemes) or 'none'})")
    print(f"team_id    {team or '(none found: set it)'}   (DEVELOPMENT_TEAM)")
    print(f"platforms  {', '.join(platforms)}")
    project_line = f"project: {xcodeproj.name}\n" if len(all_projects) > 1 else ""
    # A platform folder is only for what differs from default/, so init writes none.
    default = root / "metadata" / "default"
    files = {config: config_text(name, bundle_id, scheme, team, platforms, project_line),
             default / "name.txt": name + "\n",
             **{default / f"{field}.txt": value + "\n" for field, value in PLACEHOLDERS.items()}}
    # Never overwrite listing text someone already wrote.
    kept = lambda path: path.exists() and path != config  # noqa: E731
    if dry_run:
        print("\nwould write:")
        for path in files:
            print(f"  {path.relative_to(root)}" + ("  (exists, kept)" if kept(path) else ""))
        return
    for path, content in files.items():
        if not kept(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print(f"wrote {path.relative_to(root)}")
    if pull:
        from .listing import store

        store.main(["pull"])
    else:
        print("\nnext: fill in metadata/default/*.txt (or `snakelane init --pull --force` for an app "
              "already on the store), then `snakelane lint`")


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane init")
