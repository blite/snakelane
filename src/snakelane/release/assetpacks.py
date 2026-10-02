"""Apple-hosted Background Assets packs: the metadata, and the archives built from it.

A pack is content Apple hosts and the app downloads after install, reviewed on its own; not an
in-app purchase, though one may unlock it.

    snakelane packs list | package <theme> | status [<theme>]
    snakelane packs upload --dry-run
    snakelane packs upload <theme> [<theme> …] [--new-version]

`package` stages files so each archive path equals its app-bundle path, then runs `ba-package`.
Pack ids and contents are permanent from the first upload; `upload` needs a person at a TTY (no
`--yes`). Why: docs/design/release.md#background-assets-packs

snakelane.yml "asset_packs" block:
    "manifests"        (required) repo-relative folder of <theme>/pack.json.
    "bundle_path"      (required) where a pack's files live in the app bundle, with {theme}.
    "content_root"     repo-relative base for pictureSource (default: repo root).
    "record"           hosted-pack record, relative to the app folder (default "ios/asset_packs.json").
    "build_dir"        repo-relative output folder (default "build/asset-packs").

pack.json (ships in the binary): snakelane reads assetPackID, delivery ("backgroundAsset" when hosted),
pictureSource, imageExtension (default "heic"), items[].resourceName (one <name>.<ext> each), productID
and tier ("free" is never priced), and writes contentVersion. The record: {"platforms": ["iOS", …],
"packs": [{"asset_pack_id", "theme", "available_from_version" (the release that enables it; upload
refuses null), "pictures", "archive_bytes", "uploaded", "apple_version"}]}.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer

from .. import project
from ..args import AppOption, command_app
from ..args import run as run_cli
from ..connect import asc
from ..project import App
from ..terminal import green, red

MAX_PACKS_PER_SUBMISSION = 10
BA_PLATFORMS = {"ios": "iOS", "macos": "macOS", "tvos": "tvOS", "visionos": "visionOS"}
# altool reports the version App Store Connect assigned among its `= KEY: value` summary lines.
APPLE_VERSION = re.compile(r"^=\s*ASSET PACK VERSION:\s*(\d+)\s*$", re.MULTILINE)


@dataclass
class Packs:
    """One app's asset-pack layout, from snakelane.yml's "asset_packs"."""

    app: App
    manifests: Path
    bundle_path: str
    content_root: Path
    record: Path
    build: Path

    @classmethod
    def load(cls, app: App) -> Packs:
        if not isinstance(config := app.config.get("asset_packs"), dict):
            raise SystemExit(
                f'{app.config_path} has no "asset_packs" block; `snakelane packs --help` '
                "and this module's docstring list its keys (at least \"manifests\" and \"bundle_path\")"
            )
        for key in ("manifests", "bundle_path"):
            if not config.get(key):
                raise SystemExit(f'"asset_packs" in {app.config_path} needs "{key}"')
        if "{theme}" not in config["bundle_path"]:
            raise SystemExit('"asset_packs.bundle_path" must contain {theme}')
        return cls(app, app.root / config["manifests"], config["bundle_path"].strip("/"),
                   content_root=app.root / config.get("content_root", "."),
                   record=app.folder / config.get("record", "ios/asset_packs.json"),
                   build=app.root / config.get("build_dir", "build/asset-packs"))

    def rel(self, path: Path) -> Path:  # for messages
        try:
            return path.resolve().relative_to(self.app.root)
        except ValueError:
            return path

    def in_bundle(self, theme: str) -> Path:
        return Path(self.bundle_path.format(theme=theme))

    def read_record(self) -> dict[str, Any]:
        if not self.record.exists():
            raise SystemExit(f"no asset pack record at {self.rel(self.record)}")
        return json.loads(self.record.read_text())

    def archive_for(self, asset_pack_id: str) -> Path:
        return self.build / f"{asset_pack_id}.aar"

    def pack(self, theme: str) -> dict[str, Any]:
        if not (manifest := self.manifests / theme / "pack.json").exists():
            raise SystemExit(f"no pack at {self.rel(manifest)}")
        return json.loads(manifest.read_text())


def picture_source(theme: str, pack: dict[str, Any]) -> str:
    if not (relative := pack.get("pictureSource")):
        raise SystemExit(f"{theme}/pack.json has no pictureSource, so there is no folder to package from")
    return relative


def stage(packs: Packs, theme: str, pack: dict[str, Any]) -> tuple[Path, list[str]]:
    """Mirror the bundled layout under a staging root; return it and its selectors.

    Why: docs/design/release.md#path-equivalence-and-the-staging-tree"""
    extension = pack.get("imageExtension", "heic")
    source_dir = packs.content_root / picture_source(theme, pack)
    if not source_dir.is_dir():
        raise SystemExit(f"{theme}: pictureSource {packs.rel(source_dir)} is not a folder")
    root, relative = packs.build / "stage" / theme, packs.in_bundle(theme)
    if root.exists():
        shutil.rmtree(root)
    (root / relative).mkdir(parents=True)
    selectors, missing = [], []
    for name in filter(None, (item.get("resourceName") for item in pack.get("items", []))):
        if not (source := source_dir / f"{name}.{extension}").exists():
            missing.append(name)
            continue
        try:
            os.link(source, root / relative / source.name)  # same filesystem: no second copy of the bytes
        except OSError:
            shutil.copy2(source, root / relative / source.name)
        selectors.append(str(relative / source.name))
    if missing:  # pack contents cannot be edited after upload, so a short archive is an error
        raise SystemExit(
            f"{len(missing)} file(s) named by pack.json are not in {packs.rel(source_dir)}:\n  "
            + "\n  ".join(missing[:10]) + ("\n  …" if len(missing) > 10 else "")
        )
    if not selectors:
        raise SystemExit(f"{theme}/pack.json names no items with a resourceName; nothing to package")
    return root, selectors


