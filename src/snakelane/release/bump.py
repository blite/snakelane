"""Set CFBundleVersion: pick it, record it in the pbxproj, stamp it into the archive just built.

Runs as the scheme's Archive post-action (`snakelane bump --post-action` prints the script; set
"Provide build settings from" to the app target, and add `--app <name>` in a multi-app repo).
The number is max(pbxproj + 1, latest TestFlight build + 1). Stamping breaks the signature; `-exportArchive` re-signs. Output is also appended to
/tmp/snakelane-<app>-bump-build.log. The repo is found from the working directory,
then $PROJECT_DIR, then $SRCROOT (set by Xcode for the post-action). Why: docs/design/release.md#build-numbers, docs/adr/0001-no-pbxproj-library.md

snakelane.yml keys:
    "bundle_id"             the app's, for the TestFlight check.
    "build_number_scope"    "project" (default: every CURRENT_PROJECT_VERSION, TestFlight across the repo's apps)
                            or "app" (only this app's and its extensions' configurations, e.g. SwiftNVR's six apps).
    "extension_bundle_ids"  embedded extensions that carry the app's numbers ("app" scope, `ship bump-version`).
    "project"               (project.py) which .xcodeproj, when the root has several.
"""

from __future__ import annotations

import contextlib
import os
import plistlib
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from .. import project
from ..args import AppOption, command_app
from ..args import run as run_cli
from ..project import App

CURRENT_VERSION_PATTERN = re.compile(r"CURRENT_PROJECT_VERSION = (\d+);")
BUNDLE_ID_PATTERN = re.compile(r'PRODUCT_BUNDLE_IDENTIFIER = "?([^";]+)"?;')
FALLBACK_LOG = Path("/tmp/snakelane-bump-build.log")  # before the app (and its log) is known
SCOPES = ("project", "app")

POST_ACTION_SCRIPT = """\
# snakelane bump: pick the build number, write it to the pbxproj and
# stamp it into this archive (the app, every .appex, the archive's
# summary). A post-action because writing the project file during a
# build makes Xcode cancel the archive. Absolute path because Xcode's
# post-action PATH does not include ~/.local/bin. Log:
# /tmp/snakelane-<app>-bump-build.log
SNAKELANE="$HOME/.local/bin/snakelane"
if [ ! -x "$SNAKELANE" ]; then
  echo "[$(date +%Y-%m-%dT%H:%M:%S)] $SNAKELANE not found, archive NOT stamped; install it: see the snakelane README" >> /tmp/snakelane-bump-build.log
  exit 1
fi
cd "${PROJECT_DIR:-${SRCROOT:-.}}" 2>/dev/null  # snakelane also falls back to $PROJECT_DIR
"$SNAKELANE" bump --archive "$ARCHIVE_PATH"
"""

def locate_app(app_arg: str | None) -> App:
    """The working directory, else (normal for a post-action) Xcode's $PROJECT_DIR, $SRCROOT."""
    try:
        root = project.find_root()
    except SystemExit as from_cwd:
        root, tried = None, [f"  working directory: {from_cwd}"]
        for var in ("PROJECT_DIR", "SRCROOT"):
            if not (value := os.environ.get(var)):
                tried.append(f"  ${var}: not set")
                continue
            try:
                root = project.find_root(Path(value))
                break
            except SystemExit as from_env:
                tried.append(f"  ${var}={value}: {from_env}")
        if root is None:
            raise SystemExit(
                "cannot find the app repo, nothing bumped. Tried:\n" + "\n".join(tried) + "\n"
                "  From an Xcode post-action, set \"Provide build settings from\" to the app\n"
                "  target so PROJECT_DIR is passed."
            ) from None
    return project.resolve_app(app_arg, root=root)


_CONFIG_START = re.compile(r"(?m)^\s*[0-9A-Za-z]+\s*(?:/\*[^*]*\*/)?\s*=\s*(\{)\s*isa = XCBuildConfiguration;")


