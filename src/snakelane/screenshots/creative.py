"""`store creative push|show`: the product page header and the search-result asset, the two
"creative assets" App Store Connect added in October 2026, through the App Asset Library.

Each slot holds at most one image or video per App Store version localization:

    <metadata>/creative/<locale>/                  every platform
    <metadata>/creative/default/                   every locale that has no folder of its own
    <metadata>/<platform>/creative/<locale>/, <metadata>/<platform>/creative/default/   overrides

    search-result.{jpg,jpeg,png,mov,m4v,mp4}       APP_STORE_SEARCH_RESULTS_ASSET
    product-page-header.{png,mov,m4v,mp4}          PRODUCT_PAGE_HEADER_ASSET
    universal.png                                  both, where the slot has no file of its own

A slot with no file is "no opinion": what's live stays live. Removing a creative asset is done in
App Store Connect. Why: docs/design/foundations.md#blank-local-text-means-no-opinion

The sizes, formats and limits are read from Apple's reference data on every run rather than kept
here, as Apple asks: the help page and the API already disagree on the header's formats.
Why: docs/design/screenshots.md#creative-assets-are-checked-against-apples-reference-data

No snakelane.yml keys: the files are the configuration.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import find_app, find_editable_version, keyed
from ..terminal import dim, green, red
from .media import read_mp4_dimensions

SEARCH, HEADER = "APP_STORE_SEARCH_RESULTS_ASSET", "PRODUCT_PAGE_HEADER_ASSET"
SLOTS = {"search-result": SEARCH, "product-page-header": HEADER}  # file stem -> placement type
UNIVERSAL = "universal"
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")
VIDEO_SUFFIXES = (".mov", ".m4v", ".mp4")
SLOT_NAMES = {SEARCH: "search result", HEADER: "product page header"}
# The state an uploaded asset reaches once Apple has processed it and it can be placed.
READY = "PREPARE_FOR_SUBMISSION"
PLACEABLE = {READY, "READY_FOR_REVIEW", "WAITING_FOR_REVIEW", "IN_REVIEW", "ACCEPTED", "APPROVED"}


@dataclass(frozen=True)
class Spec:
    """One of Apple's image or video specifications, as the reference data gives it."""
    spec_id: str
    short_name: str
    video: bool
    placement_types: frozenset[str]
    min_size: tuple[int, int]
    max_size: tuple[int, int]
    extensions: frozenset[str]
    alpha_allowed: bool = False
    max_file_size: int | None = None
    durations: tuple[float, float] | None = None  # seconds
    frame_rates: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class RefData:
    """What the reference data says about the two creative slots."""
    specs: tuple[Spec, ...]
    groups: dict[str, str]          # placement type -> placement group (DEFAULT_PROFILE today)

    def specs_for(self, placement_type: str, video: bool) -> list[Spec]:
        return [s for s in self.specs if placement_type in s.placement_types and s.video == video]


