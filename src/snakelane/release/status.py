"""`snakelane status [--app A] [--json]`: what App Store Connect holds for the app right now. Read-only.

Each platform's live version and anything newer (state, release type, phased release), review
submissions in progress, and the latest TestFlight build's processing state. `--json` for scripts.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from .. import project
from ..args import AppOption, command_app, run
from ..connect import asc
from ..connect.resources import find_app, get_optional

LIVE = "READY_FOR_SALE"
FINISHED_REVIEW = {"COMPLETE", "CANCELED"}
PLATFORM_NAMES = {"IOS": "iOS", "MAC_OS": "macOS", "TV_OS": "tvOS", "VISION_OS": "visionOS"}


def collect(client: asc.Client, app: project.App) -> dict[str, Any]:
    found = find_app(client, app.config)
    app_id = found["id"]
    versions: dict[str, list[dict[str, Any]]] = {}
    for version in client.get_all(f"/v1/apps/{app_id}/appStoreVersions", {"limit": 50}):
        a = asc.attributes(version)
        shown = versions.setdefault(PLATFORM_NAMES.get(a.get("platform"), a.get("platform")), [])
        if any(v["state"] == LIVE for v in shown):  # older live versions are history
            continue
        entry = {"version": a.get("versionString"), "state": a.get("appStoreState"),
                 "release_type": a.get("releaseType"), "earliest_release_date": a.get("earliestReleaseDate"),
                 "created": a.get("createdDate")}
        if entry["state"] != LIVE:
            phased = get_optional(client, f"/v1/appStoreVersions/{version['id']}/appStoreVersionPhasedRelease")
            entry["phased_release"] = asc.attributes(phased).get("phasedReleaseState") if phased else None
        shown.append(entry)
    submissions = client.get("/v1/reviewSubmissions", {"filter[app]": app_id, "limit": 10}).get("data", [])
    reviews = [{"state": r.get("state"), "platform": PLATFORM_NAMES.get(r.get("platform"), r.get("platform")),
                "submitted": r.get("submittedDate")}
               for r in map(asc.attributes, submissions) if r.get("state") not in FINISHED_REVIEW]
    builds = client.get("/v1/builds", {"filter[app]": app_id, "sort": "-uploadedDate", "limit": 1}).get("data", [])
    b = asc.attributes(builds[0]) if builds else {}
    return {
        "app": {"name": asc.attributes(found).get("name"), "bundle_id": app.config.get("bundle_id"),
                "apple_id": app_id, "primary_locale": asc.attributes(found).get("primaryLocale")},
        "versions": versions,
        "reviews_in_progress": reviews,
        "latest_build": {"version": b.get("version"), "processing": b.get("processingState"),
                         "uploaded": b.get("uploadedDate"), "expired": b.get("expired")} if builds else None,
    }


def describe_release(entry: dict[str, Any]) -> str:
    kind = {"AFTER_APPROVAL": "releases after approval", "MANUAL": "manual release",
            "SCHEDULED": f"scheduled for {entry.get('earliest_release_date')}"}.get(entry.get("release_type") or "")
    phased = entry.get("phased_release")
    return ", ".join(x for x in (kind, phased and f"phased ({phased.lower()})") if x)


def report(status: dict[str, Any]) -> None:
    a = status["app"]
    print(f"{a['name']} ({a['bundle_id']}) — app {a['apple_id']}, primary language {a['primary_locale']}")
    for platform, entries in status["versions"].items():
        for i, entry in enumerate(entries):
            live = entry["state"] == LIVE
            release = "" if live else describe_release(entry)
            print(f"  {platform if i == 0 else '':9} {entry['version']:<8} {entry['state']}{'  live' if live else ''}"
                  + (f"  — {release}" if release else ""))
    for r in status["reviews_in_progress"]:
        submitted = f" (submitted {r['submitted']})" if r["submitted"] else ""
        print(f"  review    {r['platform']}: {r['state']}{submitted}")
    if not status["reviews_in_progress"]:
        print("  review    nothing in progress")
    if b := status["latest_build"]:
        expired = ", expired" if b["expired"] else ""
        print(f"  TestFlight latest build {b['version']} ({b['processing']}{expired}, uploaded {b['uploaded']})")
    else:
        print("  TestFlight no builds")


cli = command_app("What App Store Connect holds for the app right now (read-only).")


@cli.command()
def status_command(
    app: AppOption = None,
    json_output: Annotated[bool, typer.Option("--json", help="print it as one JSON object")] = False,
) -> None:
    resolved = project.resolve_app(app)
    status = collect(asc.Client(), resolved)
    print(json.dumps(status, indent=2)) if json_output else report(status)


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane status")