def _object_end(source: str, brace: int) -> int:
    """Past the `}` closing `source[brace]`; counted, since buildSettings and `${VAR}` nest braces."""
    depth = 0
    for i in range(brace, len(source)):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return i + 1
    raise SystemExit("unbalanced braces in the pbxproj")


def config_spans(source: str) -> list[tuple[int, int, str | None]]:
    """(start, end, PRODUCT_BUNDLE_IDENTIFIER or None) of every XCBuildConfiguration, found structurally."""
    spans = []
    for match in _CONFIG_START.finditer(source):
        start, end = match.start(1), _object_end(source, match.start(1))
        ids = BUNDLE_ID_PATTERN.findall(source[start:end])
        spans.append((start, end, ids[0] if ids else None))
    return spans


def own_bundle_ids(app: App) -> set[str]:
    if not (bundle_id := app.config.get("bundle_id")):
        raise SystemExit(f'{app.config_path} has no "bundle_id"')
    return {bundle_id, *app.config.get("extension_bundle_ids", [])}


def app_config_spans(app: App, source: str) -> list[tuple[int, int]]:
    """The app's and its extensions' configurations; fails rather than bump nothing."""
    wanted = own_bundle_ids(app)
    if not (spans := [(s, e) for s, e, bundle in config_spans(source) if bundle in wanted]):
        raise SystemExit(
            f"no build configuration in {app.pbxproj} has PRODUCT_BUNDLE_IDENTIFIER in "
            f"{sorted(wanted)}; check snakelane.yml's bundle_id / extension_bundle_ids"
        )
    return spans


def scope(app: App) -> str:
    if (value := app.config.get("build_number_scope", "project")) not in SCOPES:
        raise SystemExit(f'"build_number_scope" in snakelane.yml must be one of {SCOPES}, not {value!r}')
    return value


def _counter_spans(app: App, source: str) -> list[tuple[int, int]]:
    return [(0, len(source))] if scope(app) == "project" else app_config_spans(app, source)


def current_versions(app: App) -> list[int]:
    source = app.pbxproj.read_text()
    found = [int(m) for s, e in _counter_spans(app, source) for m in CURRENT_VERSION_PATTERN.findall(source[s:e])]
    if not found:
        where = "" if scope(app) == "project" else f" for {sorted(own_bundle_ids(app))}"
        raise SystemExit(
            f"no CURRENT_PROJECT_VERSION found in {app.pbxproj}{where}. In \"app\" scope it "
            "must be set on the target's own configurations, not inherited from the project."
        )
    return found


def committed_build(app: App) -> int:
    """What the pbxproj records now; `ship` compares it across the archive to prove the post-action ran."""
    return max(current_versions(app))


def write_pbxproj(app: App, build: int) -> int:
    """Write `build` to every CURRENT_PROJECT_VERSION in scope; return the count.

    Only safe after the build: docs/design/release.md#why-an-archive-post-action"""
    source = app.pbxproj.read_text()
    source, count = rewrite_spans(source, _counter_spans(app, source), CURRENT_VERSION_PATTERN,
                                  f"CURRENT_PROJECT_VERSION = {build};")
    app.pbxproj.write_text(source)
    print(f"  wrote CURRENT_PROJECT_VERSION = {build} to {count} build configurations")
    return count


def rewrite_spans(source: str, spans: list[tuple[int, int]], pattern: re.Pattern[str],
                  replacement: str) -> tuple[str, int]:
    """`pattern` replaced inside each span only; returns the new source and the count."""
    count = 0
    for start, end in reversed(spans):  # from the end, so earlier spans stay valid
        block, n = pattern.subn(replacement, source[start:end])
        source, count = source[:start] + block + source[end:], count + n
    return source, count


