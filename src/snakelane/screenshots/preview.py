"""`snakelane preview`: record the app's App Preview from its video UI test on each simulator, with
the app's own sound, and encode it into the deck as `ap-01.m4v`, which `store previews push` uploads.
Design notes: docs/design/screenshots.md#recording-a-preview

snakelane.yml "previews" (all optional; full reference in the skill's references/config.md):
    launch        launch arguments: record the app launched straight into its video fixture, with no
                  UI test attached (smoother: see below); the app marks its own moments
    test          -only-testing id of the video test, when there is no "launch";
                  default <scheme>UITests/<scheme>UITestsVideoPreviewUITests
    scheme, test_plan, env, devices    default the "screenshots" ones
    locales       ASC locales to record; default the first screenshot locale (a locale without
                  its own preview shows the primary's on the store)
    fit           "crop" (default: fill the frame, cropping the sliver the aspect differs by) | "pad"
    max_seconds   longest clip kept; default 29 (Apple's ceiling is 30)
    audio         {"capture": true, "bed": path, "bed_gain": -14, "loudness": -16}
                  capture: tap the app's process for its sound (macOS 14.2+); bed: a music file
                  looped under it at bed_gain dB; loudness: the mix's integrated LUFS
    overlay       {"style": "band", "captions": …, "depth": 0.085, "framing": {…}}
                  band: the screenshots' caption band across the top of the full-screen clip,
                  drawn by `snakelane frame`'s code from "screenshots.framing" with "framing" on top.
                  captions: one string, a list of {"at", "text"}, or either keyed by locale; "at" is
                  seconds into the clip or the name of a moment the test marked

The app (or its test) and snakelane talk through files on the Mac's disk, which the simulator shares:
    /tmp/<slug>-preview-events.jsonl   appended {"event": name, "t": epoch seconds}: "start" / "end"
                                       bound the clip; any other name is a moment captions can follow.
                                       A test also marks "ready" once the scene is up, then waits for
    /tmp/<slug>-preview-rolling        which snakelane writes once the recorder has its first frame.
With "launch", snakelane starts recording first, then launches the app, which marks "start" when
its scene is up and "end" when the clip is over: a UI test attached to the app costs it frames.
Why: docs/design/screenshots.md#the-test-and-the-recorder-shake-hands and
docs/design/screenshots.md#a-preview-is-recorded-without-a-ui-test-attached
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import typer

from ..args import AppOption, command_app
from ..args import run as run_cli
from ..project import App, DeckTree, resolve_app
from ..xcode import run, show, sweep_test_devices
from . import media
from .shoot import (
    DeviceSpec,
    Simulator,
    load_config,
    locale_file,
    pin_status_bar,
    resolve_simulator,
    xcodebuild_test,
)

KNOWN_KEYS = {"launch", "test", "scheme", "test_plan", "env", "devices", "locales", "fit", "max_seconds", "audio",
              "overlay", "_comment"}
AUDIO_KEYS = {"capture", "bed", "bed_gain", "loudness", "_comment"}
OVERLAY_KEYS = {"style", "captions", "depth", "framing", "_comment"}
CLIP = "ap-01.m4v"
READY_TIMEOUT = 240     # build-for-testing has already run: this is launch and scene set-up
ROLLING_TIMEOUT = 10    # simctl's first frame
SLACK = 60              # past max_seconds before a test that never says "end" is cut off


@dataclass
class PreviewConfig:  # snakelane.yml's "previews", defaults applied
    scheme: str
    test: str
    launch: list[str] | None
    test_plan: str | None
    env: dict[str, str]
    devices: list[DeviceSpec]
    locales: dict[str, str | None]
    fit: str
    max_seconds: float
    capture: bool
    bed: Path | None
    bed_gain: float
    loudness: float
    overlay: str | None
    captions: Any
    depth: float
    framing: dict[str, Any]


def load_preview_config(app: App) -> PreviewConfig:
    raw = app.config.get("previews") or {}
    if not isinstance(raw, dict):
        raise SystemExit(f'"previews" in {app.config_path} must be an object')
    for where, entry, known in (("previews", raw, KNOWN_KEYS), ("previews.audio", raw.get("audio") or {}, AUDIO_KEYS),
                                ("previews.overlay", raw.get("overlay") or {}, OVERLAY_KEYS)):
        if unknown := set(entry) - known:
            raise SystemExit(f'unknown key(s) in snakelane.yml "{where}": {", ".join(sorted(unknown))}')
    shots = load_config(app)
    locales = shots.locales
    if "locales" in raw:
        if unknown := [l for l in raw["locales"] if l not in shots.locales]:
            raise SystemExit(f"previews.locales {unknown} are not in screenshots.locales ({', '.join(shots.locales)})")
        locales = {l: shots.locales[l] for l in raw["locales"]}
    else:
        first = next(iter(shots.locales))
        locales = {first: shots.locales[first]}
    if (fit := raw.get("fit", "crop")) not in ("crop", "pad"):
        raise SystemExit(f'previews.fit must be "crop" or "pad", not {fit!r}')
    audio, overlay = raw.get("audio") or {}, raw.get("overlay") or {}
    if (style := overlay.get("style")) not in (None, "none", "band"):
        raise SystemExit(f'previews.overlay.style must be "band" or "none", not {style!r}')
    if style == "band" and not overlay.get("captions"):
        raise SystemExit("previews.overlay.style is band, and previews.overlay.captions is empty")
    launch = raw.get("launch")
    if launch is not None:
        if not isinstance(launch, list) or not all(isinstance(a, str) for a in launch):
            raise SystemExit('previews.launch is a list of launch arguments, e.g. ["--ui-screenshot=video"]')
        if "test" in raw:
            raise SystemExit("previews has both launch and test: launch records the app with no test")
    bed = None
    if audio.get("bed"):
        if not (bed := app.root / audio["bed"]).is_file():
            raise SystemExit(f"previews.audio.bed: no file {bed}")
    return PreviewConfig(
        scheme=raw.get("scheme") or shots.scheme,
        test=raw.get("test") or f"{app.scheme}UITests/{app.scheme}UITestsVideoPreviewUITests",
        launch=launch,
        test_plan=raw.get("test_plan", shots.test_plan),
        env={**shots.env, **{k if k.startswith("TEST_RUNNER_") else f"TEST_RUNNER_{k}": str(v)
                             for k, v in (raw.get("env") or {}).items()}},
        devices=[DeviceSpec.parse(d) for d in raw["devices"]] if "devices" in raw else shots.devices,
        locales=locales,
        fit=fit,
        max_seconds=float(raw.get("max_seconds", 29)),
        capture=bool(audio.get("capture", True)),
        bed=bed,
        bed_gain=float(audio.get("bed_gain", -14)),
        loudness=float(audio.get("loudness", -16)),
        overlay=None if style in (None, "none") else style,
        captions=overlay.get("captions"),
        depth=float(overlay.get("depth", 0.085)),
        framing=overlay.get("framing") or {},
    )


def events_file(app: App) -> Path:
    return Path("/tmp") / f"{app.slug}-preview-events.jsonl"


def rolling_file(app: App) -> Path:
    return Path("/tmp") / f"{app.slug}-preview-rolling"


# --- captions -------------------------------------------------------------------------------------

def captions_for(config: PreviewConfig, locale: str, primary: str) -> list[dict[str, Any]]:
    """The overlay's captions for `locale` as [{"at", "text"}], the primary locale's when it has none."""
    value = config.captions
    if isinstance(value, dict):
        value = value.get(locale, value.get(primary))
        if value is None:
            raise SystemExit(f"previews.overlay.captions has neither {locale} nor {primary}")
    entries = [{"at": 0, "text": value}] if isinstance(value, str) else list(value or [])
    for entry in entries:
        if not isinstance(entry, dict) or "text" not in entry:
            raise SystemExit(f'previews.overlay.captions entries are {{"at", "text"}}, not {entry!r}')
    return entries


def caption_times(entries: list[dict[str, Any]], moments: dict[str, float], length: float) -> list[tuple[float, float, str]]:
    """(from, to, text) in clip seconds: each caption holds until the next one."""
    timed = []
    for entry in entries:
        at = entry.get("at", 0)
        if isinstance(at, str):
            if at not in moments:
                raise SystemExit(f"caption {entry['text']!r} is at moment {at!r}, which the test never marked "
                                 f"(it marked: {', '.join(sorted(moments)) or 'nothing'})")
            at = moments[at]
        timed.append((max(0.0, float(at)), str(entry["text"])))
    timed.sort()
    return [(at, timed[i + 1][0] if i + 1 < len(timed) else length, text) for i, (at, text) in enumerate(timed)]


# --- the band -------------------------------------------------------------------------------------

def band_layer(app: App, config: PreviewConfig, text: str, capture: tuple[int, int], target: tuple[int, int],
               path: Path) -> tuple[Path, tuple[int, int]]:
    """The caption band as a transparent PNG and where it goes, drawn by the screenshot framing.

    compose() runs twice, over a black and a white stand-in capture; where the canvases differ is
    where the capture shows through, which gives the band's exact alpha without a second renderer.
    Why: docs/design/screenshots.md#the-band-is-the-screenshots-band"""
    from PIL import Image, ImageChops

    from .frame import framing
    from .framing.compose import compose
    from .framing.style import check_framing, style_for

    base = {k: v for k, v in framing(app).items() if k in ("theme", "caption")}
    cfg = {**base, **config.framing}
    caption = {"shape": "band", **(base.get("caption") or {}), **(config.framing.get("caption") or {})}
    caption.update(position="top", depth=config.depth)
    caption.pop("size", None)
    cfg.update(layout="full-bleed", fit="crop", caption=caption)
    check_framing(cfg)
    style = style_for(cfg, {}, None)
    canvases = []
    for shade in (0, 255):
        stand_in = path.with_name(f"stand-in-{shade}.png")
        Image.new("RGB", capture, (shade,) * 3).save(stand_in)
        canvases.append(compose(app, style, stand_in, text, target)[0])
    alpha = ImageChops.difference(canvases[1], canvases[0]).convert("L").point(lambda v: 255 - v)
    layer = canvases[0].convert("RGBA")
    layer.putalpha(alpha)
    if (box := layer.getbbox()) is None:
        raise SystemExit("the band overlay came out empty")
    layer.crop(box).save(path)
    return path, (box[0], box[1])


