"""Running Xcode's tools: the echoed command, and the simulator clones a killed test run leaves behind."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

XCTEST_DEVICES = Path.home() / "Library" / "Developer" / "XCTestDevices"


def show(cmd: list[str], env: dict[str, str] | None = None) -> str:
    """`cmd` as a shell line, with `env`'s additions in front: what `run` prints, pasteable."""
    return "".join(f"{k}={shlex.quote(v)} " for k, v in (env or {}).items()) + shlex.join(map(str, cmd))


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Echo, then run; `env` is added to this process's environment."""
    print(f"$ {show(cmd, env)}")
    subprocess.run(cmd, check=True, env={**os.environ, **env} if env else None)


def sweep_test_devices() -> None:
    """Delete the simulator clones `xcodebuild test` leaks when it is killed or crashes."""
    for entry in XCTEST_DEVICES.glob("*"):
        shutil.rmtree(entry, ignore_errors=True)
