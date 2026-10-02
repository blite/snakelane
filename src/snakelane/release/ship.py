"""Test, archive, upload and submit, with no fastlane underneath.

    snakelane ship test | beta [--platform macos] [--skip-tests]
    snakelane ship release [--platform macos] [--skip-tests] [--no-submit]
    snakelane ship bump-version [--bump minor|patch|major | --version 1.6]

`beta`: refuse a marketing version already live, test, archive, check the archive carries the
post-action's build number, upload, wait for processing, write git subjects into "What to Test".
`release`: the same through the upload, then attach the build to the editable version, apply the
release settings and submit (`--no-submit` stops short). The build number is bump.py's job, never
this module's. Why: docs/design/release.md#shipping

snakelane.yml keys:
    "scheme" / "team_id" / "bundle_id"   (required) archived scheme, export signing team, ASC lookup.
    "apple_id"              asserted against what the bundle id finds.
    "platforms"             stores `bump-version` checks the live version on (default ["ios"]).
    "extension_bundle_ids"  extensions whose MARKETING_VERSION moves with the app's (else ITMS-90473).
    "test"                  the release test gate, all optional:
        "scheme"            scheme to test (default: "scheme"), for an app scheme with no test bundles.
        "test_plan"         -testPlan.
        "skip_testing"      -skip-testing: identifiers, usually the slow screenshot UI tests.
        "device"            simulator name (default "iPhone 17 Pro Max").
        "destination"       a full -destination, overriding "device".
        "env"               test-process variables, e.g. {"RUN_CONTENT_TESTS": "1"}; TEST_RUNNER_ is added.
    "release"               how `ship release` lets it go out (absent: whatever ASC has); checked before tests:
        "type"              after_approval | manual | scheduled
        "date"              for scheduled: ISO time with timezone, e.g. "2026-11-03T09:00:00-08:00"
        "phased"            true: 7-day phased release; false: everyone at once
"""

from __future__ import annotations

import datetime as dt
import os
import plistlib
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from .. import project
from ..args import AppOption, command_app
from ..args import run as run_cli
from ..connect import asc
from ..connect.resources import (
    NoEditableVersion,
    find_app,
    find_editable_app_info,
    find_editable_version,
    find_listing_version,
    get_optional,
    live_version,
)
from ..listing import lint
from ..listing.push import build_push_plan, diff_plan_against_live, fetch_live_state
from ..project import App
from ..xcode import run, sweep_test_devices
from . import bump

DEFAULT_TEST_DEVICE = "iPhone 17 Pro Max"
ARCHIVE_DESTINATIONS = {"ios": "generic/platform=iOS", "macos": "generic/platform=macOS"}
PROCESSING_TIMEOUT = 45 * 60  # usually 5–15 minutes; on a timeout the caller says how to finish by hand
PROCESSING_POLL_INTERVAL = 30
RELEASE_TYPES = {"after_approval": "AFTER_APPROVAL", "manual": "MANUAL", "scheduled": "SCHEDULED"}
MARKETING_SETTING = re.compile(r"MARKETING_VERSION = ([\d.]+);")


def build_dir(app: App) -> Path:
    (path := app.root / "build").mkdir(exist_ok=True)
    return path


def load_app(app_arg: str | None) -> App:
    app = project.resolve_app(app_arg)
    for key in ("scheme", "team_id", "bundle_id"):
        if not app.config.get(key):
            raise SystemExit(f'{app.config_path} is missing "{key}"')
    return app


def test_command(app: App) -> list[str]:
    """The gate's xcodebuild: one iOS simulator, serially. Why: docs/design/release.md#the-release-test-gate"""
    test = app.config.get("test", {})
    destination = test.get("destination") or f"platform=iOS Simulator,name={test.get('device', DEFAULT_TEST_DEVICE)}"
    return [
        "xcodebuild", "-project", str(app.project), "-scheme", test.get("scheme") or app.scheme,
        *(["-testPlan", test["test_plan"]] if test.get("test_plan") else []),
        "-destination", destination, "-parallel-testing-enabled", "NO",
        *(f"-skip-testing:{identifier}" for identifier in test.get("skip_testing", [])),
        "clean", "test",
    ]


