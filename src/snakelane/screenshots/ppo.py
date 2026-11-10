"""`store ppo push|show`: product page optimization tests (App Store Connect's A/B tests of the product
page against the live one), from `<metadata>/ppo/`. Each test is a folder:

    ppo/<test>/experiment.yml
        name: Search result art      the test's name in App Store Connect: how it is found again
        traffic: 50                  percent of visitors shown a treatment, split between them (1-100)
        treatments:                  up to three, folder -> treatment name
          table: Table mid-trick
    ppo/<test>/<folder>/creative/<locale>/, .../creative/default/,
    ppo/<test>/<folder>/creative/<platform>/<locale>/, .../creative/<platform>/default/
        the treatment's creative assets, named as for the version (search-result.*,
        product-page-header.*, universal.png); the most specific folder wins

A test is matched by name and platform, a treatment by name within it, and a treatment localization
by locale; what's missing is created, and the files are uploaded once to the App Asset Library and
placed as `store media push --only creative` places them. A slot with no file is left as it is. Only
a test still being prepared is written: Apple locks one once it is submitted, and a finished test's
name is refused rather than reused, so a new test gets a new name. A test that exists but is no
longer in `ppo/` is left alone.

Not pushed: treatment screenshots and app icons, and sending a test to review or starting it. Those
are done in App Store Connect. Why: docs/design/screenshots.md#product-page-optimizations

No snakelane.yml keys: the folders are the configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .. import project
from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import find_app, keyed
from ..terminal import dim, green
from . import creative

EXPERIMENT = "appStoreVersionExperiments"   # the v2 resource keeps the v1 type name
TREATMENT = "appStoreVersionExperimentTreatments"
TREATMENT_LOCALIZATION = "appStoreVersionExperimentTreatmentLocalizations"
EDITABLE = {"PREPARE_FOR_SUBMISSION", "REJECTED"}
FINISHED = {"COMPLETED", "STOPPED"}
MAX_TREATMENTS = 3


@dataclass(frozen=True)
class Treatment:
    folder: str
    name: str
    slots: dict[str, dict[str, Path]]   # locale -> placement type -> file


@dataclass(frozen=True)
class Test:
    folder: Path
    name: str
    traffic: int
    treatments: tuple[Treatment, ...]


# --- the local plan --------------------------------------------------------------------------------


def treatment_dirs(base: Path, platform: str, locale: str) -> list[Path]:
    root = base / "creative"
    return [root / platform / locale, root / platform / "default", root / locale, root / "default"]


def load_test(folder: Path, platform: str, locales: list[str]) -> Test:
    """One test folder, checked: a problem stops the run before anything is read from Apple."""
    config_path = folder / "experiment.yml"
    config = project.load_yaml(config_path) or {}
    if not isinstance(config, dict):
        raise SystemExit(f"{config_path}: expected a mapping with name, traffic and treatments")
    name, traffic, treatments = config.get("name"), config.get("traffic"), config.get("treatments")
    if not isinstance(name, str) or not name.strip():
        raise SystemExit(f"{config_path}: `name` is required (the test's name in App Store Connect)")
    if isinstance(traffic, bool) or not isinstance(traffic, int) or not 1 <= traffic <= 100:
        raise SystemExit(f"{config_path}: `traffic` is a whole percent from 1 to 100, not {traffic!r}")
    if not isinstance(treatments, dict) or not treatments:
        raise SystemExit(f"{config_path}: `treatments` maps each treatment's folder to its name")
    if len(treatments) > MAX_TREATMENTS:
        raise SystemExit(f"{config_path}: {len(treatments)} treatments; App Store Connect takes {MAX_TREATMENTS}")
    names = [str(n) for n in treatments.values()]
    if len(set(names)) != len(names):
        raise SystemExit(f"{config_path}: two treatments named alike; a treatment is found again by its name")
    parsed = []
    for sub, treatment_name in treatments.items():
        base = folder / str(sub)
        if not base.is_dir():
            raise SystemExit(f"{config_path}: no folder {base.relative_to(folder.parent)} for {treatment_name!r}")
        slots = {locale: s for locale in locales if (s := creative.slots_in(treatment_dirs(base, platform, locale)))}
        if not slots:
            raise SystemExit(f"{base}: no creative assets for {platform} in "
                             f"{', '.join(locales)}: a treatment shows nothing the live page doesn't")
        parsed.append(Treatment(str(sub), str(treatment_name), slots))
    return Test(folder, name.strip(), traffic, tuple(parsed))


def load_tests(metadata: Path, platform: str, locales: list[str]) -> list[Test]:
    root = metadata / "ppo"
    tests = [load_test(d, platform, locales) for d in sorted(root.iterdir()) if (d / "experiment.yml").is_file()] \
        if root.is_dir() else []
    seen: dict[str, Path] = {}
    for test in tests:
        if test.name in seen:
            raise SystemExit(f"{seen[test.name].name} and {test.folder.name} both name the test {test.name!r}")
        seen[test.name] = test.folder
    return tests


def print_tests(tests: list[Test], metadata: Path) -> None:
    for test in tests:
        print(f"  {test.name!r}: {test.traffic}% of visitors, {len(test.treatments)} treatment(s)")
        for treatment in test.treatments:
            for locale, slots in treatment.slots.items():
                for kind, path in sorted(slots.items()):
                    print(f"    {treatment.name:<20} {locale:<8} {creative.SLOT_NAMES[kind]:<20} "
                          f"{path.relative_to(metadata)}")


# --- App Store Connect -----------------------------------------------------------------------------


def experiments(client: asc.Client, app_id: str, platform: str) -> list[dict[str, Any]]:
    wanted = asc.platform_enum(platform)
    return [e for e in client.get_all(f"/v1/apps/{app_id}/appStoreVersionExperimentsV2")
            if asc.attributes(e).get("platform") == wanted]


def find_or_create_test(client: asc.Client, app_id: str, platform: str, test: Test,
                        live: list[dict[str, Any]]) -> dict[str, Any]:
    """The prepared test of this name, created if there is none; its traffic set to the file's."""
    same = [e for e in live if asc.attributes(e).get("name") == test.name]
    if editable := next((e for e in same if asc.attributes(e).get("state") in EDITABLE), None):
        attributes = asc.attributes(editable)
        print(dim(f"  test {test.name!r} ({editable['id']}, {attributes.get('state')})"))
        if attributes.get("trafficProportion") != test.traffic:
            client.patch(f"/v2/appStoreVersionExperiments/{editable['id']}", asc.resource_body(
                EXPERIMENT, {"trafficProportion": test.traffic}, id_=editable["id"]))
            client.report(f"  traffic {attributes.get('trafficProportion')}% -> {test.traffic}%")
        return editable
    if same:
        state = asc.attributes(same[0]).get("state")
        why = ("has finished: give the next test a new name" if state in FINISHED
               else "is submitted or running, and App Store Connect locks it until it ends")
        raise SystemExit(f"test {test.name!r} ({same[0]['id']}, {state}) {why}")
    created = client.post("/v2/appStoreVersionExperiments", asc.resource_body(
        EXPERIMENT, {"name": test.name, "platform": asc.platform_enum(platform), "trafficProportion": test.traffic},
        relationships={"app": asc.relationship("apps", app_id)}))["data"]
    client.report(green(f"  ✓ created test {test.name!r} ({created['id']})"))
    return created


