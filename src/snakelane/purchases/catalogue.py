"""metadata/iap.yml: what the app sells — one-time `products` and `subscription_groups` — loaded and validated.

Product ids are permanent at Apple: creation is behind `--create`.
Why: docs/design/release.md#in-app-purchases-and-subscriptions
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import project
from ..terminal import red

CATALOGUE = "iap.yml"
CATALOGUE_KEYS = {"products", "subscription_groups"}
# Keys an entry may carry; others warn as likely misspellings. "_" keys are comments.
IAP_PRODUCT_KEYS = {"product_id", "reference_name", "type", "family_sharable", "price", "review_note",
                    "review_screenshot", "localizations"}
SUBSCRIPTION_GROUP_KEYS = {"reference_name", "localizations", "subscriptions"}
SUBSCRIPTION_KEYS = {"product_id", "reference_name", "period", "group_level", "family_sharable", "review_note",
                     "localizations", "review_screenshot"}
SUBSCRIPTION_PERIODS = {"ONE_WEEK", "ONE_MONTH", "TWO_MONTHS", "THREE_MONTHS", "SIX_MONTHS", "ONE_YEAR"}
# Apple's limits, IAPs and subscriptions alike; ASC rejects the whole request when one is over.
LOCALIZATION_LIMITS = {"name": 30, "description": 45}
GROUP_NAME_LIMIT = {"name": 75}
# Checked only at creation, when an id becomes permanent.
PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._]+$")


def warn_unknown_keys(path: Path, owner: str, entry: dict[str, Any], known: set[str]) -> None:
    if unknown := sorted(k for k in entry if k not in known and not k.startswith("_")):
        print(red(f"⚠ {path.name}: {owner} has unknown key(s) {unknown} — ignored. Expected some of {sorted(known)}."))


def check_lengths(path: Path, owner: str, localizations: dict[str, Any], limits: dict[str, int]) -> None:
    for locale, loc in localizations.items():
        for key, limit in limits.items():
            if len(value := loc.get(key, "")) > limit:
                raise SystemExit(f"{path}: {owner} [{locale}] {key} is {len(value)} chars (limit {limit})")


def confirm_create(product_id: str, create: bool, indent: str, what: str) -> None:
    """Stop unless --create, and refuse an id ASC won't accept before it is spent."""
    if not create:
        raise SystemExit(f"{product_id} does not exist in App Store Connect. Product ids are permanent — like "
                         "Game Center ids, they can never be reused, even after deletion — so creating one is "
                         "deliberate: re-run with --create.")
    if not PRODUCT_ID_PATTERN.match(product_id):
        raise SystemExit(f"{product_id!r} is not a legal product id — App Store Connect accepts only letters, "
                         "digits, underscores and periods, and the id is permanent once created. "
                         "Rename it in the catalogue before --create spends it.")
    print(f"{indent}⚠ creating {what} {product_id} — this id is now permanently spoken for.")


def catalogue_path(platform_dir: Path) -> Path:
    """metadata/iap.yml: purchases belong to the app, not a platform (universal purchase)."""
    return platform_dir.parent / CATALOGUE


def read_catalogue(platform_dir: Path) -> tuple[Path, dict[str, Any]]:
    """Both sections share one id space, so a repeated id is refused here.

    Why one file: docs/design/release.md#one-catalogue-file"""
    if not (path := catalogue_path(platform_dir)).exists():
        raise SystemExit(f"no catalogue at {path} — this app has no {CATALOGUE}")
    if not isinstance(data := project.load_yaml(path) or {}, dict):
        raise SystemExit(f"{path}: expected `products:` and/or `subscription_groups:` at the top level")
    warn_unknown_keys(path, "the catalogue", data, CATALOGUE_KEYS)
    entries = [*(data.get("products") or []),
               *(s for g in data.get("subscription_groups") or [] for s in g.get("subscriptions") or [])]
    if not_jpeg := [f"{e.get('product_id')}: {shot}" for e in entries
                    if (shot := e.get("review_screenshot")) and Path(shot).suffix.lower() not in project.DECK_SUFFIXES]:
        raise SystemExit(f"{path}: review screenshots must be JPEG (docs/adr/0002-jpeg-only-screenshot-decks.md), "
                         "and these are not:\n" + "".join(f"  {line}\n" for line in not_jpeg)
                         + "Convert them; App Store Connect also rejects an alpha channel, which JPEG can't carry.")
    ids = [e.get("product_id") for e in entries]
    if repeated := sorted({i for i in ids if i and ids.count(i) > 1}):
        raise SystemExit(f"{path}: product id(s) used more than once: {', '.join(repeated)} — one-time "
                         "purchases and subscriptions share one id space, and an id is permanent")
    return path, data


