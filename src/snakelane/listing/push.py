"""`store push`, `store pull` and `store show`: listing text, categories, copyright, App Review card and age
rating — planned offline, diffed against live, confirmed, written, verified."""

from __future__ import annotations

import contextlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .. import project
from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import (
    find_app,
    find_editable_app_info,
    find_editable_version,
    find_listing_version,
    find_or_create_locale_resource,
    get_optional,
    live_version,
)
from ..terminal import dim, format_text_diff, green, red, truncate
from . import lint, translations
from .fields import (
    APP_CATEGORIES,
    CATEGORY_INCLUDE,
    CATEGORY_RELATIONSHIP_NAMES,
    LISTING,
    REVIEW,
    age_rating_attributes,
    category_problems,
    hard_limit_problems,
    mask,
    read_copyright,
    read_listing,
    read_review,
    review_attributes,
)

SKIPPED = ": (no file, or empty — skipped)"
LONG = {"description", "promotional_text", "release_notes"}  # `store show` prints their start


def build_push_plan(platform_dir: Path, locales: list[str], app_config: dict[str, Any]) -> dict[str, Any]:
    """Every field from disk into the exact plan `cmd_push` runs. No network, so --dry-run needs no key."""
    categories = app_config.get("categories", {})
    if unknown := sorted(set(categories) - set(CATEGORY_RELATIONSHIP_NAMES)):  # else a KeyError, or silently skipped
        raise SystemExit(f"snakelane.yml \"categories\" has unknown key(s) {unknown} — expected "
                         f"{sorted(CATEGORY_RELATIONSHIP_NAMES)}")
    if problems := category_problems(categories, APP_CATEGORIES):
        raise SystemExit("snakelane.yml \"categories\": " + "; ".join(problems)
                         + " (checked against Apple's list as of 2026-10; see listing/fields.py APP_CATEGORIES)")
    per_locale = read_listing(platform_dir, locales)
    plan = {
        "age_rating": age_rating_attributes(app_config.get("age_rating")),
        "category_relationships": {CATEGORY_RELATIONSHIP_NAMES[k]: v for k, v in categories.items() if v},
        "copyright": read_copyright(platform_dir),
        "per_locale": per_locale,
        "review": read_review(platform_dir),
    }
    violations = [f"{locale}/{stem}: {message}" for locale, fields in per_locale.items()
                  for stem, value in fields.items() for _, message in hard_limit_problems(stem, value)]
    violations += [f"review/notes: {message}" for _, message in hard_limit_problems("notes", plan["review"].get("notes"))]
    if violations:
        for violation in violations:
            print(red(f"✗ {violation}"))
        raise SystemExit("field(s) App Store Connect would reject — fix the files above")
    return plan


def print_push_plan(plan: dict[str, Any]) -> None:
    def field(name: str, value: str | None, note: str = "") -> None:
        print(f"  {name} = {truncate(value)!r}{note}" if value else f"  {name}{SKIPPED}")

    if plan["age_rating"]:
        print("-- age rating --")
        for name, value in plan["age_rating"].items():
            print(f"  {name} = {value!r}")
    print("-- AppInfo categories --")
    for name, value in plan["category_relationships"].items():
        print(f"  {name} = {value}")
    if not plan["category_relationships"]:
        print("  (none set in snakelane.yml — skipped)")
    print("-- AppStoreVersion --")
    field("copyright", plan["copyright"])
    for locale, fields in plan["per_locale"].items():
        for home, label in (("app", "AppInfoLocalization"), ("version", "AppStoreVersionLocalization")):
            print(f"-- {locale}: {label} --")
            for stem in (s for s, f in LISTING.items() if f.home == home):
                field(stem, fields[stem], " (pushed only if a prior live version exists — checked at push time)"
                      if stem == "release_notes" else "")
    print("-- App Review information (appStoreReviewDetail) --")
    for key, value in plan["review"].items():
        print(f"  {key} = {mask(key, truncate(str(value)))!r}")
    if not plan["review"]:
        print("  (no review/ files — skipped)")


def push_review_detail(client: asc.Client, version: dict[str, Any], review: dict[str, str]) -> None:
    """Create or update: Apple doesn't create it on a fresh app.

    Why: docs/design/foundations.md#the-review-detail-is-created-on-first-push"""
    attrs = review_attributes(review)
    if existing := get_optional(client, f"/v1/appStoreVersions/{version['id']}/appStoreReviewDetail"):
        client.patch(f"/v1/appStoreReviewDetails/{existing['id']}",
                     asc.resource_body("appStoreReviewDetails", attrs, id_=existing["id"]))
    else:
        client.post("/v1/appStoreReviewDetails", asc.resource_body(
            "appStoreReviewDetails", attrs,
            relationships={"appStoreVersion": asc.relationship("appStoreVersions", version["id"])}))
    print(f"✓ appStoreReviewDetail {'updated' if existing else 'created'}: {', '.join(attrs)}")


