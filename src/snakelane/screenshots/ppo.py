"""`store ppo push|show`: product page optimization tests (App Store Connect's A/B tests of the product
page against the live one), from `<metadata>/ppo/`. Each test is a folder:

    ppo/<test>/experiment.yml
        name: Search result art      the test's name in App Store Connect: how it is found again
        traffic: 50                  percent of visitors shown a treatment, split between them (1-100)
        treatments:                  up to three, folder -> treatment name, or -> {name, preview}
          table: Table mid-trick
          promise:
            name: Promise first
            preview: {…}             `snakelane preview --ppo <test>/promise`: snakelane.yml's
                                     previews keys this treatment's App Preview records with
                                     instead (documented in preview.py)
    ppo/<test>/<folder>/creative/<locale>/, .../creative/default/,
    ppo/<test>/<folder>/creative/<platform>/<locale>/, .../creative/<platform>/default/
        the treatment's creative assets, named as for the version (search-result.*,
        product-page-header.*, universal.png); the most specific folder wins
    ppo/<test>/<folder>/screenshots/<platform>/<locale>/ (and its iphone/, ipad/, … folders)
        the treatment's screenshots, ss-NN.jpg, and App Previews, ap-NN.m4v with the ap-NN.json
        poster sidecar `snakelane preview --ppo` writes, laid out as the version's deck

A treatment has screenshots, previews, creative assets or any mix; one with none for the platform is
refused.

A test is matched by name and platform, a treatment by name within it, and a treatment localization
by locale; what's missing is created. Creative files are uploaded once to the App Asset Library and
placed as `store media push --only creative` places them; a slot with no file is left as it is.
Screenshots and previews go through the version push's own code (`upload.mirror_sets`), with its
rules: the slot from each file's pixel size, at most ten screenshots to a set, a developer-build HUD
refused, a preview checked as Apple would and sent with its poster frame, and a set replaced
wholesale, a slot the folder no longer fills deleted. A locale with no screenshots folder keeps the
sets it has, and a treatment with no preview anywhere keeps its preview sets.

App Store Connect fills a new treatment localization with copies of the live page's screenshot and
preview sets, so the push's deletions include those copies; a dry run, which can't see them, says so. Only a test still being prepared is written: Apple locks one once it is submitted, and
a finished test's name is refused rather than reused, so a new test gets a new name. A test that
exists but is no longer in `ppo/` is left alone.

Not pushed: treatment app icons, and sending a test to review or starting it. Those
are done in App Store Connect. Why: docs/design/screenshots.md#product-page-optimizations

No snakelane.yml keys: the folders are the configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, NamedTuple

from .. import project
from ..args import load_app, resolve_platform
from ..connect import asc
from ..connect.resources import find_app, keyed
from ..terminal import dim, green
from . import creative, upload
from .media import PREVIEW_SUFFIXES, deck_files, locale_dirs

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
    screenshots: dict[str, dict[str, list[Path]]]   # locale -> display type -> files; a locale with a folder
    previews: dict[str, dict[str, list[Path]]] = field(default_factory=dict)  # locale -> preview type -> files;
    # empty when the treatment has no preview anywhere, so its preview sets are left alone
    posters: dict[Path, str | None] = field(default_factory=dict)
    preview: dict[str, Any] | None = None   # experiment.yml's preview block, for `snakelane preview --ppo`

    @property
    def locales(self) -> list[str]:
        return list(dict.fromkeys([*self.slots, *self.screenshots]))

    def shows(self, locale: str) -> bool:
        """Whether the locale has anything to put on the treatment (an empty screenshots folder only clears)."""
        return bool(self.slots.get(locale) or any((self.screenshots.get(locale) or {}).values())
                    or any((self.previews.get(locale) or {}).values()))

    def screenshot_files(self) -> list[Path]:
        return [f for sets in self.screenshots.values() for files in sets.values() for f in files]


@dataclass(frozen=True)
class Test:
    folder: Path
    name: str
    traffic: int
    treatments: tuple[Treatment, ...]


# --- the local plan --------------------------------------------------------------------------------


def treatment_deck(base: Path, platform: str) -> Path:
    """The folder of a treatment's `<locale>/` decks, laid out as the version's."""
    return base / "screenshots" / platform


def treatment_screenshots(base: Path, platform: str, locales: list[str]) -> dict[str, dict[str, list[Path]]]:
    """Each locale's screenshots by display type, for the locales with a folder: the version deck's rules."""
    root = treatment_deck(base, platform)
    return {locale: upload.locale_screenshots(dirs) for locale in locales if (dirs := locale_dirs(root, locale))}


def treatment_previews(base: Path, platform: str, locales: list[str], label: str,
                       posters: dict[Path, str | None]) -> dict[str, dict[str, list[Path]]]:
    """Each locale's previews by type, checked as the version's are; {} when the treatment has none at
    all, which leaves its preview sets (App Store Connect's copies of the live page's) alone."""
    root = treatment_deck(base, platform)
    dirs = {locale: d for locale in locales if (d := locale_dirs(root, locale))}
    if not any(deck_files(d, PREVIEW_SUFFIXES, "preview", quiet=True) for d in dirs.values()):
        return {}
    return {locale: upload.locale_previews(d, f"{label} {locale}", posters) for locale, d in dirs.items()}


def parse_treatment(config_path: Path, sub: Any, value: Any) -> tuple[str, dict[str, Any] | None]:
    """A treatments entry: folder -> name, or folder -> {name, preview}."""
    if isinstance(value, dict):
        if unknown := set(value) - {"name", "preview", "_comment"}:
            raise SystemExit(f"{config_path}: treatment {sub!r} has unknown key(s) {', '.join(sorted(unknown))}; "
                             "it takes name and preview")
        if not isinstance(value.get("name"), str) or not value["name"].strip():
            raise SystemExit(f"{config_path}: treatment {sub!r} needs a name")
        if (block := value.get("preview")) is not None and not isinstance(block, dict):
            raise SystemExit(f"{config_path}: treatment {sub!r}'s preview is a mapping of previews keys")
        return value["name"].strip(), block
    if value is None or isinstance(value, (dict, list)):
        raise SystemExit(f"{config_path}: treatment {sub!r} needs a name")
    return str(value), None


def treatment_dirs(base: Path, platform: str, locale: str) -> list[Path]:
    root = base / "creative"
    return [root / platform / locale, root / platform / "default", root / locale, root / "default"]


def read_experiment(folder: Path) -> tuple[Path, str, int, dict[str, tuple[str, dict[str, Any] | None]]]:
    """experiment.yml, checked: its path, the test's name and traffic, and folder -> (treatment name,
    preview block). Nothing about the files: `snakelane preview --ppo` records into a treatment that
    may have none yet."""
    config_path = folder / "experiment.yml"
    if not config_path.is_file():
        raise SystemExit(f"no {config_path}: a test is a folder under ppo/ with an experiment.yml")
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
    entries = {str(sub): parse_treatment(config_path, sub, value) for sub, value in treatments.items()}
    names = [treatment for treatment, _ in entries.values()]
    if len(set(names)) != len(names):
        raise SystemExit(f"{config_path}: two treatments named alike; a treatment is found again by its name")
    return config_path, name.strip(), traffic, entries


def load_test(folder: Path, platform: str, locales: list[str]) -> Test:
    """One test folder, checked: a problem stops the run before anything is read from Apple."""
    config_path, name, traffic, entries = read_experiment(folder)
    parsed = []
    for sub, (treatment_name, preview_block) in entries.items():
        base = folder / str(sub)
        if not base.is_dir():
            raise SystemExit(f"{config_path}: no folder {base.relative_to(folder.parent)} for {treatment_name!r}")
        slots = {locale: s for locale in locales if (s := creative.slots_in(treatment_dirs(base, platform, locale)))}
        posters: dict[Path, str | None] = {}
        treatment = Treatment(str(sub), treatment_name, slots, treatment_screenshots(base, platform, locales),
                              treatment_previews(base, platform, locales, treatment_name, posters), posters,
                              preview_block)
        if not any(treatment.shows(locale) for locale in locales):
            raise SystemExit(f"{base}: no screenshots, previews or creative assets for {platform} in "
                             f"{', '.join(locales)}: a treatment shows nothing the live page doesn't")
        upload.check_screenshot_plan({f"{treatment.name} {locale}": sets
                                      for locale, sets in treatment.screenshots.items()})
        parsed.append(treatment)
    return Test(folder, name, traffic, tuple(parsed))


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
            for locale in treatment.locales:
                for kind, path in sorted(treatment.slots.get(locale, {}).items()):
                    print(f"    {treatment.name:<20} {locale:<8} {creative.SLOT_NAMES[kind]:<20} "
                          f"{path.relative_to(metadata)}")
                if (sets := treatment.screenshots.get(locale)) == {}:
                    print(f"    {treatment.name:<20} {locale:<8} {'screenshots':<20} "
                          "(empty folder: any live sets are deleted)")
                for display_type, files in sorted((sets or {}).items()):
                    print(f"    {treatment.name:<20} {locale:<8} {display_type:<20} "
                          f"{files[0].parent.relative_to(metadata)}/ {', '.join(f.name for f in files)}")
                if (previews := treatment.previews.get(locale)) == {}:
                    print(f"    {treatment.name:<20} {locale:<8} {'previews':<20} "
                          "(none in this locale's folder: any live preview sets are deleted)")
                for preview_type, files in sorted((previews or {}).items()):
                    print(f"    {treatment.name:<20} {locale:<8} {'preview ' + preview_type:<20} "
                          f"{files[0].parent.relative_to(metadata)}/ {', '.join(f.name for f in files)}")


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
    for locale in treatment.locales:
        if (localization := live.get(locale)) is None and not treatment.shows(locale):
            continue  # only an empty screenshots folder, and no localization holding sets to clear
        if localization is None:
            localization = client.post(f"/v1/{TREATMENT_LOCALIZATION}", asc.resource_body(
                TREATMENT_LOCALIZATION, {"locale": locale},
                relationships={"appStoreVersionExperimentTreatment": asc.relationship(TREATMENT, treatment_id)}))["data"]
            client.report(f"  created {treatment.name} {locale} ({localization['id']})")
            if asc.planned(localization["id"]):
                note_prefill(client, treatment, locale)
        targets[locale] = treatment_target(localization["id"], treatment.name, locale)
    return targets


def note_prefill(client: asc.Client, treatment: Treatment, locale: str) -> None:
    """A dry run can't read the sets Apple puts on a new localization, so it says what becomes of them."""
    kinds = [kind for kind, plan in (("screenshot", treatment.screenshots), ("preview", treatment.previews))
             if locale in plan]
    if not kinds:
        return
    filled = sorted(slot for plan in (treatment.screenshots, treatment.previews) for slot in plan.get(locale, {}))
    client.report(dim(f"    App Store Connect fills a new treatment localization with copies of the live page's "
                      f"{' and '.join(kinds)} sets; the push deletes every one but "
                      f"{', '.join(filled) or 'none'} (not listed here: the dry run can't read them)"))


