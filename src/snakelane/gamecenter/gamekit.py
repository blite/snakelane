"""Reading Xcode's Game Center bundle (`*.gamekit`): which image belongs to which record and locale.

Xcode's Game Center editor writes a folder holding `gameCenterResources.json` and the PNGs it
names. The parts read here:

    resources.achievementImages        {localID: [{localID, url}]}  url is relative to the bundle
    resources.achievementLocalizations {vendorIdentifier: [{locale, localID, …}]}
    resources.leaderboardImages        as achievementImages
    resources.leaderboardLocalizations as achievementLocalizations
    resources.gameActivityDefaultImages {vendorIdentifier: {localID, url}}  one per activity, no locale
    resources.gameActivityLocalizations as achievementLocalizations
    resources.achievements             [{vendorIdentifier, points, archived, …}]  for lint's points check
                                       and to leave archived records out of `sync`
    resources.leaderboards             [{vendorIdentifier, recurrenceRule, recurrenceDuration, …}]
                                       for lint's recurrence check

A localID is mapped to its record and locale through the localizations, never by splitting the
string: a vendor identifier may itself contain hyphens.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESOURCES = "gameCenterResources.json"
SKIP_DIRS = {"build", "DerivedData", ".build", "Pods", "node_modules", "Carthage"}

# Apple's spec: RGB, no transparency. Achievement and leaderboard images are 1024×1024; an
# activity's default image is 3840×2160 (the challenge image size, and what ASC holds for one).
SIZES = {"achievement": (1024, 1024), "leaderboard": (1024, 1024), "activity": (3840, 2160)}

# App Store Connect's caps on achievement points. Xcode's sync sends them unchecked and, when ASC
# refuses one, shows nothing and creates nothing. Why: docs/design/foundations.md#game-center-points
MAX_ACHIEVEMENT_POINTS = 100
MAX_TOTAL_POINTS = 1_000

# What App Store Connect takes for a recurring leaderboard, which Xcode's editor doesn't check: a
# rule of minutes, hours or days only (no FREQ=WEEKLY), and a duration with a time part (PT168H,
# not P7D). A week is FREQ=DAILY;INTERVAL=7 for PT168H.
# Why: docs/design/foundations.md#recurring-leaderboards
RECURRENCE_RULE = re.compile(r"FREQ=(MINUTELY|HOURLY|DAILY);INTERVAL=[1-9][0-9]*")
RECURRENCE_DURATION = re.compile(r"P(?:[0-9]+D)?T(?=[0-9])(?:[0-9]+H)?(?:[0-9]+M)?(?:[0-9]+S)?")

# App Store Connect's cap on a localized name, in every language: its 409 is "'name' cannot be
# longer than '30' characters". Xcode's editor doesn't check it, and a translation runs longer
# than the English it was made from. Seen on a leaderboard; an achievement's title has the same
# cap in App Store Connect. Activities are left alone until one is refused.
# Why: docs/design/foundations.md#game-center-names
MAX_NAME_LENGTH = 30
NAME_CAPPED_KINDS = ("achievement", "leaderboard", "activity")


# Each kind's localized text, as the bundle and App Store Connect both name the fields.
LOCALIZATIONS = {"achievement": "achievementLocalizations", "leaderboard": "leaderboardLocalizations",
                 "activity": "gameActivityLocalizations"}
RECORDS = {"achievement": "achievements", "leaderboard": "leaderboards", "activity": "gameActivities"}
TEXT_FIELDS = {
    "achievement": ("name", "beforeEarnedDescription", "afterEarnedDescription"),
    "leaderboard": ("name", "description", "formatterOverride", "formatterSuffix", "formatterSuffixSingular"),
    "activity": ("name", "description"),
}


@dataclass(frozen=True)
class Text:
    """One record's words in one locale; `fields` holds only what the bundle sets (a blank or
    missing field is no opinion, never pushed)."""

    kind: str
    vendor_id: str
    locale: str
    fields: tuple[tuple[str, str], ...]

    @property
    def values(self) -> dict[str, str]:
        return dict(self.fields)


@dataclass(frozen=True)
class Image:
    kind: str            # achievement | leaderboard | activity
    vendor_id: str
    locale: str | None   # None: an activity's default image
    path: Path

    @property
    def label(self) -> str:
        return f"{self.kind} {self.vendor_id}" + (f" [{self.locale}]" if self.locale else "")


def find_bundle(root: Path, configured: str | None = None) -> Path:
    """`gamecenter.gamekit` (repo-relative), else the repo's only `*.gamekit` folder."""
    if configured:
        path = root / configured
        if not (path / RESOURCES).is_file():
            raise SystemExit(f'"gamecenter": {{"gamekit": {configured!r}}} in the config: no {RESOURCES} in {path}')
        return path
    found: list[Path] = []
    for here, dirs, _files in os.walk(root):
        if here.endswith(".gamekit"):
            found.append(Path(here))
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
    if len(found) == 1:
        return found[0]
    if not found:
        raise SystemExit(f"no *.gamekit folder under {root} — create one with Xcode's Game Center editor, "
                         'or set "gamecenter": {"gamekit": <path>} in the config')
    raise SystemExit(f"{len(found)} *.gamekit folders under {root} ("
                     + ", ".join(str(p.relative_to(root)) for p in sorted(found))
                     + '); name one with "gamecenter": {"gamekit": <path>} in the config')