def run_tests(app: App) -> None:
    try:  # xcodebuild hands TEST_RUNNER_-prefixed variables to the tests
        run(test_command(app), project.runner_vars((app.config.get("test") or {}).get("env") or {}))
    except subprocess.CalledProcessError:
        sweep_test_devices()
        raise SystemExit("tests failed, nothing was archived or uploaded")


def upload(app: App, archive_path: Path) -> None:
    """Sign and upload in one step: `xcodebuild -exportArchive` with `destination: upload`."""
    credentials = asc.Credentials.load()
    export_options = build_dir(app) / "ExportOptions.plist"
    export_options.write_bytes(plistlib.dumps({
        "method": "app-store-connect", "destination": "upload", "signingStyle": "automatic",
        "teamID": app.config["team_id"], "uploadSymbols": True,
        # Why: docs/design/release.md#xcode-does-not-manage-the-build-number-at-export
        "manageAppVersionAndBuildNumber": False,
    }))
    # Why: docs/design/release.md#usrbin-first-on-path-for-the-export
    env = {"PATH": f"/usr/bin:{os.environ.get('PATH', '')}"}
    run(["xcodebuild", "-exportArchive", "-archivePath", str(archive_path),
         "-exportOptionsPlist", str(export_options), "-allowProvisioningUpdates",
         # Absolute: xcodebuild rejects a relative or tilde'd key path.
         "-authenticationKeyPath", str(credentials.key_path.resolve()),
         "-authenticationKeyID", credentials.key_id, "-authenticationKeyIssuerID", credentials.issuer_id], env)


def wait_for_build(client: asc.Client, app_id: str, build_number: str, platform: str) -> dict[str, Any] | None:
    """Poll until the build has processed; None on timeout, for the caller to judge."""
    deadline = time.monotonic() + PROCESSING_TIMEOUT
    print(f"waiting for build {build_number} to process (up to {PROCESSING_TIMEOUT // 60} min)…")
    query = {"filter[app]": app_id, "filter[version]": build_number, "sort": "-uploadedDate", "limit": 1,
             "filter[preReleaseVersion.platform]": asc.platform_enum(platform)}
    while time.monotonic() < deadline:
        if builds := list(client.get_all("/v1/builds", query)):
            state = asc.attributes(builds[0]).get("processingState")
            if state == "VALID":
                print(f"  build {build_number} processed")
                return builds[0]
            if state in ("FAILED", "INVALID"):
                raise SystemExit(
                    f"App Store Connect rejected build {build_number} (processingState={state}): check the "
                    "build's page in App Store Connect for the reason (missing export compliance is the usual one)"
                )
            print(f"  processingState={state}…")
        else:
            print("  build not visible in App Store Connect yet…")
        time.sleep(PROCESSING_POLL_INTERVAL)
    print(f"  gave up waiting after {PROCESSING_TIMEOUT // 60} min; the upload itself succeeded")
    return None


def set_whats_new(client: asc.Client, build: dict[str, Any], text: str) -> None:
    """TestFlight's "What to Test" on the processed build, in every locale it has (else en-US)."""
    if not (localizations := list(client.get_all(f"/v1/builds/{build['id']}/betaBuildLocalizations"))):
        client.post("/v1/betaBuildLocalizations", asc.resource_body(
            "betaBuildLocalizations", {"locale": "en-US", "whatsNew": text},
            relationships={"build": asc.relationship("builds", build["id"])}))
        return print("  created en-US TestFlight changelog")
    for loc in localizations:
        client.patch(f"/v1/betaBuildLocalizations/{loc['id']}",
                     asc.resource_body("betaBuildLocalizations", {"whatsNew": text}, id_=loc["id"]))
        print(f"  set TestFlight changelog for {asc.attributes(loc).get('locale')}")


