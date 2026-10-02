"""`snakelane auth` and the credential files every command reads. Offline: HOME points at a
temporary directory and no test reaches App Store Connect."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from snakelane.connect import asc, auth

KEY_ID = "ABC123DEF4"
ISSUER = "69a6de7e-0000-47e3-e053-5b8c7c11a4d1"


@pytest.fixture(autouse=True)
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def p8() -> bytes:
    return ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def download(home: Path, data: bytes | None = None, name: str = f"AuthKey_{KEY_ID}.p8") -> Path:
    path = home / "Downloads" / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(p8() if data is None else data)
    return path


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_not_set_up() -> None:
    assert not asc.Credentials.available()
    with pytest.raises(asc.ASCError, match="snakelane auth setup"):
        asc.Credentials.load()


def test_setup_moves_key_and_writes_config(home: Path) -> None:
    source = download(home)
    pem = source.read_bytes()
    auth.main(["setup", "--key", str(source), "--issuer-id", ISSUER])

    credentials = asc.Credentials.load()
    assert (credentials.key_id, credentials.issuer_id) == (KEY_ID, ISSUER)
    assert credentials.key_path == home / ".appstoreconnect/private_keys" / f"AuthKey_{KEY_ID}.p8"
    assert credentials.key_path.read_bytes() == pem
    assert not source.exists(), "the downloaded copy must be moved, not left behind"
    assert mode(credentials.key_path) == 0o600
    assert mode(credentials.key_path.parent) == 0o700
    assert mode(asc.config_path()) == 0o600
    assert json.loads(asc.config_path().read_text()) == {"key_id": KEY_ID, "issuer_id": ISSUER}


def test_setup_from_stdin_needs_key_id(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import sys

    pem = p8()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(pem)))
    with pytest.raises(SystemExit, match="--key-id"):
        auth.main(["setup", "--key", "-", "--issuer-id", ISSUER])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(pem)))
    auth.main(["setup", "--key", "-", "--issuer-id", ISSUER, "--key-id", KEY_ID])
    assert asc.Credentials.load().key_path.read_bytes() == pem


def test_setup_rejects_a_file_that_is_not_a_key(home: Path) -> None:
    source = download(home, b"-----BEGIN PRIVATE KEY-----\ntruncated\n")
    with pytest.raises(SystemExit, match="not a usable"):
        auth.main(["setup", "--key", str(source), "--issuer-id", ISSUER])
    assert source.exists(), "nothing moves when validation fails"
    assert not asc.Credentials.available()


def test_setup_never_overwrites_a_different_key(home: Path) -> None:
    auth.main(["setup", "--key", str(download(home)), "--issuer-id", ISSUER])
    installed = asc.Credentials.load().key_path.read_bytes()
    second = download(home)
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        auth.main(["setup", "--key", str(second), "--issuer-id", ISSUER])
    assert asc.Credentials.load().key_path.read_bytes() == installed
    assert second.exists()


def test_missing_key_file_is_not_available(home: Path) -> None:
    auth.main(["setup", "--key", str(download(home)), "--issuer-id", ISSUER])
    asc.Credentials.load().key_path.unlink()
    assert not asc.Credentials.available()
    with pytest.raises(asc.ASCError, match="missing"):
        asc.Credentials.load()


def test_check_offline_flags_a_readable_key(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    auth.main(["setup", "--key", str(download(home)), "--issuer-id", ISSUER])
    auth.main(["check", "--offline"])
    assert KEY_ID in capsys.readouterr().out

    asc.Credentials.load().key_path.chmod(0o644)
    with pytest.raises(SystemExit):
        auth.main(["check", "--offline"])
    assert "other users can read it" in capsys.readouterr().out


def test_client_signs_with_the_installed_key(home: Path) -> None:
    import jwt

    auth.main(["setup", "--key", str(download(home)), "--issuer-id", ISSUER])
    token = asc.Client().token()
    assert jwt.get_unverified_header(token)["kid"] == KEY_ID
    assert jwt.decode(token, options={"verify_signature": False})["iss"] == ISSUER


@pytest.mark.parametrize("content", ["[]", '"ABC123"', "42", "null"])
def test_config_that_is_not_an_object_is_unavailable_not_a_crash(content: str) -> None:
    path = asc.config_path()
    path.parent.mkdir(parents=True)
    path.write_text(content)
    assert not asc.Credentials.available()
    with pytest.raises(asc.ASCError, match="not a JSON object"):
        asc.Credentials.load()


def test_check_reports_a_network_failure_as_one(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth.main(["setup", "--key", str(download(home)), "--issuer-id", ISSUER])

    def unreachable(self: asc.Client, path: str, params: object = None) -> dict:
        raise asc.TransientNetworkError("GET /v1/apps: read timed out")

    monkeypatch.setattr(asc.Client, "get", unreachable)
    with pytest.raises(SystemExit, match="could not reach App Store Connect") as raised:
        auth.main(["check"])
    assert "rejected" not in str(raised.value)