def read_resources(bundle: Path) -> dict[str, Any]:
    try:
        return json.loads((bundle / RESOURCES).read_text()).get("resources") or {}
    except (OSError, ValueError) as error:
        raise SystemExit(f"{bundle / RESOURCES}: {error}") from None


def points_problems(bundle: Path) -> list[tuple[str, str]]:
    """(vendor identifier or "achievements", why) for every achievement worth more than ASC takes,
    and for a total over its cap. Archived achievements count: ASC keeps them."""
    achievements = read_resources(bundle).get("achievements") or []
    problems = [(a.get("vendorIdentifier", "?"), f"{points} points: App Store Connect takes 0 to "
                 f"{MAX_ACHIEVEMENT_POINTS} for an achievement, and Xcode's sync fails without a word")
                for a in achievements
                if not 0 <= (points := a.get("points") or 0) <= MAX_ACHIEVEMENT_POINTS]
    if (total := sum(a.get("points") or 0 for a in achievements)) > MAX_TOTAL_POINTS:
        problems.append(("achievements", f"{total} points in all: App Store Connect takes at most "
                         f"{MAX_TOTAL_POINTS:,} for an app"))
    return problems


def recurrence_problems(bundle: Path) -> list[tuple[str, str]]:
    """(vendor identifier, why) for every recurring leaderboard App Store Connect would refuse: a
    rule other than minutes, hours or days, or a duration without a time part. Xcode's sync sends
    them unchecked and, when ASC refuses one, leaves the board off ASC without a word."""
    problems = []
    for board in read_resources(bundle).get("leaderboards") or []:
        rule, duration = board.get("recurrenceRule"), board.get("recurrenceDuration")
        if rule is None and duration is None:
            continue
        vendor_id = board.get("vendorIdentifier", "?")
        if not RECURRENCE_RULE.fullmatch(rule or ""):
            problems.append((vendor_id, f"recurrence rule {rule!r}: App Store Connect takes only "
                             "FREQ=MINUTELY, HOURLY or DAILY with an INTERVAL (a week is "
                             "FREQ=DAILY;INTERVAL=7), and Xcode's sync fails without a word"))
        if not RECURRENCE_DURATION.fullmatch(duration or ""):
            problems.append((vendor_id, f"recurrence duration {duration!r}: App Store Connect takes an ISO "
                             "8601 duration with a time part (PT24H a day, PT168H a week, not P7D), and "
                             "Xcode's sync fails without a word"))
    return problems