def manifest_platforms(packs: Packs) -> list[str]:
    """The record's `platforms`, not snakelane.yml's; a ratchet (ITMS-91148).

    Why: docs/design/release.md#platforms-are-a-ratchet"""
    if not (declared := packs.read_record().get("platforms")):
        raise SystemExit(f"{packs.rel(packs.record)} declares no `platforms`")
    if unknown := [p for p in declared if p.lower() not in BA_PLATFORMS]:
        raise SystemExit(
            f"{packs.rel(packs.record)} names platform(s) Background Assets does not take: {', '.join(unknown)}"
        )
    return [BA_PLATFORMS[p.lower()] for p in declared]


def cmd_package(packs: Packs, theme: str) -> None:
    pack = packs.pack(theme)
    if pack.get("delivery") != "backgroundAsset":
        raise SystemExit(f"{theme} is delivery={pack.get('delivery', 'bundled')}; only a hosted pack is packaged, "
                         "since a bundled one already ships inside the app")
    root, selectors = stage(packs, theme, pack)
    if not (asset_pack_id := pack.get("assetPackID")):
        raise SystemExit(f"{theme}/pack.json declares no assetPackID")
    manifest = packs.build / f"{asset_pack_id}.manifest.json"
    manifest.write_text(json.dumps({
        "assetPackID": asset_pack_id,
        "downloadPolicy": {"onDemand": {}},
        "fileSelectors": [{"file": path} for path in selectors],
        "platforms": manifest_platforms(packs),
    }, indent=2) + "\n")
    (archive := packs.archive_for(asset_pack_id)).unlink(missing_ok=True)
    subprocess.run(["xcrun", "ba-package", "package", str(manifest), "-o", str(archive)], cwd=root, check=True)

    # Read the archive back: its paths must mirror the bundle and its file count match pack.json.
    listing = subprocess.run(["xcrun", "aa", "list", "-i", str(archive)],
                             capture_output=True, text=True, check=True).stdout.splitlines()
    payload = [line for line in listing if line.endswith(f".{pack.get('imageExtension', 'heic')}")]
    if stray := [line for line in payload if not line.startswith(f"Contents/{packs.in_bundle(theme).as_posix()}/")]:
        raise SystemExit("archive paths do not mirror the bundled layout, so a downloaded pack would resolve "
                         "differently from a bundled one:\n  " + "\n  ".join(stray[:5]))
    if len(payload) != len(selectors):
        raise SystemExit(f"archive holds {len(payload)} files, pack.json names {len(selectors)}")
    print(f"  paths mirror the bundle: {payload[0]}\n  files: {len(payload)} (matches pack.json)")
    print(green(f"  ✓ {theme}: archive verified"))
    print(f"\n{packs.rel(archive)}  —  {archive.stat().st_size / 1_000_000:.1f} MB")
    print(f"asset pack id: {asset_pack_id}  (frozen at first upload)")
    print("\nServe it to a device — its own terminal, because the keychain prompts:")
    print(f"  xcrun ba-serve serve {packs.rel(archive)} --host <ip> --port 63748")
    print("\nThen upload it — from your own terminal, because the confirmation is typed:")
    print(f"  snakelane packs upload {theme}")


