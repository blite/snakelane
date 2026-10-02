"""`store iap show|push`: one-time in-app purchases synced from iap.yml's `products`, plus the sync steps
subscriptions share."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import (
    find_app,
    get_optional,
    keyed,
    report_processing,
    upload_asset_resource,
    wait_for_asset_processing,
)
from ..terminal import green, red
from .catalogue import (
    confirm_create,
    load_iap_catalogue,
    print_catalogue_lines,
    print_offline_note,
    select_iap_products,
)


def sync_localizations(client: asc.Client, indent: str, label: str, kind: str,
                       relationships: dict[str, Any], live: dict[str, dict[str, Any]],
                       wanted: dict[str, dict[str, Any]]) -> None:
    """Create missing locales, PATCH only changed non-blank fields: a touched localization re-opens review."""
    for locale, fields in wanted.items():
        fields = {k: v for k, v in fields.items() if v}
        if (current := live.get(locale)) is None:
            client.post(f"/v1/{kind}", asc.resource_body(kind, {"locale": locale, **fields},
                                                         relationships=relationships))
            client.report(f"{indent}✓ {label} created [{locale}]")
        elif not (changed := {k: v for k, v in fields.items() if v != asc.attributes(current).get(k)}):
            print(f"{indent}= {label} [{locale}] already matches")
        else:
            client.patch(f"/v1/{kind}/{current['id']}", asc.resource_body(kind, changed, id_=current["id"]))
            client.report(f"{indent}✓ {label} updated [{locale}]: {', '.join(changed)}")


def ensure_availability(client: asc.Client, indent: str, existing: str, kind: str,
                        relationship: tuple[str, str, str]) -> None:
    """Every territory, and new ones, once; `relationship` is (name, type, id) of the product."""
    if get_optional(client, existing) is not None:
        print(f"{indent}= availability already configured — skipped")
    else:
        territories = [t["id"] for t in client.get_all("/v1/territories", {"limit": 200})]
        name, rel_type, rel_id = relationship
        client.post(f"/v1/{kind}", {"data": {
            "type": kind,
            "attributes": {"availableInNewTerritories": True},
            "relationships": {name: asc.relationship(rel_type, rel_id),
                              "availableTerritories": {"data": [{"type": "territories", "id": t} for t in territories]}},
        }})
        client.report(f"{indent}✓ availability set: {len(territories)} territories, available in new ones")


def upload_review_screenshot(client: asc.Client, indent: str, path: Path, existing: str, kind: str,
                             relationships: dict[str, Any], product_id: str, problems: list[str]) -> None:
    """Uploaded once (replacing re-opens review); a reject is reported in `problems`, not retried."""
    if not path.exists():
        print(f"{indent}⚠ review screenshot missing at {path} — skipped")
    elif get_optional(client, existing) is not None:
        print(f"{indent}= review screenshot already uploaded — skipped (replacing re-opens review)")
    else:
        shot_id = upload_asset_resource(client, kind, path, relationships)
        _, failed, timed_out = wait_for_asset_processing(client, kind, {shot_id: f"review screenshot {path.name}"})
        if report_processing(failed, timed_out, indent):
            client.report(green(f"{indent}✓ review screenshot uploaded and accepted ({path.name})"))
        else:
            problems.append(f"{product_id}: review screenshot rejected or still processing (see above)")


def finish(what: str, problems: list[str], dry: bool) -> None:
    """Anything that didn't land is reported together, and sets the exit code."""
    if problems:
        raise SystemExit(red(f"\n{what} push finished with problems:\n  " + "\n  ".join(problems)))
    print("\n[dry-run] nothing was written." if dry else f"\n{what} push complete. Submit for review from ASC when ready.")


def create_price_schedule(client: asc.Client, product_id: str, price: dict[str, str]) -> None:
    territory, wanted = price["base_territory"], price["customer_price"]
    if asc.planned(product_id):  # a product the dry run would create has no price points to look up yet
        return print(f"  [dry-run] would set price: {wanted} ({territory} base)")
    points = client.get_all(f"/v2/inAppPurchases/{product_id}/pricePoints", {"filter[territory]": territory, "limit": 200})
    if not (point_id := next((p["id"] for p in points if asc.attributes(p).get("customerPrice") == wanted), None)):
        raise SystemExit(f"no price point with customerPrice={wanted!r} in {territory} — "
                         "list them with the ASC API or pick a standard tier price")
    # Compound document: the new manual price rides in `included` under a placeholder id.
    placeholder = "${new-price}"
    client.post("/v1/inAppPurchasePriceSchedules", {
        "data": {"type": "inAppPurchasePriceSchedules", "relationships": {
            "inAppPurchase": asc.relationship("inAppPurchases", product_id),
            "baseTerritory": asc.relationship("territories", territory),
            "manualPrices": {"data": [{"type": "inAppPurchasePrices", "id": placeholder}]},
        }},
        "included": [{"type": "inAppPurchasePrices", "id": placeholder,
                      "attributes": {"startDate": None, "endDate": None},
                      "relationships": {"inAppPurchasePricePoint": asc.relationship("inAppPurchasePricePoints", point_id)}}],
    })
    client.report(f"  ✓ price schedule created: {wanted} ({territory} base)")


