"""`store subs show|pull|push`: auto-renewable subscriptions synced with iap.yml's `subscription_groups`.

Prices are never pushed or pulled: set them once on the App Store Connect website; `subs show` prints the
USA price. Why: docs/design/release.md#subscriptions-are-priced-on-the-website
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from .. import project
from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import find_app, keyed
from ..terminal import red
from .catalogue import (
    catalogue_path,
    confirm_create,
    load_subscription_catalogue,
    print_catalogue_lines,
    print_offline_note,
)
from .iap import ensure_availability, finish, sync_localizations, upload_review_screenshot


def find_subscription_groups(client: asc.Client, app_id: str) -> dict[str, dict[str, Any]]:
    """Keyed by reference name, the only stable handle a group has."""
    return keyed(client, f"/v1/apps/{app_id}/subscriptionGroups", "referenceName")


def find_subscriptions(client: asc.Client, group_id: str) -> dict[str, dict[str, Any]]:
    return keyed(client, f"/v1/subscriptionGroups/{group_id}/subscriptions", "productId")


def base_territory_price(client: asc.Client, subscription_id: str, territory: str = "USA") -> str | None:
    """The current customer price in one territory, or None when unpriced."""
    for price in client.get_all(f"/v1/subscriptions/{subscription_id}/prices",
                                {"filter[territory]": territory, "include": "subscriptionPricePoint", "limit": 200}):
        if point := price.get("relationships", {}).get("subscriptionPricePoint", {}).get("data"):
            # No except: a failed read must stop, not read as "unpriced".
            return asc.attributes(client.get(f"/v1/subscriptionPricePoints/{point['id']}")["data"]).get("customerPrice")
    return None


def localizations(client: asc.Client, path: str, fields: dict[str, str]) -> dict[str, dict[str, Any]]:
    """{locale: {local key: live value}} for `fields` {local key: ASC attribute}."""
    return {(a := asc.attributes(loc))["locale"]: {k: a.get(api) for k, api in fields.items()}
            for loc in client.get_all(path)}


def cmd_subs_show(args: SimpleNamespace) -> None:
    _folder, app_config = load_app(args.app)
    client = asc.Client()
    groups = find_subscription_groups(client, find_app(client, app_config)["id"])
    print(f"--- ASC subscription groups for {app_config['bundle_id']} ---")
    if not groups:
        print("  (none)")
    for reference_name, group in groups.items():
        print(f"  group {reference_name!r} ({group['id']})")
        for loc in client.get_all(f"/v1/subscriptionGroups/{group['id']}/subscriptionGroupLocalizations"):
            a = asc.attributes(loc)
            print(f"    [{a.get('locale')}] {a.get('name')!r} customAppName={a.get('customAppName')!r} ({a.get('state')})")
        for product_id, sub in find_subscriptions(client, group["id"]).items():
            a = asc.attributes(sub)
            print(f"    {product_id}: {a.get('name')!r} {a.get('subscriptionPeriod')} level={a.get('groupLevel')} "
                  f"state={a.get('state')} price(USA)={base_territory_price(client, sub['id'])}")
            for loc in client.get_all(f"/v1/subscriptions/{sub['id']}/subscriptionLocalizations"):
                la = asc.attributes(loc)
                print(f"      [{la.get('locale')}] {la.get('name')!r} — {la.get('description')!r} ({la.get('state')})")


def cmd_subs_pull(args: SimpleNamespace) -> None:
    """Write iap.yml's `subscription_groups` from ASC, for an app that already sells subscriptions."""
    folder, app_config = load_app(args.app)
    path = catalogue_path(folder / resolve_platform(app_config, args.platform))
    client = asc.Client()
    groups_out = []
    for reference_name, group in find_subscription_groups(client, find_app(client, app_config)["id"]).items():
        group_locs = localizations(client, f"/v1/subscriptionGroups/{group['id']}/subscriptionGroupLocalizations",
                                   {"name": "name", "custom_app_name": "customAppName"})
        subs_out = []
        for product_id, sub in sorted(find_subscriptions(client, group["id"]).items(),
                                      key=lambda item: asc.attributes(item[1]).get("groupLevel") or 0):
            a = asc.attributes(sub)
            subs_out.append({
                "product_id": product_id, "reference_name": a.get("name"), "period": a.get("subscriptionPeriod"),
                "group_level": a.get("groupLevel"), "family_sharable": bool(a.get("familySharable")),
                **({"review_note": a["reviewNote"]} if a.get("reviewNote") else {}),
                "localizations": {locale: {k: v or "" for k, v in loc.items()} for locale, loc in localizations(
                    client, f"/v1/subscriptions/{sub['id']}/subscriptionLocalizations",
                    {"name": "name", "description": "description"}).items()},
            })
        groups_out.append({"reference_name": reference_name,
                           "localizations": {locale: {k: v for k, v in loc.items() if v} for locale, loc in group_locs.items()},
                           "subscriptions": subs_out})
    # Only this section: one-time purchases and every comment in the file stay as they were.
    project.set_yaml_section(path, "subscription_groups", groups_out,
                             header="# Everything the app sells. `subscription_groups` was written by\n"
                                    "# `snakelane store subs pull` from App Store Connect; edit freely after.\n")
    print(f"wrote subscription_groups in {path} ({sum(len(g['subscriptions']) for g in groups_out)} subscriptions "
          f"in {len(groups_out)} group(s))")


