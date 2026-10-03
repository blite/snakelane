"""`snakelane shoot`: run the app's screenshot UI test per simulator (or this Mac) and locale, and file
the captures as JPEGs into the deck `store screenshots push` uploads.
A failed shoot deletes the test-clone simulators it leaked. Design notes: docs/design/screenshots.md#shooting

snakelane.yml "screenshots" (all optional; full reference in the skill's references/config.md):
    scheme            scheme to test under; default the top-level "scheme"
    test              -only-testing id, or null: whole scheme; default <scheme>UITests/<scheme>UITestsScreenshotsUITests
    test_plan         -testPlan name
    devices           names, UDIDs or {"name"|"id", "os", "deck"}; default ["iPhone 14 Plus", "iPad Pro 13-inch (M5)"]
    locales           ASC locales, or {ASC locale: language key for the test}; default ["en-US"]
    env               extra test-runner variables (TEST_RUNNER_ prefix added); default {}
    frame             who draws captions: "test" (default; reframe runs reframe_test) | "snakelane" | "none"
    reframe_test      -only-testing id of the UI test that re-frames raws on disk (frame "test")
    framing           `snakelane frame`'s settings — see screenshots/frame.py
    mac               enables --platform macos: {} or {"scheme", "test", "reframe_test", "destination"}
    check             `snakelane check` settings — see screenshots/check.py

The runner gets TEST_RUNNER_SNAKELANE_{LOCALE, LANGUAGE, PLATFORM, DEVICE, REFRAME_LOCALE, BANNER}; an iOS
runner does not reliably see them, so the language key and band depth also travel in
/tmp/<slug>-screenshot-locale and /tmp/<slug>-screenshot-banner.json.
Why: docs/design/screenshots.md#the-locale-travels-in-a-file-not-the-environment
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import typer

from .. import project
from ..args import AppOption, PlatformOption, command_app, resolve_platform
from ..args import run as run_cli
from ..project import IMAGE_SUFFIXES, App, DeckTree, device_deck, resolve_app
from ..xcode import run, show, sweep_test_devices
from .extract import extract_deck

# The 6.5" iPhone class (deliberately not 6.9") and the 13" iPad.
# Why: docs/design/screenshots.md#the-default-lineup
DEFAULT_DEVICES = ["iPhone 14 Plus", "iPad Pro 13-inch (M5)"]
MAC_DESTINATION = "platform=macOS,arch=arm64"  # the app sizes its own window to an ASC Mac size
# framed/: every image, since the push uploads every image there. raw/: only the shots.
# Why: docs/design/screenshots.md#what-a-shoot-clears
CLEAR = {"framed": ["*"], "raw": ["ss-*", "_ss-*"]}
BANNER = "TEST_RUNNER_SNAKELANE_BANNER"
UDID_RE = re.compile(r"^[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
HANDOFF_DIR = Path("/tmp")  # where the test finds the files below; tests point it elsewhere


def locale_file(app: App) -> Path:
    return HANDOFF_DIR / f"{app.slug}-screenshot-locale"


def banner_file(app: App) -> Path:
    return HANDOFF_DIR / f"{app.slug}-screenshot-banner.json"


@dataclass
class DeviceSpec:  # one lineup entry as snakelane.yml wrote it, before simctl is asked
    name: str | None = None
    udid: str | None = None
    os: str | None = None
    deck: str | None = None  # "iphone" / "ipad"; default from the device's name

    @classmethod
    def parse(cls, entry: Any) -> DeviceSpec:
        if isinstance(entry, str):
            return cls(udid=entry) if UDID_RE.match(entry) else cls(name=entry)
        if not isinstance(entry, dict):
            raise SystemExit(f"screenshots.devices entries are strings or objects, not {entry!r}")
        if unknown := set(entry) - {"name", "id", "os", "deck"}:
            raise SystemExit(f'screenshots.devices entry has unknown key(s) {sorted(unknown)}: {entry}')
        if not (entry.get("name") or entry.get("id")):
            raise SystemExit(f'screenshots.devices entry needs "name" or "id": {entry}')
        return cls(entry.get("name"), entry.get("id"), entry.get("os"), entry.get("deck"))

    def label(self) -> str:
        return self.name or self.udid or "?"


@dataclass
class ShotsConfig:  # snakelane.yml's "screenshots", defaults applied
    scheme: str
    test: str | None
    test_plan: str | None
    devices: list[DeviceSpec]
    locales: dict[str, str | None]
    env: dict[str, str]
    frame: str
    reframe_test: str | None
    mac: dict[str, Any] | None

    @property
    def writes_locale_file(self) -> bool:
        """Only the mapping form has anything to say to the test."""
        return any(v is not None for v in self.locales.values())


KNOWN_KEYS = {f.name for f in fields(ShotsConfig)} | {"framing", "check", "_comment"}

def load_config(app: App) -> ShotsConfig:
    raw = app.config.get("screenshots") or {}
    if not isinstance(raw, dict):
        raise SystemExit(f'"screenshots" in {app.config_path} must be an object')
    # A typo'd key falling back to a default is how a deck gets shot on the wrong scheme.
    if unknown := set(raw) - KNOWN_KEYS:
        raise SystemExit(f'unknown key(s) in snakelane.yml "screenshots": {", ".join(sorted(unknown))}')
    match locales := raw.get("locales", ["en-US"]):
        case list():
            locales = {str(l): None for l in locales}
        case dict():
            locales = {str(k): (None if v is None else str(v)) for k, v in locales.items()}
        case _:
            raise SystemExit("screenshots.locales is a list of ASC locales or an object of locale → language key")
    if not locales:
        raise SystemExit("screenshots.locales is empty")
    if (frame := frame_mode(raw)) not in ("test", "snakelane", "none"):
        raise SystemExit(f'screenshots.frame must be "test", "snakelane" or "none", not {frame!r}')
    env = project.runner_vars(raw.get("env") or {})
    mac = raw.get("mac")
    mac = {} if mac is True else None if mac is False else mac
    if mac is not None and not isinstance(mac, dict):
        raise SystemExit('screenshots.mac is an object ({} for all defaults)')
    return ShotsConfig(
        scheme=raw.get("scheme") or app.scheme,
        test=raw["test"] if "test" in raw else f"{app.scheme}UITests/{app.scheme}UITestsScreenshotsUITests",
        **{key: raw.get(key) for key in ("test_plan", "reframe_test")},
        devices=[DeviceSpec.parse(d) for d in raw.get("devices", DEFAULT_DEVICES)],
        locales=locales,
        env=env,
        frame=frame,
        mac=mac,
    )


def frame_mode(screenshots: dict[str, Any]) -> str:
    """Who draws the captions. Unset, it's snakelane when there is a framing block, else the UI test."""
    return screenshots.get("frame") or ("snakelane" if screenshots.get("framing") else "test")