def name_problems(bundle: Path) -> list[tuple[str, str]]:
    """(vendor identifier [locale], why) for every achievement, leaderboard or activity name longer
    than App Store Connect takes, in any language. Archived records are left out, as `read_texts`
    does."""
    return [(f"{text.vendor_id} [{text.locale}]",
             f"name {name!r} is {len(name)} characters: App Store Connect takes at most "
             f"{MAX_NAME_LENGTH} for {'a' if text.kind == 'leaderboard' else 'an'} {text.kind}'s name in "
             "any language, and refuses the sync partway through")
            for text in read_texts(bundle) if text.kind in NAME_CAPPED_KINDS
            if len(name := text.values.get("name", "")) > MAX_NAME_LENGTH]


def read_bundle(bundle: Path) -> tuple[list[Image], list[str]]:
    """(every image the bundle names, problems with the bundle itself). A missing file is not a
    problem here: the push reports and skips it."""
    resources = read_resources(bundle)
    images: list[Image] = []
    problems: list[str] = []
    for kind in ("achievement", "leaderboard"):
        owners = localized_ids(resources.get(f"{kind}Localizations") or {})
        for key, entries in sorted((resources.get(f"{kind}Images") or {}).items()):
            for entry in entries if isinstance(entries, list) else [entries]:
                local_id = entry.get("localID") or key
                if (owner := owners.get(local_id)) is None:
                    problems.append(f"{kind} image {local_id!r} has no {kind} localization with that localID")
                    continue
                images.append(Image(kind, owner[0], owner[1], bundle / entry["url"]))
    for vendor_id, entry in sorted((resources.get("gameActivityDefaultImages") or {}).items()):
        images.append(Image("activity", vendor_id, None, bundle / entry["url"]))
    return images, problems


def read_texts(bundle: Path) -> list[Text]:
    """Every localization the bundle holds, archived records left out."""
    resources = read_resources(bundle)
    texts: list[Text] = []
    for kind, key in LOCALIZATIONS.items():
        records = resources.get(RECORDS[kind]) or []
        archived = {r.get("vendorIdentifier") for r in (records if isinstance(records, list) else [])
                    if r.get("archived")}
        for vendor_id, items in sorted((resources.get(key) or {}).items()):
            if vendor_id in archived:
                continue
            for item in items or []:
                if not item.get("locale"):
                    continue
                fields = tuple((f, item[f]) for f in TEXT_FIELDS[kind] if item.get(f) not in (None, ""))
                texts.append(Text(kind, vendor_id, item["locale"], fields))
    return texts


def localized_ids(localizations: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """localID -> (vendorIdentifier, locale)."""
    return {item["localID"]: (vendor_id, item["locale"])
            for vendor_id, items in localizations.items() for item in items or []
            if item.get("localID") and item.get("locale")}


def image_problem(image: Image) -> str | None:
    """Why ASC would refuse the file (size, transparency), checked before any network call."""
    from PIL import Image as PILImage

    try:
        with PILImage.open(image.path) as opened:
            size, mode, info = opened.size, opened.mode, opened.info
    except OSError as error:
        return f"cannot read {image.path.name}: {error}"
    if size != (want := SIZES[image.kind]):
        return f"{image.path.name} is {size[0]}×{size[1]}; a {image.kind} image must be {want[0]}×{want[1]}"
    if mode in ("RGBA", "LA", "PA") or "transparency" in info:
        return f"{image.path.name} has an alpha channel; ASC wants RGB with no transparency (flatten it)"
    if mode not in ("RGB", "L", "P"):
        return f"{image.path.name} is {mode}; ASC wants RGB"
    return None


def same_pixels(local: Path, remote: Any) -> bool:
    """Compared as RGB: ASC re-encodes what it is sent (a PNG comes back RGBA, bytes and checksum
    differ), so only the pixels say whether the live image is this file.
    Why: docs/design/gamecenter.md#pixels-not-bytes"""
    from PIL import Image as PILImage
    from PIL import ImageChops

    with PILImage.open(local) as opened:
        mine = opened.convert("RGB")
    theirs = remote.convert("RGB")
    return mine.size == theirs.size and ImageChops.difference(mine, theirs).getbbox() is None