def testflight_high_water(app: App) -> int:
    """The largest TestFlight build number, or 0 if unknown.

    Never fails: docs/design/release.md#the-testflight-check-degrades-never-fails"""
    try:
        # Lazy: the local half must work even if the API stack cannot load.
        from ..connect import asc
        from ..connect.resources import find_app
    except ImportError as error:
        print(f"  (App Store Connect client unavailable, skipping TestFlight check: {error})")
        return 0
    if not asc.Credentials.available():
        print("  (no API key set up — `snakelane auth setup` — skipping TestFlight check)")
        return 0
    high, apps = 0, [app] if scope(app) == "app" else project.list_apps(app.root)
    try:
        # No retries, so a dead network degrades in seconds; `get`, not `get_all`, which would page every build.
        client = asc.Client(timeout=10, retries=0)
        for bundle_id in [a.config["bundle_id"] for a in apps if a.config.get("bundle_id")]:
            query = {"filter[app]": find_app(client, {"bundle_id": bundle_id})["id"], "sort": "-version", "limit": 1}
            builds = client.get("/v1/builds", query)["data"]
            latest = int(asc.attributes(builds[0]).get("version", 0)) if builds else 0
            print(f"  TestFlight[{bundle_id}] latest build = {latest}")
            high = max(high, latest)
    except Exception as error:
        print(f"  (TestFlight check failed, continuing with local arithmetic: {error})")
    return high


def next_build(app: App, check_testflight: bool = True) -> int:
    current = committed_build(app)
    build = max(current, testflight_high_water(app) if check_testflight else 0) + 1
    print(f"  pbxproj={current} -> build {build}")
    return build


def _info_plist(bundle: Path) -> Path:
    """iOS bundles keep Info.plist at the top, macOS under Contents/."""
    if found := next((p for p in (bundle / "Info.plist", bundle / "Contents" / "Info.plist") if p.exists()), None):
        return found
    raise SystemExit(f"no Info.plist in {bundle}")


def _load(path: Path) -> dict:
    with path.open("rb") as f:
        return plistlib.load(f)