def cmd_subs_push(args: SimpleNamespace) -> None:
    problems: list[str] = []
    folder, app_config = load_app(args.app)
    platform_dir = folder / resolve_platform(app_config, args.platform)
    catalogue = load_subscription_catalogue(platform_dir)
    if args.dry_run and not asc.Credentials.available():
        for group in catalogue:
            print(f"group {group['reference_name']!r}:")
            print_catalogue_lines(group.get("subscriptions", []))
        print_offline_note("iap.yml's subscription_groups")
        return
    client = asc.Client(dry_run=args.dry_run)
    app = find_app(client, app_config)
    live_groups = find_subscription_groups(client, app["id"])
    for group in catalogue:
        reference_name = group["reference_name"]
        print(f"\n→ group {reference_name!r}")
        if (live_group := live_groups.get(reference_name)) is None:
            if not args.create:
                raise SystemExit(f"subscription group {reference_name!r} does not exist in App Store Connect — "
                                 "creating one is deliberate: re-run with --create.")
            live_group = client.post("/v1/subscriptionGroups", asc.resource_body(
                "subscriptionGroups", {"referenceName": reference_name},
                relationships={"app": asc.relationship("apps", app["id"])}))["data"]
            client.report(f"  ✓ group created ({live_group['id']})")
        group_id = live_group["id"]
        # A locale may have an APPROVED copy and an editable draft; prefer the draft.
        live_group_locs: dict[str, dict[str, Any]] = {}
        for loc in client.get_all(f"/v1/subscriptionGroups/{group_id}/subscriptionGroupLocalizations"):
            locale = asc.attributes(loc).get("locale")
            if locale not in live_group_locs or asc.attributes(live_group_locs[locale]).get("state") == "APPROVED":
                live_group_locs[locale] = loc
        sync_localizations(client, "  ", "group localization", "subscriptionGroupLocalizations",
                           {"subscriptionGroup": asc.relationship("subscriptionGroups", group_id)}, live_group_locs,
                           {locale: {"name": w.get("name"), "customAppName": w.get("custom_app_name")}
                            for locale, w in group.get("localizations", {}).items()})

        live_subs = find_subscriptions(client, group_id)
        for sub in group.get("subscriptions", []):
            product_id = sub["product_id"]
            print(f"\n  → {product_id}")
            existing = live_subs.get(product_id)
            if created := existing is None:
                confirm_create(product_id, args.create, "    ", "subscription")
                existing = client.post("/v1/subscriptions", asc.resource_body("subscriptions", {
                    "name": sub["reference_name"], "productId": product_id, "subscriptionPeriod": sub["period"],
                    "groupLevel": sub.get("group_level"), "familySharable": sub.get("family_sharable", False),
                    "reviewNote": sub.get("review_note"),
                }, relationships={"group": asc.relationship("subscriptionGroups", group_id)}))["data"]
                client.report(f"    ✓ created ({existing['id']})")
            sub_id, attrs = existing["id"], asc.attributes(existing)
            rel = asc.relationship("subscriptions", sub_id)
            # Period and family sharing are terms of a live subscription: report a mismatch, never fix it.
            for key, api in (("period", "subscriptionPeriod"), ("family_sharable", "familySharable")):
                if key in sub and attrs.get(api) is not None and sub[key] != attrs.get(api):
                    print(red(f"    ⚠ {key}: local {sub[key]!r} ≠ live {attrs.get(api)!r} — change this in the ASC web UI"))
            if patch := {api: sub[key] for key, api in (("reference_name", "name"), ("review_note", "reviewNote"),
                                                        ("group_level", "groupLevel"))
                         if sub.get(key) is not None and sub[key] != attrs.get(api)}:
                client.patch(f"/v1/subscriptions/{sub_id}", asc.resource_body("subscriptions", patch, id_=sub_id))
                client.report(f"    ✓ updated {', '.join(patch)}")
            sync_localizations(client, "    ", "localization", "subscriptionLocalizations", {"subscription": rel},
                               keyed(client, f"/v1/subscriptions/{sub_id}/subscriptionLocalizations"),
                               {locale: {k: w.get(k) for k in ("name", "description")}
                                for locale, w in sub.get("localizations", {}).items()})
            if created:  # never priced here: docs/design/release.md#subscriptions-are-priced-on-the-website
                print("    → set its price in App Store Connect (Subscriptions → this product → "
                      "Subscription Prices): one price there fills in every territory")
            ensure_availability(client, "    ", f"/v1/subscriptions/{sub_id}/subscriptionAvailability",
                                "subscriptionAvailabilities", ("subscription", "subscriptions", sub_id))
            if shot := sub.get("review_screenshot"):
                upload_review_screenshot(client, "    ", platform_dir.parent / shot,  # relative to metadata/
                                         f"/v1/subscriptions/{sub_id}/appStoreReviewScreenshot",
                                         "subscriptionAppStoreReviewScreenshots", {"subscription": rel},
                                         product_id, problems)
    finish("Subscription", problems, client.dry_run)