def treatment_target(localization_id: str, treatment: str, locale: str) -> creative.Target:
    return creative.Target(TREATMENT_LOCALIZATION, "appStoreVersionExperimentTreatmentLocalization",
                           localization_id, f"{treatment} {locale}")


class Pushed(NamedTuple):
    placements: int                 # creative placements changed
    uploads: list[dict[str, Any]]   # screenshots uploaded, for the processing wait
    previews: list[dict[str, Any]]  # App Previews uploaded, likewise


def push_tests(client: asc.Client, app_id: str, platform: str, tests: list[Test],
               ref: creative.RefData | None) -> Pushed:
    """Every test's treatments, placements and screenshot sets. Every creative file is in the library
    and processed before the first test is touched, so a failed upload changes nothing; `ref` is
    None when no treatment has one."""
    paths = [p for test in tests for t in test.treatments for slots in t.slots.values() for p in slots.values()]
    assets = creative.upload_missing(client, app_id, paths) if paths else {}
    live = experiments(client, app_id, platform)
    changed, uploads, previews = 0, [], []
    for test in tests:
        experiment = find_or_create_test(client, app_id, platform, test, live)
        for treatment in test.treatments:
            treatment_id = find_or_create_treatment(client, experiment["id"], treatment.name)["id"]
            for locale, target in treatment_targets(client, treatment, treatment_id).items():
                if (slots := treatment.slots.get(locale)) and ref is not None:
                    changed += creative.place_slots(client, target, slots, assets, ref)
                if (sets := treatment.screenshots.get(locale)) is not None:
                    uploads += upload.mirror_sets(client, target, sets, upload.SCREENSHOTS)
                if (sets := treatment.previews.get(locale)) is not None:
                    previews += upload.mirror_sets(client, target, sets, upload.PREVIEWS,
                                                   upload.poster_attributes(treatment.posters))
    return Pushed(changed, uploads, previews)