# --- the plan -------------------------------------------------------------------------------------

@dataclass
class Pass:  # one recording: one simulator, one locale
    sim: Simulator
    locale: str
    language: str | None
    tree: DeckTree
    masters: Path              # .snakelane/<slug>/previews/<deck>/<locale>/
    build: list[str]
    test: list[str]

    @property
    def clip(self) -> Path:
        return self.tree.framed(self.locale) / CLIP

    def master(self, suffix: str) -> Path:
        return self.masters / f"master{suffix}"


@dataclass
class Plan:
    app: App
    config: PreviewConfig
    passes: list[Pass] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def xcodebuild_build(app: App, scheme: str, destination: str, settings: bool = False) -> list[str]:
    return ["xcodebuild", "-project", str(app.project), "-scheme", scheme, "-destination", destination,
            *(["-showBuildSettings", "-json"] if settings else ["build"])]


def built_app(app: App, scheme: str, destination: str) -> Path:
    """The .app `xcodebuild_build` wrote for this simulator: the scheme's target with the config's bundle id."""
    listing = json.loads(subprocess.run(xcodebuild_build(app, scheme, destination, settings=True),
                                        check=True, capture_output=True, text=True).stdout)
    for target in listing:
        settings = target.get("buildSettings", {})
        if settings.get("WRAPPER_EXTENSION") == "app" and settings.get("PRODUCT_BUNDLE_IDENTIFIER") == app.config["bundle_id"]:
            return Path(settings["TARGET_BUILD_DIR"]) / settings["WRAPPER_NAME"]
    raise SystemExit(f"scheme {scheme} builds no app with bundle id {app.config['bundle_id']}")


