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
    with pytest.raises(SystemExit, match="no screenshots or creative assets for macos"):
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
    assert ppo.push_tests(client, "app", "ios", tests, ref()) == (1, [])
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
    assert ppo.push_tests(client, "app", "ios", tests, ref()) == (0, [])
    assert [(verb, p) for verb, p, _ in client.writes] == [("PATCH", "/v2/appStoreVersionExperiments/E")]
    assert client.writes[0][2]["data"]["attributes"] == {"trafficProportion": 50}


def test_a_changed_file_replaces_the_treatments_placement(tmp_path: Path) -> None:
    tests, path = planned_tests(tmp_path)
    client = Client(gets(path, [experiment("E")],
                         treatments=[{"id": "T", "attributes": {"name": "Table mid-trick"}}],
                         localizations=[{"id": "TL", "attributes": {"locale": "en-US"}}],
                         placements=[placement("OLD")]))
    assert ppo.push_tests(client, "app", "ios", tests, ref()) == (1, [])
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


# --- treatment screenshots ---------------------------------------------------------------------------

SHOTS_CONFIG = "name: No ads first\ntraffic: 50\ntreatments:\n  promise: Promise first\n"
IPHONE, IPAD = (1206, 2622), (2064, 2752)


def shots_test(tmp_path: Path, locale: str = "en-US", count: int = 3) -> Path:
    files = {f"promise/screenshots/ios/{locale}/{device}/ss-{n:02d}.jpg": size
             for device, size in (("iphone", IPHONE), ("ipad", IPAD)) for n in range(1, count + 1)}
    return write_test(tmp_path, SHOTS_CONFIG, files)


def test_a_treatment_with_only_screenshots_reads_its_sets_by_size(tmp_path: Path) -> None:
    shots_test(tmp_path)
    (test,) = ppo.load_tests(tmp_path, "ios", ["en-US", "de-DE"])
    (treatment,) = test.treatments
    assert treatment.slots == {}
    # de-DE has no folder: no opinion, so it isn't in the plan at all.
    assert set(treatment.screenshots) == {"en-US"}
    sets = treatment.screenshots["en-US"]
    assert sorted(sets) == ["APP_IPAD_PRO_3GEN_129", "APP_IPHONE_61"]
    for files in sets.values():
        assert [f.name for f in files] == ["ss-01.jpg", "ss-02.jpg", "ss-03.jpg"]
    assert {f.parent.name for files in sets.values() for f in files} == {"iphone", "ipad"}
    assert treatment.locales == ["en-US"]


def test_a_treatment_with_more_than_ten_shots_in_a_set_is_refused(tmp_path: Path) -> None:
    shots_test(tmp_path, count=11)
    with pytest.raises(SystemExit, match="too many screenshots"):
        ppo.load_tests(tmp_path, "ios", ["en-US"])


def test_a_treatment_screenshot_of_an_unknown_size_is_refused(tmp_path: Path) -> None:
    write_test(tmp_path, SHOTS_CONFIG, {"promise/screenshots/ios/en-US/iphone/ss-01.jpg": (1000, 1000)})
    with pytest.raises(SystemExit):
        ppo.load_tests(tmp_path, "ios", ["en-US"])


def test_screenshots_for_another_platform_dont_make_a_treatment(tmp_path: Path) -> None:
    shots_test(tmp_path)
    with pytest.raises(SystemExit, match="no screenshots or creative assets for macos"):
        ppo.load_tests(tmp_path, "macos", ["en-US"])


def test_screenshots_upload_into_new_sets_on_a_new_treatment_localization(tmp_path: Path) -> None:
    shots_test(tmp_path)
    tests = ppo.load_tests(tmp_path, "ios", ["en-US"])
    client = Client({"/v1/apps/app/appStoreVersionExperimentsV2": {"data": [experiment("E", name="No ads first")]}})
    pushed = ppo.push_tests(client, "app", "ios", tests, None)
    assert pushed.placements == 0
    assert len(pushed.uploads) == 6
    posts = [(p, body["data"]) for verb, p, body in client.writes if verb == "POST"]
    # No creative assets: the App Asset Library is never touched.
    assert [p for p, _ in posts[:2]] == ["/v1/appStoreVersionExperimentTreatments",
                                         "/v1/appStoreVersionExperimentTreatmentLocalizations"]
    localization_id = "new-2"
    sets = [data for p, data in posts if p == "/v1/appScreenshotSets"]
    assert len(sets) == 2
    for data in sets:
        assert data["relationships"] == {"appStoreVersionExperimentTreatmentLocalization": {"data": {
            "type": "appStoreVersionExperimentTreatmentLocalizations", "id": localization_id}}}
    shots = [data for p, data in posts if p == "/v1/appScreenshots"]
    assert sorted(d["attributes"]["fileName"] for d in shots) == sorted(["ss-01.jpg", "ss-02.jpg", "ss-03.jpg"] * 2)
    assert not any("assetLibrary" in p or "Placements" in p for _, p, _ in client.writes)