def load_iap_catalogue(platform_dir: Path) -> list[dict[str, Any]]:
    path, data = read_catalogue(platform_dir)
    if not (products := data.get("products")):
        raise SystemExit(f"no one-time purchases (`products:`) in {path}")
    for product in products:
        warn_unknown_keys(path, product.get("product_id", "a product"), product, IAP_PRODUCT_KEYS)
        check_lengths(path, product.get("product_id"), product.get("localizations", {}), LOCALIZATION_LIMITS)
    return products


def select_iap_products(catalogue: list[dict[str, Any]], wanted: list[str] | None) -> list[dict[str, Any]]:
    """`--product` ids in the order given, else everything. Full ids only, no guessing: an id is permanent."""
    if not wanted:
        return catalogue
    by_id = {product["product_id"]: product for product in catalogue}
    if unknown := next((p for p in wanted if p not in by_id), None):
        example = f", e.g. {catalogue[0]['product_id']}" if catalogue else ""
        raise SystemExit(f"--product {unknown!r} is not a product id in iap.yml. Use the full id{example}")
    return [by_id[p] for p in dict.fromkeys(wanted)]


def print_catalogue_lines(catalogue: list[dict[str, Any]]) -> None:
    """An already-validated catalogue one product a line, for a dry run without credentials."""
    for product in catalogue:
        price = (product.get("price") or {}).get("customer_price")
        locales = ", ".join(product.get("localizations", {}))
        print(f"  {product['product_id']} [{product.get('type') or product.get('period')}]"
              f"{f' {price}' if price else ''} — {locales or 'no localizations'}")


def print_offline_note(what: str) -> None:
    print(f"\n[dry-run] no API key set up (`snakelane auth setup`), so {what} was validated "
          "locally but not compared with App Store Connect. Nothing was written.")


def load_subscription_catalogue(platform_dir: Path) -> list[dict[str, Any]]:
    """Same rules as `products`: docs/design/release.md#set-once-price-availability-and-review-screenshot"""
    path = catalogue_path(platform_dir)
    if not (groups := (read_catalogue(platform_dir)[1] if path.exists() else {}).get("subscription_groups")):
        raise SystemExit(f"no `subscription_groups:` in {path} — run `snakelane store subs pull` to write them from ASC")
    for group in groups:
        warn_unknown_keys(path, f"group {group.get('reference_name')!r}", group, SUBSCRIPTION_GROUP_KEYS)
        for sub in group.get("subscriptions", []):
            if "price" in sub:  # older catalogues carried one: explain rather than warn "unknown key"
                print(f"  ({sub.get('product_id')}: price is ignored — subscriptions are priced on "
                      "App Store Connect's website, where one price fills in every territory)")
            warn_unknown_keys(path, sub.get("product_id", "a subscription"),
                              {k: v for k, v in sub.items() if k != "price"}, SUBSCRIPTION_KEYS)
            if (period := sub.get("period")) not in SUBSCRIPTION_PERIODS:
                raise SystemExit(f"{path}: {sub['product_id']} has period {period!r} — expected one of "
                                 f"{sorted(SUBSCRIPTION_PERIODS)}")
            check_lengths(path, sub["product_id"], sub.get("localizations", {}), LOCALIZATION_LIMITS)
        check_lengths(path, f"group {group.get('reference_name')!r}", group.get("localizations", {}), GROUP_NAME_LIMIT)
    return groups