def make_plan(app: App, config: PreviewConfig, args: SimpleNamespace) -> Plan:
    plan = Plan(app, config)
    locales = config.locales
    if args.locales:
        requested = [l.strip() for l in args.locales.split(",") if l.strip()]
        if unknown := [l for l in requested if l not in load_config(app).locales]:
            raise SystemExit(f"unknown locale(s): {', '.join(unknown)}")
        locales = {l: load_config(app).locales[l] for l in requested}
    specs = [DeviceSpec.parse(args.device)] if args.device else config.devices
    for spec in specs:
        sim = resolve_simulator(spec, strict=not (args.dry_run or args.encode_only))
        if sim.problem:
            plan.problems.append(f"{spec.label()}: {sim.problem}")
        destination = f"platform=iOS Simulator,id={sim.udid or '<unresolved>'}"
        if config.launch is not None:
            build, test = xcodebuild_build(app, config.scheme, destination), []
        else:
            common = {"test": config.test, "test_plan": config.test_plan, "xcresult": None, "mac": False,
                      "retry": False}
            build = xcodebuild_test(app, config.scheme, destination, action="build-for-testing", **common)
            test = xcodebuild_test(app, config.scheme, destination, action="test-without-building", **common)
        tree = DeckTree(app, "ios", sim.deck)
        for locale, language in locales.items():
            masters = app.work_dir / "previews" / sim.deck / locale
            plan.passes.append(Pass(sim, locale, language, tree, masters, build, test))
    return plan