def test_a_live_set_is_replaced_wholesale_and_a_slot_no_longer_filled_is_deleted(tmp_path: Path) -> None:
    write_test(tmp_path, SHOTS_CONFIG, {f"promise/screenshots/ios/en-US/iphone/ss-0{n}.jpg": IPHONE for n in (1, 2)})
    tests = ppo.load_tests(tmp_path, "ios", ["en-US"])
    (iphone_type,) = tests[0].treatments[0].screenshots["en-US"]
    client = Client({
        "/v1/apps/app/appStoreVersionExperimentsV2": {"data": [experiment("E", name="No ads first")]},
        "/v2/appStoreVersionExperiments/E/appStoreVersionExperimentTreatments": {
            "data": [{"id": "T", "attributes": {"name": "Promise first"}}]},
        "/v1/appStoreVersionExperimentTreatments/T/appStoreVersionExperimentTreatmentLocalizations": {
            "data": [{"id": "TL", "attributes": {"locale": "en-US"}}]},
        "/v1/appStoreVersionExperimentTreatmentLocalizations/TL/appScreenshotSets": {"data": [
            {"id": "S1", "attributes": {"screenshotDisplayType": iphone_type}},
            {"id": "S2", "attributes": {"screenshotDisplayType": "APP_IPAD_PRO_3GEN_129"}}]},
        "/v1/appScreenshotSets/S1/appScreenshots": {"data": [{"id": "old-1"}, {"id": "old-2"}, {"id": "old-3"}]},
    })
    pushed = ppo.push_tests(client, "app", "ios", tests, None)
    assert [(verb, p) for verb, p, _ in client.writes if verb == "DELETE"] == [
        ("DELETE", "/v1/appScreenshotSets/S2"),
        ("DELETE", "/v1/appScreenshots/old-1"), ("DELETE", "/v1/appScreenshots/old-2"),
        ("DELETE", "/v1/appScreenshots/old-3")]
    # The kept set is refilled, not recreated; the localization already exists.
    assert not any(p in ("/v1/appScreenshotSets", "/v1/appStoreVersionExperimentTreatmentLocalizations")
                   for verb, p, _ in client.writes if verb == "POST")
    assert [u["relationships"]["appScreenshotSet"]["data"]["id"] for u in pushed.uploads] == ["S1", "S1"]


def test_a_locale_without_a_screenshots_folder_keeps_its_live_sets(tmp_path: Path) -> None:
    shots_test(tmp_path, locale="en-US")
    tests = ppo.load_tests(tmp_path, "ios", ["en-US", "de-DE"])
    client = Client({
        "/v1/apps/app/appStoreVersionExperimentsV2": {"data": [experiment("E", name="No ads first")]},
        "/v2/appStoreVersionExperiments/E/appStoreVersionExperimentTreatments": {
            "data": [{"id": "T", "attributes": {"name": "Promise first"}}]},
        "/v1/appStoreVersionExperimentTreatments/T/appStoreVersionExperimentTreatmentLocalizations": {
            "data": [{"id": "EN", "attributes": {"locale": "en-US"}}, {"id": "DE", "attributes": {"locale": "de-DE"}}]},
        "/v1/appStoreVersionExperimentTreatmentLocalizations/DE/appScreenshotSets": {"data": [
            {"id": "DE-SET", "attributes": {"screenshotDisplayType": "APP_IPHONE_67"}}]},
    })
    ppo.push_tests(client, "app", "ios", tests, None)
    assert not any("DE" in p for _, p, _ in client.writes)


def test_screenshots_and_creative_assets_on_one_treatment(tmp_path: Path) -> None:
    folder = write_test(tmp_path, CONFIG, {"table/creative/default/search-result.jpg": (1920, 1280),
                                           "table/screenshots/ios/en-US/iphone/ss-01.jpg": IPHONE})
    tests = ppo.load_tests(tmp_path, "ios", ["en-US"])
    client = Client(gets(folder / "table/creative/default/search-result.jpg", [experiment("E")]))
    pushed = ppo.push_tests(client, "app", "ios", tests, ref())
    assert pushed.placements == 1
    assert len(pushed.uploads) == 1
    paths = [p for verb, p, _ in client.writes if verb == "POST"]
    assert paths.count("/v1/appStoreVersionExperimentTreatmentLocalizations") == 1
    assert "/v1/appAssetLibraryPlacements" in paths and "/v1/appScreenshotSets" in paths


def test_the_dry_run_without_a_key_prints_the_local_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                         capsys: pytest.CaptureFixture[str]) -> None:
    from types import SimpleNamespace

    from snakelane.connect import asc

    from .helpers import make_app

    app = make_app(tmp_path, developer_chrome_check=False)
    shots_test(app.folder)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(asc.Credentials, "available", staticmethod(lambda: False))
    ppo.cmd_ppo_push(SimpleNamespace(app=None, platform="ios", dry_run=True, allow_developer_chrome=False))
    out = capsys.readouterr().out
    assert "'No ads first': 50% of visitors, 1 treatment(s)" in out
    assert "ppo/art/promise/screenshots/ios/en-US/iphone/ ss-01.jpg, ss-02.jpg, ss-03.jpg" in out
    assert "nothing was written" in out
