"""`snakelane gamecenter`: Game Center resources from Xcode's `.gamekit` bundle; today, their images.

Xcode's Game Center editor syncs records and text to App Store Connect, but not the images, so
`gamecenter images push` uploads them: diff (pixels) against live, confirm, write, re-read.

## snakelane.yml keys this module reads

    "gamecenter"    {"gamekit": "App/GameCenter/GameCenterResources.gamekit"}: the bundle, repo-relative.
                    Default: the repo's only *.gamekit folder (build output, DerivedData, Pods and
                    dot-folders skipped); none or several is an error naming them
    "bundle_id", "apple_id"   finding the app (listing/store.py)
"""

from __future__ import annotations

from typing import Annotated

import typer

from ..args import AppOption, command_app, run
from ..listing.store import call
from .images import cmd_push, cmd_show

cli = command_app("Game Center resources from Xcode's .gamekit bundle.")
images = command_app("Achievement, leaderboard and activity images: Xcode's sync leaves them out.")
cli.add_typer(images, name="images")


@images.command("show")
def images_show(app: AppOption = None) -> None:
    """Each bundle image against App Store Connect: new, changed, unchanged or skipped (read-only)."""
    call(cmd_show, locals())


@images.command("push")
def images_push(app: AppOption = None,
                dry_run: Annotated[bool, typer.Option("--dry-run", help="compare against App Store Connect and "
                                                                        "print the writes; write nothing")] = False,
                yes: Annotated[bool, typer.Option("--yes", help="skip the confirmation (non-tty runs)")] = False,
                new_version: Annotated[bool, typer.Option(
                    "--new-version", help="for a record whose newest version is LIVE, create the next version "
                                          "and put the image there (it goes to review)")] = False,
                ) -> None:
    """Upload new and changed images: compare pixels with live, confirm, upload, re-read and verify."""
    call(cmd_push, locals())


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane gamecenter")
