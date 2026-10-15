"""`asset_packs.source_under`: packaging refuses a pictureSource outside the reviewed folder."""

import pytest

from snakelane.release.assetpacks import picture_source


def test_no_restriction_by_default():
    assert picture_source("animals", {"pictureSource": "candidates/animals"}) == "candidates/animals"


def test_source_under_accepts_its_own_folder():
    assert picture_source("animals", {"pictureSource": "approved/animals"}, "approved") == "approved/animals"


@pytest.mark.parametrize("source", ["candidates/animals", "approved-old/animals", "wip/approved/animals"])
def test_source_under_refuses_anything_else(source):
    with pytest.raises(SystemExit, match="not under approved/"):
        picture_source("animals", {"pictureSource": source}, "approved")


def test_missing_source_is_still_refused():
    with pytest.raises(SystemExit, match="no pictureSource"):
        picture_source("animals", {}, "approved")