def show(packs: Packs) -> None:
    """What is hosted, what ships when, and what has been uploaded."""
    if not (rows := packs.read_record().get("packs", [])):
        return print(f"no hosted packs in {packs.rel(packs.record)}")
    width = max(len(r["asset_pack_id"]) for r in rows)
    print(f"{len(rows)} hosted packs — {packs.rel(packs.record)}\n")
    for row in sorted(rows, key=lambda r: (r.get("available_from_version") or "zzz", r["asset_pack_id"])):
        size = f"{row['archive_bytes'] / 1_000_000:.0f} MB" if row.get("archive_bytes") else "unmeasured"
        state = "uploaded" if row.get("uploaded") else "not uploaded"
        print(f"  {row['asset_pack_id']:<{width}}  {row.get('available_from_version') or '—':<4}  "
              f"{row.get('pictures', '?'):>3} items  {size:>11}  {state}")
    print("\nasset pack ids freeze at first upload.")


def apple_id(packs: Packs) -> str:
    """The numeric App Store Connect app id from snakelane.yml."""
    if not (value := str(packs.app.config.get("apple_id") or "")).isdigit():
        raise SystemExit(f'no numeric "apple_id" in {packs.app.config_path}')
    return value


def altool_auth_flags() -> list[str]:
    """altool takes no .p8 path, only a search for AuthKey_<id>.p8, so API_PRIVATE_KEYS_DIR pins it."""
    credentials = asc.Credentials.load()
    os.environ["API_PRIVATE_KEYS_DIR"] = str(credentials.key_path.parent)
    return ["--apiKey", credentials.key_id, "--apiIssuer", credentials.issuer_id]


def rows_for(packs: Packs, themes: list[str]) -> list[dict[str, Any]]:
    """Rows named by theme or id, or by default every unsent pack with an archive.

    Why only unsent: docs/design/release.md#only-unsent-packs-by-default"""
    rows = packs.read_record().get("packs", [])
    if not themes:
        return [row for row in rows if packs.archive_for(row["asset_pack_id"]).exists() and not row.get("uploaded")]
    named = {row["asset_pack_id"]: row for row in rows} | {row["theme"]: row for row in rows}  # themes win
    if unknown := next((name for name in themes if name not in named), None):
        raise SystemExit(f"{unknown} is not in {packs.rel(packs.record)}")
    return [named[name] for name in themes]