def find_or_create_treatment(client: asc.Client, experiment_id: str, name: str) -> dict[str, Any]:
    live = keyed(client, f"/v2/appStoreVersionExperiments/{experiment_id}/appStoreVersionExperimentTreatments",
                 "name")
    if found := live.get(name):
        return found
    created = client.post(f"/v1/{TREATMENT}", asc.resource_body(
        TREATMENT, {"name": name},
        relationships={"appStoreVersionExperimentV2": asc.relationship(EXPERIMENT, experiment_id)}))["data"]
    client.report(green(f"  ✓ created treatment {name!r} ({created['id']})"))
    return created


def treatment_targets(client: asc.Client, treatment: Treatment, treatment_id: str) -> dict[str, creative.Target]:
    """Each planned locale's treatment localization, created where it's missing."""
    live = keyed(client, f"/v1/{TREATMENT}/{treatment_id}/appStoreVersionExperimentTreatmentLocalizations")
    targets = {}
    for locale in treatment.slots:
        if (localization := live.get(locale)) is None:
            localization = client.post(f"/v1/{TREATMENT_LOCALIZATION}", asc.resource_body(
                TREATMENT_LOCALIZATION, {"locale": locale},
                relationships={"appStoreVersionExperimentTreatment": asc.relationship(TREATMENT, treatment_id)}))["data"]
            client.report(f"  created {treatment.name} {locale} ({localization['id']})")
        targets[locale] = treatment_target(localization["id"], treatment.name, locale)
    return targets


