"""`snakelane store`: routes listing, media (screenshots, previews, creative), IAP and subscription commands
to their modules. `store screenshots|previews|creative` are the older, hidden spellings of `store media
--only …`, kept because apps' docs and scripts call them.

The metadata folder (default `metadata/`) is sorted by kind, and its listing is written once for every
platform; a platform folder holds only what differs. Each field comes from the most specific non-blank
file, else it is skipped, never pushed blank. Why: docs/design/foundations.md#blank-local-text-means-no-opinion

    listing/default/<field>.txt           name, subtitle, description, keywords, promotional_text,
    listing/locales/<locale>/<field>.txt    release_notes, support_url, marketing_url, privacy_url,
                                            privacy_choices_url
    listing/default/review_notes.txt      the App Review notes (not localized; the contact is
                                          snakelane.yml's review.contact)
    snakelane.yml's copyright             one per version, not per locale
    listing/<platform>/default/, …/locales/<locale>/, …/copyright.txt
                                          platform overrides (app-level fields refused here)
    purchases/iap.yml, purchases/         products and subscription_groups; their review screenshots
    screenshots/<platform>/<locale>/      ss-NN.jpg and ap-NN.m4v; in iphone/, ipad/ and duo/ for iOS
    creative/<locale>/, creative/default/  search-result.*, product-page-header.*, universal.png
                                          (store creative; creative/<platform>/ overrides)
    release/asset_packs.json              the asset pack record

An app still in the flat layout (no listing/) reads as before; `snakelane migrate-layout` moves it.

Every command takes `--app` and, except `subs show`, `--platform`. Every `--dry-run` reads App Store
Connect and shows what would change when a key is set up, and the local plan when none is.

## snakelane.yml keys this module reads

    "name"          display name, for log lines
    "bundle_id"     how the app is found in App Store Connect (exact match)
    "apple_id"      numeric App Store id, asserted when set; empty = record not created yet
    "locales"       which locales are pushed — NOT whichever folders exist
    "platforms"     which `--platform` values are legal
    "categories"    primary / secondary and their _subcategory_one / _two: Apple's ids, null = unset
    "aliases"       (project.py) extra names `--app` accepts
    "developer_chrome_check"  `media push` OCRs for a debug HUD: true = required, false = never,
                    absent = when the `snakelane[check]` extra is installed
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from enum import Enum
from types import SimpleNamespace
from typing import Annotated, Any

import typer

from ..args import AppOption, PlatformOption, command_app, run
from ..connect import asc
from ..purchases.iap import cmd_iap_push, cmd_iap_show
from ..purchases.subscriptions import cmd_subs_pull, cmd_subs_push, cmd_subs_show
from ..screenshots.creative import cmd_creative_push, cmd_creative_show
from ..screenshots.upload import (
    MEDIA,
    cmd_media_push,
    cmd_media_show,
    cmd_previews_push,
    cmd_screenshots_push,
    cmd_screenshots_show,
)
from .push import cmd_pull, cmd_push, cmd_show

cli = command_app("Push, pull and show the listing, screenshots, App Previews, creative assets, in-app "
                  "purchases and subscriptions.")
media = command_app("Screenshots, App Previews and creative assets (the product page header and search-result "
                    "asset), pushed together; --only picks some.")
screenshots = command_app("Screenshot decks.")
previews = command_app("App Previews: their own App Store Connect resource, though the files share "
                       "the deck folders.")
iap = command_app("One-time in-app purchases (iap.yml's products).")
subs = command_app("Auto-renewable subscriptions (iap.yml's subscription_groups).")
creative = command_app("Creative assets: the product page header and the search-result image or video, "
                       "through the App Asset Library.")
for sub_app, sub_name in ((media, "media"), (iap, "iap"), (subs, "subs")):
    cli.add_typer(sub_app, name=sub_name)
for sub_app, sub_name in ((screenshots, "screenshots"), (previews, "previews"), (creative, "creative")):
    cli.add_typer(sub_app, name=sub_name, hidden=True)

DRY_RUN = Annotated[bool, typer.Option("--dry-run", help="print the plan; write nothing")]
Media = Enum("Media", {name: name for name in MEDIA}, type=str)
ONLY = Annotated[list[Media] | None, typer.Option("--only", help="only these (repeatable); default: all three")]
ALLOW_DEVELOPER_CHROME = Annotated[bool, typer.Option("--allow-developer-chrome",
                                                      help="upload even if a shot carries a debug HUD")]
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
         dry_run: Annotated[bool, typer.Option("--dry-run", help="diff against App Store Connect and stop; without a key, print the local plan")] = False,
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


@media.command("push")
def media_push(app: AppOption = None, platform: PlatformOption = None, only: ONLY = None, dry_run: DRY_RUN = False,
               allow_developer_chrome: ALLOW_DEVELOPER_CHROME = False) -> None:
    """Upload each locale's deck and previews, replacing what's live, then place the creative assets."""
    only = [m.value for m in only] if only else None
    call(cmd_media_push, locals())


@media.command("show")
def media_show(app: AppOption = None, platform: PlatformOption = None, only: ONLY = None) -> None:
    """List the live screenshot and preview sets and creative placements per locale (read-only)."""
    only = [m.value for m in only] if only else None
    call(cmd_media_show, locals())


@screenshots.command("push")
def screenshots_push(app: AppOption = None, platform: PlatformOption = None, dry_run: DRY_RUN = False,
                     allow_developer_chrome: ALLOW_DEVELOPER_CHROME = False) -> None:
    """Same as `store media push --only screenshots`."""
    call(cmd_screenshots_push, locals())


@screenshots.command("show")
def screenshots_show(app: AppOption = None, platform: PlatformOption = None) -> None:
    """Same as `store media show --only screenshots --only previews`."""
    call(cmd_screenshots_show, locals())


@previews.command("push")
def previews_push(app: AppOption = None, platform: PlatformOption = None, dry_run: DRY_RUN = False) -> None:
    """Same as `store media push --only previews`."""
    call(cmd_previews_push, locals())


@creative.command("push")
def creative_push(app: AppOption = None, platform: PlatformOption = None, dry_run: DRY_RUN = False) -> None:
    """Same as `store media push --only creative`."""
    call(cmd_creative_push, locals())


@creative.command("show")
def creative_show(app: AppOption = None, platform: PlatformOption = None) -> None:
    """Same as `store media show --only creative`."""
    call(cmd_creative_show, locals())


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