def iso_seconds(value: str | None) -> float | None:
    """`PT5S`, `PT1M30S` (ISO 8601 durations as the reference data writes them) in seconds."""
    if not value or not (match := re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", value)):
        return None
    hours, minutes, seconds = (float(part) if part else 0.0 for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def parse_ref_data(payload: dict[str, Any]) -> RefData:
    """The creative slots' specs, placement groups and limits out of `GET /v1/appAssetLibraryRefData`."""
    data = payload.get("data")
    attributes = asc.attributes(data[0] if isinstance(data, list) else data or {})
    wanted = set(SLOTS.values())
    specs: list[Spec] = []
    for video, key in ((False, "imageSpecs"), (True, "videoSpecs")):
        for raw in attributes.get(key) or []:
            types = frozenset(raw.get("compatiblePlacementTypes") or []) & wanted
            if not types:
                continue
            dims = raw.get("dimensions") or {}
            duration = raw.get("duration") or {}
            low, high = iso_seconds(duration.get("min")), iso_seconds(duration.get("max"))
            specs.append(Spec(
                spec_id=raw.get("specId", "?"), short_name=raw.get("shortName", "?"), video=video,
                placement_types=types,
                min_size=(dims.get("minWidth", 0), dims.get("minHeight", 0)),
                max_size=(dims.get("maxWidth", 10**6), dims.get("maxHeight", 10**6)),
                extensions=frozenset(e.lower() for e in raw.get("fileExtensions") or []),
                alpha_allowed=bool(raw.get("alphaAllowed")), max_file_size=raw.get("maxFileSize"),
                durations=(low or 0.0, high or float("inf")) if (low or high) else None,
                frame_rates=tuple((r.get("minFps", 0), r.get("maxFps", 0)) for r in raw.get("frameRates") or [])))
    groups: dict[str, str] = {}
    for placement in attributes.get("placementTypes") or []:
        if (kind := placement.get("placementTypeId")) in wanted and (mappings := placement.get("specMappings")):
            groups[kind] = mappings[0].get("placementGroupId", "DEFAULT_PROFILE")
    missing = wanted - groups.keys()
    if missing:
        raise asc.ASCError(f"App Store Connect's reference data has no placement group for {sorted(missing)}: "
                           "the creative asset API may have changed")
    return RefData(tuple(specs), groups)


# --- the local plan --------------------------------------------------------------------------------


def creative_dirs(folder: Path, platform: str, locale: str) -> list[Path]:
    """Where a locale's creative assets may be, most specific first."""
    return [folder / platform / "creative" / locale, folder / platform / "creative" / "default",
            folder / "creative" / locale, folder / "creative" / "default"]


def _candidates(directory: Path, stem: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.stem == stem and p.suffix.lower() in IMAGE_SUFFIXES + VIDEO_SUFFIXES)


def find_slot_file(dirs: list[Path], stem: str) -> Path | None:
    """The file for one slot: the first folder that has one wins. Two in one folder is refused."""
    for directory in dirs:
        if found := _candidates(directory, stem):
            if len(found) > 1:
                raise SystemExit(f"{directory}: {', '.join(p.name for p in found)} — one {stem} file per folder")
            return found[0]
    return None


def locale_plan(folder: Path, platform: str, locale: str) -> dict[str, Path]:
    """Placement type -> file for one locale. A slot's own file outranks `universal.png` at any depth."""
    dirs = creative_dirs(folder, platform, locale)
    plan = {kind: path for stem, kind in SLOTS.items() if (path := find_slot_file(dirs, stem))}
    if (universal := find_slot_file(dirs, UNIVERSAL)) is not None:
        for kind in SLOTS.values():
            plan.setdefault(kind, universal)
    return plan


# --- checking a file against the specs -------------------------------------------------------------


def has_alpha(image: Image.Image) -> bool:
    """An alpha channel at all, opaque or not: Apple refuses the channel, not the transparency."""
    return image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)


def probe_video(path: Path) -> tuple[float | None, float | None]:
    """Duration in seconds and frame rate, from ffprobe when it's installed; (None, None) otherwise."""
    if not shutil.which("ffprobe"):
        return None, None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate:format=duration",
         "-of", "default=noprint_wrappers=1", str(path)], capture_output=True, text=True, check=False)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    duration = float(values["duration"]) if values.get("duration", "N/A") != "N/A" else None
    fps = None
    if rate := values.get("r_frame_rate"):
        numerator, _, denominator = rate.partition("/")
        if denominator and float(denominator):
            fps = float(numerator) / float(denominator)
    return duration, fps


def spec_problems(path: Path, spec: Spec) -> list[str]:
    """Why `path` doesn't meet `spec` (empty when it does)."""
    problems: list[str] = []
    if path.suffix.lower() not in spec.extensions:
        problems.append(f"{path.suffix.lower()} (takes {', '.join(sorted(spec.extensions))})")
    if spec.max_file_size and path.stat().st_size > spec.max_file_size:
        problems.append(f"{path.stat().st_size} bytes (limit {spec.max_file_size})")
    if spec.video:
        try:
            width, height = read_mp4_dimensions(path)
        except ValueError as error:
            return [*problems, str(error)]
    else:
        with Image.open(path) as image:
            (width, height), alpha = image.size, has_alpha(image)
        if alpha and not spec.alpha_allowed:
            problems.append("an alpha channel (save it without one)")
    (min_w, min_h), (max_w, max_h) = spec.min_size, spec.max_size
    if not (min_w <= width <= max_w and min_h <= height <= max_h):
        wanted = f"{min_w}x{min_h}" if spec.min_size == spec.max_size else f"{min_w}x{min_h} to {max_w}x{max_h}"
        problems.append(f"{width}x{height} (wants {wanted})")
    elif spec.min_size != spec.max_size and abs(width * min_h - height * min_w) > max(width, height):
        problems.append(f"{width}x{height} is not {min_w}:{min_h} in proportion")
    if spec.video:
        duration, fps = probe_video(path)
        if duration is not None and spec.durations and not spec.durations[0] <= duration <= spec.durations[1]:
            problems.append(f"{duration:.1f}s long (takes {spec.durations[0]:g} to {spec.durations[1]:g}s)")
        if fps is not None and spec.frame_rates and not any(lo - 0.5 <= fps <= hi + 0.5 for lo, hi in spec.frame_rates):
            rates = ", ".join(f"{lo}" if lo == hi else f"{lo}-{hi}" for lo, hi in spec.frame_rates)
            problems.append(f"{fps:.2f} fps (takes {rates})")
    return problems


