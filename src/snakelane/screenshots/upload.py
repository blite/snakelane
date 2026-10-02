"""`store screenshots push|show` and `store previews push`: each locale's deck mirrored to App
Store Connect, refused when it was shot from a developer build.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

from .. import project
from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import (
    find_app,
    find_editable_version,
    keyed,
    report_processing,
    upload_asset_resource,
    wait_for_asset_processing,
)
from ..terminal import dim, green, red
from .media import (
    DECK_SUFFIXES,
    PREVIEW_SUFFIXES,
    deck_dirs,
    deck_files,
    display_type_for,
    oversized_sets,
    preview_type_for,
    refuse_png_in_deck,
    screenshot_dimensions,
    size_warnings,
)

Plan = dict[str, dict[str, list[Path]] | None]  # locale -> slot -> files; None = no local opinion


class Kind(NamedTuple):
    noun: str        # "screenshot" / "preview"
    sets: str        # the set resource
    items: str       # the resource inside a set
    type_key: str    # the set's slot attribute
    stale: str       # how a stale set is named in messages


SCREENSHOTS = Kind("screenshot", "appScreenshotSets", "appScreenshots", "screenshotDisplayType", "set")
PREVIEWS = Kind("preview", "appPreviewSets", "appPreviews", "previewType", "preview set")


def offline_dry_run(plan: Plan, noun: str) -> bool:
    """With no credentials, a dry run prints the local plan, says so, and returns True.

    Why: docs/design/screenshots.md#a-dry-run-without-credentials-still-shows-the-local-plan"""
    if asc.Credentials.available():
        return False
    for locale, groups in plan.items():
        if groups is None:
            continue
        if not groups:
            print(f"  [dry-run] {locale}: no local {noun}s — every live {noun} set would be deleted")
        for slot, files in sorted(groups.items()):
            print(f"  [dry-run] {locale}/{slot}: {len(files)} file(s) — {', '.join(f.name for f in files)}")
    print(f"\n[dry-run] no API key set up (`snakelane auth setup`), so the live {noun} sets were "
          "not read: the plan above is local only (what would be uploaded, not what would be "
          "deleted first). Nothing was written.")
    return True


