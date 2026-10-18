"""Offline checks on `store creative push`: Apple's reference data, the folder layout, the spec
check, and what the push writes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from snakelane.screenshots import creative

from .fakes import FakeClient
from .helpers import image

HEADER, SEARCH = creative.HEADER, creative.SEARCH

# Trimmed from App Store Connect's answer to GET /v1/appAssetLibraryRefData (2026-10-18).
REF_DATA: dict[str, Any] = {"data": [{"type": "appAssetLibraryRefData", "id": "1", "attributes": {
    "imageSpecs": [
        {"specId": "d2ff", "shortName": "i3x2w1920~3840a0", "aspectRatio": "3:2",
         "dimensions": {"minWidth": 1920, "maxWidth": 3840, "minHeight": 1280, "maxHeight": 2560},
         "compatiblePlacementTypes": [SEARCH], "alphaAllowed": False,
         "fileExtensions": [".jpg", ".jpeg", ".png"], "maxFileSize": 524288000},
        {"specId": "c8f4", "shortName": "i5244x2950a0", "aspectRatio": "16:9",
         "dimensions": {"minWidth": 5244, "maxWidth": 5244, "minHeight": 2950, "maxHeight": 2950},
         "compatiblePlacementTypes": [SEARCH, HEADER], "alphaAllowed": False,
         "fileExtensions": [".png"], "maxFileSize": 524288000, "universalAsset": True},
        {"specId": "1eb4", "shortName": "i3840x1646a0", "aspectRatio": "21:9",
         "dimensions": {"minWidth": 3840, "maxWidth": 3840, "minHeight": 1646, "maxHeight": 1646},
         "compatiblePlacementTypes": [HEADER], "alphaAllowed": False,
         "fileExtensions": [".png"], "maxFileSize": 524288000},
        {"specId": "ss", "shortName": "a screenshot", "dimensions": {"minWidth": 1320, "maxWidth": 1320},
         "compatiblePlacementTypes": ["APP_SCREENSHOT"], "fileExtensions": [".png"]},
    ],
    "videoSpecs": [
        {"specId": "a28b", "shortName": "v3x2w1920~3840f30f60t15~30u0",
         "dimensions": {"minWidth": 1920, "maxWidth": 3840, "minHeight": 1280, "maxHeight": 2560},
         "compatiblePlacementTypes": [SEARCH], "frameRates": [{"minFps": 30, "maxFps": 30}],
         "duration": {"min": "PT5S", "max": "PT30S"}, "fileExtensions": [".mp4", ".m4v", ".mov"]},
    ],
    "placementTypes": [
        {"placementTypeId": HEADER, "acceptsAssetCategories": ["CREATIVE_ASSETS"],
         "specMappings": [{"placementGroupId": "DEFAULT_PROFILE", "specs": ["c8f4", "1eb4"]}]},
        {"placementTypeId": SEARCH, "acceptsAssetCategories": ["CREATIVE_ASSETS"],
         "specMappings": [{"placementGroupId": "DEFAULT_PROFILE", "specs": ["c8f4", "d2ff", "a28b"]}]},
        {"placementTypeId": "APP_SCREENSHOT",
         "specMappings": [{"placementGroupId": "IPAD_13_PROFILE", "specs": ["ss"]}]},
    ],
}}]}


def ref() -> creative.RefData:
    return creative.parse_ref_data(REF_DATA)


def test_reference_data_keeps_the_creative_slots_only() -> None:
    parsed = ref()
    assert parsed.groups == {HEADER: "DEFAULT_PROFILE", SEARCH: "DEFAULT_PROFILE"}
    assert {s.short_name for s in parsed.specs} == {
        "i3x2w1920~3840a0", "i5244x2950a0", "i3840x1646a0", "v3x2w1920~3840f30f60t15~30u0"}
    [video] = parsed.specs_for(SEARCH, video=True)
    assert video.durations == (5.0, 30.0) and video.frame_rates == ((30, 30),)


def test_reference_data_without_the_slots_stops() -> None:
    with pytest.raises(Exception, match="no placement group"):
        creative.parse_ref_data({"data": [{"attributes": {"placementTypes": []}}]})


@pytest.mark.parametrize("value, seconds", [("PT5S", 5.0), ("PT1M30S", 90.0), ("PT0.5S", 0.5), (None, None)])
def test_iso_durations(value: str | None, seconds: float | None) -> None:
    assert creative.iso_seconds(value) == seconds


# --- the folders -----------------------------------------------------------------------------------


def test_the_most_specific_folder_wins(tmp_path: Path) -> None:
    image(tmp_path / "creative" / "default" / "search-result.jpg", 1920, 1280)
    image(tmp_path / "creative" / "en-US" / "search-result.jpg", 1920, 1280)
    image(tmp_path / "ios" / "creative" / "default" / "product-page-header.png", 3840, 1646)
    plan = creative.locale_plan(tmp_path, "ios", "en-US")
    assert plan == {SEARCH: tmp_path / "creative" / "en-US" / "search-result.jpg",
                    HEADER: tmp_path / "ios" / "creative" / "default" / "product-page-header.png"}
    # Another locale falls back to the shared default; another platform doesn't see ios's header.
    assert creative.locale_plan(tmp_path, "macos", "de-DE") == {
        SEARCH: tmp_path / "creative" / "default" / "search-result.jpg"}


def test_universal_fills_only_the_slots_without_their_own_file(tmp_path: Path) -> None:
    universal = image(tmp_path / "creative" / "default" / "universal.png", 5244, 2950)
    search = image(tmp_path / "creative" / "en-US" / "search-result.jpg", 1920, 1280)
    assert creative.locale_plan(tmp_path, "ios", "en-US") == {SEARCH: search, HEADER: universal}
    assert creative.locale_plan(tmp_path, "ios", "fr-FR") == {SEARCH: universal, HEADER: universal}


def test_two_files_for_one_slot_are_refused(tmp_path: Path) -> None:
    image(tmp_path / "creative" / "en-US" / "search-result.jpg", 1920, 1280)
    image(tmp_path / "creative" / "en-US" / "search-result.png", 1920, 1280)
    with pytest.raises(SystemExit, match="one search-result file per folder"):
        creative.locale_plan(tmp_path, "ios", "en-US")


def test_no_files_means_no_plan(tmp_path: Path) -> None:
    assert creative.build_plan(tmp_path, "ios", ["en-US", "de-DE"]) == {}


# --- the spec check --------------------------------------------------------------------------------


@pytest.mark.parametrize("name, size", [("search-result.jpg", (3840, 2560)), ("search-result.png", (1920, 1280)),
                                        ("universal.png", (5244, 2950))])
def test_files_that_fit_the_search_slot(tmp_path: Path, name: str, size: tuple[int, int]) -> None:
    assert creative.check_file(image(tmp_path / name, *size), SEARCH, ref())


def test_a_jpeg_header_is_refused_whatever_the_help_page_says(tmp_path: Path) -> None:
    """Apple's help page lists .jpg for the 21:9 header; the reference data takes .png alone."""
    with pytest.raises(SystemExit, match=r"\.jpg \(takes \.png\)"):
        creative.check_file(image(tmp_path / "product-page-header.jpg", 3840, 1646), HEADER, ref())