def treatment_target(localization_id: str, treatment: str, locale: str) -> creative.Target:
    return creative.Target(TREATMENT_LOCALIZATION, "appStoreVersionExperimentTreatmentLocalization",
                           localization_id, f"{treatment} {locale}")


def push_tests(client: asc.Client, app_id: str, platform: str, tests: list[Test], ref: creative.RefData) -> int:
    """Every test's treatments and placements; returns how many placements changed. Every file is
    in the library and processed before the first test is touched, so a failed upload changes nothing."""
    assets = creative.upload_missing(client, app_id, [p for test in tests for t in test.treatments
                                                      for slots in t.slots.values() for p in slots.values()])
    live = experiments(client, app_id, platform)
    changed = 0
    for test in tests:
        experiment = find_or_create_test(client, app_id, platform, test, live)
        for treatment in test.treatments:
            treatment_id = find_or_create_treatment(client, experiment["id"], treatment.name)["id"]
            for locale, target in treatment_targets(client, treatment, treatment_id).items():
                changed += creative.place_slots(client, target, treatment.slots[locale], assets, ref)
    return changed


# --- commands --------------------------------------------------------------------------------------


def cmd_ppo_push(args: SimpleNamespace) -> None:
    """Create or update each test in ppo/ and place its treatments' creative assets."""
    folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    if not (tests := load_tests(folder, platform, app_config["locales"])):
        print(f"no tests under {folder.name}/ppo/ (a folder with an experiment.yml): nothing to do")
        return
    print(f"product page optimizations for {app_config.get('name', app_config['bundle_id'])} ({platform}):")
    print_tests(tests, folder)
    plan = {f"{test.name}/{t.name}/{locale}": slots for test in tests for t in test.treatments
            for locale, slots in t.slots.items()}
    if args.dry_run and creative.offline_dry_run(plan):
        return
    client = asc.Client(dry_run=args.dry_run)
    ref = creative.check_plan(client, plan)
    app = find_app(client, app_config)
    changed = push_tests(client, app["id"], platform, tests, ref)
    if client.dry_run:
        print("\n[dry-run] nothing was created, uploaded or placed.")
    else:
        print(f"\n{changed} placement(s) changed. Send the test to review and start it in App Store Connect.")


def cmd_ppo_show(args: SimpleNamespace) -> None:
    """Each test on the platform: state, traffic, treatments and their creative placements."""
    _folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    client = asc.Client()
    app = find_app(client, app_config)
    live = experiments(client, app["id"], platform)
    print(f"--- product page optimizations for {app_config['bundle_id']} ({platform}) ---")
    if not live:
        print("  (none)")
        return
    backing = creative.placement_labels(client, app["id"])
    for experiment in live:
        attributes = asc.attributes(experiment)
        dates = " to ".join(d[:10] for d in (attributes.get("startDate"), attributes.get("endDate")) if d)
        print(f"  {attributes.get('name')!r} [{attributes.get('state')}] {attributes.get('trafficProportion')}% "
              f"of visitors{f', {dates}' if dates else ''}")
        for treatment in client.get_all(
                f"/v2/appStoreVersionExperiments/{experiment['id']}/appStoreVersionExperimentTreatments"):
            name = asc.attributes(treatment).get("name")
            localizations = list(client.get_all(
                f"/v1/{TREATMENT}/{treatment['id']}/appStoreVersionExperimentTreatmentLocalizations"))
            if not localizations:
                print(f"    {name}: (no localizations)")
            for localization in localizations:
                locale = asc.attributes(localization).get("locale")
                live_slots = creative.live_slots(client, treatment_target(localization["id"], name, locale))
                for kind in creative.SLOTS.values():
                    shown = ", ".join(backing.get(p["id"], p["id"]) for p in live_slots.get(kind) or []) or "(none)"
                    print(f"    {name:<20} [{locale}] {creative.SLOT_NAMES[kind]:<20} {shown}")
