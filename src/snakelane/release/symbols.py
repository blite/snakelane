"""Upload an archive's dSYMs to Sentry, so the crashes it reports symbolicate.

    snakelane ship symbols [--platform macos]

`ship beta` and `ship release` do this on their own after the TestFlight upload when the app
names a Sentry project; `ship symbols` re-sends the last archive's, for when that step failed.
The token is sentry-cli's (`sentry-cli login`, kept in ~/.sentryclirc): snakelane never reads,
stores or passes it. Why: docs/design/release.md#dsyms-to-sentry

snakelane.yml keys:
    "sentry"    absent = no upload. All three are checked before the test gate runs:
        "org"       (required) the organization slug.
        "project"   (required) the project slug.
        "url"       a self-hosted Sentry's address (default: sentry.io).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..project import App
from ..xcode import run, show

SENTRY_KEYS = {"org", "project", "url"}


def sentry_config(app: App) -> dict[str, Any] | None:
    """The app's `sentry` block, checked, or None when it has none."""
    if (config := app.config.get("sentry")) is None:
        return None
    if not isinstance(config, dict):
        raise SystemExit("sentry is an object: {org: …, project: …}")
    if unknown := set(config) - SENTRY_KEYS:
        raise SystemExit(f"sentry: unknown key {', '.join(sorted(unknown))} (expected org, project, url)")
    for key in ("org", "project"):
        if not config.get(key):
            raise SystemExit(f'sentry is missing "{key}"')
    return config


def cli_base(config: dict[str, Any]) -> list[str]:
    """sentry-cli with the global options every call needs."""
    return ["sentry-cli", *(["--url", config["url"]] if config.get("url") else [])]


def upload_command(config: dict[str, Any], archive: Path) -> list[str]:
    return [*cli_base(config), "debug-files", "upload", "--org", config["org"], "--project", config["project"],
            str(archive / "dSYMs")]


def preflight(app: App) -> None:
    """Before the test gate: a missing sentry-cli or sign-in should cost seconds, not an archive.
    Why: docs/design/release.md#dsyms-to-sentry"""
    if (config := sentry_config(app)) is None:
        return
    if shutil.which("sentry-cli") is None:
        raise SystemExit("sentry is set but sentry-cli isn't installed: brew install getsentry/tools/sentry-cli, "
                         "then sentry-cli login")
    # `--no-defaults` checks the token alone; the org and project come from snakelane.yml.
    check = subprocess.run([*cli_base(config), "info", "--no-defaults"], capture_output=True, text=True)
    if check.returncode:
        raise SystemExit(f"sentry-cli can't sign in to {config.get('url') or 'sentry.io'}: run sentry-cli login "
                         "with a token that may upload debug files (project:releases)")


def upload(app: App, archive: Path, platform: str) -> str | None:
    """Send `archive`'s dSYMs when the app names a Sentry project: None on success (or nothing
    to do), else what went wrong. The caller decides whether that stops it: after a TestFlight
    upload it only warns, because the build is already on its way."""
    if (config := sentry_config(app)) is None:
        return None
    if not any((archive / "dSYMs").glob("*.dSYM")):
        return f"{archive.name} has no dSYMs; check DEBUG_INFORMATION_FORMAT is dwarf-with-dsym for Release"
    command = upload_command(config, archive)
    try:
        run(command)
    except subprocess.CalledProcessError:
        retry = "snakelane ship symbols" + ("" if platform == "ios" else f" --platform {platform}")
        return (f"the dSYM upload to Sentry failed, so crashes from this build won't symbolicate until it's sent. "
                f"Retry with {retry} (or: {show(command)})")
    print(f"uploaded dSYMs to Sentry ({config['org']}/{config['project']})")
    return None