# --- commands --------------------------------------------------------------------------------------


def cmd_ppo_push(args: SimpleNamespace) -> None:
    """Create or update each test in ppo/, place its treatments' creative assets and replace their screenshots."""
    folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    if not (tests := load_tests(folder, platform, app_config["locales"])):
        print(f"no tests under {folder.name}/ppo/ (a folder with an experiment.yml): nothing to do")
        return
    print(f"product page optimizations for {app_config.get('name', app_config['bundle_id'])} ({platform}):")
    print_tests(tests, folder)
    # Before --dry-run gets a pass, as for the version's deck.
    upload.refuse_developer_chrome_in(app_config, [f for test in tests for t in test.treatments
                                                   for f in t.screenshot_files()],
                                      allow=args.allow_developer_chrome)
    plan = {f"{test.name}/{t.name}/{locale}": slots for test in tests for t in test.treatments
            for locale, slots in t.slots.items()}
    if args.dry_run and not asc.Credentials.available():
        print("\n[dry-run] no API key set up (`snakelane auth setup`): the plan above is local only. Creative "
              "assets were not checked against Apple's specs, the live tests and screenshot sets were not "
              "read, and nothing was written.")
        return
    client = asc.Client(dry_run=args.dry_run)
    ref = creative.check_plan(client, plan) if plan else None
    app = find_app(client, app_config)
    pushed = push_tests(client, app["id"], platform, tests, ref)
    if client.dry_run:
        print("\n[dry-run] nothing was created, uploaded, placed or deleted.")
        return
    shots_ok = not pushed.uploads or upload.verify_screenshot_processing(client, pushed.uploads)
    previews_ok = not pushed.previews or upload.verify_preview_processing(client, pushed.previews)
    if not (shots_ok and previews_ok):
        raise SystemExit("Treatment screenshots or previews finished WITH FAILURES — see above.")
    print(f"\n{pushed.placements} placement(s) changed, {len(pushed.uploads)} screenshot(s) and "
          f"{len(pushed.previews)} preview(s) uploaded. Send the test to review and start it in App Store Connect.")


