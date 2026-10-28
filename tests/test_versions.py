"""Which App Store version a push plans against."""

from __future__ import annotations

import pytest

from snakelane.connect import resources


class Versions:
    """An app whose only version is live: no draft yet."""

    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run

    def get_all(self, path, params=None):
        yield {"id": "live", "attributes": {"appStoreState": "READY_FOR_SALE", "versionString": "1.2"}}


def test_a_dry_run_without_a_draft_plans_against_the_live_version() -> None:
    assert resources.version_to_push(Versions(dry_run=True), "A1", "ios")["id"] == "live"


def test_a_real_push_without_a_draft_stops() -> None:
    with pytest.raises(resources.NoEditableVersion):
        resources.version_to_push(Versions(dry_run=False), "A1", "ios")
