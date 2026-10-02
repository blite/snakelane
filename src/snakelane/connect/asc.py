"""App Store Connect REST API core: token signing and a thin JSON:API client.

One team API key (App Manager), written by `snakelane auth setup`, serves every app: the .p8 at
~/.appstoreconnect/private_keys/AuthKey_<key_id>.p8 (0600) and {"key_id", "issuer_id"} in
~/.config/snakelane/credentials.json. No env vars, XDG_CONFIG_HOME or Keychain.
Why: docs/design/foundations.md#credentials-are-files-at-fixed-paths
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..terminal import truncate

BASE_URL = "https://api.appstoreconnect.apple.com"
PLANNED = "planned-"  # the id a dry run's create hands back; nothing exists under it


def planned(resource_id: str) -> bool:
    """Whether `resource_id` came from a dry run's create, so there is nothing to read under it."""
    return str(resource_id).startswith(PLANNED)


class ASCError(RuntimeError):
    """An API failure with Apple's detail text; `status` is None when Apple never answered."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TransientNetworkError(ASCError):
    """Apple never answered; after a write the live state is unknown, so callers print what is done."""


def config_path() -> Path:
    return Path.home() / ".config" / "snakelane" / "credentials.json"


@dataclass
class Credentials:
    key_id: str
    issuer_id: str

    @property
    def key_path(self) -> Path:
        return Path.home() / ".appstoreconnect" / "private_keys" / f"AuthKey_{self.key_id}.p8"

    @classmethod
    def load(cls) -> Credentials:
        """The configured key. Every failure is an ASCError: `available()` and the Archive post-action rely on it."""
        path = config_path()
        redo = "re-run `snakelane auth setup`"
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            raise ASCError("no App Store Connect API key set up — run `snakelane auth setup` "
                           "(see `snakelane auth --help`)") from None
        except (OSError, ValueError) as error:
            raise ASCError(f"cannot read {path}: {error} — {redo}") from None
        if not isinstance(data, dict):
            raise ASCError(f"{path} is not a JSON object — {redo}")
        key_id, issuer_id = (str(data.get(k) or "").strip() for k in ("key_id", "issuer_id"))
        if not key_id or not issuer_id:
            raise ASCError(f"{path} needs both \"key_id\" and \"issuer_id\" — {redo}")
        credentials = cls(key_id=key_id, issuer_id=issuer_id)
        if not credentials.key_path.is_file():
            raise ASCError(f"{path} names key {key_id}, but {credentials.key_path} is missing — {redo} with the .p8")
        return credentials

    @staticmethod
    def available() -> bool:
        try:
            Credentials.load()
            return True
        except ASCError:
            return False


class _AnnouncedRetry(Retry):
    """Prints a line per retry so a slow run doesn't look hung."""

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        retry = super().increment(method, url, response, error, _pool, _stacktrace)
        reason = f"HTTP {response.status}" if response is not None and response.status else type(error).__name__
        print(f"  … {method} {reason}; retrying in {retry.get_backoff_time():.0f}s "
              f"({len(retry.history)}/{retry.total + len(retry.history) if retry.total is not None else '?'})")
        return retry