def _dump(path: Path, plist: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(plist, f, fmt=plistlib.FMT_BINARY)


def archived_app(archive_path: Path) -> Path:
    if len(apps := sorted((archive_path / "Products" / "Applications").glob("*.app"))) != 1:
        raise SystemExit(f"expected exactly one .app in {archive_path}, found {len(apps)}")
    return apps[0]


def archived_bundles(archive_path: Path) -> list[Path]:
    """The app and every .appex inside it, wherever the platform nests them."""
    app = archived_app(archive_path)
    return [app, *sorted(app.glob("**/*.appex"))]


def archived_versions(archive_path: Path) -> tuple[str, str]:
    """(CFBundleShortVersionString, CFBundleVersion) of the archived app."""
    plist = _load(_info_plist(archived_app(archive_path)))
    short, build = plist.get("CFBundleShortVersionString"), plist.get("CFBundleVersion")
    if not short or not build:
        raise SystemExit(f"the archived app in {archive_path} has no version")
    return str(short), str(build)


def stamp_archive(archive_path: Path, build: int) -> None:
    """Write `build` into the app, every .appex and ApplicationProperties. Idempotent.

    Breaking the signature is safe: docs/design/release.md#stamping-a-signed-archive"""

    def rewrite(path: Path, *keys: str) -> bool:
        node = plist = _load(path)
        for key in keys[:-1]:
            if (node := node.get(key)) is None:
                return False
        if node.get(keys[-1]) == str(build):
            return False
        node[keys[-1]] = str(build)
        _dump(path, plist)
        return True

    # Resolve every plist before writing any, so a malformed bundle cannot leave a half-stamp.
    for plist_path in [_info_plist(bundle) for bundle in archived_bundles(archive_path)]:
        verb = "stamped" if rewrite(plist_path, "CFBundleVersion") else "already"
        print(f"  {verb} CFBundleVersion = {build} in {plist_path.relative_to(archive_path)}")
    if (summary := archive_path / "Info.plist").exists():  # not fatal if absent: the app is what ships
        rewrite(summary, "ApplicationProperties", "CFBundleVersion")
        print(f"  ApplicationProperties.CFBundleVersion = {build}")


def verify_archive(app: App, archive_path: Path, before: int | None = None) -> int:
    """Refuse an archive not carrying the pbxproj's number everywhere; return the number.

    `before` catches a post-action that never ran: docs/design/release.md#no-build-number-bump-in-ship"""
    log, expected = app.log_path("bump-build"), committed_build(app)
    if before is not None and expected <= before:
        raise SystemExit(f"the build number did not move (still {expected}), nothing uploaded.\n"
                         f"  Did the Archive post-action run? See {log}.")
    plists = [(bundle.name, _load(_info_plist(bundle))) for bundle in archived_bundles(archive_path)]
    if bad := [f"  {name}: CFBundleVersion {p.get('CFBundleVersion')}, expected {expected}"
               for name, p in plists if p.get("CFBundleVersion") != str(expected)]:
        raise SystemExit("the archive was not stamped, nothing uploaded:\n" + "\n".join(bad)
                         + f"\n  Did the Archive post-action run? See {log}.")
    short_versions = {name: p.get("CFBundleShortVersionString") for name, p in plists}
    if len(set(short_versions.values())) > 1:  # ITMS-90473 is a warning at Apple, so a warning here
        print(f"warning: the archive's bundles disagree on CFBundleShortVersionString: {short_versions}"
              "\n  list the extensions in snakelane.yml's extension_bundle_ids so bump-version moves them too")
    print(f"archive carries build {expected} in the app and every extension")
    return expected


class _Tee(tuple):
    """Streams written and flushed together."""

    def write(self, text: str) -> int:
        for stream in self:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self:
            stream.flush()


@contextlib.contextmanager
def logging_to(path: Path):
    """Also append everything printed to `path`; Xcode hides a post-action's output."""
    with path.open("a") as log:
        saved = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Tee((saved[0], log)), _Tee((saved[1], log))  # type: ignore[assignment]
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            sys.stdout, sys.stderr = saved


def _stamp_line() -> str:
    return f"[{datetime.now().isoformat(timespec='seconds')}] snakelane bump"


cli = command_app("Pick CFBundleVersion, record it in the pbxproj, and stamp it into an archive. "
                  'Archive post-action: "$HOME/.local/bin/snakelane" bump --archive "$ARCHIVE_PATH"; '
                  "`--post-action` prints the full script.", no_args_is_help=False)


@cli.command()
def bump_command(
    app: AppOption = None,
    archive: Annotated[str | None, typer.Option("--archive", metavar="XCARCHIVE", help="the Archive post-action mode: "
        "pick the number, write it to the pbxproj, stamp it into this finished archive")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="print the number without writing anything")] = False,
    post_action: Annotated[bool, typer.Option(
        "--post-action", help="print the Archive post-action script to paste into the scheme")] = False,
) -> None:
    """Pick CFBundleVersion, record it in the pbxproj, and stamp it into an archive.

    In the scheme's Archive post-action: "$HOME/.local/bin/snakelane" bump --archive "$ARCHIVE_PATH"
    (`--post-action` prints the whole script).
    """
    if post_action:
        return print(POST_ACTION_SCRIPT, end="")
    try:
        located = locate_app(app)
    except SystemExit as error:
        with FALLBACK_LOG.open("a") as log:
            log.write(f"{_stamp_line()} {' '.join(sys.argv[1:])}\nerror: {error}\n")
        raise
    with logging_to(located.log_path("bump-build")):
        try:
            print(f"{_stamp_line()} ({located.folder.name}, {located.pbxproj})")
            if archive is not None:
                if not archive.strip():
                    raise SystemExit(
                        "--archive was given an empty path, so ARCHIVE_PATH is unset: archive NOT "
                        "stamped.\n  Set the post-action's \"Provide build settings from\" to the app target."
                    )
                if not Path(archive).is_dir():
                    raise SystemExit(f"no archive at {archive}, nothing stamped")
            build = next_build(located)
            if dry_run:
                return print("  [dry-run] pbxproj and archive not modified")
            write_pbxproj(located, build)
            if archive is not None:
                stamp_archive(Path(archive), build)
        except SystemExit as error:
            if error.code not in (None, 0) and not isinstance(error.code, int):
                print(f"error: {error.code}", file=sys.stderr)
                raise SystemExit(1) from None
            raise


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane bump")
