"""`packs package` gives a new pack its record row; `packs status` reads altool's version blocks."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from snakelane.release.assetpacks import Packs, add_row, parse_versions, upload

SENT = {"asset_pack_id": "unicorns1", "theme": "unicorns1", "available_from_version": "1.9",
        "pictures": 15, "archive_bytes": 6569042, "uploaded": True, "apple_version": 2}


def make(tmp_path: Path, *rows: dict) -> Packs:
    record = tmp_path / "asset_packs.json"
    record.write_text(json.dumps({"platforms": ["iOS"], "packs": list(rows)}, indent=2) + "\n")
    return Packs(SimpleNamespace(root=tmp_path), tmp_path / "packs", "packs/{theme}",
                 content_root=tmp_path, record=record, build=tmp_path / "build")


def rows(packs: Packs) -> list[dict]:
    return json.loads(packs.record.read_text())["packs"]


def test_a_new_pack_gets_a_row_with_no_release_guessed(tmp_path):
    packs = make(tmp_path, SENT)
    add_row(packs, "houses1", "houses1", 36, 1234, None)
    assert rows(packs) == [SENT, {"asset_pack_id": "houses1", "theme": "houses1", "available_from_version": None,
                                  "pictures": 36, "archive_bytes": 1234, "uploaded": False}]


def test_the_new_row_is_one_upload_refuses_until_a_release_is_set(tmp_path):
    packs = make(tmp_path)
    add_row(packs, "houses1", "houses1", 36, 1234, None)
    packs.build.mkdir()
    packs.archive_for("houses1").write_bytes(b"x")
    with pytest.raises(SystemExit, match="available_from_version is null"):
        upload(packs, ["houses1"], dry_run=True, new_version=False)


def test_available_from_is_taken_only_when_given(tmp_path):
    packs = make(tmp_path)
    add_row(packs, "houses1", "houses1", 36, 1234, "1.9")
    assert rows(packs)[0]["available_from_version"] == "1.9"


def test_an_existing_row_is_not_overwritten(tmp_path):
    packs = make(tmp_path, SENT)
    before = packs.record.read_text()
    message = add_row(packs, "unicorns1", "unicorns1", 99, 1, "2.0")
    assert packs.record.read_text() == before
    assert "left as it is" in message


def test_a_null_release_on_an_existing_row_is_filled_from_the_option(tmp_path):
    packs = make(tmp_path, SENT | {"available_from_version": None, "uploaded": False})
    add_row(packs, "unicorns1", "unicorns1", 99, 1, "1.9")
    assert rows(packs)[0] == SENT | {"uploaded": False}


def test_a_theme_recorded_under_another_id_stops(tmp_path):
    packs = make(tmp_path, SENT | {"asset_pack_id": "unicorns"})
    with pytest.raises(SystemExit, match="ids freeze"):
        add_row(packs, "unicorns1", "unicorns1", 15, 1, None)


def test_a_release_that_is_not_a_version_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="expected a version"):
        add_row(make(tmp_path), "houses1", "houses1", 36, 1, "next")


# Real output (Jigsaw, 2026-11-13): unicorns1 after its second upload.
VERSIONS = """
=======================
= Asset Pack Identifier: unicorns1
= Apple ID: 6762405588
=======================
= Version ID: 7170794e-52ba-4553-98f0-faf6859b7a93
= Version: 1
= State: SUPERSEDED
= Date Created: 8/17/26, 9:27:24 AM
= Platforms: IOS, MAC_OS
===========
= Version ID: 846df1cd-34b4-45bf-93fe-1f0197e00149
= Version: 2
= State: READY_FOR_TESTING
= Date Created: 11/13/26, 7:56:47 AM
= Platforms: IOS, MAC_OS
===========
"""


def test_versions_are_parsed_latest_first():
    assert parse_versions(VERSIONS) == [
        {"version_id": "846df1cd-34b4-45bf-93fe-1f0197e00149", "version": 2, "state": "READY_FOR_TESTING",
         "date_created": "11/13/26, 7:56:47 AM", "platforms": "IOS, MAC_OS"},
        {"version_id": "7170794e-52ba-4553-98f0-faf6859b7a93", "version": 1, "state": "SUPERSEDED",
         "date_created": "8/17/26, 9:27:24 AM", "platforms": "IOS, MAC_OS"},
    ]


def test_a_pack_with_no_versions_parses_to_none():
    # altool exits 0 and says "No background asset pack versions found" on stderr.
    assert parse_versions("") == []
