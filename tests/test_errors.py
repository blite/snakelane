"""A failed read is never mistaken for an absent resource."""

from __future__ import annotations

import pytest

from snakelane.connect import asc
from snakelane.connect.resources import get_optional
from snakelane.purchases.subscriptions import base_territory_price


class Failing:
    def __init__(self, error: asc.ASCError) -> None:
        self.error = error

    def get(self, path, params=None):
        raise self.error

    def get_all(self, path, params=None):
        yield {"relationships": {"subscriptionPricePoint": {"data": {"id": "p1"}}}}


def test_only_a_404_reads_as_absent() -> None:
    assert get_optional(Failing(asc.ASCError("gone", status=404)), "/v1/x") is None
    with pytest.raises(asc.ASCError, match="boom"):
        get_optional(Failing(asc.ASCError("boom", status=500)), "/v1/x")
    with pytest.raises(asc.TransientNetworkError):
        get_optional(Failing(asc.TransientNetworkError("timed out")), "/v1/x")


def test_a_failed_price_read_stops_rather_than_reads_as_unpriced() -> None:
    with pytest.raises(asc.ASCError):
        base_territory_price(Failing(asc.TransientNetworkError("timed out")), "sub1")