def category_ids(client: asc.Client, app_info_id: str) -> dict[str, str | None]:
    """Needs `include`, or the relationships carry only links."""
    payload = client.get(f"/v1/appInfos/{app_info_id}", {"include": CATEGORY_INCLUDE})
    relationships = payload.get("data", {}).get("relationships", {})
    return {name: ((relationships.get(name) or {}).get("data") or {}).get("id")
            for name in CATEGORY_RELATIONSHIP_NAMES.values()}


def fetch_live_state(client: asc.Client, app_info_id: str, version: dict[str, Any], locales: list[str]) -> dict[str, Any]:
    """Live values shaped like the plan, so the pre-push diff and post-push verification are one comparison."""
    def by_locale(path: str) -> dict[str, Any]:
        return {asc.attributes(item).get("locale"): item for item in client.get_all(path)}

    info_locs = by_locale(f"/v1/appInfos/{app_info_id}/appInfoLocalizations")
    asvls = by_locale(f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")
    per_locale = {}
    for locale in locales:
        info, asvl = asc.attributes(info_locs.get(locale, {})), asc.attributes(asvls.get(locale, {}))
        per_locale[locale] = {stem: (info if f.home == "app" else asvl).get(f.api) for stem, f in LISTING.items()}
    categories = category_ids(client, app_info_id)
    detail = get_optional(client, f"/v1/appStoreVersions/{version['id']}/appStoreReviewDetail")
    declaration = get_optional(client, f"/v1/appInfos/{app_info_id}/ageRatingDeclaration") or {}
    return {
        "age_rating": asc.attributes(declaration),
        "age_rating_id": declaration.get("id"),
        "categories": categories,
        "copyright": asc.attributes(client.get(f"/v1/appStoreVersions/{version['id']}")["data"]).get("copyright"),
        "per_locale": per_locale,
        "review": {stem: asc.attributes(detail).get(f.api) for stem, f in REVIEW.items()} if detail else {},
        # So applying the diff doesn't page through them again.
        "info_loc_resources": info_locs,
        "asvl_resources": asvls,
    }


def diff_plan_against_live(plan: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Only the fields whose planned value differs from live: exactly what gets pushed."""
    live_locales = live["per_locale"]
    return {
        "age_rating": {n: v for n, v in plan.get("age_rating", {}).items() if live.get("age_rating", {}).get(n) != v},
        "categories": {n: v for n, v in plan["category_relationships"].items() if live["categories"].get(n) != v},
        "copyright": plan["copyright"] if plan["copyright"] and plan["copyright"] != live["copyright"] else None,
        "per_locale": {locale: changed for locale, fields in plan["per_locale"].items()
                       if (changed := {stem: v for stem, v in fields.items()
                                       if v and v != live_locales.get(locale, {}).get(stem)})},
        "review": {k: v for k, v in plan["review"].items() if live["review"].get(k) != v},
    }


def each_change(changes: dict[str, Any], live: dict[str, Any] | None = None) -> Iterator[tuple[str, str, Any, Any]]:
    """(section, field, new, live value) for every change."""
    live = live or {}
    for section, key in (("age rating", "age_rating"), ("categories", "categories")):
        for name, value in changes.get(key, {}).items():
            yield section, name, value, live.get(key, {}).get(name)
    if changes["copyright"]:
        yield "version", "copyright", changes["copyright"], live.get("copyright")
    for locale, fields in changes["per_locale"].items():
        for stem, value in fields.items():
            yield locale, stem, value, live.get("per_locale", {}).get(locale, {}).get(stem)
    for key, value in changes["review"].items():
        yield "review", key, value, live.get("review", {}).get(key)


def count_changes(changes: dict[str, Any]) -> int:
    return sum(1 for _ in each_change(changes))


def print_diff(changes: dict[str, Any], live: dict[str, Any]) -> None:
    for section, field, new, old in each_change(changes, live):
        old, new = mask(field, old), mask(field, new)
        print(f"  {section}: {field}:" + ("" if old is not None else dim(" (unset)")))
        for line in format_text_diff(None if old is None else str(old), str(new)):
            print(line)


def verify_push(changes: dict[str, Any], live_after: dict[str, Any]) -> bool:
    """Why: docs/design/foundations.md#a-push-is-verified-by-reading-it-back"""
    mismatches = [m for m in each_change(changes, live_after) if m[2] != m[3]]
    if not mismatches:
        print(green("✓ verified: App Store Connect now matches everything pushed"))
        return True
    for section, field, pushed, actual in mismatches:
        pushed, actual = mask(field, pushed), mask(field, actual)
        print(red(f"✗ {section}/{field}: pushed {truncate(str(pushed))!r} but ASC now has {truncate(str(actual))!r}"))
    return False


def upsert_localization(client: asc.Client, resource: dict[str, Any] | None, label: str, kind: str,
                        parent: tuple[str, str, str], locale: str, attrs: dict[str, Any]) -> None:
    """PATCH the live localization, or find-or-create it; `parent` is (relationship, type, id)."""
    created = False
    if resource is None:
        rel, parent_type, parent_id = parent
        resource, created = find_or_create_locale_resource(
            client, f"/v1/{parent_type}/{parent_id}/{kind}", locale, kind, rel, parent_type, parent_id, attrs)
    if not created:
        client.patch(f"/v1/{kind}/{resource['id']}", asc.resource_body(kind, attrs, id_=resource["id"]))
    print(f"✓ {label} {'created' if created else 'updated'}: {', '.join(attrs)}")


def cmd_push(args: SimpleNamespace) -> None:
    app = project.resolve_app(args.app)
    folder, app_config = app.folder, app.config
    platform = resolve_platform(app_config, args.platform)
    locales: list[str] = app_config["locales"]
    print(f"→ {app_config['name']} ({app_config['bundle_id']}), platform={platform}, locales={locales}")
    if not args.skip_lint:  # first: lint reports every problem, the plan's own check stops at the first
        lint.gate(app, platform)
    plan = build_push_plan(folder / platform, locales, app_config)
    translations.warn_stale(folder, locales)
    if args.dry_run:
        print_push_plan(plan)
        print("\n[dry-run] no network calls made — nothing above was written to App Store Connect.")
        return

    client = asc.Client()  # the first credential check
    app_id = find_app(client, app_config)["id"]
    print(f"→ found app {app_config['bundle_id']} (id={app_id})")
    app_info = find_editable_app_info(client, app_id)
    version = find_editable_version(client, app_id, platform)
    version_string = asc.attributes(version).get("versionString")
    if live_version(client, app_id, platform) is None:  # ASC rejects whatsNew on an app's first version
        for locale, fields in plan["per_locale"].items():
            if fields.get("release_notes"):
                fields["release_notes"] = None
                print(f"  (skipping release_notes for {locale} — no prior live version; "
                      "ASC rejects it on a first submission)")
    if problems := category_problems(app_config.get("categories", {}), {c["id"] for c in client.get_all("/v1/appCategories", {"limit": 200})}):
        raise SystemExit("snakelane.yml \"categories\": " + "; ".join(problems))
    live = fetch_live_state(client, app_info["id"], version, locales)
    if plan["age_rating"] and (unknown := sorted(set(plan["age_rating"]) - set(live["age_rating"]))):
        raise SystemExit(f"snakelane.yml \"age_rating\": App Store Connect has no question(s) {unknown}; "
                         f"it asks: {', '.join(sorted(live['age_rating']))}")
    changes = diff_plan_against_live(plan, live)
    if not (total := count_changes(changes)):
        print(green("\n✓ App Store Connect already matches the local tree — nothing to push."))
        return
    print(f"\n{total} change(s) to push:")
    print_diff(changes, live)
    if not args.yes:
        if not sys.stdin.isatty():
            raise SystemExit("stdin is not a terminal — pass --yes to push without the prompt")
        if input("\nPush these changes to App Store Connect? [y/N] ").strip().lower() not in ("y", "yes"):
            print("aborted — nothing pushed")
            return

    if changes["age_rating"]:  # only the changed answers: Apple refuses a PATCH whose every attribute matches
        client.patch(f"/v1/ageRatingDeclarations/{live['age_rating_id']}",
                     asc.resource_body("ageRatingDeclarations", changes["age_rating"], id_=live["age_rating_id"]))
        print(f"✓ age rating updated: {', '.join(changes['age_rating'])}")
    if changes["categories"]:
        relationships = {n: asc.relationship("appCategories", v) for n, v in changes["categories"].items()}
        client.patch(f"/v1/appInfos/{app_info['id']}",
                     {"data": {"type": "appInfos", "id": app_info["id"], "relationships": relationships}})
        print(f"✓ AppInfo categories set: {', '.join(changes['categories'])}")
    if changes["copyright"]:
        client.patch(f"/v1/appStoreVersions/{version['id']}",
                     asc.resource_body("appStoreVersions", {"copyright": changes["copyright"]}, id_=version["id"]))
        print(f"✓ AppStoreVersion[{version_string}] copyright updated")
    for locale, fields in changes["per_locale"].items():
        attrs = {home: {LISTING[s].api: v for s, v in fields.items() if LISTING[s].home == home}
                 for home in ("app", "version")}
        if info_attrs := attrs["app"]:
            upsert_localization(client, live["info_loc_resources"].get(locale), f"AppInfoLocalization[{locale}]",
                                "appInfoLocalizations", ("appInfo", "appInfos", app_info["id"]), locale, info_attrs)
        if asvl_attrs := attrs["version"]:
            upsert_localization(client, live["asvl_resources"].get(locale),
                                f"AppStoreVersionLocalization[{locale}, {version_string}]",
                                "appStoreVersionLocalizations", ("appStoreVersion", "appStoreVersions", version["id"]),
                                locale, asvl_attrs)
    if changes["review"]:  # the full card: a create with only the delta would drop the rest
        push_review_detail(client, version, plan["review"])

    print("\nverifying against a fresh read of App Store Connect…")
    if not verify_push(changes, fetch_live_state(client, app_info["id"], version, locales)):
        raise SystemExit(red("\nMetadata push finished WITH MISMATCHES — see above."))  # non-zero for CI and agents
    print(green("\nMetadata push complete."))


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    print(f"wrote {path}")


def cmd_pull(args: SimpleNamespace) -> None:
    folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    platform_dir, locales = folder / platform, app_config["locales"]
    live = show_json(app_config, platform, masked=False)
    if live["copyright"]:
        write(platform_dir / "copyright.txt", live["copyright"])
    for locale, fields in live["per_locale"].items():
        # One locale writes default/; several write per locale so one doesn't overwrite default/.
        target_dir = platform_dir / ("default" if len(locales) == 1 else locale)
        for stem, value in fields.items():
            if value:
                write(target_dir / f"{stem}.txt", value)
    for stem, value in live["review"].items():  # platform-level, not per locale; absent on a fresh app
        if value:
            write(platform_dir / "review" / f"{stem}.txt", value)
    print("\nPull complete.")


def show_json(app_config: dict[str, Any], platform: str, masked: bool = True) -> dict[str, Any]:
    """The live listing as push compares it: draft version, else live; demo passwords masked."""
    client = asc.Client()
    app = find_app(client, app_config)
    if (version := find_listing_version(client, app["id"], platform)) is None:
        raise SystemExit(f"no {platform} version in App Store Connect yet")
    info = find_editable_app_info(client, app["id"])
    live = fetch_live_state(client, info["id"], version, app_config["locales"])
    attrs = asc.attributes(version)
    return {
        "version": attrs.get("versionString"),
        "state": attrs.get("appStoreState"),
        **{k: live[k] for k in ("categories", "copyright", "age_rating", "per_locale")},
        "review": {k: mask(k, v) if masked else v for k, v in live["review"].items()},
    }


def cmd_show(args: SimpleNamespace) -> None:
    _folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    with contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext():
        data = show_json(app_config, platform)  # progress lines must not corrupt the JSON
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return
    c = data["categories"]
    print(f"--- ASC live state for {app_config['bundle_id']} ({platform}, {data['version']} {data['state']}) ---")
    print(f"  primary_category   = {c['primaryCategory']!r} / "
          f"{c['primarySubcategoryOne']!r} / {c['primarySubcategoryTwo']!r}")
    print(f"  secondary_category  = {c['secondaryCategory']!r} / "
          f"{c['secondarySubcategoryOne']!r} / {c['secondarySubcategoryTwo']!r}")
    print(f"  copyright           = {data['copyright']!r}")
    for locale, fields in data["per_locale"].items():
        print(f"  [{locale}]")
        for stem, value in fields.items():
            print(f"    {stem:19} = {truncate(value) if stem in LONG else value!r}")
    print("  [review]")
    if data["review"]:
        for stem, value in data["review"].items():
            print(f"    {stem:19} = {truncate(value)!r}")
    else:
        print("    (no appStoreReviewDetail resource yet — created on first push)")
