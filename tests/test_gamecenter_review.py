"""`gamecenter submit` and `ship release`: Game Center records waiting for review join the draft."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from snakelane.connect import asc
from snakelane.gamecenter import review
from snakelane.release import ship

from .fakes import FakeClient
from .helpers import make_app

DETAIL = "/v1/gameCenterDetails/d1"


def record(id_: str, vendor: str, archived: bool = False) -> dict[str, Any]:
    return {"id": id_, "attributes": {"vendorIdentifier": vendor, "archived": archived}}


def version(id_: str, number: int, state: str) -> dict[str, Any]:
    return {"id": id_, "attributes": {"version": number, "state": state}}


def app_store_connect(app_state: str = "PREPARE_FOR_SUBMISSION") -> FakeClient:
    """An app with a draft submission, its 1.0 in `app_state`, and Game Center records in every state
    that matters: new, live, already in a draft, archived."""
    return FakeClient({
        "/v1/apps": {"data": [{"id": "42", "attributes": {"bundleId": "com.example.app"}}]},
        "/v1/apps/42/gameCenterDetail": {"data": {"id": "d1"}},
        f"{DETAIL}/gameCenterAchievementsV2": {"data": [record("a1", "ach.new"), record("a2", "ach.live"),
                                                        record("a3", "ach.gone", archived=True)]},
        "/v2/gameCenterAchievements/a1/versions": {"data": [version("a1v1", 1, "PREPARE_FOR_SUBMISSION")]},
        "/v2/gameCenterAchievements/a2/versions": {"data": [version("a2v1", 1, "LIVE")]},
        "/v2/gameCenterAchievements/a3/versions": {"data": [version("a3v1", 1, "PREPARE_FOR_SUBMISSION")]},
        f"{DETAIL}/gameCenterLeaderboardsV2": {"data": [record("l1", "lb.drafted"), record("l2", "lb.redo")]},
        "/v2/gameCenterLeaderboards/l1/versions": {"data": [version("l1v1", 1, "READY_FOR_REVIEW")]},
        # The newest version decides: version 2 was rejected and goes back.
        "/v2/gameCenterLeaderboards/l2/versions": {"data": [version("l2v1", 1, "LIVE"),
                                                            version("l2v2", 2, "REJECTED")]},
        "/v1/apps/42/reviewSubmissions": {"data": [{"id": "s1", "attributes": {"state": "READY_FOR_REVIEW"}}]},
        "/v1/apps/42/appStoreVersions": {"data": [{"id": "v1", "attributes": {
            "versionString": "1.0", "appStoreState": app_state}}]},
        "/v1/appStoreVersions/v1": {"data": {"id": "v1", "attributes": {"appStoreState": app_state}}},
    })


def added(client: FakeClient) -> list[tuple[str, str]]:
    """(relationship, id) for every item posted to the submission."""
    found = []
    for method, path, body in client.writes:
        if (method, path) == ("POST", "/v1/reviewSubmissionItems"):
            (name, target), = ((k, v) for k, v in body["data"]["relationships"].items() if k != "reviewSubmission")
            assert body["data"]["relationships"]["reviewSubmission"]["data"]["id"] == "s1"
            found.append((name, target["data"]["id"]))
    return found


@pytest.fixture
def config(tmp_path: Path) -> dict[str, Any]:
    return make_app(tmp_path).config


def test_only_records_waiting_for_review_are_added(config: dict[str, Any]) -> None:
    client = app_store_connect()
    pending = review.pending_items(client, config)
    assert [(i.vendor_id, i.version["id"]) for i in pending if i.version] == [("ach.new", "a1v1"), ("lb.redo", "l2v2")]


def test_submit_adds_the_version_and_the_records_to_the_open_draft_and_never_submits(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_app(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = app_store_connect()
    monkeypatch.setattr(asc, "Client", lambda **_: client)
    review.cmd_submit(SimpleNamespace(app=None, platform=None, dry_run=False, yes=True, without_version=False))
    assert added(client) == [("appStoreVersion", "v1"), ("gameCenterAchievementVersion", "a1v1"),
                             ("gameCenterLeaderboardVersion", "l2v2")]
    assert not [w for w in client.writes if w[0] == "PATCH"]  # nothing submitted


def test_without_version_leaves_the_app_version_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_app(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = app_store_connect()
    monkeypatch.setattr(asc, "Client", lambda **_: client)
    review.cmd_submit(SimpleNamespace(app=None, platform=None, dry_run=False, yes=True, without_version=True))
    assert ("appStoreVersion", "v1") not in added(client)


def test_ship_release_sends_the_records_with_the_version(config: dict[str, Any]) -> None:
    client = app_store_connect()
    ship.submit_for_review(client, "42", "v1", "ios", config)
    assert added(client) == [("appStoreVersion", "v1"), ("gameCenterAchievementVersion", "a1v1"),
                             ("gameCenterLeaderboardVersion", "l2v2")]
    assert client.writes[-1][:2] == ("PATCH", "/v1/reviewSubmissions/s1")


def test_ship_release_doesn_t_add_a_version_already_in_the_draft(config: dict[str, Any]) -> None:
    client = app_store_connect(app_state="READY_FOR_REVIEW")
    ship.submit_for_review(client, "42", "v1", "ios", config)
    assert ("appStoreVersion", "v1") not in added(client)


def test_a_version_not_ready_for_review_says_what_to_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_app(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = app_store_connect()

    def refuse(path: str, body: dict[str, Any]) -> dict[str, Any]:
        raise asc.ASCError("POST /v1/reviewSubmissionItems → HTTP 409: not in valid state", status=409)

    monkeypatch.setattr(client, "post", refuse)
    monkeypatch.setattr(asc, "Client", lambda **_: client)
    with pytest.raises(SystemExit, match=r"store push"):
        review.cmd_submit(SimpleNamespace(app=None, platform=None, dry_run=False, yes=True, without_version=False))