def ensure_editable_version(client: asc.Client, app_id: str, platform: str, version_string: str) -> dict[str, Any]:
    """The editable AppStoreVersion, created or corrected to the archived marketing version."""
    try:
        version = find_editable_version(client, app_id, platform)
    except NoEditableVersion:
        print(f"  no editable version, creating {version_string}")
        return client.post("/v1/appStoreVersions", asc.resource_body(
            "appStoreVersions", {"platform": asc.platform_enum(platform), "versionString": version_string},
            relationships={"app": asc.relationship("apps", app_id)}))["data"]
    if (current := asc.attributes(version).get("versionString")) != version_string:
        print(f"  updating version string {current} -> {version_string}")
        client.patch(f"/v1/appStoreVersions/{version['id']}",
                     asc.resource_body("appStoreVersions", {"versionString": version_string}, id_=version["id"]))
    return version


def release_settings(app: App) -> dict[str, Any]:
    """The config's `release` block, validated: {"type", "date", "phased"}, each None when unset."""
    block = app.config.get("release") or {}
    if unknown := sorted(set(block) - {"type", "date", "phased"}):
        raise SystemExit(f'"release" in {app.config_path.name} has unknown key(s) {unknown}; '
                         'expected type, date, phased')
    kind = str(block["type"]).lower() if block.get("type") is not None else None
    if kind is not None and kind not in RELEASE_TYPES:
        raise SystemExit(f'release.type {block["type"]!r}: expected one of {", ".join(RELEASE_TYPES)}')
    if (date := block.get("date")) is not None:
        if isinstance(date, str):  # YAML gives a datetime unquoted, text quoted
            try:
                date = dt.datetime.fromisoformat(date)
            except ValueError:
                raise SystemExit(f"release.date {date!r} is not an ISO time, "
                                 "e.g. 2026-11-03T09:00:00-08:00") from None
        if not isinstance(date, dt.datetime) or date.tzinfo is None:
            raise SystemExit("release.date needs a time and a timezone, e.g. 2026-11-03T09:00:00-08:00")
        date = date.isoformat()
    if (kind == "scheduled") != bool(date):
        raise SystemExit("release.date goes with type: scheduled, and scheduled needs a date")
    if (phased := block.get("phased")) is not None and not isinstance(phased, bool):
        raise SystemExit(f"release.phased is true or false, not {phased!r}")
    return {"type": RELEASE_TYPES[kind] if kind else None, "date": date, "phased": phased}


def apply_release_settings(client: asc.Client, version: dict[str, Any], settings: dict[str, Any]) -> None:
    """Set how the version releases, writing only what differs from App Store Connect."""
    current = asc.attributes(version)
    attrs = {api: settings[key] for key, api in (("type", "releaseType"), ("date", "earliestReleaseDate"))
             if settings[key] and current.get(api) != settings[key]}
    if attrs:
        client.patch(f"/v1/appStoreVersions/{version['id']}",
                     asc.resource_body("appStoreVersions", attrs, id_=version["id"]))
        print(f"  release: {', '.join(f'{k}={v}' for k, v in attrs.items())}")
    if settings["phased"] is None:
        return
    existing = get_optional(client, f"/v1/appStoreVersions/{version['id']}/appStoreVersionPhasedRelease")
    if settings["phased"] and not existing:
        client.post("/v1/appStoreVersionPhasedReleases", asc.resource_body(
            "appStoreVersionPhasedReleases", {"phasedReleaseState": "INACTIVE"},
            relationships={"appStoreVersion": asc.relationship("appStoreVersions", version["id"])}))
        print("  release: phased over 7 days (starts when the version goes live)")
    elif not settings["phased"] and existing:
        client.delete(f"/v1/appStoreVersionPhasedReleases/{existing['id']}")
        print("  release: phased release removed — everyone gets it at once")


def submit_for_review(client: asc.Client, app_id: str, version_id: str, platform: str) -> None:
    """Add the version to the open review submission (or a new one) and submit it."""
    platform_enum = asc.platform_enum(platform)
    submissions = client.get_all(f"/v1/apps/{app_id}/reviewSubmissions", {"filter[platform]": platform_enum})
    if submission := next((s for s in submissions if asc.attributes(s).get("state") == "READY_FOR_REVIEW"), None):
        print(f"  reusing open review submission {submission['id']}")
    else:
        submission = client.post("/v1/reviewSubmissions", asc.resource_body(
            "reviewSubmissions", {"platform": platform_enum},
            relationships={"app": asc.relationship("apps", app_id)}))["data"]
        print(f"  created review submission {submission['id']}")
    client.post("/v1/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
        "reviewSubmission": asc.relationship("reviewSubmissions", submission["id"]),
        "appStoreVersion": asc.relationship("appStoreVersions", version_id),
    }}})
    print("  added the version to the submission")
    client.patch(f"/v1/reviewSubmissions/{submission['id']}",
                 asc.resource_body("reviewSubmissions", {"submitted": True}, id_=submission["id"]))
    print("  SUBMITTED FOR REVIEW")