def mirror(client: asc.Client, app_config: dict[str, Any], platform: str, plan: Plan,
           kind: Kind) -> list[dict[str, Any]]:
    """Make each locale's live sets match `plan`; returns the uploads for the processing wait.

    ASC has no replace-in-place, so a kept set is emptied and refilled, and a set for a slot the
    deck no longer fills is deleted. Why: docs/design/screenshots.md#remote-mirrors-local"""
    version = find_editable_version(client, find_app(client, app_config)["id"], platform)
    asvls = keyed(client, f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")
    uploads: list[dict[str, Any]] = []
    for locale, by_type in plan.items():
        if by_type is None:
            continue
        if (asvl := asvls.get(locale)) is None:
            raise asc.ASCError(f"no AppStoreVersionLocalization for {locale}: add the language in App Store Connect")
        existing = [(asc.attributes(s).get(kind.type_key), s)
                    for s in client.get_all(f"/v1/appStoreVersionLocalizations/{asvl['id']}/{kind.sets}")]
        for slot, stale in existing:
            if slot in by_type:
                continue
            client.delete(f"/v1/{kind.sets}/{stale['id']}")
            client.report(f"  deleted stale {locale}/{slot} {kind.stale} {stale['id']}")
        for slot, group in sorted(by_type.items()):
            if current := next((s for t, s in existing if t == slot), None):
                for item in client.get_all(f"/v1/{kind.sets}/{current['id']}/{kind.items}"):
                    client.delete(f"/v1/{kind.items}/{item['id']}")
                    client.report(f"  deleted {locale}/{slot} {kind.noun} {item['id']}")
                set_id = current["id"]
            else:
                set_id = client.post(f"/v1/{kind.sets}", asc.resource_body(
                    kind.sets, {kind.type_key: slot}, relationships={"appStoreVersionLocalization": asc.relationship(
                        "appStoreVersionLocalizations", asvl["id"])}))["data"]["id"]
                client.report(f"  created {kind.sets[:-1]} {locale}/{slot} ({set_id})")
            for file in group:
                relationships = {kind.sets[:-1]: asc.relationship(kind.sets, set_id)}
                resource_id = upload_asset_resource(client, kind.items, file, relationships)
                client.report(f"  uploaded {file.name} -> {locale}/{slot}")
                uploads.append({"id": resource_id, "path": file, "relationships": relationships,
                                "label": f"{locale}/{slot}/{file.name}"})
    return uploads


def cmd_previews_push(args: SimpleNamespace) -> None:
    """Upload the App Previews in the deck directories, mirroring each locale's sets.

    Why a separate command: docs/design/screenshots.md#previews-and-screenshots-are-separate-pushes"""
    folder, app_config = deck_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    # The whole local plan first, so a bad encode fails before any live preview is deleted.
    plan: Plan = {}
    for locale in app_config["locales"]:
        if not (dirs := deck_dirs(folder / platform, locale)):
            print(f"  (no deck directory for {locale} — skipping)")
            plan[locale] = None
            continue
        # An empty map is an instruction: the sweep deletes every live set.
        # Why: docs/design/screenshots.md#an-empty-local-deck-deletes-the-live-sets
        plan[locale] = by_type = {}
        for file in deck_files(dirs, PREVIEW_SUFFIXES, "preview"):
            by_type.setdefault(preview_type_for(file, file.parent), []).append(file)
        if not by_type:
            print(f"  (no App Previews for {locale} — removing any that are live)")
    if args.dry_run and offline_dry_run(plan, "preview"):
        return
    client = asc.Client(dry_run=args.dry_run)
    uploads = mirror(client, app_config, platform, plan, PREVIEWS)
    if client.dry_run:
        print("\n[dry-run] no App Previews were changed.")
        return
    if not uploads:
        return
    print(f"\nwaiting for App Store Connect to process {len(uploads)} preview(s)…")
    # 20 minutes: a preview is transcoded, not just checksummed.
    complete, failed, timed_out = wait_for_asset_processing(
        client, "appPreviews", {r["id"]: r["label"] for r in uploads}, timeout=1200)
    for name in complete:
        print(f"✓ {name} processed")
    if not report_processing(failed, timed_out):
        raise SystemExit("App Preview upload did not complete cleanly")


def developer_chrome_check_available() -> bool:
    """Whether `snakelane check` can run here: macOS and the `snakelane[check]` extra.

    Checked up front because an import failure in the subprocess would also exit 1 ("chrome found")."""
    return sys.platform == "darwin" and importlib.util.find_spec("Vision") is not None


def refuse_developer_chrome(app_config: dict[str, Any], platform_dir: Path, locales: list[str],
                            allow: bool = False) -> None:
    """Stop the push if any shot was taken from a developer build, via a `snakelane check` subprocess.

    snakelane.yml's "developer_chrome_check" (documented in listing/store.py) decides what a missing
    extra means: true required, false off, absent best-effort.
    Why: docs/design/screenshots.md#the-push-runs-the-check-up-front-as-a-subprocess"""
    if (setting := app_config.get("developer_chrome_check")) is False:
        return
    # The upload's own rules, so an excluded file cannot block the push.
    files = [path for locale in locales
             for path in deck_files(deck_dirs(platform_dir, locale), DECK_SUFFIXES, "screenshot", quiet=True)]
    if not files:
        return
    if not developer_chrome_check_available():
        if setting is True and allow:
            print(red("  (developer-chrome check unavailable — uploading unchecked: "
                      "--allow-developer-chrome was passed)"))
        elif setting is True:
            raise SystemExit(
                'snakelane.yml sets "developer_chrome_check": true, but the check cannot run here '
                "(it needs macOS, the snakelane[check] extra — `uv tool install 'snakelane[check]'` or "
                "`uv sync --extra check` — and the `snakelane check` command). Refusing to upload an unchecked deck."
            )
        else:
            print(dim("  (developer-chrome check skipped: needs macOS and the snakelane[check] extra)"))
        return
    code = subprocess.run([sys.executable, "-m", "snakelane", "check", *map(str, files)], check=False).returncode
    if code == 0:
        return
    # 1 = developer chrome, 2 = unreadable; anything else is the checker failing, not the deck.
    problem = {1: "a shot carries developer chrome (see above)",
               2: "the check could not read every shot (see above)"}.get(
        code, f"the check itself failed (exit {code}), so the deck is unchecked")
    if allow:
        print(red(f"  ({problem} — uploading anyway: --allow-developer-chrome was passed)"))
        return
    raise SystemExit(f"refusing to upload: {problem}. Re-shoot from a build without the developer HUD (the "
                     "app's Release / Screenshots scheme), or pass --allow-developer-chrome if this really is intended")


def deck_app(app_arg: str | None) -> tuple[Path, dict[str, Any]]:
    """The app's folder and config, refused first (dry run included) if a killed shoot left a half-done deck."""
    app = project.resolve_app(app_arg)
    app.refuse_if_shoot_was_killed()
    return app.folder, app.config


def cmd_screenshots_push(args: SimpleNamespace) -> None:
    folder, app_config = deck_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    platform_dir = folder / platform
    locales: list[str] = app_config["locales"]
    # Before anything touches ASC, and before --dry-run gets a pass.
    refuse_developer_chrome(app_config, platform_dir, locales, allow=args.allow_developer_chrome)
    # The whole local plan first, so an unknown size fails before the first DELETE.
    plan: Plan = {}
    all_dimensions: list[tuple[int, int]] = []
    for locale in locales:
        if not (dirs := deck_dirs(platform_dir, locale)):
            print(f"  (no screenshots under {platform_dir / 'screenshots' / locale} — skipping {locale}; "
                  "the App Store shows the primary language's)")
            plan[locale] = None
            continue
        refuse_png_in_deck(dirs)  # skipped, a PNG would be deleted from the store
        # The suffix filter lets an App Preview (`ap-01.m4v`) share the folder.
        if previews := [p for d in dirs for p in d.iterdir() if p.suffix.lower() in PREVIEW_SUFFIXES]:
            print(f"  (not uploading {len(previews)} App Preview(s) here — they are a separate ASC resource: "
                  "`snakelane store previews push`)")
        plan[locale] = by_type = {}  # empty: the sweep deletes every live set
        for file in deck_files(dirs, DECK_SUFFIXES, "screenshot"):
            all_dimensions.append(dimensions := screenshot_dimensions(file))
            by_type.setdefault(display_type_for(file, dimensions), []).append(file)
        if not by_type:
            print(f"  (no screenshots for {locale} — removing any that are live)")
    # Before the dry run returns, and before the first DELETE.
    for warning in size_warnings(all_dimensions):
        print(f"  warning: {warning}")
    if oversized := oversized_sets(plan):
        raise SystemExit("too many screenshots in a set:\n  " + "\n  ".join(oversized)
                         + "\nRemove or underscore-prefix (`_ss-11.jpg`) the extras.")
    if args.dry_run and offline_dry_run(plan, "screenshot"):
        return
    client = asc.Client(dry_run=args.dry_run)
    uploads = mirror(client, app_config, platform, plan, SCREENSHOTS)
    if client.dry_run:
        print("\n[dry-run] no screenshots were changed.")
        return
    if uploads and not verify_screenshot_processing(client, uploads):
        raise SystemExit("Screenshots push finished WITH FAILURES — see above.")
    print("\nScreenshots push complete.")


def cmd_screenshots_show(args: SimpleNamespace) -> None:
    """The live screenshot and App Preview sets, per locale, and the files in each (read only)."""
    _folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    client = asc.Client()
    version = find_editable_version(client, find_app(client, app_config)["id"], platform)
    print(f"--- ASC screenshot + preview sets for {app_config['bundle_id']} ({platform}) ---")
    asvls = keyed(client, f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")
    for locale in app_config["locales"]:
        print(f"  [{locale}]")
        if (asvl := asvls.get(locale)) is None:
            print("    (no AppStoreVersionLocalization for this locale yet)")
            continue
        found = [(kind, prefix, list(client.get_all(f"/v1/appStoreVersionLocalizations/{asvl['id']}/{kind.sets}")))
                 for kind, prefix in ((SCREENSHOTS, ""), (PREVIEWS, "preview "))]
        if not any(sets for _, _, sets in found):
            print("    (none)")
        for kind, prefix, sets in found:
            for live in sets:
                names = [asc.attributes(s).get("fileName")
                         for s in client.get_all(f"/v1/{kind.sets}/{live['id']}/{kind.items}")]
                print(f"    {prefix}{asc.attributes(live).get(kind.type_key)}: "
                      f"{len(names)} — {', '.join(str(n) for n in names)}")


def verify_screenshot_processing(client: asc.Client, uploads: list[dict[str, Any]]) -> bool:
    """Wait until Apple accepts every uploaded screenshot, re-uploading rejects once; report the rest in red."""
    print(f"\nwaiting for App Store Connect to process {len(uploads)} screenshot(s)…")
    # By resource id, never file name: every locale has an ss-01.jpg.
    # Why: docs/design/screenshots.md#processing-is-verified-and-rejects-are-retried-once
    pending = {record["id"]: record["label"] for record in uploads}
    complete, failed, timed_out = wait_for_asset_processing(client, "appScreenshots", pending)
    if failed:
        by_id = {record["id"]: record for record in uploads}
        retry: dict[str, str] = {}
        for label, resource_id, errors in failed:
            print(red(f"✗ {label}: rejected by Apple ({errors}) — retrying once"))
            client.delete(f"/v1/appScreenshots/{resource_id}")
            record = by_id[resource_id]
            retry[upload_asset_resource(client, "appScreenshots", record["path"], record["relationships"])] = label
        retried_ok, failed, retry_timed_out = wait_for_asset_processing(client, "appScreenshots", retry)
        complete += retried_ok
        timed_out += retry_timed_out
    if not report_processing(failed, timed_out):
        return False
    print(green(f"✓ verified: Apple accepted all {len(complete)} screenshot(s)"))
    return True