def quiet(*cmd: str) -> None:
    subprocess.run(["xcrun", "simctl", *cmd], check=False, capture_output=True)


def banner_json(config: ShotsConfig, tree: DeckTree, locale: str | None = None) -> str | None:
    """The band depth for this deck's passes in `locale` (frame "snakelane"): it lays out that
    locale's captions, which per-locale captions make differ."""
    if config.frame != "snakelane":
        return None
    from .frame import banner_handoff
    return json.dumps(banner_handoff(tree.app, tree.deck, locale), separators=(",", ":"))


def runner_env(config: ShotsConfig, locale: str, language: str | None, tree: DeckTree,
               banner: str | None = None) -> dict[str, str]:
    return {
        **({BANNER: banner} if banner else {}),
        "TEST_RUNNER_SNAKELANE_LOCALE": locale,
        "TEST_RUNNER_SNAKELANE_PLATFORM": tree.platform,
        "TEST_RUNNER_SNAKELANE_DEVICE": tree.device,
        **({"TEST_RUNNER_SNAKELANE_LANGUAGE": language} if language is not None else {}),
        **config.env,
    }


@dataclass
class Simulator:
    name: str
    udid: str | None
    runtime: str
    deck: str
    problem: str | None = None


@functools.cache
def available_simulators() -> list[tuple[str, tuple[int, ...], dict]]:
    """(family, version, device) for every available simulator, oldest runtime first."""
    listing = json.loads(subprocess.run(["xcrun", "simctl", "list", "devices", "available", "--json"],
                                        check=True, capture_output=True, text=True).stdout)
    rows = []
    for key, devices in listing.get("devices", {}).items():
        # `com.apple.CoreSimulator.SimRuntime.iOS-26-5` → ("iOS", (26, 5))
        family, _, version = key.rsplit(".", 1)[-1].partition("-")
        rows += [(family, tuple(int(p) for p in version.split("-") if p.isdigit()), d) for d in devices]
    return sorted(rows, key=lambda r: (r[0], r[1]))


