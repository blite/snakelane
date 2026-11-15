"""`gamecenter sync`: make App Store Connect hold what the `.gamekit` says, in one command. Each
record's localized text and images are compared with its newest version, written where they
differ (into a new version when the newest is LIVE), and every record waiting for review joins the
app's draft review submission (created if there is none), beside the app version. Never submits.

Where the text lives (an image's path is in images.py):

    achievement   /v2/gameCenterAchievementVersions/{id}/localizations  → gameCenterAchievementLocalizations (v2)
    leaderboard   /v2/gameCenterLeaderboardVersions/{id}/localizations  → gameCenterLeaderboardLocalizations (v2)
    activity      /v1/gameCenterActivityVersions/{id}/localizations     → gameCenterActivityLocalizations (v1)

App Store Connect won't take an achievement for review until every language has a picture (leaderboards
and activities don't need one), so a language the bundle gives no achievement picture gets the
primary locale's: a picture with no words serves every language, and the bundle keeps one set.
Why: docs/design/gamecenter.md#every-achievement-language-needs-a-picture

Records themselves (ids, points, formatters, recurrence) are still made by Xcode's sync: a record
missing on App Store Connect is reported and skipped. A locale App Store Connect holds and the
bundle doesn't is reported, never deleted.
Why: docs/design/gamecenter.md#xcode-leaves-a-live-record-s-new-languages-behind
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from .. import project
from ..args import resolve_platform
from ..connect import asc
from ..connect.resources import find_app
from ..terminal import dim, green, red
from . import gamekit, images, review
from .images import EDITABLE, KINDS, Target

LOCALIZATION = {"achievement": ("v2", "gameCenterAchievementLocalizations"),
                "leaderboard": ("v2", "gameCenterLeaderboardLocalizations"),
                "activity": ("v1", "gameCenterActivityLocalizations")}


@dataclass
class TextChange:
    locale: str
    fields: dict[str, str]                   # only what differs from the live localization
    live: dict[str, Any] | None = None       # the ASC localization; None: create it


@dataclass
class Record:
    kind: str
    vendor_id: str
    texts: list[gamekit.Text] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)   # every image the bundle names for it
    record: dict[str, Any] | None = None
    version: dict[str, Any] | None = None
    changes: list[TextChange] = field(default_factory=list)
    extra_locales: list[str] = field(default_factory=list)
    problem: str = ""
    new_version: bool = False
    created: bool = False
    failed: bool = False

    @property
    def label(self) -> str:
        return f"{self.kind} {self.vendor_id}"

    @property
    def images(self) -> list[Target]:
        return [t for t in self.targets if t.status in ("new", "changed")]

    @property
    def changed(self) -> bool:
        return bool(self.changes or self.images)


def localizations(client: asc.Client, kind: str, version: dict[str, Any]) -> dict[str, dict[str, Any]]:
    k = KINDS[kind]
    if asc.planned(version["id"]):
        return {}
    path = f"/{k.versions_api}/{k.version_type}/{version['id']}/localizations"
    return {asc.attributes(loc).get("locale"): loc for loc in client.get_all(path)}


def diff(texts: list[gamekit.Text], live: dict[str, dict[str, Any]]) -> list[TextChange]:
    """What each bundle locale needs: every field for a new locale, the differing ones otherwise."""
    changes = []
    for text in texts:
        loc = live.get(text.locale)
        held = asc.attributes(loc) if loc else {}
        fields = {k: v for k, v in text.values.items() if held.get(k) != v}
        if fields:
            changes.append(TextChange(text.locale, fields, loc))
    return changes


def fill_achievement_images(texts: list[gamekit.Text], local_images: list[gamekit.Image],
                            primary: str) -> list[gamekit.Image]:
    """An image for each achievement language the bundle has text for and no picture: the primary
    locale's picture, else the first the record has."""
    held: dict[str, dict[str | None, gamekit.Image]] = {}
    for image in local_images:
        if image.kind == "achievement":
            held.setdefault(image.vendor_id, {})[image.locale] = image
    filled = []
    for text in texts:
        if text.kind != "achievement" or not (pictures := held.get(text.vendor_id)) or text.locale in pictures:
            continue
        source = pictures.get(primary) or next(iter(sorted(pictures.values(), key=lambda i: i.locale or "")))
        filled.append(gamekit.Image("achievement", text.vendor_id, text.locale, source.path))
    return filled


