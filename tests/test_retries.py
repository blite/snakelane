"""The App Store Connect client's retry policy, against a local HTTP server."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from urllib3.util.retry import Retry

from snakelane.connect import asc


class Server:
    """Answers each request with the next status in `script` (then 200), counting hits."""

    def __init__(self, script: list[int]) -> None:
        self.script, self.hits = list(script), []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                outer.hits.append(self.command)
                status = outer.script.pop(0) if outer.script else 200
                body = json.dumps({"data": {"ok": True}} if status == 200 else
                                  {"errors": [{"title": "Unavailable", "detail": "try later", "code": "X"}]})
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body.encode())

            do_GET = do_POST = _answer

            def log_message(self, *args) -> None:
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1/x"


class Unsigned(asc.Client):
    def __init__(self) -> None:
        super().__init__(credentials=asc.Credentials("K", "I"), timeout=5)

    def _headers(self) -> dict[str, str]:
        return {}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Retry, "sleep", lambda self, response=None: None)


def test_a_get_rides_out_apples_5xx() -> None:
    server = Server([503, 500])
    assert Unsigned()._get(server.url, None) == {"data": {"ok": True}}
    assert server.hits == ["GET", "GET", "GET"]


def test_a_get_that_keeps_failing_is_a_network_error_with_apples_text() -> None:
    server = Server([503] * 10)
    with pytest.raises(asc.TransientNetworkError, match="try later") as raised:
        Unsigned()._get(server.url, None)
    assert raised.value.status == 503 and len(server.hits) == 4  # the first try and 3 retries


def test_a_write_is_never_retried_once_sent() -> None:
    server = Server([503])
    with pytest.raises(asc.ASCError, match="HTTP 503"):
        Unsigned()._write("post", server.url, json={})
    assert server.hits == ["POST"]