def print_plan(plan: Plan, encode_only: bool) -> None:
    app, config = plan.app, plan.config
    print(f"app        {app.name}  (slug {app.slug})")
    if config.launch is not None:
        print(f"launch     {app.config['bundle_id']} {' '.join(config.launch)}  (no UI test attached)")
    else:
        print(f"test       {config.test}" + (f"  plan {config.test_plan}" if config.test_plan else ""))
    print(f"handshake  {events_file(app)}, {rolling_file(app)}")
    audio = ["the app's sound (process tap)" if config.capture else "no capture"]
    if config.bed:
        audio.append(f"bed {config.bed.relative_to(app.root)} at {config.bed_gain:+g} dB")
    print(f"audio      {', '.join(audio)}; {config.loudness:g} LUFS")
    print(f"overlay    {config.overlay or 'none'}" + (f" (depth {config.depth:g})" if config.overlay else ""))
    print(f"clip       ≤{config.max_seconds:g}s, fit {config.fit}")
    for p in plan.passes:
        where = f"{p.sim.udid} ({p.sim.runtime})" if p.sim.udid else f"UNRESOLVED — {p.sim.problem}"
        print(f"[{p.sim.name} {p.locale}] {where}")
        print(f"  masters  {p.masters.relative_to(app.root)}/")
        print(f"  clip     {p.clip.relative_to(app.root)}")
        if not encode_only:
            print(f"  $ {show(p.build)}")
            if p.test:
                print(f"  $ {show(p.test, config.env)}")
        if config.overlay:
            for entry in captions_for(config, p.locale, app.primary_locale):
                print(f"  caption  at {entry.get('at', 0)}: {entry['text']}")
    if plan.problems:
        print("problems" + "".join(f"\n  ! {problem}" for problem in plan.problems))


# --- recording ------------------------------------------------------------------------------------

def read_events(path: Path, since: float) -> dict[str, float]:
    """The test's events written after `since`, first of each name: a stale file can't pass for this run."""
    found: dict[str, float] = {}
    if not path.exists():
        return found
    for line in path.read_text().splitlines():
        try:
            event = json.loads(line)
            name, t = str(event["event"]), float(event["t"])
        except (ValueError, KeyError, TypeError):
            continue
        if t >= since:
            found.setdefault(name, t)
    return found


def app_pid(udid: str, bundle_id: str) -> int:
    """The app's pid, from launchd inside the simulator (`UIKitApplication:<bundle id>[…]`)."""
    listing = subprocess.run(["xcrun", "simctl", "spawn", udid, "launchctl", "list"], check=True,
                             capture_output=True, text=True).stdout
    for line in listing.splitlines():  # PID  Status  Label
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[2].startswith(f"UIKitApplication:{bundle_id}[") and parts[0].isdigit():
            return int(parts[0])
    raise SystemExit(f"{bundle_id} is not running on the simulator; the test said it was ready")