def check_file(path: Path, placement_type: str, ref: RefData) -> Spec:
    """The spec `path` meets for `placement_type`, or a SystemExit listing what's wrong against each."""
    video = path.suffix.lower() in VIDEO_SUFFIXES
    specs = ref.specs_for(placement_type, video)
    if not specs:
        raise SystemExit(f"{path}: App Store Connect takes no {'video' if video else 'image'} for the "
                         f"{SLOT_NAMES[placement_type]}")
    report = []
    for spec in specs:
        if not (problems := spec_problems(path, spec)):
            return spec
        report.append(f"    {spec.short_name}: {'; '.join(problems)}")
    raise SystemExit(f"{path} fits none of Apple's {SLOT_NAMES[placement_type]} specs:\n" + "\n".join(report))


# --- App Store Connect -----------------------------------------------------------------------------


def reference_name(path: Path, data: bytes) -> str:
    """How an upload is found again: the file's name and a hash of its bytes, so an unchanged file
    is reused from the library instead of uploaded twice. Why: docs/design/screenshots.md#creative-assets-are-found-by-content"""
    return f"{path.name} · {hashlib.sha256(data).hexdigest()[:16]}"


def library_assets(client: asc.Client, library_id: str) -> dict[str, dict[str, Any]]:
    """The library's images and videos by reference name (the newest wins a tie)."""
    found: dict[str, dict[str, Any]] = {}
    for kind in ("images", "videos"):
        for asset in client.get_all(f"/v1/appAssetLibraries/{library_id}/{kind}"):
            attributes = asc.attributes(asset)
            if attributes.get("state") in ("FAILED", "REJECTED", "ARCHIVED"):
                continue
            if (name := attributes.get("referenceName")) and (
                    name not in found
                    or attributes.get("createdDate", "") > asc.attributes(found[name]).get("createdDate", "")):
                found[name] = asset
    return found


def asset_resource(path: Path) -> str:
    return "appAssetLibraryVideos" if path.suffix.lower() in VIDEO_SUFFIXES else "appAssetLibraryImages"


def upload(client: asc.Client, library_id: str, path: Path, data: bytes, name: str) -> dict[str, Any]:
    """Reserve, upload each part, commit with `uploaded` alone (the library takes no checksum)."""
    kind = asset_resource(path)
    asset = client.post(f"/v1/{kind}", asc.resource_body(
        kind, {"category": "CREATIVE_ASSETS", "fileName": path.name, "fileSize": len(data), "referenceName": name},
        relationships={"assetLibrary": asc.relationship("appAssetLibraries", library_id)}))["data"]
    for operation in asc.attributes(asset).get("uploadOperations") or []:
        client.upload_part(operation, data)
    client.patch(f"/v1/{kind}/{asset['id']}", asc.resource_body(kind, {"uploaded": True}, id_=asset["id"]))
    client.report(f"  uploaded {path.name} ({asset['id']})")
    return asset