def resolve_simulator(spec: DeviceSpec, strict: bool = True) -> Simulator:
    """The one simulator a lineup entry means (newest runtime unless it pins "os"), addressed by UDID.
    Why: docs/design/screenshots.md#simulators-are-addressed-by-udid"""
    def unresolved(udid: str | None, problem: str) -> Simulator:
        return Simulator(spec.label(), udid, "?", spec.deck or device_deck(spec.label()), problem=problem)

    try:
        rows = available_simulators()
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
        if strict:
            raise SystemExit(f"could not list simulators: {exc}")
        return unresolved(spec.udid, f"simctl unavailable ({exc})")
    candidates = [
        (family, version, device) for family, version, device in rows
        if family == "iOS"
        and (not spec.udid or device["udid"].upper() == spec.udid.upper())
        and (not spec.name or device["name"] == spec.name)
        and (not spec.os or (v := ".".join(map(str, version))) == spec.os or v.startswith(spec.os + "."))
    ]
    if not candidates:
        problem = f"no available simulator {spec.label()}" + (f" on iOS {spec.os}" if spec.os else "")
        if strict:
            raise SystemExit(problem)
        return unresolved(None, problem)
    family, version, device = candidates[-1]
    return Simulator(device["name"], device["udid"], f"{family} {'.'.join(map(str, version))}",
                     spec.deck or device_deck(device["name"]))


def pin_status_bar(udid: str) -> None:
    """Apple's 9:41 status bar (a fallback to hiding it). Boots first: a shut-down device ignores the override.
    Why: docs/design/screenshots.md#the-status-bar-is-pinned-to-941"""
    quiet("boot", udid)
    quiet("bootstatus", udid, "-b")
    run(["xcrun", "simctl", "status_bar", udid, "override", "--time", "9:41",
         "--dataNetwork", "wifi", "--wifiMode", "active", "--wifiBars", "3",
         "--cellularMode", "active", "--cellularBars", "4", "--batteryState", "discharging", "--batteryLevel", "100"])


def automation_mode_ready(status: str) -> bool:
    """`automationmodetool`'s status (lowercased): on now, or off at rest but switchable on by the
    test run without a password. Why: docs/design/screenshots.md#automation-mode-is-on-only-during-a-run"""
    if "automation mode is enabled" in status:
        return True
    return "does not require user authentication" in status


def require_mac_ui_testing() -> None:
    """Fail early, printing the admin commands, if developer mode or Automation Mode is off.
    Why: docs/design/screenshots.md#the-mac-lane-checks-for-developer-mode-and-automation-mode"""
    def output(cmd: list[str]) -> str:
        return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout.lower()

    problems = []
    if "enabled" not in output(["DevToolsSecurity", "-status"]):
        problems.append("sudo DevToolsSecurity -enable")
    if not automation_mode_ready(output(["automationmodetool"])):
        problems.append("sudo automationmodetool enable-automationmode-without-authentication")
    if problems:
        raise SystemExit("macOS UI testing isn't set up on this machine, so the shoot would fail after building "
                         "everything.\nRun once (each asks for your password):\n\n"
                         + "".join(f"    {command}\n" for command in problems))