def wait_for(condition, timeout: float, test: subprocess.Popen, log: Path, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if test.poll() is not None:
            raise SystemExit(f"the test exited ({test.returncode}) before {what} — see {log}")
        if time.monotonic() > deadline:
            raise SystemExit(f"no {what} after {timeout:.0f}s — see {log}")
        time.sleep(0.1)


def finish(test: subprocess.Popen, log: Path, timeout: float = 120) -> int:
    """The test's exit code. xcodebuild can hang after a passing test (Spades, 2026-10-16: more than
    two minutes after XCTest's "Test Suite 'Selected tests' passed"), so a log that already says the
    tests passed is taken as a pass and the stuck xcodebuild is stopped.
    Why: docs/design/screenshots.md#a-passed-test-is-a-pass-even-if-xcodebuild-hangs"""
    deadline = time.monotonic() + timeout
    while (code := test.poll()) is None:
        if time.monotonic() > deadline:
            test.kill()
            test.wait()
            if any(line in log.read_text(errors="replace") for line in TEST_PASSED):
                print("  note: xcodebuild hung after the test passed; stopped it")
                return 0
            raise SystemExit(f"the test did not finish within {timeout:.0f}s of its end — see {log}")
        time.sleep(0.5)
    return code


TEST_PASSED = ("** TEST EXECUTE SUCCEEDED **", "Test Suite 'Selected tests' passed")


class Recorder:
    """`simctl io recordVideo`, run as simctl itself: SIGINT to a wrapper never reaches it, and SIGINT is
    what writes the movie's index. Why: docs/design/screenshots.md#the-recorder-is-simctl-itself"""

    def __init__(self, udid: str, path: Path) -> None:
        simctl = subprocess.run(["xcrun", "--find", "simctl"], check=True, capture_output=True, text=True).stdout.strip()
        path.unlink(missing_ok=True)
        self.log = path.with_suffix(".recorder.log")
        self.process = subprocess.Popen([simctl, "io", udid, "recordVideo", "--codec=h264", "--force", str(path)],
                                        stdout=subprocess.DEVNULL, stderr=self.log.open("w"))
        self.started = 0.0

    def wait_started(self) -> None:
        """simctl says so once it has its first frame; the clip's clock starts there."""
        deadline = time.monotonic() + ROLLING_TIMEOUT
        while "Recording started" not in self.log.read_text():
            if self.process.poll() is not None or time.monotonic() > deadline:
                raise SystemExit(f"simctl never started recording: {self.log.read_text().strip()}")
            time.sleep(0.02)
        self.started = time.time()

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                raise SystemExit("simctl ignored SIGINT for 30s; the recording has no index")


def launch_pid(udid: str, bundle_id: str, arguments: list[str]) -> int:
    out = subprocess.run(["xcrun", "simctl", "launch", "--terminate-running-process", udid, bundle_id, *arguments],
                         check=True, capture_output=True, text=True).stdout
    return int(out.rsplit(":", 1)[-1].strip())  # "com.example.app: 12345"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # a simulated app is a process on this Mac
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def record_launched(plan: Plan, p: Pass) -> None:
    """Record first, then launch the app into its fixture; it marks "start" and "end" itself.
    Why: docs/design/screenshots.md#a-preview-is-recorded-without-a-ui-test-attached"""
    app, config = plan.app, plan.config
    from .audiotap import Tap

    p.masters.mkdir(parents=True, exist_ok=True)
    events, bundle_id = events_file(app), app.config["bundle_id"]
    tap = recorder = None
    try:
        if p.language is not None:
            locale_file(app).write_text(p.language)
        events.unlink(missing_ok=True)
        subprocess.run(["xcrun", "simctl", "terminate", p.sim.udid, bundle_id], capture_output=True)
        since = time.time()
        recorder = Recorder(p.sim.udid, p.master(".partial.mov"))
        recorder.wait_started()
        print(f"$ xcrun simctl launch {p.sim.udid} {bundle_id} {' '.join(config.launch or [])}")
        pid = launch_pid(p.sim.udid, bundle_id, config.launch or [])
        if config.capture:
            tap = Tap(pid, p.master(".partial.caf"))
        print(f"  recording {p.sim.name} {p.locale}…")
        deadline = time.monotonic() + READY_TIMEOUT + config.max_seconds + SLACK
        while "end" not in read_events(events, since):
            if not alive(pid):
                raise SystemExit(f"{bundle_id} quit before it marked \"end\"; what was recorded is "
                                 f"{p.master('.partial.mov')}")
            if time.monotonic() > deadline:
                raise SystemExit(f'{bundle_id} never marked "end" in {events}; is it marking its moments?')
            time.sleep(0.1)
        recorder.stop()
        capture = tap.stop() if tap else None
        tap = None
        subprocess.run(["xcrun", "simctl", "terminate", p.sim.udid, bundle_id], capture_output=True)
        save_masters(p, recorder, capture, read_events(events, since))
    except (SystemExit, KeyboardInterrupt, subprocess.CalledProcessError):
        if recorder is not None and recorder.process.poll() is None:
            recorder.process.kill()
        if tap:
            tap.kill()
        raise
    finally:
        locale_file(app).unlink(missing_ok=True)


def save_masters(p: Pass, recorder: Recorder, capture: Any, found: dict[str, float]) -> None:
    """The three masters replaced together, so --encode-only never pairs one run's video with another's
    timings."""
    p.master(".partial.mov").replace(p.master(".mov"))
    if capture:
        p.master(".partial.caf").replace(p.master(".caf"))
    else:
        p.master(".caf").unlink(missing_ok=True)
    p.master(".json").write_text(json.dumps({
        "video_start": recorder.started,
        "audio_start": capture.first_buffer if capture else None,
        "audio_peak": capture.peak if capture else None,
        "events": found,
        "simulator": p.sim.name,
    }, indent=2) + "\n")
    if capture and (capture.first_buffer is None or capture.peak == 0):
        # Spades launches silent in the simulator (2026-10-16): a tap of silence looks like success.
        print("  warning: the app played no sound while recording; is its sound on in the video launch?")


def record(plan: Plan, p: Pass) -> None:
    app, config = plan.app, plan.config
    from .audiotap import Tap

    p.masters.mkdir(parents=True, exist_ok=True)
    events, rolling = events_file(app), rolling_file(app)
    log = p.master(".test.log")
    tap = recorder = test = None
    try:
        if p.language is not None:
            locale_file(app).write_text(p.language)
        events.unlink(missing_ok=True)
        rolling.unlink(missing_ok=True)
        since = time.time()
        print(f"$ {show(p.test, config.env)}  > {log}")
        test = subprocess.Popen(p.test, stdout=log.open("w"), stderr=subprocess.STDOUT,
                                env={**os.environ, **config.env})
        wait_for(lambda: "ready" in read_events(events, since), READY_TIMEOUT, test, log, 'the test\'s "ready"')
        if config.capture:
            tap = Tap(app_pid(p.sim.udid, app.config["bundle_id"]), p.master(".partial.caf"))
        recorder = Recorder(p.sim.udid, p.master(".partial.mov"))
        recorder.wait_started()
        rolling.write_text(str(recorder.started))
        print(f"  recording {p.sim.name} {p.locale}…")
        # Until the test says "end" or exits; one that does neither is cut off a minute past the longest clip.
        deadline = time.monotonic() + config.max_seconds + SLACK
        while test.poll() is None and "end" not in read_events(events, since) and time.monotonic() < deadline:
            time.sleep(0.1)
        recorder.stop()
        capture = tap.stop() if tap else None
        tap = None
        code = finish(test, log)
        if code:
            raise SystemExit(f"the video test failed ({code}) — see {log}; what it recorded is "
                             f"{p.master('.partial.mov')}")
        save_masters(p, recorder, capture, read_events(events, since))
    except (SystemExit, KeyboardInterrupt, subprocess.CalledProcessError):
        for process in (recorder.process if recorder else None, test):
            if process is not None and process.poll() is None:
                process.kill()
        if tap:
            tap.kill()
        sweep_test_devices()
        raise
    finally:
        locale_file(app).unlink(missing_ok=True)
        rolling.unlink(missing_ok=True)


# --- encoding -------------------------------------------------------------------------------------

def preview_size(capture: tuple[int, int], deck: Path) -> tuple[int, int]:
    """The preview slot's size, in the recording's orientation. The slot comes from the deck's shots
    when there are some, else from the recording's own pixels (the same device class)."""
    shots = media.deck_files([deck], media.DECK_SUFFIXES, "screenshot", quiet=True) if deck.is_dir() else []
    display = media.display_type_for(shots[0]) if shots else media.SCREENSHOT_DISPLAY_TYPES.get(capture)
    if display is None or (accepted := media.ACCEPTED_PREVIEW_SIZES.get(display.removeprefix("APP_"))) is None:
        raise SystemExit(f"a {capture[0]}x{capture[1]} recording fills no App Preview slot snakelane knows; "
                         "record on a simulator from the screenshot lineup")
    landscape = capture[0] > capture[1]
    return next(size for size in sorted(accepted) if (size[0] > size[1]) == landscape)


# A stall: a gap between recorded frames, with the screen moving on both sides and the frame after it
# a bigger jump than its neighbours. simctl writes a frame only when the screen changes, so a gap
# alone is a still table, not jank.
# Why: docs/design/screenshots.md#a-stall-in-the-recording-is-a-warning
STALL_GAP = 0.05     # seconds between frames: three frames missed at 60 fps
STALL_MOVING = 0.15  # mean grey-level change per pixel that counts as motion
STALL_JUMP = 1.5     # the jump across the gap against the larger neighbouring step
STALL_WIDTH = 96     # frames are compared at this width: enough to see a card move


def find_stalls(times: list[float], steps: list[float], start: float, length: float) -> list[tuple[float, float]]:
    """(clip seconds, gap seconds) for each stall; `steps[i]` is frame i's change from frame i-1."""
    found = []
    for i in range(2, len(times) - 1):
        gap, at = times[i] - times[i - 1], times[i] - times[0] - start
        if gap <= STALL_GAP or not 0 <= at <= length:
            continue
        before, across, after = steps[i - 1], steps[i], steps[i + 1]
        if before > STALL_MOVING and after > STALL_MOVING and across > STALL_JUMP * max(before, after):
            found.append((at, gap))
    return found


def stalls_in(mov: Path, start: float, length: float, size: tuple[int, int]) -> list[tuple[float, float]]:
    """The stalls in a recording's clip window, read frame by frame as simctl wrote them."""
    from PIL import Image, ImageChops, ImageStat

    if shutil.which("ffprobe") is None:
        return []
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                            "-of", "csv=p=0", str(mov)], capture_output=True, text=True)
    times = [float(t) for t in probe.stdout.replace(",", " ").split() if t not in ("", "N/A")]
    w, h = STALL_WIDTH, round(STALL_WIDTH * size[1] / size[0] / 2) * 2
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mov), "-fps_mode", "passthrough", "-vf", f"scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True).stdout
    frames = [Image.frombytes("L", (w, h), raw[i:i + w * h]) for i in range(0, len(raw) - w * h + 1, w * h)]
    n = min(len(frames), len(times))
    steps = [0.0] + [ImageStat.Stat(ImageChops.difference(frames[i], frames[i - 1])).mean[0] for i in range(1, n)]
    return find_stalls(times[:n], steps, start, length)


