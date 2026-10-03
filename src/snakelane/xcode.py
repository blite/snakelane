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


def run_logged(cmd: list[str], env: dict[str, str] | None = None) -> str:
    """`run`, but also returning the combined output, for a caller that explains known failures.

    Streams as it goes, so a long export still shows progress. A non-zero exit raises
    `CalledProcessError` with the output attached.
    """
    print(f"$ {show(cmd, env)}")
    lines: list[str] = []
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          env={**os.environ, **env} if env else None) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            lines.append(line)
    output = "".join(lines)
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, cmd, output=output)
    return output


def sweep_test_devices() -> None:
    """Delete the simulator clones `xcodebuild test` leaks when it is killed or crashes."""
    for entry in XCTEST_DEVICES.glob("*"):
        shutil.rmtree(entry, ignore_errors=True)