def cmd_iap_show(args: SimpleNamespace) -> None:
    folder, app_config = load_app(args.app)
    load_iap_catalogue(folder / resolve_platform(app_config, args.platform))  # validates limits even in show
    client = asc.Client()
    live = keyed(client, f"/v1/apps/{find_app(client, app_config)['id']}/inAppPurchasesV2", "productId")
    print(f"--- ASC in-app purchases for {app_config['bundle_id']} ---")
    if not live:
        print("  (none)")
    for product_id, resource in live.items():
        a = asc.attributes(resource)
        print(f"  {product_id}: {a.get('name')!r} [{a.get('inAppPurchaseType')}] state={a.get('state')}")
        for loc in client.get_all(f"/v2/inAppPurchases/{resource['id']}/inAppPurchaseLocalizations"):
            la = asc.attributes(loc)
            print(f"    [{la.get('locale')}] {la.get('name')!r} — {la.get('description')!r} ({la.get('state')})")


def cmd_iap_push(args: SimpleNamespace) -> None:
    problems: list[str] = []
    folder, app_config = load_app(args.app)
    platform_dir = folder / resolve_platform(app_config, args.platform)
    catalogue = select_iap_products(load_iap_catalogue(platform_dir), args.product)
    if args.product:
        print(f"Pushing {len(catalogue)} of the catalogue: " + ", ".join(p["product_id"] for p in catalogue))
    if args.dry_run and not asc.Credentials.available():
        print_catalogue_lines(catalogue)
        print_offline_note("iap.yml")
        return
    client = asc.Client(dry_run=args.dry_run)
    app = find_app(client, app_config)
    live = keyed(client, f"/v1/apps/{app['id']}/inAppPurchasesV2", "productId")
    for product in catalogue:
        product_id = product["product_id"]
        print(f"\n→ {product_id}")
        if (existing := live.get(product_id)) is None:
            confirm_create(product_id, args.create, "  ", "product")
            existing = client.post("/v2/inAppPurchases", asc.resource_body("inAppPurchases", {
                "name": product["reference_name"], "productId": product_id, "inAppPurchaseType": product["type"],
                "familySharable": product.get("family_sharable", False),
            }, relationships={"app": asc.relationship("apps", app["id"])}))["data"]
            client.report(f"  ✓ created ({existing['id']})")
        resource_id = existing["id"]
        rel = asc.relationship("inAppPurchases", resource_id)
        if (note := product.get("review_note")) and asc.attributes(existing).get("reviewNote") != note:
            client.patch(f"/v2/inAppPurchases/{resource_id}",
                         asc.resource_body("inAppPurchases", {"reviewNote": note}, id_=resource_id))
            client.report("  ✓ reviewNote updated")
        sync_localizations(client, "  ", "localization", "inAppPurchaseLocalizations", {"inAppPurchaseV2": rel},
                           keyed(client, f"/v2/inAppPurchases/{resource_id}/inAppPurchaseLocalizations"),
                           {locale: {k: w.get(k) for k in ("name", "description")}
                            for locale, w in product.get("localizations", {}).items()})
        # Price, availability and review screenshot are set once, never changed by a sync.
        # Why: docs/design/release.md#set-once-price-availability-and-review-screenshot
        if product.get("price"):
            if get_optional(client, f"/v2/inAppPurchases/{resource_id}/iapPriceSchedule") is None:
                create_price_schedule(client, resource_id, product["price"])
            else:
                print("  = price schedule already exists (repricing is web-UI territory — skipped)")
        ensure_availability(client, "  ", f"/v2/inAppPurchases/{resource_id}/inAppPurchaseAvailability",
                            "inAppPurchaseAvailabilities", ("inAppPurchase", "inAppPurchases", resource_id))
        if shot := product.get("review_screenshot"):
            upload_review_screenshot(client, "  ", platform_dir.parent / shot,  # relative to metadata/
                                     f"/v2/inAppPurchases/{resource_id}/appStoreReviewScreenshot",
                                     "inAppPurchaseAppStoreReviewScreenshots", {"inAppPurchaseV2": rel},
                                     product_id, problems)
    finish("IAP", problems, client.dry_run)