def wait_until_placeable(client: asc.Client, assets: dict[str, tuple[str, str]], timeout: float = 600,
                         interval: float = 10) -> list[str]:
    """Poll new uploads (id -> (resource, label)) until Apple has processed them; returns the failures.

    Placements can only be made once an asset is processed, so the wait comes before any placement."""
    remaining = {i: v for i, v in assets.items() if not asc.planned(i)}
    failures: list[str] = []
    deadline = time.monotonic() + timeout
    while remaining and time.monotonic() < deadline:
        for asset_id, (resource, label) in list(remaining.items()):
            attributes = asc.attributes(client.get(f"/v1/{resource}/{asset_id}").get("data") or {})
            state = attributes.get("state")
            if state in PLACEABLE:
                del remaining[asset_id]
            elif state in ("FAILED", "REJECTED"):
                details = "; ".join(d.get("description") or d.get("code") or "?"
                                    for d in attributes.get("stateDetails") or []) or "(no detail from Apple)"
                failures.append(f"{label}: {state.lower()} by Apple ({details})")
                del remaining[asset_id]
        if remaining:
            time.sleep(interval)
    failures += [f"{label}: still processing when the wait gave up — check App Store Connect"
                 for _, label in remaining.values()]
    return failures


def live_slots(client: asc.Client, asvl_id: str) -> dict[str, list[dict[str, Any]]]:
    """The localization's creative placements, by placement type."""
    slots: dict[str, list[dict[str, Any]]] = {}
    for placement in client.get_all(f"/v1/appStoreVersionLocalizations/{asvl_id}/placements"):
        if (kind := asc.attributes(placement).get("placementType")) in SLOTS.values():
            slots.setdefault(kind, []).append(placement)
    return slots


def placement_ids(client: asc.Client, path: Path, asset_id: str) -> set[str]:
    """Every placement an asset backs. A placement doesn't name its asset, so the asset is asked."""
    return {p["id"] for p in client.get_all(f"/v1/{asset_resource(path)}/{asset_id}/placements")}


def place(client: asc.Client, path: Path, asset_id: str, placement_type: str, group: str, asvl_id: str) -> str:
    media = "video" if asset_resource(path) == "appAssetLibraryVideos" else "image"
    return client.post("/v1/appAssetLibraryPlacements", {"data": {
        "type": "appAssetLibraryPlacements",
        "attributes": {"placementType": placement_type, "placementGroup": group},
        "relationships": {media: asc.relationship(asset_resource(path), asset_id),
                          "appStoreVersionLocalization": asc.relationship("appStoreVersionLocalizations", asvl_id)},
    }})["data"]["id"]


# --- commands --------------------------------------------------------------------------------------


def build_plan(folder: Path, platform: str, locales: list[str]) -> dict[str, dict[str, Path]]:
    plan = {locale: locale_plan(folder, platform, locale) for locale in locales}
    return {locale: slots for locale, slots in plan.items() if slots}


def print_plan(plan: dict[str, dict[str, Path]], folder: Path) -> None:
    for locale, slots in plan.items():
        for kind, path in sorted(slots.items()):
            print(f"  {locale:<8} {SLOT_NAMES[kind]:<20} {path.relative_to(folder)}")


def cmd_creative_push(args: SimpleNamespace) -> None:
    """Upload each locale's creative assets to the App Asset Library and place them on the editable version."""
    folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    plan = build_plan(folder, platform, app_config["locales"])
    if not plan:
        print(f"no creative assets for {platform} under {folder.name}/creative/ or {folder.name}/{platform}/creative/ "
              "— nothing to do (a slot without a file is left as it is live)")
        return
    print(f"creative assets for {app_config.get('name', app_config['bundle_id'])} ({platform}):")
    print_plan(plan, folder)
    if args.dry_run and not asc.Credentials.available():
        print("\n[dry-run] no API key set up (`snakelane auth setup`): the files above were not checked against "
              "Apple's specs and nothing was read or written.")
        return
    client = asc.Client(dry_run=args.dry_run)
    ref = parse_ref_data(client.get("/v1/appAssetLibraryRefData"))
    # Every file against the specs before the first write.
    for slots in plan.values():
        for kind, path in slots.items():
            spec = check_file(path, kind, ref)
            print(dim(f"  {path.name} meets {spec.short_name} for the {SLOT_NAMES[kind]}"))
    app = find_app(client, app_config)
    version = find_editable_version(client, app["id"], platform)
    changed = apply_plan(client, app["id"], version, plan, ref)
    if client.dry_run:
        print("\n[dry-run] nothing was uploaded or placed.")
    else:
        print(f"\n{changed} placement(s) changed. They go to App Review with version {version_string(version)}.")