def test_an_alpha_channel_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "product-page-header.png"
    Image.new("RGBA", (3840, 1646), (255, 255, 255, 255)).save(path)
    with pytest.raises(SystemExit, match="alpha channel"):
        creative.check_file(path, HEADER, ref())


@pytest.mark.parametrize("size", [(3840, 2160), (1600, 1066), (4000, 2667)])
def test_the_wrong_proportion_or_size_is_refused(tmp_path: Path, size: tuple[int, int]) -> None:
    with pytest.raises(SystemExit, match="fits none"):
        creative.check_file(image(tmp_path / "search-result.jpg", *size), SEARCH, ref())


# --- the push --------------------------------------------------------------------------------------


class Client(FakeClient):
    """FakeClient whose creates answer with an id, as Apple's do."""

    def __init__(self, gets: dict[str, Any]) -> None:
        super().__init__(gets)
        self.created = 0

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        super().post(path, body)
        self.created += 1
        return {"data": {**body["data"], "id": f"new-{self.created}",
                         "attributes": {**body["data"].get("attributes", {}), "uploadOperations": []}}}


VERSION = {"id": "v1", "attributes": {"versionString": "1.3"}}


def gets(library: list[dict[str, Any]], placements: list[dict[str, Any]],
         backing: dict[str, list[str]] | None = None) -> dict[str, Any]:
    answers: dict[str, Any] = {
        "/v1/appStoreVersions/v1/appStoreVersionLocalizations": {"data": [{"id": "L", "attributes": {"locale": "en-US"}}]},
        "/v1/apps/app/assetLibrary": {"data": {"id": "lib"}},
        "/v1/appAssetLibraries/lib/images": {"data": library},
        "/v1/appAssetLibraries/lib/videos": {"data": []},
        "/v1/appStoreVersionLocalizations/L/placements": {"data": placements},
    }
    for asset_id, ids in (backing or {}).items():
        answers[f"/v1/appAssetLibraryImages/{asset_id}/placements"] = {"data": [{"id": i} for i in ids]}
    return answers