def stale_files(tree: DeckTree, locales: list[str] | None, device: str | None) -> list[Path]:
    """The images a shoot of this tree replaces, raw and framed (never the App Preview).

    `locales` None sweeps every locale folder.
    Why: docs/design/screenshots.md#what-a-shoot-clears"""
    return sorted({
        path
        for kind, base, folder_for in (("raw", tree.raw_base, tree.raw), ("framed", tree.framed_base, tree.framed))
        if base.is_dir()
        for locale in (locales if locales is not None else [p.name for p in base.iterdir() if p.is_dir()])
        if (folder := folder_for(locale)).is_dir()
        for pattern in CLEAR[kind]
        for path in folder.glob(pattern)
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    })


class PreviousDeck:
    """The deck a shoot replaces, moved to `App.shoot_stash` until the shoot succeeds; also a
    context manager that stashes, then restores on any failure or discards on success.
    A stash left by a killed run is refused, never overwritten: it may be the only good copy.
    Why: docs/design/screenshots.md#a-failed-shoot-puts-the-previous-deck-back"""

    def __init__(self, targets: list[tuple[DeckTree, str | None]], locales: list[str] | None) -> None:
        self.targets, self.locales = targets, locales
        self.moved: list[tuple[Path, Path]] = []
        self.app = targets[0][0].app if targets else None
        if self.app is not None:
            self.app.refuse_if_shoot_was_killed()

    def _current(self) -> list[Path]:
        return sorted({p for tree, device in self.targets
                       for p in stale_files(tree, self.locales, device)})

    def stash(self) -> None:
        for path in self._current():
            target = self.app.shoot_stash / path.relative_to(self.app.root)
            target.parent.mkdir(parents=True, exist_ok=True)
            path.rename(target)
            self.moved.append((path, target))
        if self.moved:
            print(f"set aside {len(self.moved)} previous screenshot(s) until the shoot succeeds")

    def restore(self) -> None:
        """Remove whatever the failed shoot wrote, and put the previous deck back."""
        for path in self._current():
            path.unlink()
        for original, stashed in self.moved:
            original.parent.mkdir(parents=True, exist_ok=True)
            stashed.rename(original)
        self.discard()
        if self.moved:
            print(f"restored the {len(self.moved)} previous screenshot(s); the deck is as it was")

    def discard(self) -> None:
        if self.app is not None:
            shutil.rmtree(self.app.shoot_stash, ignore_errors=True)

    def __enter__(self) -> PreviousDeck:
        self.stash()
        return self

    def __exit__(self, kind: type[BaseException] | None, *_: object) -> None:
        if kind:
            self.restore()
        else:
            self.discard()


@dataclass
class Pass:  # one `xcodebuild test`: one device (or the Mac), one locale
    label: str
    tree: DeckTree
    locale: str
    language: str | None
    xcresult: Path
    cmd: list[str]
    env: dict[str, str]
    sim: Simulator | None = None