def cmd_ppo_show(args: SimpleNamespace) -> None:
    """Each test on the platform: state, traffic, treatments, their creative placements and screenshot sets."""
    _folder, app_config = load_app(args.app)
    platform = resolve_platform(app_config, args.platform)
    client = asc.Client()
    app = find_app(client, app_config)
    live = experiments(client, app["id"], platform)
    print(f"--- product page optimizations for {app_config['bundle_id']} ({platform}) ---")
    if not live:
        print("  (none)")
        return
    library: dict[str, str] | None = None

    def backing() -> dict[str, str]:
        # Only when a placement needs naming: a test without creative assets never reads the library,
        # whose reads Apple has failed with a 500 (2026-11-17).
        nonlocal library
        if library is None:
            library = creative.placement_labels(client, app["id"])
        return library

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
                    placed = live_slots.get(kind) or []
                    shown = ", ".join(backing().get(p["id"], p["id"]) for p in placed) if placed else "(none)"
                    print(f"    {name:<20} [{locale}] {creative.SLOT_NAMES[kind]:<20} {shown}")
                for kind, prefix in ((upload.SCREENSHOTS, ""), (upload.PREVIEWS, "preview ")):
                    show_sets(client, name, locale, localization["id"], kind, prefix)


def show_sets(client: asc.Client, treatment: str, locale: str, localization_id: str, kind: upload.Kind,
              prefix: str) -> None:
    sets = list(client.get_all(f"/v1/{TREATMENT_LOCALIZATION}/{localization_id}/{kind.sets}"))
    if not sets:
        print(f"    {treatment:<20} [{locale}] {kind.noun + 's':<20} (none)")
    for live in sets:
        names = [str(asc.attributes(s).get("fileName"))
                 for s in client.get_all(f"/v1/{kind.sets}/{live['id']}/{kind.items}")]
        print(f"    {treatment:<20} [{locale}] {prefix + str(asc.attributes(live).get(kind.type_key)):<20} "
              f"{len(names)} — {', '.join(names)}")
