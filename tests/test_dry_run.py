"""A dry run is the client's job: against a live App Store Connect (a local stand-in here), every
push reads what it needs and sends no write at all."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from typing import Any

import pytest

from snakelane.connect import asc

from .test_examples import TRAILHEAD

LIVE: dict[str, Any] = {  # path -> `data`; anything else is an empty list
    "/v1/apps": [{"id": "1", "attributes": {"bundleId": "com.example.trailhead"}}],
    "/v1/apps/1/appStoreVersions": [{"id": "v", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION"}}],
    "/v1/appStoreVersions/v/appStoreVersionLocalizations": [
        {"id": f"L-{locale}", "attributes": {"locale": locale}} for locale in ("en-US", "en-AU", "de-DE")],
    "/v1/appStoreVersionLocalizations/L-en-US/appScreenshotSets": [
        {"id": "S", "attributes": {"screenshotDisplayType": "APP_IPHONE_65"}}],
    "/v1/appScreenshotSets/S/appScreenshots": [{"id": "old", "attributes": {"fileName": "ss-01.jpg"}}],
    "/v1/apps/1/appInfos": [{"id": "i", "attributes": {"appStoreState": "PREPARE_FOR_SUBMISSION"}}],
    "/v1/appInfos/i": {"id": "i", "relationships": {}},
    "/v1/appStoreVersions/v": {"id": "v", "attributes": {}},
    "/v1/appCategories": [{"id": "HEALTH_AND_FITNESS"}, {"id": "NAVIGATION"}],
}


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serves LIVE and returns the methods it was sent; the commands run against the example app."""
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            hits.append(self.command)
            body = json.dumps({"data": LIVE.get(self.path.split("?")[0], [])}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = _answer

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    class Local(asc.Client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(asc.Credentials("K", "I"), timeout=5, **kwargs)

        def _headers(self) -> dict[str, str]:
            return {}

    monkeypatch.setattr(asc, "BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(asc, "Client", Local)
    monkeypatch.setattr(asc.Credentials, "available", staticmethod(lambda: True))
    monkeypatch.chdir(TRAILHEAD)
    yield hits
    server.shutdown()


def test_the_client_plans_writes_and_reads_nothing_under_a_planned_id(live: list[str],
                                                                       capsys: pytest.CaptureFixture) -> None:
    client = asc.Client(dry_run=True)
    created = client.post("/v1/things", asc.resource_body("things", {"name": "A"}))["data"]
    assert asc.planned(created["id"]) and created["attributes"] == {"name": "A"}
    client.patch(f"/v1/things/{created['id']}", {"data": {"attributes": {"name": "B"}}})
    client.delete("/v1/things/7")
    client.upload_part({"method": "PUT", "length": 3, "offset": 0, "url": "https://upload.example"}, b"abc")
    assert client.get(f"/v1/things/{created['id']}/parts") == {}
    assert list(client.get_all(f"/v1/things/{created['id']}/parts")) == []
    assert live == [], "nothing reached the server"
    out = capsys.readouterr().out
    assert "would POST /v1/things  name='A'" in out and "would DELETE /v1/things/7" in out


@pytest.mark.parametrize("module, command, options", [
    ("listing.push", "cmd_push", {"platform": None, "skip_lint": False, "yes": False}),
    ("purchases.iap", "cmd_iap_push", {"platform": None, "create": True, "product": None}),
    ("purchases.subscriptions", "cmd_subs_push", {"platform": None, "create": True}),
    ("screenshots.upload", "cmd_screenshots_push", {"platform": None, "allow_developer_chrome": False}),
])
def test_every_push_dry_run_reads_but_never_writes(live: list[str], monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture, module: str, command: str,
                                                   options: dict[str, Any]) -> None:
    import importlib

    from snakelane.screenshots import upload

    monkeypatch.setattr(upload, "developer_chrome_check_available", lambda: False)
    run = getattr(importlib.import_module(f"snakelane.{module}"), command)
    run(SimpleNamespace(app=None, dry_run=True, **options))
    assert live and set(live) == {"GET"}, f"only reads reached App Store Connect: {live}"
    out = capsys.readouterr().out
    assert "[dry-run] would POST" in out or "change(s) to push" in out
    assert "✓" not in out, "no line claims a write happened"
