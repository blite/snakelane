"""`snakelane store`: routes listing, screenshot, preview, IAP and subscription commands to their modules.

The metadata folder (default `metadata/`) is written once for every platform; a platform folder holds only
what differs, plus its screenshots. Each field comes from the most specific non-blank file, else it is
skipped, never pushed blank. Why: docs/design/foundations.md#blank-local-text-means-no-opinion

    default/<field>.txt, <locale>/<field>.txt   name, subtitle, description, keywords, promotional_text,
                                          release_notes, support_url, marketing_url, privacy_url, privacy_choices_url
    copyright.txt                         one per version, not per locale
    review/<field>.txt                    App Review contact card + notes (not localized)
    iap.yml, iap/                         products and subscription_groups; their review screenshots
    <platform>/default/, <platform>/<locale>/   version-field overrides (app-level fields refused here)
    <platform>/copyright.txt, <platform>/review/   platform overrides, per file / per field
    <platform>/screenshots/<locale>/      ss-NN.jpg/png and ap-NN.m4v; in iphone/ and ipad/ for iOS

Every command takes `--app` and, except `subs show`, `--platform`. `push --dry-run` needs no key; other
dry runs diff against live when a key is set up.

## snakelane.yml keys this module reads

    "name"          display name, for log lines
    "bundle_id"     how the app is found in App Store Connect (exact match)
    "apple_id"      numeric App Store id, asserted when set; empty = record not created yet
    "locales"       which locales are pushed — NOT whichever folders exist
    "platforms"     which `--platform` values are legal
    "categories"    primary / secondary and their _subcategory_one / _two: Apple's ids, null = unset
    "aliases"       (project.py) extra names `--app` accepts
    "developer_chrome_check"  `screenshots push` OCRs for a debug HUD: true = required, false = never,
                    absent = when the `snakelane[check]` extra is installed
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import Annotated, Any

import typer

from ..args import AppOption, PlatformOption, command_app, run
from ..connect import asc
from ..purchases.iap import cmd_iap_push, cmd_iap_show
from ..purchases.subscriptions import cmd_subs_pull, cmd_subs_push, cmd_subs_show
from ..screenshots.upload import cmd_previews_push, cmd_screenshots_push, cmd_screenshots_show
from .push import cmd_pull, cmd_push, cmd_show

cli = command_app("Push, pull and show the listing, screenshots, App Previews, in-app purchases and "
                  "subscriptions.")
screenshots = command_app("Screenshot decks.")
previews = command_app("App Previews: their own App Store Connect resource, though the files share "
                       "the deck folders.")
iap = command_app("One-time in-app purchases (iap.yml's products).")
subs = command_app("Auto-renewable subscriptions (iap.yml's subscription_groups).")
for sub_app, sub_name in ((screenshots, "screenshots"), (previews, "previews"), (iap, "iap"), (subs, "subs")):
    cli.add_typer(sub_app, name=sub_name)

DRY_RUN = Annotated[bool, typer.Option("--dry-run", help="print the plan; write nothing")]
CREATE = Annotated[bool, typer.Option("--create", help="allow creating products that don't exist yet: "
                                                        "product ids are permanent")]


def call(command: Callable[[SimpleNamespace], None], options: dict[str, Any], show: str | None = None) -> None:
    """Run a command; `show` is suggested when a network failure stops a create partway (`args.run`
    reports the failure itself)."""
    try:
        command(SimpleNamespace(**options))
    except asc.TransientNetworkError:
        if show:
            print("\nThe run stopped partway. Anything already reported as created above EXISTS "
                  f"and its product id is permanent.\n  snakelane store {show}\nshows the live "
                  "catalogue; re-running the push updates what exists rather than duplicating it.",
                  file=sys.stderr)
        raise


@cli.command()
def push(app: AppOption = None, platform: PlatformOption = None,
         dry_run: Annotated[bool, typer.Option("--dry-run", help="print the field plan; no network, no key")] = False,
         skip_lint: Annotated[bool, typer.Option("--skip-lint", help="push even when `snakelane lint` finds "
                                                                    "errors (prefer the config's lint.ignore)")] = False,
         yes: Annotated[bool, typer.Option("--yes", help="skip the confirmation after the diff (non-tty runs)")] = False,
         ) -> None:
    """Push listing text, categories and age rating: diff against live, confirm, write, verify."""
    call(cmd_push, locals())


@cli.command()
def pull(app: AppOption = None, platform: PlatformOption = None) -> None:
    """Write the local listing from what App Store Connect holds."""
    call(cmd_pull, locals())


@cli.command()
def show(app: AppOption = None, platform: PlatformOption = None,
         json: Annotated[bool, typer.Option("--json", help="the live listing as JSON (draft version, else live)")] = False,
         ) -> None:
    """Print the live listing (read-only)."""
    call(cmd_show, locals())


@screenshots.command("push")
def screenshots_push(app: AppOption = None, platform: PlatformOption = None, dry_run: DRY_RUN = False,
                     allow_developer_chrome: Annotated[bool, typer.Option(
                         "--allow-developer-chrome", help="upload even if a shot carries a debug HUD")] = False,
                     ) -> None:
    """Upload each locale's deck, replacing what's live."""
    call(cmd_screenshots_push, locals())


@screenshots.command("show")
def screenshots_show(app: AppOption = None, platform: PlatformOption = None) -> None:
    """List the live screenshot and App Preview sets per locale (read-only)."""
    call(cmd_screenshots_show, locals())


@previews.command("push")
def previews_push(app: AppOption = None, platform: PlatformOption = None, dry_run: DRY_RUN = False) -> None:
    """Upload App Previews from the deck folders, replacing what's live."""
    call(cmd_previews_push, locals())


@iap.command("show")
def iap_show(app: AppOption = None, platform: PlatformOption = None) -> None:
    """List live one-time purchases and their localizations."""
    call(cmd_iap_show, locals())


@iap.command("push")
def iap_push(app: AppOption = None, platform: PlatformOption = None, create: CREATE = False,
             dry_run: DRY_RUN = False,
             product: Annotated[list[str] | None, typer.Option(
                 "--product", metavar="PRODUCT_ID", help="only this product (repeatable)")] = None,
             ) -> None:
    """Sync products: localizations and review note; price, availability and review screenshot at creation only."""
    call(cmd_iap_push, locals(), show="iap show")


@subs.command("show")
def subs_show(app: AppOption = None) -> None:
    """List live subscription groups, subscriptions, localizations and prices."""
    call(cmd_subs_show, locals())


@subs.command("pull")
def subs_pull(app: AppOption = None, platform: PlatformOption = None) -> None:
    """Write iap.yml's subscription_groups from what is live (the rest of the file is kept)."""
    call(cmd_subs_pull, locals())


@subs.command("push")
def subs_push(app: AppOption = None, platform: PlatformOption = None, create: CREATE = False,
              dry_run: DRY_RUN = False) -> None:
    """Sync subscription groups: localizations, review notes, availability. Never prices."""
    call(cmd_subs_push, locals(), show="subs show")


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane store")