class Client:
    """Minimal JSON:API client; tokens last 15 minutes and are re-minted two minutes early.

    Only GET/HEAD are retried once sent (a timed-out write may have landed); a request that never
    connected always is. Why: docs/design/foundations.md#only-gets-are-retried

    `dry_run=True` reads App Store Connect as usual but never writes: each POST, PATCH and DELETE is
    printed instead, and a create answers with a `planned-N` id whose reads come back empty, so the
    rest of the plan runs (and prints) as it would after a real create. The dry run lives here, not
    at each call site, so a new write can't forget it.
    """

    RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

    def __init__(self, credentials: Credentials | None = None, timeout: float = 60, retries: int = 3,
                 dry_run: bool = False):
        self.credentials = credentials or Credentials.load()
        self.dry_run, self._planned = dry_run, 0
        self.timeout = timeout  # per phase; bump's archive hook passes less so a dead network costs seconds
        self.retries = retries
        self._token: str | None = None
        self._token_expiry = 0.0
        adapter = HTTPAdapter(max_retries=_AnnouncedRetry(
            total=retries, allowed_methods=frozenset({"GET", "HEAD"}), status_forcelist=self.RETRYABLE_STATUS,
            backoff_factor=1, backoff_jitter=0.5, respect_retry_after_header=True,
            raise_on_status=False))  # hand back Apple's last answer, so its error text survives
        self.session = requests.Session()
        for scheme in ("https://", "http://"):  # tests talk to a local server
            self.session.mount(scheme, adapter)

    def _get(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        try:
            response = self.session.get(url, headers=self._headers(), params=params, timeout=self.timeout)
        except (requests.Timeout, requests.ConnectionError) as error:
            raise TransientNetworkError(f"GET {url} failed after {self.retries} retries: {error}") from error
        if response.status_code in self.RETRYABLE_STATUS:  # "Apple is unwell", not "Apple said no"
            error = self._error(response)
            raise TransientNetworkError(f"{error} (after {self.retries} retries)", status=error.status) from None
        return self._checked(response)

    def _write(self, verb: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if self.dry_run:
            return self._plan(verb, url.removeprefix(BASE_URL), kwargs.get("json") or {})
        try:
            response = self.session.request(verb.upper(), url, headers=self._headers(), timeout=self.timeout, **kwargs)
        except (requests.Timeout, requests.ConnectionError) as error:
            raise TransientNetworkError(
                f"{verb.upper()} {url} did not complete: {error}\nThis is NOT retried automatically: the write "
                "may have landed before the response was lost, and repeating it could create a duplicate (for an "
                "in-app purchase, a second permanent product id). Check the live state before re-running.") from error
        return self._checked(response)

    def _plan(self, verb: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """A dry run's write: printed, and a create answered as Apple would, with a planned id."""
        data = body.get("data") or {}
        shown = [f"{k}={truncate(v) if isinstance(v, str) else v!r}" for k, v in (data.get("attributes") or {}).items()]
        shown += [f"{k}→{r['data']['id']}" if isinstance(r.get("data"), dict) else k
                  for k, r in (data.get("relationships") or {}).items()]
        print(f"  [dry-run] would {verb.upper()} {path}" + (f"  {', '.join(shown)}" if shown else ""))
        if verb != "post":
            return {}
        self._planned += 1
        return {"data": {**data, "id": f"{PLANNED}{self._planned}"}}

    def report(self, message: str) -> None:
        """A write's result line; a dry run already printed what it would have sent."""
        if not self.dry_run:
            print(message)

    def token(self) -> str:
        if self._token is None or time.time() > self._token_expiry - 120:
            issued = int(time.time())
            self._token_expiry = issued + 15 * 60
            self._token = jwt.encode(
                {"iss": self.credentials.issuer_id, "iat": issued, "exp": self._token_expiry,
                 "aud": "appstoreconnect-v1"},
                self.credentials.key_path.read_text(), algorithm="ES256",
                headers={"kid": self.credentials.key_id, "typ": "JWT"})
        return self._token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {} if PLANNED in path else self._get(f"{BASE_URL}{path}", params)

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Every `data` element across pagination."""
        url: str | None = None if PLANNED in path else f"{BASE_URL}{path}"
        while url:
            payload = self._get(url, params)
            yield from payload.get("data", [])
            url, params = payload.get("links", {}).get("next"), {}  # `next` already carries the query

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._write("post", f"{BASE_URL}{path}", json=body)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._write("patch", f"{BASE_URL}{path}", json=body)

    def delete(self, path: str) -> None:
        self._write("delete", f"{BASE_URL}{path}")  # not retried: a DELETE that landed answers 404 next time

    def upload_part(self, operation: dict[str, Any], data: bytes) -> None:
        """One byte range of an asset to the presigned URL a reservation handed back: another host, no token."""
        if self.dry_run:
            return print(f"  [dry-run] would {operation['method']} {operation['length']} bytes to Apple's upload host")
        headers = {h["name"]: h["value"] for h in operation.get("requestHeaders", [])}
        requests.request(operation["method"], operation["url"], headers=headers, timeout=120,
                         data=data[operation["offset"]: operation["offset"] + operation["length"]]).raise_for_status()

    @staticmethod
    def _error(response: requests.Response) -> ASCError:
        try:
            errors = response.json().get("errors", [])
            details = "; ".join(f"{e.get('title', '?')}: {e.get('detail', '?')}" for e in errors)
        except Exception:
            details = response.text[:500]
        return ASCError(f"{response.request.method} {response.request.path_url} → "
                        f"HTTP {response.status_code}: {details}", status=response.status_code)

    @classmethod
    def _checked(cls, response: requests.Response) -> dict[str, Any]:
        if not response.ok:
            raise cls._error(response)
        return response.json() if response.content else {}


# MAC_OS, not MACOS: a bare .upper() of the folder name matches nothing.
PLATFORM_ENUM = {"ios": "IOS", "macos": "MAC_OS", "tvos": "TV_OS", "visionos": "VISION_OS"}


def platform_enum(platform: str) -> str:
    if platform not in PLATFORM_ENUM:
        raise ASCError(f"unknown platform {platform!r} — expected one of {sorted(PLATFORM_ENUM)}")
    return PLATFORM_ENUM[platform]


def attributes(resource: dict[str, Any]) -> dict[str, Any]:
    return resource.get("attributes", {})


def resource_body(type_: str, attributes: dict[str, Any], id_: str | None = None,
                  relationships: dict[str, Any] | None = None) -> dict[str, Any]:
    optional = {"id": id_, "relationships": relationships}
    return {"data": {"type": type_, "attributes": attributes, **{k: v for k, v in optional.items() if v is not None}}}


def relationship(type_: str, id_: str) -> dict[str, Any]:
    return {"data": {"type": type_, "id": id_}}