def plan(client: asc.Client, app_config: dict[str, Any], texts: list[gamekit.Text],
         local_images: list[gamekit.Image]) -> tuple[list[Record], str]:
    """Every bundle record against its newest version on App Store Connect; read-only."""
    targets, holder = images.plan(client, app_config, local_images, allow_new_version=True)
    prefix, _, grp = images.owner(client, app_config)
    on_asc = {kind: {asc.attributes(r).get("vendorIdentifier"): r for r in client.get_all(f"{prefix}/{k.records}")}
              for kind, k in KINDS.items()}
    records: dict[tuple[str, str], Record] = {}
    for text in texts:
        records.setdefault((text.kind, text.vendor_id), Record(text.kind, text.vendor_id)).texts.append(text)
    for target in targets:
        key = (target.image.kind, target.image.vendor_id)
        records.setdefault(key, Record(*key)).targets.append(target)
    for r in records.values():
        if (record := on_asc[r.kind].get(r.vendor_id)) is None:
            hint = f" (ids in a group start {grp!r})" if grp and not r.vendor_id.startswith(grp) else ""
            r.problem = f"no such {r.kind} on App Store Connect yet{hint} — create it with Xcode's sync first"
            continue
        r.record = record
        k = KINDS[r.kind]
        r.version = images.newest(list(client.get_all(f"/{k.versions_api}/{k.record_type}/{record['id']}/versions")))
        if r.version is None:
            r.problem = "no version on App Store Connect"
            continue
        live = localizations(client, r.kind, r.version)
        r.changes = diff(r.texts, live)
        r.extra_locales = sorted(set(live) - {t.locale for t in r.texts}) if r.texts else []
        creating = {c.locale for c in r.changes if c.live is None}
        for target in r.targets:
            # An image for a locale this run adds has no localization to hang off yet; it will.
            if target.status == "skip" and target.parent is None and target.image.locale in creating:
                target.status, target.reason = "new", ""
        state, number = asc.attributes(r.version).get("state"), asc.attributes(r.version).get("version")
        if not r.changed or state in EDITABLE:
            continue
        if state == "LIVE":
            r.new_version = True
        else:
            r.problem = f"version {number} is {state}: wait until it is live, then sync again"
    return list(records.values()), holder


def print_plan(records: list[Record]) -> None:
    for r in records:
        attrs = asc.attributes(r.version or {})
        where = f"version {attrs.get('version')} {attrs.get('state')}" if r.version else ""
        skipped = [t for t in r.targets if t.status == "skip"]
        if r.problem:
            print(red(f"  ✗ {r.label}: {r.problem}"))
            continue
        if not r.changed:
            print(dim(f"  = {r.label}: unchanged  ({where})"))
        else:
            into = f" → new version {(attrs.get('version') or 0) + 1}" if r.new_version else ""
            print(f"  ~ {r.label}  {dim(where)}{into}")
            for change in r.changes:
                mark = green("+") if change.live is None else "~"
                print(f"      {mark} {change.locale}: {', '.join(change.fields)}")
            for target in r.images:
                print(f"      {'+' if target.status == 'new' else '~'} image{f' [{target.image.locale}]' if target.image.locale else ''}")
        for target in skipped:
            print(red(f"      ✗ image{f' [{target.image.locale}]' if target.image.locale else ''}: {target.reason}"))
        if r.extra_locales:
            print(dim(f"      only on App Store Connect, left alone: {', '.join(r.extra_locales)}"))


def write_text(client: asc.Client, r: Record) -> None:
    api, type_ = LOCALIZATION[r.kind]
    k = KINDS[r.kind]
    for change in r.changes:
        if change.live:
            client.patch(f"/{api}/{type_}/{change.live['id']}",
                         asc.resource_body(type_, change.fields, id_=change.live["id"]))
            client.report(f"  updated {r.label} [{change.locale}]: {', '.join(change.fields)}")
        else:
            client.post(f"/{api}/{type_}", asc.resource_body(
                type_, {"locale": change.locale, **change.fields},
                relationships={"version": asc.relationship(k.version_type, r.version["id"])}))
            client.report(f"  added {r.label} [{change.locale}]")


