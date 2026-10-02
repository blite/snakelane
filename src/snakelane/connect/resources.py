"""App Store Connect lookups and uploads every command shares: the app, its editable or live version
and AppInfo, per-locale resources, and the reserve-upload-commit-wait cycle for assets."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from ..terminal import red
from . import asc

# States in which ASC accepts a PATCH; AppInfo and AppStoreVersion have separate state machines.
APP_INFO_EDITABLE_STATES = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED",
                            "WAITING_FOR_REVIEW", "PENDING_DEVELOPER_RELEASE"}
VERSION_EDITABLE_STATES = {"PREPARE_FOR_SUBMISSION", "METADATA_REJECTED", "DEVELOPER_REJECTED", "REJECTED",
                           "INVALID_BINARY", "WAITING_FOR_REVIEW"}


class NoEditableVersion(asc.ASCError):
    """The app has no version in an editable state (a live one, but no draft)."""


def find_app(client: asc.Client, app_config: dict[str, Any]) -> dict[str, Any]:
    """Exactly this bundle id (`filter[bundleId]` is a prefix match), checked against "apple_id"."""
    bundle_id, expected_id = app_config["bundle_id"], app_config.get("apple_id")
    app = next((a for a in client.get_all("/v1/apps", {"filter[bundleId]": bundle_id})
                if asc.attributes(a).get("bundleId") == bundle_id), None)
    if app is None:
        raise asc.ASCError(f"no App Store Connect app with bundle id {bundle_id}")
    if expected_id and app["id"] != str(expected_id):
        raise asc.ASCError(f"bundle id {bundle_id} resolved to app {app['id']}, but snakelane.yml says "
                           f"{expected_id} — refusing to touch an app the registry doesn't name")
    return app


def keyed(client: asc.Client, path: str, attribute: str = "locale") -> dict[str, dict[str, Any]]:
    """Resources keyed by an attribute (a locale, or a product id rather than ASC's resource id)."""
    return {asc.attributes(resource).get(attribute): resource for resource in client.get_all(path)}


def _state(resource: dict[str, Any]) -> str | None:
    return asc.attributes(resource).get("appStoreState")


def _versions(client: asc.Client, app_id: str, platform: str, **filters: str) -> list[dict[str, Any]]:
    params = {"filter[platform]": asc.platform_enum(platform), **{f"filter[{k}]": v for k, v in filters.items()}}
    return list(client.get_all(f"/v1/apps/{app_id}/appStoreVersions", params))


def find_editable_app_info(client: asc.Client, app_id: str) -> dict[str, Any]:
    """An editable AppInfo, else the first (ASC's PATCH then says why). Logged: the wrong one fails silently."""
    infos = list(client.get_all(f"/v1/apps/{app_id}/appInfos"))
    if not infos:
        raise asc.ASCError(f"no AppInfo resources at all for app {app_id}")
    if info := next((i for i in infos if _state(i) in APP_INFO_EDITABLE_STATES), None):
        print(f"  using editable AppInfo {info['id']} (appStoreState={_state(info)})")
        return info
    print(f"  no AppInfo in a known-editable state; falling back to {infos[0]['id']} "
          f"(appStoreState={_state(infos[0])})")
    return infos[0]


def find_editable_version(client: asc.Client, app_id: str, platform: str) -> dict[str, Any]:
    versions = _versions(client, app_id, platform)
    if version := next((v for v in versions if _state(v) in VERSION_EDITABLE_STATES), None):
        print(f"  editable AppStoreVersion {version['id']} ({asc.attributes(version).get('versionString')}, "
              f"appStoreState={_state(version)})")
        return version
    raise NoEditableVersion(
        f"no editable AppStoreVersion for platform {platform} on app {app_id} "
        f"— states seen: {[_state(v) for v in versions] or '(no versions at all)'}. When the live version "
        "is READY_FOR_SALE with no newer draft, create one in App Store Connect: "
        "the app's page, '+' next to the current version, enter the next version "
        "string, Save. (The same one-time step deliver's 'No data' abort wanted.)")


def find_listing_version(client: asc.Client, app_id: str, platform: str) -> dict[str, Any] | None:
    """The editable version, else the live one; quiet, for readers."""
    versions = _versions(client, app_id, platform)
    return (next((v for v in versions if _state(v) in VERSION_EDITABLE_STATES), None)
            or next((v for v in versions if _state(v) == "READY_FOR_SALE"), None))


def live_version(client: asc.Client, app_id: str, platform: str) -> str | None:
    """The version string on sale for this platform, or None before the first release."""
    live = _versions(client, app_id, platform, appStoreState="READY_FOR_SALE")
    return asc.attributes(live[0]).get("versionString") if live else None


def find_or_create_locale_resource(
    client: asc.Client, list_path: str, locale: str, resource_type: str, parent_relationship: str,
    parent_type: str, parent_id: str, attributes: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """(resource, created). A created one already carries `attributes`; don't PATCH them again."""
    if item := keyed(client, list_path).get(locale):
        return item, False
    body = asc.resource_body(resource_type, {"locale": locale, **attributes},
                             relationships={parent_relationship: asc.relationship(parent_type, parent_id)})
    return client.post(f"/v1/{resource_type}", body)["data"], True


def source_checksum(data: bytes) -> str:
    """What App Store Connect records as `sourceFileChecksum`, so a gallery can match an upload."""
    return hashlib.md5(data).hexdigest()


def upload_asset_resource(client: asc.Client, resource_type: str, path: Path, relationships: dict[str, Any]) -> str:
    """Reserve, upload each byte range to its presigned URL, commit with the MD5; returns the resource
    id. Apple can still reject it: see `wait_for_asset_processing`."""
    data = path.read_bytes()
    resource = client.post(f"/v1/{resource_type}", asc.resource_body(
        resource_type, {"fileName": path.name, "fileSize": len(data)}, relationships=relationships))["data"]
    for op in asc.attributes(resource).get("uploadOperations", []):
        client.upload_part(op, data)
    client.patch(f"/v1/{resource_type}/{resource['id']}", asc.resource_body(
        resource_type, {"uploaded": True, "sourceFileChecksum": source_checksum(data)}, id_=resource["id"]))
    return resource["id"]


def wait_for_asset_processing(
    client: asc.Client, resource_type: str, pending: dict[str, str], timeout: float = 600, interval: float = 10,
) -> tuple[list[str], list[tuple[str, str, str]], list[str]]:
    """Poll until Apple's ingest reaches a verdict. `pending` is id -> name; returns
    (complete names, failed (name, id, Apple's error), timed-out names).
    Why: docs/design/foundations.md#an-upload-is-done-when-apple-has-processed-it
    """
    remaining = {i: name for i, name in pending.items() if not asc.planned(i)}  # a dry run's: nothing to wait for
    complete: list[str] = []
    failed: list[tuple[str, str, str]] = []
    deadline = time.monotonic() + timeout
    while remaining and time.monotonic() < deadline:
        for resource_id in list(remaining):
            try:
                payload = client.get(f"/v1/{resource_type}/{resource_id}")
            except asc.ASCError as error:
                # Any failed read means "unknown", i.e. timed out.
                # Why: docs/design/foundations.md#a-failed-processing-poll-counts-as-timed-out
                print(f"  … could not read processing state ({error}); treating as still processing")
                return complete, failed, list(remaining.values())
            delivery = asc.attributes(payload.get("data", {})).get("assetDeliveryState") or {}
            if delivery.get("state") == "COMPLETE":
                complete.append(remaining.pop(resource_id))
            elif delivery.get("state") == "FAILED":
                errors = "; ".join(e.get("description") or e.get("code") or "?" for e in delivery.get("errors") or [])
                failed.append((remaining.pop(resource_id), resource_id, errors or "(no detail from Apple)"))
        if remaining:
            time.sleep(interval)
    return complete, failed, list(remaining.values())


def report_processing(failed: list[tuple[str, str, str]], timed_out: list[str], indent: str = "") -> bool:
    """Print each asset Apple rejected or never finished, in red; True when there were none."""
    for name, _, errors in failed:
        print(red(f"{indent}✗ {name}: rejected by Apple ({errors})"))
    for name in timed_out:
        print(red(f"{indent}✗ {name}: still processing when the wait gave up — check App Store Connect"))
    return not (failed or timed_out)


def get_optional(client: asc.Client, path: str) -> dict[str, Any] | None:
    """404 (or empty `data`) is None; any other failure raises, since "absent" would create it again."""
    try:
        return client.get(path).get("data")
    except asc.ASCError as error:
        if error.status == 404:
            return None
        raise