def clip_window(moments: dict[str, float], recorded: float, max_seconds: float) -> tuple[float, float]:
    """(start, length) in the recording: between the test's "start" and "end" marks, and when that runs
    long it loses its beginning, not its end, because "end" is where the test put its payoff."""
    end = min(moments.get("end", recorded), recorded)
    start = max(0.0, moments.get("start", 0.0), end - max_seconds)
    return start, end - start


def encode(plan: Plan, p: Pass) -> Path:
    app, config = plan.app, plan.config
    if shutil.which("ffmpeg") is None:
        raise SystemExit("encoding a preview needs ffmpeg: brew install ffmpeg")
    mov, caf, meta = p.master(".mov"), p.master(".caf"), p.master(".json")
    if not mov.exists() or not meta.exists():
        raise SystemExit(f"no recording in {p.masters} — run `snakelane preview` without --encode-only first")
    info = json.loads(meta.read_text())
    capture = media.read_movie(mov)
    target = preview_size(capture.dimensions, p.tree.framed(p.locale))
    video_start = info["video_start"]
    moments = {name: t - video_start for name, t in info["events"].items()}
    start, length = clip_window(moments, capture.seconds, config.max_seconds)
    if length < media.PREVIEW_SECONDS[0]:
        raise SystemExit(f"the clip is {length:.1f}s between the test's start and end; Apple needs at least "
                         f"{media.PREVIEW_SECONDS[0]:.0f}s — make the video test play longer")
    clip_moments = {name: t - start for name, t in moments.items()}

    inputs: list[str] = ["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(mov)]
    tw, th = target
    if config.fit == "pad":
        fit = f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black"
    else:
        fit = f"scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th}"
    graph = [f"[0:v]fps=30,{fit},setsar=1[v0]"]  # fps first: simctl records at whatever rate the screen ran
    label, n = "[v0]", 1
    with tempfile.TemporaryDirectory(prefix="snakelane-preview-") as tmp:
        if config.overlay == "band":
            for i, (frm, to, text) in enumerate(caption_times(
                    captions_for(config, p.locale, app.primary_locale), clip_moments, length)):
                png, (x, y) = band_layer(app, config, text, capture.dimensions, target, Path(tmp) / f"band-{i}.png")
                inputs += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(png)]
                graph.append(f"{label}[{n}:v]overlay={x}:{y}:enable='between(t,{frm:.3f},{to:.3f})'[v{i + 1}]")
                label, n = f"[v{i + 1}]", n + 1
        graph.append(f"{label}format=yuv420p[v]")

        sources = []
        if config.capture and caf.exists() and info.get("audio_start"):
            # The tap's frame 0 is the app's first sound, not the recorder's start.
            offset = info["audio_start"] - video_start - start
            inputs += ["-i", str(caf)]
            shift = f"adelay={offset * 1000:.0f}:all=1" if offset >= 0 else f"atrim=start={-offset:.3f},asetpts=PTS-STARTPTS"
            graph.append(f"[{n}:a]{shift},apad,atrim=0:{length:.3f},aresample=48000[app]")
            sources.append("[app]")
            n += 1
        if config.bed:
            inputs += ["-stream_loop", "-1", "-i", str(config.bed)]
            fade_out = max(0.0, length - 1.8)
            graph.append(f"[{n}:a]aresample=48000,atrim=0:{length:.3f},volume={config.bed_gain}dB,"
                         f"afade=t=in:d=0.8,afade=t=out:st={fade_out:.3f}:d=1.8[bed]")
            sources.append("[bed]")
            n += 1
        if sources:
            mixed = (f"{''.join(sources)}amix=inputs={len(sources)}:duration=longest:normalize=0,"
                     if len(sources) > 1 else f"{sources[0]}")
            graph.append(f"{mixed}loudnorm=I={config.loudness}:TP=-1.5,aresample=48000,"
                         f"apad,atrim=0:{length:.3f}[a]")
        else:  # Apple has bounced previews without an audio track; silence is the safe default
            inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
            graph.append(f"[{n}:a]anull[a]")

        p.clip.parent.mkdir(parents=True, exist_ok=True)
        partial = p.clip.with_name(f"_{CLIP}.partial.m4v")  # `_`: never uploaded, even if left behind
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs,
               "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]", "-t", f"{length:.3f}",
               # One video and one audio track: simctl's chapter and data tracks don't go to Apple.
               "-dn", "-map_chapters", "-1", "-map_metadata", "-1",
               # Apple's H.264 spec: High profile up to level 4.0, 10–12 Mbps; audio stereo AAC 256 kbps.
               "-c:v", "libx264", "-profile:v", "high", "-level", "4.0", "-preset", "slow",
               "-b:v", "11M", "-maxrate", "12M", "-bufsize", "24M",
               "-c:a", "aac", "-b:a", "256k", "-ac", "2", "-movflags", "+faststart", str(partial)]
        run(cmd)
    movie = media.read_movie(partial)
    errors, warnings = media.preview_problems(movie)
    if movie.dimensions != target:
        errors.append(f"came out {movie.dimensions[0]}x{movie.dimensions[1]}, not {tw}x{th}")
    if errors:
        raise SystemExit(f"{partial}: {'; '.join(errors)}")
    for at, gap in stalls_in(mov, start, length, capture.dimensions):
        warnings.append(f"the picture stalls {gap * 1000:.0f} ms mid-motion at {at:.1f}s; "
                        "re-record with nothing else running on the Mac")
    for warning in warnings:
        print(f"  warning: {warning}")
    partial.replace(p.clip)
    print(f"  {p.clip.relative_to(app.root)}  {tw}x{th}  {movie.seconds:.1f}s  {movie.video.fps:.0f} fps  "
          f"{p.clip.stat().st_size / 1e6:.1f} MB")
    return p.clip


