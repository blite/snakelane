"""`snakelane <command> …`: routes each command to its module's `main(argv)`."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from . import __version__, project

# command -> (module, one-line summary)
COMMANDS: dict[str, tuple[str, str]] = {
    "auth": ("connect.auth", "install and check the App Store Connect API key"),
    "store": ("listing.store", "listing text, categories, screenshots, previews, IAPs and subscriptions"),
    "ship": ("release.ship", "test → archive → TestFlight → submit for review"),
    "shoot": ("screenshots.shoot", "shoot the screenshot deck from the app's UI test"),
    "bump": ("release.bump", "set and stamp CFBundleVersion (the Archive post-action)"),
    "packs": ("release.assetpacks", "package and upload Background Assets packs"),
    "check": ("screenshots.check", "OCR a deck for developer overlays (debug HUDs) before upload"),
    "frame": ("screenshots.frame", "caption the deck again from its raw shots, without shooting"),
    "lint": ("listing.lint", "lint the listing for what App Review rejects, offline"),
    "translations": ("listing.translations", "track which translated fields are stale or unreviewed"),
    "status": ("release.status", "what App Store Connect holds right now: versions, review, builds"),
    "init": ("init", "write snakelane.yml and metadata/ for an Xcode project"),
    "gallery": ("screenshots.gallery", "an HTML page of every deck and a search-result mock, for review"),
}

def usage() -> str:
    width = max(map(len, COMMANDS))
    return "\n".join([
        f"snakelane {__version__} — App Store Connect from plain-text metadata/, without fastlane", "",
        "usage: snakelane [-C <repo>] [--config <file>] <command> [args…]", "", "commands:",
        *(f"  {name:<{width}}  {summary}" for name, (_, summary) in COMMANDS.items()),
        "", "Run `snakelane <command> --help` for a command's own options."])


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    while args[:1] in (["-C"], ["--config"]):
        if len(args) < 2:
            raise SystemExit(f"{args[0]} needs a {'directory' if args[0] == '-C' else 'file'}")
        if args[0] == "-C":
            os.chdir(args[1])
        else:  # resolved now, so a later -C doesn't move it
            project.config_override = Path(args[1]).expanduser().resolve()
        args = args[2:]
    if not args or args[0] in ("-h", "--help", "help"):
        return print(usage())
    if args[0] in ("-V", "--version"):
        return print(__version__)
    command, rest = args[0], args[1:]
    if command not in COMMANDS:
        raise SystemExit(f"unknown command {command!r}\n\n{usage()}")
    sys.argv = [f"snakelane {command}", *rest]
    importlib.import_module(f".{COMMANDS[command][0]}", __package__).main(rest)


if __name__ == "__main__":
    main()
