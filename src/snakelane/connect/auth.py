"""`snakelane auth setup --issuer-id <uuid> --key <AuthKey_<id>.p8 | - [--key-id <id>]>` and `auth check`.

`setup` is the only writer of the key's place (see connect/asc.py): it checks the key is EC, moves
rather than copies it, and never overwrites a different key.
Why: docs/design/foundations.md#auth-setup-moves-the-key-and-never-overwrites-one
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Annotated

import typer

from ..args import command_app, run
from . import asc


def write_private(path: Path, data: bytes) -> None:
    """Mode 0600 from creation, never briefly readable (and re-chmodded in case it already existed)."""
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(data)
    os.chmod(path, 0o600)


def private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


cli = command_app("Install and check the App Store Connect API key every snakelane command uses.")


@cli.command()
def setup(
    key: Annotated[str, typer.Option("--key", help="path to the downloaded AuthKey_<id>.p8, or - for stdin")],
    issuer_id: Annotated[str, typer.Option("--issuer-id", help="the Issuer ID shown above the team keys list")],
    key_id: Annotated[str | None, typer.Option(
        "--key-id", help="the key's id (default: from an AuthKey_<id>.p8 filename)")] = None,
) -> None:
    """Move a downloaded .p8 into place and record its key id and issuer id.

    Create the key at App Store Connect > Users and Access > Integrations > App Store Connect
    API (Team Keys, role App Manager), download the .p8, then run this. The .p8 is moved, not
    copied."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    source = None if key == "-" else Path(key).expanduser()
    if source and not source.is_file():
        raise SystemExit(f"no such file: {source}")
    pem = source.read_bytes() if source else sys.stdin.buffer.read()
    if not key_id:
        if not (match := source and re.search(r"AuthKey_([A-Z0-9]+)\.p8$", source.name)):
            raise SystemExit("pass --key-id: it is the AuthKey_<KEY_ID>.p8 part of Apple's filename, "
                             "and is shown beside the key in App Store Connect")
        key_id = match.group(1)
    key_id, issuer_id = key_id.strip(), issuer_id.strip()
    if not re.fullmatch(r"[A-Z0-9]+", key_id):
        raise SystemExit(f"{key_id!r} does not look like an API key id (e.g. 2X9R4HXF34)")
    try:
        private_key = load_pem_private_key(pem, password=None)
    except (ValueError, TypeError) as error:
        raise SystemExit(f"not a usable .p8 private key: {error}") from None
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise SystemExit("not an App Store Connect key: expected an EC (P-256) private key")

    destination = asc.Credentials(key_id=key_id, issuer_id=issuer_id).key_path
    private_dir(destination.parent)
    if not destination.exists():
        write_private(destination, pem)
        print(f"installed key at {destination}")
    elif destination.read_bytes().strip() == pem.strip():
        print(f"key already installed at {destination}")
    else:
        raise SystemExit(f"{destination} already holds a different key; refusing to overwrite "
                         "a credential. Remove it by hand if replacing it is intended.")
    if source is not None and source.resolve() != destination.resolve():
        source.unlink()
        print(f"removed {source} (the installed copy is now the only one)")
    os.chmod(destination, 0o600)

    config = asc.config_path()
    private_dir(config.parent)
    try:
        previous = json.loads(config.read_text()) if config.exists() else None
    except ValueError:
        previous = None
    write_private(config, (json.dumps({"key_id": key_id, "issuer_id": issuer_id}, indent=2) + "\n").encode())
    if previous and previous.get("key_id") not in (None, key_id):
        print(f"switched {config} from key {previous.get('key_id')} to {key_id}")
    else:
        print(f"wrote {config}")
    print("\nnext: `snakelane auth check` makes one read-only request to confirm Apple accepts it")


@cli.command()
def check(offline: Annotated[bool, typer.Option(
        "--offline", help="read the configuration only; no request")] = False) -> None:
    """Show the configured key and prove Apple accepts it."""
    credentials = asc.Credentials.load()
    key_path = credentials.key_path
    print(f"config:  {asc.config_path()}\nkey id:  {credentials.key_id}\n"
          f"issuer:  {credentials.issuer_id}\nkey:     {key_path}")
    problems = 0
    if (mode := stat.S_IMODE(key_path.stat().st_mode)) & 0o077:
        problems += 1
        print(f"warning: the key is mode {mode:o}; other users can read it. Fix: chmod 600 {key_path}")
    if repo := next((p for p in key_path.resolve().parents if (p / ".git").exists()), None):
        problems += 1
        print(f"warning: the key sits inside the git work tree at {repo}; make sure that repo "
              "ignores it and is never pushed anywhere public")
    if offline:
        print("\n--offline: configuration read; App Store Connect not contacted")
    else:
        try:
            payload = asc.Client(credentials, timeout=20).get("/v1/apps", {"limit": 1})
        except asc.TransientNetworkError as error:
            # Before ASCError (its base): calling this a rejection would get a working key revoked.
            raise SystemExit(f"\ncould not reach App Store Connect, so the key was not tested: {error}") from None
        except asc.ASCError as error:
            raise SystemExit(f"\nApp Store Connect rejected the key: {error}") from None
        total = payload.get("meta", {}).get("paging", {}).get("total")
        visible = f" ({total} app(s) visible to it)" if total is not None else ""
        print(f"\n✓ App Store Connect accepted the key{visible}")
    if problems:
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane auth")
