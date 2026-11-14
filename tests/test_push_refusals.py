from __future__ import annotations

from typing import Any

from snakelane.connect import asc
from snakelane.listing.push import upsert_locale_or_report

IN_USE = ("PATCH /v1/appInfoLocalizations/x → HTTP 409: The app name you entered is already being used. "
          "If you have trademark rights to this name …")


def test_a_name_in_use_is_reported_and_the_rest_of_the_locale_still_lands() -> None:
    writes: list[dict[str, Any]] = []

    def write(attrs: dict[str, Any]) -> None:
        writes.append(attrs)
        if "name" in attrs:
            raise asc.ASCError(IN_USE, status=409)

    refused: list[tuple[str, str, str]] = []
    upsert_locale_or_report(refused, "en-US", write, {"name": "Taken", "subtitle": "Sub"})
    assert writes == [{"name": "Taken", "subtitle": "Sub"}, {"subtitle": "Sub"}]
    assert refused == [("en-US", "name 'Taken'", "already used by another app — choose another")]


def test_any_other_refusal_is_reported_against_its_locale() -> None:
    def write(attrs: dict[str, Any]) -> None:
        raise asc.ASCError("HTTP 422: invalid field", status=422)

    refused: list[tuple[str, str, str]] = []
    upsert_locale_or_report(refused, "ko", write, {"description": "…"})
    assert refused == [("ko", "description", "HTTP 422: invalid field")]


def test_a_network_failure_still_stops_the_push() -> None:
    def write(attrs: dict[str, Any]) -> None:
        raise asc.TransientNetworkError("timed out")

    try:
        upsert_locale_or_report([], "fr-FR", write, {"name": "x"})
    except asc.TransientNetworkError:
        return
    raise AssertionError("a network failure must not be swallowed")