def upload(packs: Packs, themes: list[str], dry_run: bool, new_version: bool) -> None:
    """Send built archives after a typed confirmation.

    Why: docs/design/release.md#upload-needs-a-person-at-a-terminal"""
    if not (chosen := rows_for(packs, themes)):
        raise SystemExit(f"no unsent .aar in {packs.rel(packs.build)} — run `snakelane packs package <theme>` first")
    problems, plan = [], []
    for row in chosen:
        if not (archive := packs.archive_for(row["asset_pack_id"])).exists():
            problems.append(f"{row['theme']}: no archive — run `snakelane packs package {row['theme']}`")
            continue
        if not row.get("available_from_version"):
            problems.append(
                f"{row['asset_pack_id']}: available_from_version is null, so no release enables it — "
                "set it in the record before uploading, because the id freezes here"
            )
        elif row.get("uploaded") and not new_version:
            problems.append(
                f"{row['asset_pack_id']}: already uploaded. A second send is a new *version* of a live "
                "pack, not a retry — pass --new-version if that is what you mean, and re-package first "
                "so the archive is not the one already delivered"
            )
        else:
            plan.append((row, archive))
    if problems:
        raise SystemExit("\n".join(problems))
    if len(plan) > MAX_PACKS_PER_SUBMISSION:
        raise SystemExit(f"{len(plan)} archives, but App Store Connect takes {MAX_PACKS_PER_SUBMISSION} per submission")

    app_id = apple_id(packs)
    print(f"App Store Connect app {app_id} — {len(plan)} archive(s):\n")
    width = max(len(row["asset_pack_id"]) for row, _ in plan)
    for row, archive in plan:
        again = ""
        if row.get("uploaded"):
            was = f"{row['archive_bytes'] / 1_000_000:.1f} MB" if row.get("archive_bytes") else "unmeasured"
            again = f"  RE-UPLOAD (was {was}, live pack, no way to withdraw)"
        print(f"  {row['asset_pack_id']:<{width}}  {archive.stat().st_size / 1_000_000:>6.1f} MB  "
              f"from {row['available_from_version']}{again}")
    if dry_run:
        return print("\n--dry-run: nothing was uploaded and no credentials were read.")
    # No --yes, on purpose: an agent or CI job must not start a review on someone's behalf.
    if not sys.stdin.isatty():
        raise SystemExit(
            "\nupload needs a terminal: an approved asset pack replaces live content for every user and "
            "there is no staging to hold it behind, so the confirmation is typed by a person. Run it "
            "yourself, or use --dry-run."
        )
    print("\nAn approved asset pack version replaces the previous one for every user, "
          "and there is no way to withdraw it.")
    if input('Type "upload" to send: ').strip() != "upload":
        raise SystemExit("nothing uploaded.")

    flags = altool_auth_flags()
    for done, (row, archive) in enumerate(plan):
        print(f"\n=== {archive.name}")
        # Streamed and captured: the upload is slow, and the assigned version is only in the output.
        process = subprocess.Popen(
            ["xcrun", "altool", "--upload-asset-pack", str(archive), "--apple-id", app_id, *flags],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        captured = []
        for line in process.stdout:  # type: ignore[union-attr]
            print(line, end="")
            captured.append(line)
        if returncode := process.wait():
            # altool printed its own diagnosis. Stop: the packs of one submission go together.
            print(red(f"\n✗ altool failed on {row['asset_pack_id']} (exit {returncode}); "
                      "nothing was marked uploaded for it."))
            if sent := [r["asset_pack_id"] for r, _ in plan[:done]]:
                print(f"already sent this run: {', '.join(sent)}")
            if remaining := [r["asset_pack_id"] for r, _ in plan[done + 1:]]:
                print(f"not attempted: {', '.join(remaining)}")
            raise SystemExit(1)
        found = APPLE_VERSION.search("".join(captured))
        mark_uploaded(packs, row, int(found.group(1)) if found else None, archive)
        print(green(f"  ✓ {row['asset_pack_id']}: uploaded{f' as version {found.group(1)}' if found else ''}"))
    print(green(f"\n✓ {len(plan)} pack(s) uploaded and marked in {packs.rel(packs.record)}."))
    print("Processing takes hours and a successful upload is not availability. Before you submit the")
    print('build, confirm each pack appears under "Items to Review" in App Store Connect — a reviewer')
    print("who gets a pack that is still processing sees a failed download, which is a 2.1 rejection.")
    print("\n  snakelane packs status")


def mark_uploaded(packs: Packs, row: dict[str, Any], apple_version: int | None, archive: Path) -> None:
    """Record `uploaded`, the size and Apple's version, and set the manifest's contentVersion to it.

    Why: docs/design/release.md#contentversion-is-apples-asset-pack-version"""
    doc = packs.read_record()
    if entry := next((c for c in doc["packs"] if c["asset_pack_id"] == row["asset_pack_id"]), None):
        entry.update(uploaded=True, archive_bytes=archive.stat().st_size)
        if apple_version is not None:
            entry["apple_version"] = apple_version
    packs.record.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    theme = row["theme"]
    if apple_version is None:
        return print("  could not read the assigned version out of altool's output; "
                     f"set contentVersion for {theme} by hand")
    if not (manifest := packs.manifests / theme / "pack.json").exists():
        return print(f"  no manifest at {packs.rel(manifest)}; contentVersion not set")
    text = manifest.read_text()
    if (current := json.loads(text).get("contentVersion")) == apple_version:
        return
    # Textual, so the file's formatting and key order are untouched.
    if (updated := re.sub(r'("contentVersion"\s*:\s*)\d+', rf"\g<1>{apple_version}", text, count=1)) == text:
        return print(f"  {packs.rel(manifest)} has no contentVersion to set")
    manifest.write_text(updated)
    print(f"  {theme}: contentVersion {current} -> {apple_version} (ships with the next build)")


def status(packs: Packs, theme: str | None) -> None:
    """List the asset packs App Store Connect holds. Read-only."""
    app_id, flags = apple_id(packs), altool_auth_flags()
    subprocess.run(["xcrun", "altool", "--list-asset-packs", "--apple-id", app_id, *flags], check=True)
    if theme:
        pack_id = rows_for(packs, [theme])[0]["asset_pack_id"]
        print(f"\n=== versions of {pack_id}")
        subprocess.run(["xcrun", "altool", "--list-asset-pack-versions", "--apple-id", app_id,
                        "--asset-pack-identifier", pack_id, *flags], check=True)


cli = command_app("Package and upload Apple-hosted Background Assets packs. Configured by the "
                  "config's asset_packs block (see release/assetpacks.py).")


def packs_for(app: str | None) -> Packs:
    return Packs.load(project.resolve_app(app))


@cli.command("list")
def list_packs(app: AppOption = None) -> None:
    """Show the hosted packs and their upload state."""
    show(packs_for(app))


@cli.command()
def package(theme: Annotated[str, typer.Argument(help="a folder under the manifests folder, e.g. animals")],
            app: AppOption = None) -> None:
    """Build one pack's .aar, locally."""
    cmd_package(packs_for(app), theme)


@cli.command("upload")
def upload_packs(
    themes: Annotated[list[str] | None, typer.Argument(
        help="themes or asset pack ids; default: every unsent archive")] = None,
    app: AppOption = None,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="print what would be sent; no credentials, no terminal")] = False,
    new_version: Annotated[bool, typer.Option(
        "--new-version", help="allow sending a pack already marked uploaded")] = False,
) -> None:
    """Send built .aar archives to App Store Connect (asks in a terminal; there is no --yes)."""
    upload(packs_for(app), themes or [], dry_run, new_version)


@cli.command("status")
def status_packs(theme: Annotated[str | None, typer.Argument(help="also list this pack's versions")] = None,
                 app: AppOption = None) -> None:
    """List the asset packs App Store Connect holds."""
    status(packs_for(app), theme)


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane packs")
