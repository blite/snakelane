"""Offline checks on `store ppo push`: the test folders, and what the push writes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from snakelane.screenshots import creative, ppo

from .helpers import image
from .test_creative import SEARCH, Client, in_library, placement, ref


def write_test(root: Path, config: str, files: dict[str, tuple[int, int]] | None = None) -> Path:
    folder = root / "ppo" / "art"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "experiment.yml").write_text(config)
    for relative, size in (files or {"table/creative/default/search-result.jpg": (1920, 1280)}).items():
        image(folder / relative, *size)
    return folder


CONFIG = "name: Search result art\ntraffic: 50\ntreatments:\n  table: Table mid-trick\n"


def test_a_test_folder_reads_into_treatments_and_slots(tmp_path: Path) -> None:
    folder = write_test(tmp_path, CONFIG, {"table/creative/default/search-result.jpg": (1920, 1280),
                                           "table/creative/ios/de-DE/search-result.jpg": (1920, 1280)})
    (test,) = ppo.load_tests(tmp_path, "ios", ["en-US", "de-DE"])
    assert (test.name, test.traffic) == ("Search result art", 50)
    (treatment,) = test.treatments
    assert treatment.name == "Table mid-trick"
    assert treatment.slots["en-US"] == {SEARCH: folder / "table/creative/default/search-result.jpg"}
    assert treatment.slots["de-DE"] == {SEARCH: folder / "table/creative/ios/de-DE/search-result.jpg"}


def test_no_ppo_folder_means_no_tests(tmp_path: Path) -> None:
    assert ppo.load_tests(tmp_path, "ios", ["en-US"]) == []


@pytest.mark.parametrize(("config", "message"), [
    ("traffic: 50\ntreatments: {table: A}\n", "`name` is required"),
    ("name: X\ntraffic: 0\ntreatments: {table: A}\n", "whole percent"),
    ("name: X\ntraffic: 50.5\ntreatments: {table: A}\n", "whole percent"),
    ("name: X\ntraffic: 50\n", "`treatments` maps"),
    ("name: X\ntraffic: 50\ntreatments: {a: A, b: B, c: C, table: D}\n", "takes 3"),
    ("name: X\ntraffic: 50\ntreatments: {table: A, other: A}\n", "named alike"),
    ("name: X\ntraffic: 50\ntreatments: {missing: A}\n", "no folder"),
])
def test_a_bad_experiment_file_stops_before_apple_is_asked(tmp_path: Path, config: str, message: str) -> None:
    write_test(tmp_path, config)
    (tmp_path / "ppo/art/other").mkdir(exist_ok=True)
    with pytest.raises(SystemExit, match=message):
        ppo.load_tests(tmp_path, "ios", ["en-US"])


def test_a_treatment_without_files_is_refused(tmp_path: Path) -> None:
    # Only an iOS file, so the Mac treatment would show nothing the live page doesn't.
    write_test(tmp_path, CONFIG, {"table/creative/ios/default/search-result.jpg": (1920, 1280)})
    with pytest.raises(SystemExit, match="no creative assets for macos"):
        ppo.load_tests(tmp_path, "macos", ["en-US"])


def experiment(id_: str, name: str = "Search result art", state: str = "PREPARE_FOR_SUBMISSION",
               platform: str = "IOS", traffic: int = 50) -> dict[str, Any]:
    return {"id": id_, "attributes": {"name": name, "state": state, "platform": platform,
                                      "trafficProportion": traffic}}


def gets(path: Path, experiments: list[dict[str, Any]], treatments: list[dict[str, Any]] | None = None,
         localizations: list[dict[str, Any]] | None = None, placements: list[dict[str, Any]] | None = None,
         backing: list[str] | None = None) -> dict[str, Any]:
    answers: dict[str, Any] = {
        "/v1/apps/app/assetLibrary": {"data": {"id": "lib"}},
        "/v1/appAssetLibraries/lib/images": {"data": [in_library(path, "A")]},
        "/v1/appAssetLibraries/lib/videos": {"data": []},
        "/v1/apps/app/appStoreVersionExperimentsV2": {"data": experiments},
        "/v1/appAssetLibraryImages/A/placements": {"data": [{"id": i} for i in backing or []]},
    }
    for e in experiments:
        answers[f"/v2/appStoreVersionExperiments/{e['id']}/appStoreVersionExperimentTreatments"] = {
            "data": treatments or []}
    for t in treatments or []:
        answers[f"/v1/appStoreVersionExperimentTreatments/{t['id']}/appStoreVersionExperimentTreatmentLocalizations"] = {
            "data": localizations or []}
    for loc in localizations or []:
        answers[f"/v1/appStoreVersionExperimentTreatmentLocalizations/{loc['id']}/placements"] = {
            "data": placements or []}
    return answers


def planned_tests(tmp_path: Path) -> tuple[list[ppo.Test], Path]:
    folder = write_test(tmp_path, CONFIG)
    return ppo.load_tests(tmp_path, "ios", ["en-US"]), folder / "table/creative/default/search-result.jpg"


def test_a_new_test_is_created_with_its_treatment_and_placement(tmp_path: Path) -> None:
    tests, path = planned_tests(tmp_path)
    # A Mac test of the same name is another platform's: not this one.
    client = Client(gets(path, [experiment("mac", platform="MAC_OS")]))
    assert ppo.push_tests(client, "app", "ios", tests, ref()) == 1
    assert [(verb, p) for verb, p, _ in client.writes] == [
        ("POST", "/v2/appStoreVersionExperiments"),
        ("POST", "/v1/appStoreVersionExperimentTreatments"),
        ("POST", "/v1/appStoreVersionExperimentTreatmentLocalizations"),
        ("POST", "/v1/appAssetLibraryPlacements"),
    ]
    test, treatment, localization, place = (body["data"] for _, _, body in client.writes)
    assert test["type"] == "appStoreVersionExperiments"
    assert test["attributes"] == {"name": "Search result art", "platform": "IOS", "trafficProportion": 50}
    assert test["relationships"]["app"]["data"] == {"type": "apps", "id": "app"}
    assert treatment["attributes"] == {"name": "Table mid-trick"}
    assert treatment["relationships"]["appStoreVersionExperimentV2"]["data"]["id"] == "new-1"
    assert localization["attributes"] == {"locale": "en-US"}
    assert localization["relationships"]["appStoreVersionExperimentTreatment"]["data"]["id"] == "new-2"
    assert place["attributes"]["placementType"] == SEARCH
    assert place["relationships"]["image"]["data"]["id"] == "A"
    assert place["relationships"]["appStoreVersionExperimentTreatmentLocalization"]["data"] == {
        "type": "appStoreVersionExperimentTreatmentLocalizations", "id": "new-3"}
    assert "appStoreVersionLocalization" not in place["relationships"]


def test_a_prepared_test_already_showing_the_file_only_has_its_traffic_set(tmp_path: Path) -> None:
    tests, path = planned_tests(tmp_path)
    client = Client(gets(path, [experiment("E", traffic=25)],
                         treatments=[{"id": "T", "attributes": {"name": "Table mid-trick"}}],
                         localizations=[{"id": "TL", "attributes": {"locale": "en-US"}}],
                         placements=[placement("P1")], backing=["P1"]))
    assert ppo.push_tests(client, "app", "ios", tests, ref()) == 0
    assert [(verb, p) for verb, p, _ in client.writes] == [("PATCH", "/v2/appStoreVersionExperiments/E")]
    assert client.writes[0][2]["data"]["attributes"] == {"trafficProportion": 50}


def test_a_changed_file_replaces_the_treatments_placement(tmp_path: Path) -> None:
    tests, path = planned_tests(tmp_path)
    client = Client(gets(path, [experiment("E")],
                         treatments=[{"id": "T", "attributes": {"name": "Table mid-trick"}}],
                         localizations=[{"id": "TL", "attributes": {"locale": "en-US"}}],
                         placements=[placement("OLD")]))
    assert ppo.push_tests(client, "app", "ios", tests, ref()) == 1
    assert [(verb, p) for verb, p, _ in client.writes] == [
        ("DELETE", "/v1/appAssetLibraryPlacements/OLD"), ("POST", "/v1/appAssetLibraryPlacements")]


@pytest.mark.parametrize(("state", "message"), [("COMPLETED", "new name"), ("IN_REVIEW", "locks it")])
def test_a_submitted_or_finished_test_is_not_touched(tmp_path: Path, state: str, message: str) -> None:
    tests, path = planned_tests(tmp_path)
    client = Client(gets(path, [experiment("E", state=state)]))
    with pytest.raises(SystemExit, match=message):
        ppo.push_tests(client, "app", "ios", tests, ref())
    assert client.writes == []


def test_a_finished_test_beside_a_prepared_one_of_the_same_name_uses_the_prepared_one(tmp_path: Path) -> None:
    tests, path = planned_tests(tmp_path)
    client = Client(gets(path, [experiment("OLD", state="COMPLETED"), experiment("E")]))
    ppo.push_tests(client, "app", "ios", tests, ref())
    assert client.writes[0][:2] == ("POST", "/v1/appStoreVersionExperimentTreatments")
    assert client.writes[0][2]["data"]["relationships"]["appStoreVersionExperimentV2"]["data"]["id"] == "E"


def test_the_version_push_still_places_on_the_version(tmp_path: Path) -> None:
    target = creative.version_target("L", "en-US")
    assert (target.resource, target.relationship) == ("appStoreVersionLocalizations", "appStoreVersionLocalization")
