"""An approved IAP localization is frozen: App Store Connect refuses an API edit (409), so the push
reports it for the website and carries on, and new locales are still created."""

from __future__ import annotations

import pytest

from snakelane.connect import asc
from snakelane.purchases.iap import sync_localizations

from .fakes import FakeClient

KIND = "inAppPurchaseLocalizations"


def live(locale: str, name: str, state: str) -> dict:
    return {"id": f"L-{locale}", "type": KIND, "attributes": {"locale": locale, "name": name, "state": state}}


def test_an_approved_change_is_reported_and_the_new_locale_still_created() -> None:
    client = FakeClient()
    problems: list[str] = []
    sync_localizations(client, "  ", "localization", KIND, {}, {"fr-FR": live("fr-FR", "Plage Pack 1", "APPROVED")},
                       {"fr-FR": {"name": "Pack Plage 1"}, "it": {"name": "Pacchetto Spiaggia 1"}},
                       "com.example.beach", problems)
    assert [(method, path) for method, path, _ in client.writes] == [("POST", f"/v1/{KIND}")]
    assert len(problems) == 1 and "com.example.beach [fr-FR]" in problems[0] and "Pack Plage 1" in problems[0]


def test_an_editable_localization_is_patched_once() -> None:
    client = FakeClient()
    problems: list[str] = []
    sync_localizations(client, "  ", "localization", KIND, {},
                       {"fr-FR": live("fr-FR", "Plage Pack 1", "PREPARE_FOR_SUBMISSION")},
                       {"fr-FR": {"name": "Pack Plage 1"}}, "com.example.beach", problems)
    assert [(method, path) for method, path, _ in client.writes] == [("PATCH", f"/v1/{KIND}/L-fr-FR")]
    assert problems == []


class RefusingClient(FakeClient):
    def patch(self, path: str, body: dict) -> dict:
        raise asc.ASCError("HTTP 409: Cannot edit InAppPurchaseLocalization when it is in ACTIVE state", status=409)


def test_a_409_on_a_state_we_did_not_know_was_frozen_is_reported_not_raised() -> None:
    problems: list[str] = []
    sync_localizations(RefusingClient(), "  ", "localization", KIND, {},
                       {"de-DE": live("de-DE", "Tiere-Paket 1", "SOMETHING_NEW")},
                       {"de-DE": {"name": "Tier-Paket 1"}}, "com.example.animals", problems)
    assert len(problems) == 1


def test_without_a_problems_list_a_refusal_still_stops_the_push() -> None:
    with pytest.raises(asc.ASCError):
        sync_localizations(RefusingClient(), "  ", "localization", KIND, {},
                           {"de-DE": live("de-DE", "Tiere-Paket 1", "APPROVED")}, {"de-DE": {"name": "Tier-Paket 1"}})
