"""`gamecenter images show|push`: the achievement, leaderboard and activity images in Xcode's
`.gamekit` bundle, uploaded to App Store Connect, which Xcode's own sync leaves out.

Where an image lives on ASC (an app in a Game Center group keeps its records on the group, not
on the app's `gameCenterDetail`):

    achievement   gameCenterAchievementsV2 → /v2/…/versions (newest) → localizations[locale] → image
    leaderboard   gameCenterLeaderboardsV2 → /v2/…/versions (newest) → localizations[locale] → image
    activity      gameCenterActivities     → /v1/…/versions (newest) → defaultImage

Records, versions and localizations are never created here, except a new version with
`--new-version`: Xcode's sync makes the records, and an image change on a record whose newest
version is LIVE needs a new version, which then goes to review with the next app version.
Why: docs/design/gamecenter.md#a-live-version-is-not-edited-in-place
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, NamedTuple

from .. import project
from ..connect import asc
from ..connect.resources import (
    fetch_image_asset,
    find_app,
    get_optional,
    report_processing,
    upload_asset_resource,
    wait_for_asset_processing,
)
from ..terminal import dim, green, red
from . import gamekit
from .gamekit import Image

# A version in one of these takes a new image; Apple's GameCenterVersionState.
EDITABLE = {"PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW", "REJECTED", "DEVELOPER_REJECTED"}


class Kind(NamedTuple):
    records: str        # the relationship on a gameCenterDetail / gameCenterGroup
    record_type: str
    versions_api: str   # "v2" for achievements and leaderboards, "v1" for activities
    version_type: str
    image_type: str
    image_api: str


KINDS = {
    "achievement": Kind("gameCenterAchievementsV2", "gameCenterAchievements", "v2",
                        "gameCenterAchievementVersions", "gameCenterAchievementImages", "v2"),
    "leaderboard": Kind("gameCenterLeaderboardsV2", "gameCenterLeaderboards", "v2",
                        "gameCenterLeaderboardVersions", "gameCenterLeaderboardImages", "v2"),
    "activity": Kind("gameCenterActivities", "gameCenterActivities", "v1",
                     "gameCenterActivityVersions", "gameCenterActivityImages", "v1"),
}


@dataclass
class Target:
    """One local image and where it lands; `status` is new, changed, unchanged or skip."""

    image: Image
    status: str = "skip"
    reason: str = ""
    record: dict[str, Any] | None = None
    version: dict[str, Any] | None = None
    parent: dict[str, Any] | None = None       # the localization, or the activity version itself
    live: dict[str, Any] | None = None         # the image ASC holds now
    new_version: bool = False                  # the newest version is LIVE: make one first
    uploaded: list[str] = field(default_factory=list)

    @property
    def kind(self) -> Kind:
        return KINDS[self.image.kind]


def newest(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return max(versions, key=lambda v: asc.attributes(v).get("version") or 0, default=None)


def status_for(live: dict[str, Any] | None, same: bool | None) -> str:
    """new (nothing live), unchanged (same pixels) or changed: a live image that failed or never
    finished processing has no pixels to compare, so it is replaced."""
    if live is None:
        return "new"
    return "unchanged" if same else "changed"


def version_problem(version: dict[str, Any] | None, allow_new_version: bool) -> tuple[str | None, bool]:
    """(why this version can't take an image, or None; whether a new version must be made first)."""
    if version is None:
        return "no version on App Store Connect", False
    state = asc.attributes(version).get("state")
    number = asc.attributes(version).get("version")
    if state in EDITABLE:
        return None, False
    if state == "LIVE":
        if allow_new_version:
            return None, True
        return (f"version {number} is LIVE and ASC doesn't edit a live version; pass --new-version to "
                "make version " f"{(number or 0) + 1} (it goes to review with the next app version)"), False
    return f"version {number} is {state}: wait until it is live, then push with --new-version", False


def owner(client: asc.Client, app_config: dict[str, Any]) -> tuple[str, str, str]:
    """(path prefix, label, group note) for whatever holds the records: the group, else the detail."""
    app = find_app(client, app_config)
    if (detail := get_optional(client, f"/v1/apps/{app['id']}/gameCenterDetail")) is None:
        raise SystemExit(f"Game Center isn't enabled for {app_config['bundle_id']} on App Store Connect")
    if group := get_optional(client, f"/v1/gameCenterDetails/{detail['id']}/gameCenterGroup"):
        name = asc.attributes(group).get("referenceName")
        return f"/v1/gameCenterGroups/{group['id']}", f"Game Center group {name!r}", "grp."
    return f"/v1/gameCenterDetails/{detail['id']}", "the app's Game Center detail", ""


def image_path(target: Target) -> str:
    """Where the image under `target.parent` is read."""
    if target.image.kind == "activity":
        return f"/v1/gameCenterActivityVersions/{target.parent['id']}/defaultImage"
    return f"/v2/{target.kind.record_type[:-1]}Localizations/{target.parent['id']}/image"


def image_relationships(target: Target) -> dict[str, Any]:
    if target.image.kind == "activity":
        return {"version": asc.relationship("gameCenterActivityVersions", target.parent["id"])}
    return {"localization": asc.relationship(f"{target.kind.record_type[:-1]}Localizations", target.parent["id"])}


def find_parent(client: asc.Client, target: Target) -> dict[str, Any] | None:
    """The version's localization for the image's locale (an activity's default image hangs off the
    version itself)."""
    if target.image.kind == "activity":
        return target.version
    path = f"/v2/{target.kind.version_type}/{target.version['id']}/localizations"
    return next((loc for loc in client.get_all(path) if asc.attributes(loc).get("locale") == target.image.locale),
                None)


def plan(client: asc.Client, app_config: dict[str, Any], images: list[Image],
         allow_new_version: bool) -> tuple[list[Target], str]:
    """Each local image against what ASC holds; read-only."""
    prefix, holder, grp = owner(client, app_config)
    records = {kind: {asc.attributes(r).get("vendorIdentifier"): r for r in client.get_all(f"{prefix}/{k.records}")}
               for kind, k in KINDS.items()}
    targets = []
    for image in images:
        targets.append(target := Target(image))
        if not image.path.is_file():
            target.reason = f"no file at {image.path}"
            continue
        if (record := records[image.kind].get(image.vendor_id)) is None:
            hint = f" (ids in a group start {grp!r})" if grp and not image.vendor_id.startswith(grp) else ""
            target.reason = f"no such {image.kind} on App Store Connect yet{hint} — sync the .gamekit from Xcode first"
            continue
        target.record = record
        versions = list(client.get_all(f"/{target.kind.versions_api}/{target.kind.record_type}/{record['id']}/versions"))
        target.version = newest(versions)
        problem, target.new_version = version_problem(target.version, allow_new_version)
        if target.version is not None and (parent := find_parent(client, target)) is not None:
            target.parent = parent
            target.live = get_optional(client, image_path(target))
        elif target.version is not None:
            problem = problem or f"no {image.locale} localization on App Store Connect — add it in Xcode and sync"
        live_pixels = fetch_image_asset(asc.attributes(target.live)) if target.live else None
        target.status = status_for(target.live, live_pixels is not None and gamekit.same_pixels(image.path, live_pixels))
        if problem and target.status != "unchanged":
            was = f"{target.status}, not uploaded: " if target.parent else ""
            target.status, target.reason = "skip", was + problem
        if target.status == "unchanged":
            target.new_version = False
    return targets, holder


def print_plan(targets: list[Target]) -> None:
    for t in targets:
        version = asc.attributes(t.version or {})
        where = dim(f"  (version {version.get('version')} {version.get('state')})") if t.version else ""
        if t.status == "skip":
            print(red(f"  ✗ {t.image.label}: {t.reason}"))
        elif t.status == "unchanged":
            print(dim(f"  = {t.image.label}: unchanged") + where)
        else:
            via = f", into a new version {(version.get('version') or 0) + 1}" if t.new_version else ""
            line = f"  {'+' if t.status == 'new' else '~'} {t.image.label}: {t.status}{via}"
            print((green(line) if t.status == "new" else line) + where)


def make_version(client: asc.Client, target: Target) -> None:
    """A new version of a record whose newest is LIVE; ASC copies the live one's localizations and
    image into it, so the parent and live image are read again from the new one."""
    kind, rel = target.kind, target.image.kind
    created = client.post(f"/{kind.versions_api}/{kind.version_type}", asc.resource_body(
        kind.version_type, {}, relationships={rel: asc.relationship(kind.record_type, target.record["id"])}))["data"]
    client.report(f"  created {target.image.kind} {target.image.vendor_id} version {created['id']}")
    target.version, target.new_version = created, False
    if asc.planned(created["id"]):
        print(dim(f"  [dry-run] then: delete the {target.image.locale or 'default'} image ASC copies into the new "
                  "version from the live one, and upload this file in its place"))
        target.parent = None
        return
    target.parent = find_parent(client, target)
    target.live = get_optional(client, image_path(target)) if target.parent else None


def push_one(client: asc.Client, target: Target) -> bool:
    """Delete the old image (one per localization), then upload; a failed upload after the delete is
    shouted, since the record is left with no image. False when nothing could be uploaded."""
    if target.new_version:
        make_version(client, target)
        if target.parent is None:
            if not client.dry_run:
                print(red(f"  ✗ {target.image.label}: the new version has no {target.image.locale} localization — "
                          "nothing uploaded; add it in App Store Connect and re-run"))
            return client.dry_run
    kind = target.kind
    if target.live:
        client.delete(f"/{kind.image_api}/{kind.image_type}/{target.live['id']}")
        client.report(f"  deleted the old image of {target.image.label}")
    try:
        target.uploaded.append(upload_asset_resource(client, kind.image_type, target.image.path,
                                                     image_relationships(target), api=kind.image_api, checksum=False))
    except Exception:
        if target.live and not client.dry_run:
            print(red(f"  ✗ {target.image.label}: the old image was DELETED and the upload FAILED — it has no image "
                      "on App Store Connect now. Re-run the push (it will show as new)."))
        raise
    client.report(f"  uploaded {target.image.path.name} → {target.image.label}")
    return True


def verify(client: asc.Client, targets: list[Target]) -> bool:
    """Wait for Apple to process each upload, then read each image back and compare pixels."""
    ok = True
    for kind_name, kind in KINDS.items():
        pending = {i: t.image.label for t in targets if t.image.kind == kind_name for i in t.uploaded}
        if not pending:
            continue
        print(f"\nwaiting for App Store Connect to process {len(pending)} {kind_name} image(s)…")
        _, failed, timed_out = wait_for_asset_processing(client, kind.image_type, pending, api=kind.image_api)
        ok = report_processing(failed, timed_out, indent="  ") and ok
    print("\nverifying against a fresh read of App Store Connect…")
    for target in (t for t in targets if t.uploaded):
        live = get_optional(client, image_path(target)) if target.parent else None
        pixels = fetch_image_asset(asc.attributes(live)) if live else None
        if pixels is None or not gamekit.same_pixels(target.image.path, pixels):
            ok = False
            print(red(f"  ✗ {target.image.label}: App Store Connect "
                      f"{'has no processed image' if pixels is None else 'holds different pixels'}"))
        else:
            print(green(f"  ✓ {target.image.label}"))
    return ok


def local_images(app: project.App) -> list[Image]:
    """The bundle's images, refused before any network call if one would be rejected."""
    bundle = gamekit.find_bundle(app.root, (app.config.get("gamecenter") or {}).get("gamekit"))
    print(f"→ {bundle.relative_to(app.root) if bundle.is_relative_to(app.root) else bundle}")
    images, problems = gamekit.read_bundle(bundle)
    problems += [f"{image.label}: {p}" for image in images
                 if image.path.is_file() and (p := gamekit.image_problem(image))]
    if problems:
        for problem in problems:
            print(red(f"  ✗ {problem}"))
        raise SystemExit("fix the .gamekit images above — nothing was read from or written to App Store Connect")
    if not images:
        raise SystemExit("the .gamekit names no achievement, leaderboard or activity images")
    return images


def cmd_show(args: SimpleNamespace) -> None:
    app = project.resolve_app(args.app)
    images = local_images(app)
    targets, holder = plan(asc.Client(), app.config, images, allow_new_version=False)
    print(f"--- Game Center images for {app.config['bundle_id']}, records on {holder} ---")
    print_plan(targets)


def cmd_push(args: SimpleNamespace) -> None:
    app = project.resolve_app(args.app)
    images = local_images(app)
    if args.dry_run and not asc.Credentials.available():
        for image in images:
            print(f"  [dry-run] {image.label}: {image.path.name}")
        print("\n[dry-run] no API key set up (`snakelane auth setup`), so App Store Connect was not read: "
              "the list above is every image the bundle names. Nothing was written.")
        return
    client = asc.Client(dry_run=args.dry_run)
    targets, holder = plan(client, app.config, images, args.new_version)
    print(f"--- {app.config['name']} ({app.config['bundle_id']}), records on {holder} ---")
    print_plan(targets)
    todo = [t for t in targets if t.status in ("new", "changed")]
    skipped = sum(t.status == "skip" for t in targets)
    if not todo:
        print(green("\n✓ nothing to upload") + (red(f" — {skipped} skipped, see above") if skipped else ""))
        if skipped and not client.dry_run:  # the bundle and ASC still differ
            raise SystemExit(1)
        return
    print(f"\n{len(todo)} image(s) to upload" + (f", {skipped} skipped" if skipped else "") + ":")
    if not client.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("stdin is not a terminal — pass --yes to push without the prompt")
        if input("\nUpload these images to App Store Connect? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted — nothing pushed")
            return
    pushed = [push_one(client, target) for target in todo]
    if client.dry_run:
        print("\n[dry-run] nothing was written to App Store Connect.")
        return
    if not verify(client, todo) or skipped or not all(pushed):
        raise SystemExit(red("\nGame Center image push finished WITH PROBLEMS — see above."))
    print(green("\nGame Center image push complete."))
