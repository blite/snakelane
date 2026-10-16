"""The audio tap `preview` records an app's sound with: audiotap.swift, built with swiftc on first use.

A simulated app is a Mac process, and a Core Audio process tap (macOS 14.2+) records exactly its
output. There is no Python binding for the tap API, so the recorder is a small Swift program, built
into ~/Library/Caches/snakelane/ keyed by its source's hash: an edit to the source rebuilds it.
Why: docs/design/screenshots.md#a-previews-sound-is-tapped-from-the-apps-process
"""

from __future__ import annotations

import hashlib
import json
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

SOURCE = Path(__file__).with_name("audiotap.swift")
CACHE = Path.home() / "Library" / "Caches" / "snakelane"


def binary() -> Path:
    """The built tap, building it when the source has changed (once, about ten seconds)."""
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()[:12]
    built = CACHE / f"audiotap-{digest}"
    if not built.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"building the audio tap ({SOURCE.name} → {built})")
        partial = built.with_suffix(".partial")
        try:
            subprocess.run(["xcrun", "swiftc", "-O", "-swift-version", "5", str(SOURCE), "-o", str(partial)],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            raise SystemExit(f"could not build the audio tap:\n{error.stderr.strip()}\n"
                             'Record without sound with "previews": {"audio": {"capture": false}}.')
        partial.rename(built)
    return built


@dataclass
class Capture:
    path: Path
    first_buffer: float | None  # epoch seconds of the file's frame 0; None: the app played nothing
    frames: int
    rate: float
    peak: float


class Tap:
    """`audiotap` running against one pid until `stop()`."""

    def __init__(self, pid: int, path: Path) -> None:
        self.path = path
        path.unlink(missing_ok=True)
        self.process = subprocess.Popen([str(binary()), str(pid), str(path)], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True)
        assert self.process.stdout is not None
        if not (line := self.process.stdout.readline()).startswith('{"started"'):
            self.process.wait(timeout=5)
            raise SystemExit(f"the audio tap did not start: {self.process.stderr.read().strip() or line.strip()}")

    def stop(self) -> Capture:
        self.process.send_signal(signal.SIGINT)
        out, err = self.process.communicate(timeout=15)
        if self.process.returncode:
            raise SystemExit(f"the audio tap failed: {err.strip()}")
        result = json.loads(out.strip().splitlines()[-1])
        return Capture(self.path, result["first_buffer"], result["frames"], result["rate"], result["peak"])

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait()
