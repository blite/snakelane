"""`gamecenter submit`: every Game Center record waiting for review, added to the app's draft review
submission beside the app version, so they go to App Review together. Never submits.

App Store Connect's web UI adds each achievement or leaderboard to a submission one page at a time
("Add for Review"). Here every kind is read off the app's Game Center detail (or its group) and
each record's newest version is added if it is ready to go:

    achievement      gameCenterAchievementsV2     → /v2/gameCenterAchievements/{id}/versions
    leaderboard      gameCenterLeaderboardsV2     → /v2/gameCenterLeaderboards/{id}/versions
    leaderboard set  gameCenterLeaderboardSetsV2  → /v2/gameCenterLeaderboardSets/{id}/versions
    activity         gameCenterActivities         → /v1/gameCenterActivities/{id}/versions
    challenge        gameCenterChallenges         → /v1/gameCenterChallenges/{id}/versions

A version in PREPARE_FOR_SUBMISSION, REJECTED or DEVELOPER_REJECTED is added; READY_FOR_REVIEW is
already in a draft; anything later is in review or live. Archived records are left out. The app
version being prepared joins the same draft unless `--without-version`: a first achievement or
leaderboard must go to review with an app version. `ship release` adds the same items to the
submission it sends. Why: docs/design/gamecenter.md#game-center-records-go-to-review-in-one-call
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any, NamedTuple

from .. import project
from ..args import resolve_platform
from ..connect import asc
from ..connect.resources import find_app
from ..terminal import dim, green
from .images import newest, owner

# A newest version in one of these is added; Apple's GameCenterVersionState.
PENDING = {"PREPARE_FOR_SUBMISSION", "REJECTED", "DEVELOPER_REJECTED"}
# An app version in one of these joins the draft; Apple's AppStoreVersionState, which also has a
# metadata rejection that Game Center versions don't.
VERSION_PENDING = PENDING | {"METADATA_REJECTED"}


class Kind(NamedTuple):
    label: str
    records: str     # the relationship on a gameCenterDetail / gameCenterGroup
    versions: str    # "/v2/gameCenterAchievements" + "/{id}/versions"
    version_type: str
    item: str        # the reviewSubmissionItem relationship


KINDS = [
    Kind("achievement", "gameCenterAchievementsV2", "/v2/gameCenterAchievements",
         "gameCenterAchievementVersions", "gameCenterAchievementVersion"),
    Kind("leaderboard", "gameCenterLeaderboardsV2", "/v2/gameCenterLeaderboards",
         "gameCenterLeaderboardVersions", "gameCenterLeaderboardVersion"),
    Kind("leaderboard set", "gameCenterLeaderboardSetsV2", "/v2/gameCenterLeaderboardSets",
         "gameCenterLeaderboardSetVersions", "gameCenterLeaderboardSetVersion"),
    Kind("activity", "gameCenterActivities", "/v1/gameCenterActivities",
         "gameCenterActivityVersions", "gameCenterActivityVersion"),
    Kind("challenge", "gameCenterChallenges", "/v1/gameCenterChallenges",
         "gameCenterChallengeVersions", "gameCenterChallengeVersion"),
]


class Item(NamedTuple):
    kind: Kind
    vendor_id: str
    version: dict[str, Any] | None
    state: str        # the newest version's state, or "no version"

    @property
    def pending(self) -> bool:
        return self.state in PENDING


def records(client: asc.Client, app_config: dict[str, Any]) -> tuple[list[Item], str]:
    """Every unarchived record with its newest version, and what holds them (for the report)."""
    prefix, holder, _ = owner(client, app_config)
    items: list[Item] = []
    for kind in KINDS:
        for record in client.get_all(f"{prefix}/{kind.records}"):
            attrs = asc.attributes(record)
            if attrs.get("archived"):
                continue
            version = newest(list(client.get_all(f"{kind.versions}/{record['id']}/versions")))
            state = asc.attributes(version).get("state") if version else "no version"
            items.append(Item(kind, attrs.get("vendorIdentifier") or record["id"], version, state or "?"))
    return items, holder


def pending_items(client: asc.Client, app_config: dict[str, Any]) -> list[Item]:
    return [item for item in records(client, app_config)[0] if item.pending]


def open_submission(client: asc.Client, app_id: str, platform: str) -> dict[str, Any] | None:
    """The app's draft review submission for `platform`, if it has one."""
    submissions = client.get_all(f"/v1/apps/{app_id}/reviewSubmissions",
                                 {"filter[platform]": asc.platform_enum(platform)})
    return next((s for s in submissions if asc.attributes(s).get("state") == "READY_FOR_REVIEW"), None)