def apply_plan(client: asc.Client, app_id: str, version: dict[str, Any], plan: dict[str, dict[str, Path]],
               ref: RefData) -> int:
    """Upload what the library lacks, wait for Apple, then make each slot show its file; returns how
    many placements changed. Files must already have passed `check_file`."""
    asvls = keyed(client, f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")
    if missing := [locale for locale in plan if locale not in asvls]:
        raise asc.ASCError(f"no AppStoreVersionLocalization for {', '.join(missing)}: add the language in App Store Connect")
    library_id = client.get(f"/v1/apps/{app_id}/assetLibrary")["data"]["id"]
    in_library = library_assets(client, library_id)

    # Upload each distinct file once, however many slots and locales use it.
    assets: dict[Path, str] = {}
    new: dict[str, tuple[str, str]] = {}
    for path in sorted({p for slots in plan.values() for p in slots.values()}):
        data = path.read_bytes()
        name = reference_name(path, data)
        if (found := in_library.get(name)) is not None:
            assets[path] = found["id"]
            print(dim(f"  {path.name} is already in the library ({found['id']})"))
            continue
        asset = upload(client, library_id, path, data, name)
        assets[path] = asset["id"]
        new[asset["id"]] = (asset_resource(path), path.name)
    if real := [i for i in new if not asc.planned(i)]:
        print(f"\nwaiting for App Store Connect to process {len(real)} upload(s)…")
        if failures := wait_until_placeable(client, new):
            for failure in failures:
                print(red(f"  ✗ {failure}"))
            raise SystemExit("creative assets were not placed: nothing live was changed")

    changed = 0
    for locale, slots in plan.items():
        asvl_id = asvls[locale]["id"]
        live = live_slots(client, asvl_id)
        for kind, path in sorted(slots.items()):
            asset_id = assets[path]
            current = live.get(kind, [])
            backing = placement_ids(client, path, asset_id) if not asc.planned(asset_id) else set()
            if current and all(p["id"] in backing for p in current):
                print(dim(f"  {locale} {SLOT_NAMES[kind]}: {path.name} is already live"))
                continue
            # One per localization: the old placement goes before the new one can be made.
            for old in current:
                client.delete(f"/v1/appAssetLibraryPlacements/{old['id']}")
                client.report(f"  removed {locale}'s previous {SLOT_NAMES[kind]} ({old['id']})")
            placement_id = place(client, path, asset_id, kind, ref.groups[kind], asvl_id)
            client.report(green(f"  ✓ {locale} {SLOT_NAMES[kind]}: {path.name} ({placement_id})"))
            changed += 1
    return changed


def version_string(version: dict[str, Any]) -> str:
    return asc.attributes(version).get("versionString", "?")


def cmd_creative_show(args: SimpleNamespace) -> None:
    """The live creative placements per locale on the editable version, and the files behind them."""
    _folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    client = asc.Client()
    app = find_app(client, app_config)
    version = find_editable_version(client, app["id"], platform)
    library_id = client.get(f"/v1/apps/{app['id']}/assetLibrary")["data"]["id"]
    # Which asset backs which placement, from the assets' side: a placement doesn't say.
    backing: dict[str, str] = {}
    for kind in ("images", "videos"):
        for asset in client.get_all(f"/v1/appAssetLibraries/{library_id}/{kind}"):
            if asc.attributes(asset).get("category") != "CREATIVE_ASSETS":
                continue
            label = f"{asc.attributes(asset).get('fileName')} [{asc.attributes(asset).get('state')}]"
            for placement in client.get_all(f"/v1/appAssetLibrary{kind.capitalize()}/{asset['id']}/placements"):
                backing[placement["id"]] = label
    print(f"--- creative assets for {app_config['bundle_id']} ({platform}, {version_string(version)}) ---")
    asvls = keyed(client, f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations")
    for locale in app_config["locales"]:
        if (asvl := asvls.get(locale)) is None:
            print(f"  [{locale}] (no AppStoreVersionLocalization yet)")
            continue
        live = live_slots(client, asvl["id"])
        for kind in SLOTS.values():
            placements = live.get(kind) or []
            shown = ", ".join(backing.get(p["id"], p["id"]) for p in placements) or "(none)"
            print(f"  [{locale}] {SLOT_NAMES[kind]:<20} {shown}")