def apply(client: asc.Client, r: Record) -> list[Target]:
    """Write one record's changes; returns the image targets uploaded, for verifying."""
    if r.new_version:
        r.version = images.create_version(client, r.kind, r.record)
        r.created, r.new_version = True, False
        if asc.planned(r.version["id"]):
            print(dim("  [dry-run] ASC copies the live version's localizations into the new one; "
                      "the updates below land on those copies"))
        else:  # the copies are what the changes now apply to
            r.changes = diff(r.texts, localizations(client, r.kind, r.version))
    write_text(client, r)
    uploaded = []
    for target in r.images:
        if r.created or target.parent is None:
            images.adopt_version(client, target, r.version)
        if target.parent is None:
            if not client.dry_run:
                print(red(f"  ✗ {target.image.label}: no {target.image.locale} localization on the version — "
                          "nothing uploaded"))
                r.failed = True
            continue
        images.push_one(client, target)
        uploaded.append(target)
    return uploaded


def verify_text(client: asc.Client, records: list[Record]) -> bool:
    ok = True
    for r in (r for r in records if r.changes and r.version):
        left = diff(r.texts, localizations(client, r.kind, r.version))
        for change in left:
            ok = False
            print(red(f"  ✗ {r.label} [{change.locale}]: App Store Connect still differs on {', '.join(change.fields)}"))
        if not left:
            print(green(f"  ✓ {r.label}: text"))
    return ok


def waiting(client: asc.Client, app_config: dict[str, Any], records: list[Record]) -> list[review.Item]:
    """Every record waiting for review, read fresh, plus the versions a dry run only planned."""
    items = review.pending_items(client, app_config)
    have = {(i.kind.label, i.vendor_id) for i in items}
    kinds = {k.label: k for k in review.KINDS}
    items += [review.Item(kinds[r.kind], r.vendor_id, r.version, "PREPARE_FOR_SUBMISSION")
              for r in records if r.created and (r.kind, r.vendor_id) not in have]
    return items


def cmd_sync(args: SimpleNamespace) -> None:
    app = project.resolve_app(args.app)
    platform = resolve_platform(app.config, args.platform)
    local_images = images.local_images(app, required=False)  # refuses a bad image before any read
    texts = gamekit.read_texts(images.bundle_path(app))
    local_images += fill_achievement_images(texts, local_images, app.primary_locale)
    client = asc.Client(dry_run=args.dry_run)
    records, holder = plan(client, app.config, texts, local_images)
    print(f"--- {app.config['name']} ({app.config['bundle_id']}), records on {holder} ---")
    print_plan(records)
    todo = [r for r in records if r.changed and not r.problem]
    problems = sum(bool(r.problem) for r in records) + sum(t.status == "skip" for r in records for t in r.targets
                                                          if not r.problem)
    app_id = find_app(client, app.config)["id"]
    version = None if args.without_version else review.preparing_version(client, app_id, platform)
    new_versions = sum(r.new_version for r in todo)
    print(f"\n{len(todo)} record(s) to write" + (f", {new_versions} into a new version" if new_versions else "")
          + (f", {problems} skipped" if problems else "") + "; then every record waiting for review"
          + (f" and app version {asc.attributes(version).get('versionString')}" if version else "")
          + " joins the draft review submission (not submitted).")
    if not client.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("stdin is not a terminal — pass --yes to sync without the prompt")
        if input("\nWrite this to App Store Connect? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted — nothing written")
            return
    uploaded: list[Target] = []
    for r in todo:
        print(f"\n{r.label}")
        uploaded += apply(client, r)
    ok = True
    if not client.dry_run and todo:
        print("\nverifying against a fresh read of App Store Connect…")
        ok = verify_text(client, todo)
        if uploaded:
            ok = images.verify(client, uploaded) and ok
    items = waiting(client, app.config, records)
    print("\nreview submission:")
    if items:
        review.queue(client, app_id, items, version, platform)
    else:
        print(dim("  no Game Center record is waiting for review"))
    if client.dry_run:
        print("\n[dry-run] nothing was written to App Store Connect.")
        return
    if not ok or problems or any(r.failed for r in todo):
        raise SystemExit(red("\nGame Center sync finished WITH PROBLEMS — see above."))
    print(green("\nGame Center sync complete. Nothing is submitted: review the draft in App Store Connect and "
                "submit it there, or with `snakelane ship release`."))