def draft(client: asc.Client, app_id: str, platform: str) -> dict[str, Any]:
    """The open draft, or a new one."""
    if submission := open_submission(client, app_id, platform):
        print(f"  using the open review submission {submission['id']}")
        return submission
    submission = client.post("/v1/reviewSubmissions", asc.resource_body(
        "reviewSubmissions", {"platform": asc.platform_enum(platform)},
        relationships={"app": asc.relationship("apps", app_id)}))["data"]
    print(f"  {'would create' if client.dry_run else 'created'} a review submission")
    return submission


def add(client: asc.Client, submission_id: str, items: list[Item]) -> list[str]:
    """Add each item; one App Store Connect refuses (409) is left out and returned, with why, so
    the rest still go in."""
    refused: list[str] = []
    for item in items:
        assert item.version is not None
        try:
            client.post("/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
                "reviewSubmission": asc.relationship("reviewSubmissions", submission_id),
                item.kind.item: asc.relationship(item.kind.version_type, item.version["id"]),
            }}})
        except asc.ASCError as error:
            if error.status != 409:
                raise
            print(f"  ⚠ {item.kind.label} {item.vendor_id} refused: {error}")
            refused.append(f"{item.kind.label} {item.vendor_id}: {error}")
            continue
        print(f"  {'would add' if client.dry_run else 'added'} {item.kind.label} {item.vendor_id}")
    return refused


def preparing_version(client: asc.Client, app_id: str, platform: str) -> dict[str, Any] | None:
    """The app version still being prepared for `platform` (not yet in a submission)."""
    versions = client.get_all(f"/v1/apps/{app_id}/appStoreVersions",
                              {"filter[platform]": asc.platform_enum(platform)})
    return next((v for v in versions if asc.attributes(v).get("appStoreState") in VERSION_PENDING), None)


def cmd_submit(args: SimpleNamespace) -> None:
    app = project.resolve_app(args.app)
    platform = resolve_platform(app.config, args.platform)
    client = asc.Client(dry_run=args.dry_run)
    app_id = find_app(client, app.config)["id"]
    items, holder = records(client, app.config)
    print(f"--- {app.config['name']} ({app.config['bundle_id']}), records on {holder} ---")
    for item in items:
        mark = green("+") if item.pending else dim("=")
        print(f"  {mark} {item.kind.label} {item.vendor_id}  {dim(item.state)}")
    todo = [item for item in items if item.pending]
    version = None if args.without_version else preparing_version(client, app_id, platform)
    if version:
        print(f"  {green('+')} app version {asc.attributes(version).get('versionString')}  "
              f"{dim(asc.attributes(version).get('appStoreState'))}")
    if not todo:
        print(green("\n✓ no Game Center record is waiting to be added for review"))
        return
    print(f"\n{len(todo)} record(s)" + (" and the app version" if version else "")
          + " to add to the draft review submission (not submitted):")
    if not client.dry_run and not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("stdin is not a terminal — pass --yes to add them without the prompt")
        if input("\nAdd them to the review submission? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted — nothing added")
            return
    submission = draft(client, app_id, platform)
    if version:
        try:
            client.post("/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
                "reviewSubmission": asc.relationship("reviewSubmissions", submission["id"]),
                "appStoreVersion": asc.relationship("appStoreVersions", version["id"]),
            }}})
        except asc.ASCError as error:
            if error.status != 409:
                raise
            raise SystemExit(
                f"App Store Connect won't take version {asc.attributes(version).get('versionString')} for review "
                "yet: it is missing something review needs, usually the listing text (`snakelane store push`), "
                "the screenshots (`snakelane store media push`) or a build. The draft submission is "
                "kept and reused next run; no Game Center record was added.\n" + str(error)) from None
        print(f"  {'would add' if client.dry_run else 'added'} app version {asc.attributes(version).get('versionString')}")
    if refused := add(client, submission["id"], todo):
        raise SystemExit("App Store Connect refused these, so they are not in the draft; finish them on "
                         "its website or in Xcode and run again:\n  " + "\n  ".join(refused))
    if client.dry_run:
        print("\n[dry-run] nothing was written to App Store Connect.")
        return
    print(green("\nAdded. Nothing is submitted: review the draft in App Store Connect and submit it there, "
                "or with `snakelane ship release`."))