# --- the command ----------------------------------------------------------------------------------

@contextmanager
def display_awake():
    """The display on for the whole recording: a simulator plays through the Mac's output device, and a
    display's speakers sleep with it, so a recording made with the Mac idle was silent and stalled
    on the app's failing audio starts.
    Why: docs/design/screenshots.md#the-display-stays-awake-while-recording"""
    if shutil.which("caffeinate") is None:
        yield
        return
    subprocess.run(["caffeinate", "-u", "-t", "2"], check=False)  # wake it if it has already slept
    hold = subprocess.Popen(["caffeinate", "-d", "-i", "-w", str(os.getpid())])
    try:
        yield
    finally:
        hold.terminate()


def cmd_preview(args: SimpleNamespace) -> None:
    app = resolve_app(args.app)
    config = load_preview_config(app)
    plan = make_plan(app, config, args)
    if args.dry_run:
        print_plan(plan, args.encode_only)
        if plan.problems and not args.encode_only:
            raise SystemExit(1)
        return
    if not args.encode_only:
        if plan.problems:
            raise SystemExit("\n".join(plan.problems))
        if config.capture:
            from .audiotap import binary
            binary()  # built before the first test, not in the middle of one
        built: set[str] = set()
        with display_awake():
            for p in plan.passes:
                if p.sim.udid not in built:
                    pin_status_bar(p.sim.udid)
                    run(p.build, config.env)
                    if config.launch is not None:
                        destination = f"platform=iOS Simulator,id={p.sim.udid}"
                        run(["xcrun", "simctl", "install", p.sim.udid,
                             str(built_app(app, config.scheme, destination))])
                    built.add(p.sim.udid)
                (record_launched if config.launch is not None else record)(plan, p)
    for p in plan.passes:
        encode(plan, p)
    print("upload with:  snakelane store previews push")


cli = command_app("Record the App Preview from the app's video UI test and encode it into the deck. "
                  "The config's previews keys are documented at the top of screenshots/preview.py.",
                  no_args_is_help=False)


@cli.command()
def preview(
    app: AppOption = None,
    device: Annotated[str | None, typer.Option(
        "--device", help="record one simulator (name or UDID) instead of the lineup")] = None,
    locales: Annotated[str | None, typer.Option(
        "--locales", "--locale", help="comma-separated locales (default: previews.locales)")] = None,
    encode_only: Annotated[bool, typer.Option(
        "--encode-only", help="encode again from the kept recordings, without recording")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="print the resolved plan and stop")] = False,
) -> None:
    """Record each simulator's App Preview with its sound and encode it as ap-01.m4v."""
    cmd_preview(SimpleNamespace(app=app, device=device, locales=locales, encode_only=encode_only, dry_run=dry_run))


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane preview")