def placement(id_: str, kind: str = SEARCH) -> dict[str, Any]:
    return {"id": id_, "attributes": {"placementType": kind, "placementGroup": "DEFAULT_PROFILE"}}


def in_library(path: Path, id_: str = "old") -> dict[str, Any]:
    return {"id": id_, "attributes": {"referenceName": creative.reference_name(path, path.read_bytes()),
                                      "state": "APPROVED", "category": "CREATIVE_ASSETS"}}


def test_an_unchanged_file_already_live_writes_nothing(tmp_path: Path) -> None:
    path = image(tmp_path / "search-result.jpg", 1920, 1280)
    client = Client(gets([in_library(path)], [placement("P1")], backing={"old": ["P1"]}))
    assert creative.apply_plan(client, "app", VERSION, {"en-US": {SEARCH: path}}, ref()) == 0
    assert client.writes == []


def test_a_new_file_is_uploaded_and_replaces_the_live_placement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = image(tmp_path / "search-result.jpg", 1920, 1280)
    monkeypatch.setattr(creative, "wait_until_placeable", lambda client, assets: [])
    client = Client(gets([], [placement("P1"), placement("S1", "APP_SCREENSHOT")]))
    assert creative.apply_plan(client, "app", VERSION, {"en-US": {SEARCH: path}}, ref()) == 1
    verbs = [(verb, path_) for verb, path_, _ in client.writes]
    assert verbs == [
        ("POST", "/v1/appAssetLibraryImages"),
        ("PATCH", "/v1/appAssetLibraryImages/new-1"),
        ("DELETE", "/v1/appAssetLibraryPlacements/P1"),   # the slot holds one; the screenshot is untouched
        ("POST", "/v1/appAssetLibraryPlacements"),
    ]
    reserve, commit, _, place = (body for _, _, body in client.writes)
    assert reserve["data"]["attributes"]["category"] == "CREATIVE_ASSETS"
    assert reserve["data"]["relationships"]["assetLibrary"]["data"]["id"] == "lib"
    assert commit["data"]["attributes"] == {"uploaded": True}  # no checksum in the library
    assert place["data"]["attributes"] == {"placementType": SEARCH, "placementGroup": "DEFAULT_PROFILE"}
    assert place["data"]["relationships"]["image"]["data"]["id"] == "new-1"
    assert place["data"]["relationships"]["appStoreVersionLocalization"]["data"]["id"] == "L"


def test_a_file_already_in_the_library_is_placed_without_uploading(tmp_path: Path) -> None:
    path = image(tmp_path / "universal.png", 5244, 2950)
    client = Client(gets([in_library(path, "U")], []))
    assert creative.apply_plan(client, "app", VERSION, {"en-US": {SEARCH: path, HEADER: path}}, ref()) == 2
    assert [(verb, p) for verb, p, _ in client.writes] == [
        ("POST", "/v1/appAssetLibraryPlacements"), ("POST", "/v1/appAssetLibraryPlacements")]
    assert {body["data"]["attributes"]["placementType"] for _, _, body in client.writes} == {SEARCH, HEADER}


def test_a_processing_failure_places_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = image(tmp_path / "search-result.jpg", 1920, 1280)
    monkeypatch.setattr(creative, "wait_until_placeable", lambda client, assets: ["search-result.jpg: failed by Apple"])
    client = Client(gets([], [placement("P1")]))
    with pytest.raises(SystemExit, match="nothing live was changed"):
        creative.apply_plan(client, "app", VERSION, {"en-US": {SEARCH: path}}, ref())
    assert not any(p.startswith("/v1/appAssetLibraryPlacements") for _, p, _ in client.writes)


def test_a_missing_localization_stops_before_writing(tmp_path: Path) -> None:
    path = image(tmp_path / "search-result.jpg", 1920, 1280)
    client = Client(gets([], []))
    with pytest.raises(Exception, match="no AppStoreVersionLocalization for de-DE"):
        creative.apply_plan(client, "app", VERSION, {"de-DE": {SEARCH: path}}, ref())
    assert client.writes == []
