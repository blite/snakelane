"""A stand-in for asc.Client that answers from a dict and records every write."""

from __future__ import annotations

from typing import Any


class FakeClient:
    def __init__(self, gets: dict[str, Any] | None = None) -> None:
        self.gets = gets or {}
        self.writes: list[tuple[str, str, Any]] = []
        self.dry_run = False

    def report(self, message: str) -> None:
        print(message)

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.gets.get(path, {"data": None})

    def get_all(self, path: str, params: dict[str, Any] | None = None):
        yield from self.gets.get(path, {"data": []})["data"]

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("PATCH", path, body))
        return body

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("POST", path, body))
        return body

    def delete(self, path: str) -> None:
        self.writes.append(("DELETE", path, None))