@dataclass
class Plan:
    """Built once, then executed or (--dry-run) printed, so the dry run can be trusted."""

    app: App
    config: ShotsConfig
    platform: str
    locales: dict[str, str | None]
    full_locales: bool
    passes: list[Pass] = field(default_factory=list)
    sims: list[Simulator] = field(default_factory=list)
    clear_targets: list[tuple[DeckTree, str | None]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def clear_locales(self) -> list[str] | None:
        """The locale folders a shoot replaces: every one on a full run (see `stale_files`)."""
        return None if self.full_locales else list(self.locales)

    @property
    def trees(self) -> list[DeckTree]:
        # Keyed by label: a DeckTree holds the App, which isn't hashable.
        return sorted({p.tree.label(): p.tree for p in self.passes}.values(), key=lambda t: t.label())

    def add_passes(self, tree: DeckTree, name: str, name_slug: str, sim: Simulator | None, scheme: str,
                   destination: str, test: str | None) -> None:
        """One pass per locale on one device; `name` is what the clear and the labels call it."""
        self.clear_targets.append((tree, name))
        for locale, language in self.locales.items():
            banner = banner_json(self.config, tree, locale)
            slug = re.sub(r"[^a-z0-9]+", "-", f"{name_slug}-{locale}".lower()).strip("-")
            xcresult = Path(f"/tmp/snakelane-{self.app.slug}-shots-{slug}.xcresult")
            cmd = xcodebuild_test(self.app, scheme, destination, test=test, test_plan=self.config.test_plan,
                                  xcresult=xcresult, mac=sim is None)
            self.passes.append(Pass(f"{name} {locale}" if len(self.locales) > 1 else name, tree, locale, language,
                                    xcresult, cmd, runner_env(self.config, locale, language, tree, banner), sim))


def xcodebuild_test(app: App, scheme: str, destination: str, *, test: str | None, test_plan: str | None,
                    xcresult: Path | None, mac: bool) -> list[str]:
    return [
        "xcodebuild", "-project", str(app.project), "-scheme", scheme,
        *(["-testPlan", test_plan] if test_plan else []),
        "-destination", destination,
        # A Mac UI test drives a signed app; its development profile is minted on first use.
        *(["-allowProvisioningUpdates"] if mac else []),
        *(["-resultBundlePath", str(xcresult)] if xcresult is not None else []),
        *(["-only-testing", test] if test else []),
        "-parallel-testing-enabled", "NO", "test",  # serial: docs/design/screenshots.md#tests-run-serially
    ]


def make_plan(app: App, config: ShotsConfig, args: SimpleNamespace) -> Plan:
    if mac := args.platform == "macos":
        if args.device:
            raise SystemExit("--device is a simulator lineup option; the Mac lane has no lineup")
        if config.mac is None:
            raise SystemExit(f'{app.name} has no Mac lane: add "mac": {{}} to snakelane.yml\'s "screenshots" once '
                             "its screenshot UI test builds for macOS")
    locales = config.locales
    if args.locales:
        requested = [l.strip() for l in args.locales.split(",") if l.strip()]
        if unknown := [l for l in requested if l not in config.locales]:
            raise SystemExit(f"unknown locale(s): {', '.join(unknown)} — expected {', '.join(config.locales)}")
        locales = {l: config.locales[l] for l in requested}
    plan = Plan(app, config, "macos" if mac else "ios", locales, full_locales=not args.locales)
    if mac:
        plan.add_passes(DeckTree(app, "macos"), "Mac", "macos", None, config.mac.get("scheme", config.scheme),
                        config.mac.get("destination", MAC_DESTINATION), config.mac.get("test", config.test))
        return plan
    for spec in [DeviceSpec.parse(args.device)] if args.device else config.devices:
        plan.sims.append(sim := resolve_simulator(spec, strict=not args.dry_run))
        if sim.problem:
            plan.problems.append(f"{spec.label()}: {sim.problem}")
    # ss-NN names carry no device, so two devices sharing a deck folder would overwrite each
    # other.
    for deck in dict.fromkeys(sim.deck for sim in plan.sims):
        if len(sharing := [sim.name for sim in plan.sims if sim.deck == deck]) > 1:
            raise SystemExit(f"{', '.join(sharing)} all map to {deck}/ and would overwrite each other's ss-NN "
                             'files. Give each a different "deck" in snakelane.yml\'s "screenshots.devices".')
    for sim in plan.sims:
        plan.add_passes(DeckTree(app, "ios", sim.deck), sim.name, sim.name, sim, config.scheme,
                        f"platform=iOS Simulator,id={sim.udid or '<unresolved>'}", config.test)
    return plan


def print_plan(plan: Plan) -> None:
    app, config = plan.app, plan.config
    print(f"app        {app.name}  ({app.config_path.name} → {app.folder.relative_to(app.root)}/, slug {app.slug})")
    print(f"project    {app.project}")
    print(f"scheme     {config.scheme}")
    print(f"test       {config.test or '(whole scheme)'}" + (f"  plan {config.test_plan}" if config.test_plan else ""))
    print(f"platform   {plan.platform}")
    if plan.platform == "ios":
        print("devices")
        for sim in plan.sims:
            where = f"{sim.udid} ({sim.runtime})" if sim.udid else f"UNRESOLVED — {sim.problem}"
            print(f"  {sim.name:<40} {where}  → {sim.deck}/")
    print("locales    " + ", ".join(l + (f"→{v}" if v is not None else "") for l, v in plan.locales.items()))
    if config.writes_locale_file:
        print(f"locale file {locale_file(app)}  (written before each pass, removed after)")
    if config.frame == "snakelane":
        print(f"banner     {banner_file(app)}  (written before each pass, removed after)")
        for (deck, locale), banner in sorted({(p.tree.deck, p.locale): p.env.get(BANNER) for p in plan.passes}.items()):
            print(f"  {deck:<7} {locale:<7} {banner}")
        from .frame import fallback_note, framing
        for locale in plan.locales:
            if note := fallback_note(app, framing(app), locale):
                print(f"  {note}")
    print("clear      " + "; ".join(f"{kind}/: {', '.join(g)}" for kind, g in CLEAR.items())
          + f"  (images only; {'every locale folder' if plan.full_locales else 'these locales only'})")
    for tree, device in plan.clear_targets:
        stale = stale_files(tree, plan.clear_locales, device)
        print(f"  {tree.label():<11} {len(stale)} file(s) would be replaced (kept aside until every pass succeeds)")
    print("extract    NN-Name → .snakelane raw, NN-Name_framed → the deck, as ss-NN.jpg")
    print(f"frame      {config.frame}"
          + ("  (snakelane frame runs after the last pass)" if config.frame == "snakelane" else ""))
    print(f"passes     {len(plan.passes)}")
    for p in plan.passes:
        print(f"  [{p.label}] → {p.tree.framed(p.locale).relative_to(plan.app.root)}")
        print(f"    $ {show(p.cmd, p.env)}")
    if plan.problems:
        print("problems" + "".join(f"\n  ! {problem}" for problem in plan.problems))


def upload_hint(platform: str) -> str:
    return "upload with:  snakelane store screenshots push" + (" --platform macos" if platform == "macos" else "")


def execute(plan: Plan) -> None:
    """Every pass, then the framing; all or nothing (see `PreviousDeck`)."""
    with PreviousDeck(plan.clear_targets, plan.clear_locales):
        run_passes(plan)
        if plan.config.frame == "snakelane":  # captions last, once every device has shot: what `reframe` does
            from .frame import frame_deck
            for locale in plan.locales:
                frame_deck(plan.app, locale, decks=sorted({p.tree.deck for p in plan.passes}))


def run_passes(plan: Plan) -> None:
    config, locale_path, banner_path = plan.config, locale_file(plan.app), banner_file(plan.app)
    pinned: set[str] = set()
    try:
        for p in plan.passes:
            if p.sim is not None and p.sim.udid not in pinned:
                pin_status_bar(p.sim.udid)
                pinned.add(p.sim.udid or "")
            if config.writes_locale_file and p.language is not None:
                locale_path.write_text(p.language)  # the test reads language, region, captions from it
            if config.frame == "snakelane":
                banner_path.write_text(p.env[BANNER])
            if p.xcresult.exists():
                shutil.rmtree(p.xcresult)
            run(p.cmd, p.env)
            extract_deck(p.xcresult, p.tree, p.locale, p.label)
    except (subprocess.CalledProcessError, KeyboardInterrupt):
        if plan.platform == "ios":
            sweep_test_devices()
            raise SystemExit("shoot failed — swept XCTestDevices clones")
        raise SystemExit("shoot failed")
    finally:
        # A stale file would make a later test run from Xcode shoot in this run's last language.
        if config.writes_locale_file:
            locale_path.unlink(missing_ok=True)
        if config.frame == "snakelane":
            banner_path.unlink(missing_ok=True)


def cmd_shoot(args: SimpleNamespace) -> None:
    app = resolve_app(args.app)
    config = load_config(app)
    plan = make_plan(app, config, args)
    if args.dry_run:
        print_plan(plan)
        if plan.problems:
            raise SystemExit(1)
        return
    if plan.platform == "macos":
        require_mac_ui_testing()
    execute(plan)
    for tree in plan.trees:
        print(f"deck written to {tree.framed_base.relative_to(app.root)} ({tree.label()})")
    print(upload_hint(plan.platform))


def reframe_with_test(args: SimpleNamespace) -> None:
    """Redraw the captions over the raw captures with the app's reframe UI test (`frame: test`);
    `snakelane frame` calls this. The test runs on its platform's host and finds the trees itself.

    Why: docs/design/screenshots.md#the-reframe-test-finds-its-own-trees"""
    app = resolve_app(args.app)
    config = load_config(app)
    mac = args.platform == "macos"
    populated = [d for d in (("mac",) if mac else ("iphone", "ipad"))
                 if (raw := DeckTree.for_deck(app, d).raw(args.locale)).is_dir() and any(raw.iterdir())]
    if config.frame == "none":
        raise SystemExit(f'{app.name} ships its raw captures ("frame": "none"); there is no banner to redraw')
    if mac and config.mac is None:
        raise SystemExit(f'{app.name} has no Mac lane ("screenshots.mac" is not set)')
    lane = config.mac if mac else {}
    if not (reframe_test := lane.get("reframe_test", config.reframe_test)):
        raise SystemExit(f'{app.name} has no reframe UI test: set "reframe_test" in snakelane.yml\'s "screenshots" '
                         '(e.g. "<Scheme>UITests/<Scheme>ReframeUITests"), or use "frame": "snakelane"')
    env = {"TEST_RUNNER_SNAKELANE_REFRAME_LOCALE": args.locale, **config.env}
    # Any simulator can host the rendering; the lineup's first keeps it predictable.
    sim = None if mac else resolve_simulator(DeviceSpec.parse(args.device) if args.device else config.devices[0],
                                             strict=not args.dry_run)
    destination = (lane.get("destination", MAC_DESTINATION) if sim is None
                   else f"platform=iOS Simulator,id={sim.udid or '<unresolved>'}")
    cmd = xcodebuild_test(app, lane.get("scheme", config.scheme), destination, test=reframe_test, test_plan=None,
                          xcresult=None, mac=mac)
    if args.dry_run:
        print(f"trees      {', '.join(map(str, populated)) or '(no raw captures yet)'}")
        print(f"$ {show(cmd, env)}")
        return
    if not populated:
        raise SystemExit(f"no raw captures for {args.locale} under {app.folder} — `raw/` is usually gitignored, "
                         "so a fresh clone has none until `shoot` has run once")
    if sim is None:
        require_mac_ui_testing()  # the reframe is hosted in a UI test, which needs the same setup as a shoot
    else:
        pin_status_bar(sim.udid)
    if config.writes_locale_file:
        locale_file(app).write_text(config.locales.get(args.locale) or args.locale)
    try:
        run(cmd, env)
    finally:
        if config.writes_locale_file:
            locale_file(app).unlink(missing_ok=True)
    for deck in populated:
        print(f"re-framed deck written to {DeckTree.for_deck(app, deck).framed(args.locale)}")
    print(upload_hint(args.platform))


cli = command_app("Shoot the screenshot deck from the app's UI test. The config's screenshots keys "
                  "are documented at the top of screenshots/shoot.py.", no_args_is_help=False)


@cli.command()
def shoot(
    app: AppOption = None,
    device: Annotated[str | None, typer.Option(
        "--device", help="shoot one simulator (name or UDID) instead of the lineup")] = None,
    locales: Annotated[str | None, typer.Option(
        "--locales", "--locale", help="comma-separated locales (default: every screenshot locale)")] = None,
    platform: PlatformOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="print the resolved plan and stop")] = False,
) -> None:
    """Run the screenshot UI test on each simulator and file the deck."""
    platform = resolve_platform(resolve_app(app).config, platform)  # ios: the simulators; macos: this Mac
    cmd_shoot(SimpleNamespace(app=app, device=device, locales=locales, platform=platform, dry_run=dry_run))


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane shoot")