def app_marketing_version(app: App) -> str:
    source = app.pbxproj.read_text()
    # By bundle id: docs/design/release.md#marketing_version-is-scoped-by-bundle-id
    versions = {v for s, e in bump.app_config_spans(app, source) for v in MARKETING_SETTING.findall(source[s:e])}
    if len(versions) != 1:
        raise SystemExit(f"the app's configurations disagree on MARKETING_VERSION: {sorted(versions) or 'none set'}")
    return versions.pop()


def version_key(version: str) -> tuple[int, ...]:
    parts = [int(p) for p in version.split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def verify_marketing_version_is_unreleased(app: App, platform: str) -> None:
    """Refuse a MARKETING_VERSION already live. Why: docs/design/release.md#the-marketing-version-gate"""
    current = app_marketing_version(app)
    client = asc.Client()
    live = live_version(client, find_app(client, app.config)["id"], platform)
    if live is not None and version_key(current) <= version_key(live):
        raise SystemExit(
            f"MARKETING_VERSION is {current}, but {live} is already on the App Store ({platform}). "
            "Apple closes a released version's train, so this upload would be rejected. "
            "Run `snakelane ship bump-version` first."
        )
    print(f"marketing version {current} is ahead of the live {platform} {live or '(nothing live)'}")


def release_findings(app: App, platform: str) -> list[lint.Finding]:
    """Lint the live listing `ship release` will submit, warning where local files differ. Read-only.

    Why: docs/design/release.md#the-release-lint-reads-app-store-connect-not-the-files"""
    client = asc.Client()
    found_app = find_app(client, app.config)
    if (version := find_listing_version(client, found_app["id"], platform)) is None:
        return []
    info = find_editable_app_info(client, found_app["id"])
    live = fetch_live_state(client, info["id"], version, app.locales)
    found = lint.lint(live["per_locale"], live["review"].get("notes"), lint.legal_terms_url(app, app.platform_dir(platform)))
    plan = build_push_plan(app.folder / platform, app.locales, app.config)
    found += [lint.Finding("warning", "unpushed", f"{locale}/listing",
                           f"local text differs from App Store Connect in {', '.join(sorted(fields))}; "
                           "run `snakelane store push` first if that should go to review")
              for locale, fields in diff_plan_against_live(plan, live)["per_locale"].items()]
    return lint.ignored(app, found)


def ship_build(app: App, platform: str, skip_tests: bool) -> tuple[asc.Client, str, dict[str, Any] | None, str]:
    """Test, archive Release, upload, wait: (client, ASC app id, processed build or None, marketing version)."""
    if not skip_tests:
        run_tests(app)
    archive_path = build_dir(app) / f"{app.scheme}-{platform}.xcarchive"
    if archive_path.exists():
        shutil.rmtree(archive_path)
    # The post-action must move and stamp the number: docs/design/release.md#no-build-number-bump-in-ship
    before = bump.committed_build(app)
    run(["xcodebuild", "-project", str(app.project), "-scheme", app.scheme, "-configuration", "Release",
         "-destination", ARCHIVE_DESTINATIONS[platform], "-archivePath", str(archive_path), "clean", "archive"])
    bump.verify_archive(app, archive_path, before=before)
    short_version, build_number = bump.archived_versions(archive_path)
    upload(app, archive_path)
    print(f"uploaded {short_version} ({build_number}) to TestFlight ({platform})")
    client = asc.Client()
    app_id = find_app(client, app.config)["id"]
    return client, app_id, wait_for_build(client, app_id, build_number, platform), short_version


PLATFORM = Annotated[Literal["ios", "macos"], typer.Option("--platform")]
SKIP_TESTS = Annotated[bool, typer.Option("--skip-tests", help="skip the test gate")]

cli = command_app("Test, archive, upload to TestFlight, and submit for review.")


@cli.command()
def test(app: AppOption = None) -> None:
    """Run the release test gate on its own."""
    run_tests(load_app(app))


@cli.command()
def beta(app: AppOption = None, platform: PLATFORM = "ios", skip_tests: SKIP_TESTS = False) -> None:
    """Test, archive, upload to TestFlight, and set "What to Test" from git."""
    resolved = load_app(app)
    verify_marketing_version_is_unreleased(resolved, platform)
    client, _, build, _ = ship_build(resolved, platform, skip_tests)
    if build is None:
        return print("add the changelog by hand in App Store Connect once processing finishes")
    log = subprocess.run(["git", "-C", str(resolved.root), "log", "--no-merges", "-20", "--pretty=- %s"],
                         check=True, capture_output=True, text=True)
    set_whats_new(client, build, log.stdout.strip())


@cli.command()
def release(
    app: AppOption = None,
    platform: PLATFORM = "ios",
    skip_tests: SKIP_TESTS = False,
    skip_lint: Annotated[bool, typer.Option(
        "--skip-lint", help="release even when `snakelane lint` finds errors")] = False,
    no_submit: Annotated[bool, typer.Option(
        "--no-submit", help="stage the build on the version but don't request review")] = False,
) -> None:
    """Test, archive, upload, attach to the version, and submit for review."""
    resolved = load_app(app)
    settings = release_settings(resolved)  # before the archive, so a typo costs seconds
    verify_marketing_version_is_unreleased(resolved, platform)
    if not skip_lint:
        lint.gate(resolved, platform, release_findings(resolved, platform))
    client, app_id, build, short_version = ship_build(resolved, platform, skip_tests)
    if build is None:
        raise SystemExit("build never finished processing; once it does, attach + submit from the App Store "
                         "Connect web UI (re-running would archive and upload a new build)")
    version = ensure_editable_version(client, app_id, platform, short_version)
    client.patch(f"/v1/appStoreVersions/{version['id']}/relationships/build",
                 {"data": {"type": "builds", "id": build["id"]}})
    print("  attached build to the version")
    apply_release_settings(client, version, settings)
    if no_submit:
        return print("staged (--no-submit): version + build are set, review not requested")
    submit_for_review(client, app_id, version["id"], platform)


@cli.command("bump-version")
def bump_version(
    app: AppOption = None,
    version: Annotated[str | None, typer.Option("--version", help="an explicit version, e.g. 1.6")] = None,
    bump: Annotated[Literal["major", "minor", "patch"], typer.Option("--bump")] = "minor",
) -> None:
    """Raise MARKETING_VERSION on the app (and its extensions)."""
    resolved = load_app(app)
    current = app_marketing_version(resolved)
    if not (target := version):
        major, minor, patch = version_key(current)[:3]
        target = {"major": f"{major + 1}.0", "minor": f"{major}.{minor + 1}",
                  "patch": f"{major}.{minor}.{patch + 1}"}[bump]
    if not re.fullmatch(r"\d+(\.\d+){0,2}", target):
        raise SystemExit(f"{target!r} is not a version (expected e.g. 1.6 or 1.6.1)")
    if version_key(target) <= version_key(current):
        raise SystemExit(f"{target} is not ahead of the current {current}")
    client = asc.Client()
    app_id = find_app(client, resolved.config)["id"]
    for platform in resolved.config.get("platforms", ["ios"]):
        if (live := live_version(client, app_id, platform)) is not None and version_key(target) <= version_key(live):
            raise SystemExit(f"{target} is not ahead of the live {platform} version {live}")
    source = resolved.pbxproj.read_text()
    source, _ = bump.rewrite_spans(source, bump.app_config_spans(resolved, source), MARKETING_SETTING,
                                   f"MARKETING_VERSION = {target};")
    resolved.pbxproj.write_text(source)
    print(f"marketing version {current} -> {target}")


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane ship")
