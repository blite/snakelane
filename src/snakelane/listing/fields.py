"""The listing's fields: where each lives in metadata/, its ASC attribute, Apple's limits, categories, age rating."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import layout


@dataclass(frozen=True)
class Field:
    """One piece of listing text: its file, where App Store Connect keeps it, and how much Apple takes."""
    stem: str                # <stem>.txt in metadata/; the key every command uses for it
    api: str                 # the ASC attribute
    home: str                # "app": AppInfoLocalization, one per locale whatever the platform;
                             # "version": the version's localization; "review": the App Review card
    limit: int | None = None
    masked: bool = False     # kept out of scrollback and CI logs

    @property
    def url(self) -> bool:
        return self.api.endswith("Url")


FIELDS = (
    Field("name", "name", "app", 30),
    Field("subtitle", "subtitle", "app", 30),
    Field("privacy_url", "privacyPolicyUrl", "app", 255),
    Field("privacy_choices_url", "privacyChoicesUrl", "app", 255),  # optional: where users opt out or delete data
    Field("description", "description", "version", 4000),
    Field("keywords", "keywords", "version", 100),
    Field("promotional_text", "promotionalText", "version", 170),
    Field("marketing_url", "marketingUrl", "version", 255),
    Field("support_url", "supportUrl", "version", 255),
    Field("release_notes", "whatsNew", "version", 4000),
    # The App Review card: per platform, not localized. Names match fastlane's review_information/.
    Field("first_name", "contactFirstName", "review"),
    Field("last_name", "contactLastName", "review"),
    Field("phone_number", "contactPhone", "review"),
    Field("email_address", "contactEmail", "review"),
    Field("demo_user", "demoAccountName", "review"),
    Field("demo_password", "demoAccountPassword", "review", masked=True),
    Field("notes", "notes", "review", 4000),
)
BY_STEM = {f.stem: f for f in FIELDS}
LISTING = {f.stem: f for f in FIELDS if f.home != "review"}  # per locale
REVIEW = {f.stem: f for f in FIELDS if f.home == "review"}
TEXT_FIELDS = tuple(stem for stem, f in LISTING.items() if not f.url)
URL_FIELDS = tuple(stem for stem, f in LISTING.items() if f.url)


def mask(stem: str, value: Any) -> Any:
    """A masked field's value as "•••", so it stays out of scrollback and CI logs."""
    return "•••" if value and stem in BY_STEM and BY_STEM[stem].masked else value


def read_text(path: Path) -> str | None:
    """None for missing or blank: blank is "no opinion", never a value."""
    return (path.read_text().strip() or None) if path.is_file() else None


def text_candidates(platform_dir: Path, locale: str, name: str) -> list[Path]:
    """The platform's <locale>, its default, the shared <locale>, the shared default — most specific first.

    Why: docs/design/foundations.md#the-listing-is-written-once-platforms-override
    """
    return layout.text_candidates(platform_dir, locale, name)


def read_field(platform_dir: Path, locale: str, field: str) -> str | None:
    """App-level fields (one per locale at ASC) refuse a platform copy, or the last platform pushed would win."""
    candidates = text_candidates(platform_dir, locale, f"{field}.txt")
    if LISTING[field].home == "app":
        if stray := [i for i in (0, 1) if candidates[i].is_file()]:
            raise SystemExit(f"{candidates[stray[0]]}: {field} is the same on every platform at App Store "
                             f"Connect; move it to {candidates[stray[0] + 2]}")
        candidates = candidates[2:]
    return next((text for c in candidates if (text := read_text(c)) is not None), None)


def read_copyright(platform_dir: Path, app_config: dict[str, Any] | None = None) -> str | None:
    """One per version, not per locale: snakelane.yml's `copyright`, a setting like the review contact.
    A platform's copyright.txt still overrides it; a shared copyright.txt is the older home, read
    only when the config has none."""
    own, shared = layout.copyright_candidates(platform_dir)
    if text := read_text(own):
        return text
    configured = (app_config or {}).get("copyright")
    if configured not in (None, ""):
        if read_text(shared):
            raise SystemExit(f"{shared}: copyright is also in snakelane.yml; keep one (delete the file)")
        return str(configured).strip()
    return read_text(shared)


def read_listing(platform_dir: Path, locales: list[str]) -> dict[str, dict[str, str | None]]:
    """{locale: {stem: text}}: what push sends, lint checks and ship compares with the live listing."""
    return {locale: {stem: read_field(platform_dir, locale, stem) for stem in LISTING} for locale in locales}


# snakelane.yml's review.contact / review.demo keys, by field stem.
CONFIG_REVIEW = {"first_name": ("contact", "first_name"), "last_name": ("contact", "last_name"),
                 "email_address": ("contact", "email"), "phone_number": ("contact", "phone"),
                 "demo_user": ("demo", "user"), "demo_password": ("demo", "password")}


def review_config(app_config: dict[str, Any] | None) -> dict[str, str]:
    """The contact and demo account from snakelane.yml's `review`: they rarely change and are the
    same for every platform, so they are settings rather than listing text."""
    review = (app_config or {}).get("review") or {}
    if not isinstance(review, dict) or set(review) - {"contact", "demo", "_comment"}:
        raise SystemExit('snakelane.yml "review" takes "contact" {first_name, last_name, email, phone} '
                         'and "demo" {user, password}')
    found = {}
    for stem, (group, key) in CONFIG_REVIEW.items():
        if (value := (review.get(group) or {}).get(key)) not in (None, ""):
            found[stem] = str(value).strip()
    return found


def read_review(platform_dir: Path, app_config: dict[str, Any] | None = None) -> dict[str, str]:
    """The App Review card: contact and demo account from snakelane.yml, notes from the listing
    (`default/review_notes.txt`, a platform's own first). Flat layout: per field `<platform>/review/`
    then `review/`, with snakelane.yml's values winning where it has them."""
    configured = review_config(app_config)
    if layout.kind_first(platform_dir.parent):
        if stray := layout.stray_review_notes(platform_dir):
            raise SystemExit(f"{stray[0]}: App Store Connect keeps one review note per version, not per "
                             "language; the notes go in default/review_notes.txt")
        notes = next((text for c in layout.review_notes_candidates(platform_dir) if (text := read_text(c))), None)
        return configured | ({"notes": notes} if notes else {})
    from_files = {stem: text for stem in REVIEW
                  if (text := next((t for d in layout.review_dirs(platform_dir)
                                    if (t := read_text(d / f"{stem}.txt"))), None))}
    return from_files | configured


# App Store Connect refuses any write to the review card while one of these is empty on it.
# Why: docs/design/foundations.md#the-review-contact-is-required-on-every-write
CONTACT = ("first_name", "last_name", "email_address", "phone_number")


def review_format_problems(review: dict[str, str]) -> list[str]:
    """Local contact values Apple would reject: the phone needs `+` and a country code."""
    problems = []
    if (phone := review.get("phone_number")) and not re.fullmatch(r"\+\d[\d ().-]{5,}", phone):
        problems.append(f"review/phone_number: {phone!r} — start with + and the country code, e.g. +1 555 123 4567")
    if (email := review.get("email_address")) and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        problems.append(f"review/email_address: {email!r} is not an email address")
    return problems


def missing_contact(local: dict[str, str], live: dict[str, Any]) -> list[str]:
    """Contact fields neither the local files nor App Store Connect's card has a value for."""
    return [stem for stem in CONTACT if not local.get(stem) and not live.get(stem)]


def review_attributes(review: dict[str, str]) -> dict[str, Any]:
    """The card as App Store Connect takes it; a demo account is also flagged as required."""
    attrs: dict[str, Any] = {REVIEW[stem].api: value for stem, value in review.items()}
    return attrs | {"demoAccountRequired": True} if "demoAccountName" in attrs else attrs


# `primarySubcategoryOne`, NOT `primaryCategoryOne`. Why: docs/design/foundations.md#category-relationship-names
CATEGORY_RELATIONSHIP_NAMES = {
    "primary": "primaryCategory",
    "primary_subcategory_one": "primarySubcategoryOne",
    "primary_subcategory_two": "primarySubcategoryTwo",
    "secondary": "secondaryCategory",
    "secondary_subcategory_one": "secondarySubcategoryOne",
    "secondary_subcategory_two": "secondarySubcategoryTwo",
}
CATEGORY_INCLUDE = ",".join(CATEGORY_RELATIONSHIP_NAMES.values())
CATEGORY_PARENTS = ("GAMES", "STICKERS")
# GET /v1/appCategories on 2026-10-02, for offline dry runs only; a real push checks the live list.
APP_CATEGORIES = frozenset("""
    BOOKS BUSINESS DEVELOPER_TOOLS EDUCATION ENTERTAINMENT FINANCE FOOD_AND_DRINK GAMES GRAPHICS_AND_DESIGN
    HEALTH_AND_FITNESS LIFESTYLE MAGAZINES_AND_NEWSPAPERS MEDICAL MUSIC NAVIGATION NEWS PHOTO_AND_VIDEO
    PRODUCTIVITY REFERENCE SHOPPING SOCIAL_NETWORKING SPORTS STICKERS TRAVEL UTILITIES WEATHER
    GAMES_ACTION GAMES_ADVENTURE GAMES_BOARD GAMES_CARD GAMES_CASINO GAMES_CASUAL GAMES_FAMILY GAMES_MUSIC
    GAMES_PUZZLE GAMES_RACING GAMES_ROLE_PLAYING GAMES_SIMULATION GAMES_SPORTS GAMES_STRATEGY GAMES_TRIVIA
    GAMES_WORD STICKERS_ANIMALS STICKERS_ART STICKERS_CELEBRATIONS STICKERS_CELEBRITIES STICKERS_CHARACTERS
    STICKERS_EATING_AND_DRINKING STICKERS_EMOJI_AND_EXPRESSIONS STICKERS_FASHION STICKERS_GAMING
    STICKERS_KIDS_AND_FAMILY STICKERS_MOVIES_AND_TV STICKERS_MUSIC STICKERS_PEOPLE STICKERS_PLACES_AND_OBJECTS
    STICKERS_SPORTS_AND_ACTIVITIES
""".split())


def category_problems(categories: dict[str, Any], known: frozenset[str] | set[str]) -> list[str]:
    """Unknown category, a subcategory in a main slot, or one outside its slot's parent."""
    problems = []
    for slot, value in categories.items():
        if not value:
            continue
        if value not in known:
            problems.append(f"{slot}: {value!r} is not an App Store category")
            continue
        is_sub = value.startswith(tuple(f"{p}_" for p in CATEGORY_PARENTS))
        if "subcategory" in slot:
            main = slot.split("_subcategory")[0]
            parent = categories.get(main)
            if not is_sub or not parent or not value.startswith(f"{parent}_"):
                problems.append(f"{slot}: {value!r} is not a subcategory of {parent or f'(no {main} set)'}")
        elif is_sub:
            problems.append(f"{slot}: {value!r} is a subcategory; it goes in {slot}_subcategory_one/two")
    return problems


def age_rating_attributes(block: dict[str, Any]) -> dict[str, Any]:
    """snake_case -> camelCase, not a fixed list. Why: docs/design/foundations.md#age-rating-keys-are-not-hardcoded"""
    def camel(key: str) -> str:
        head, *rest = key.split("_")
        return head + "".join(part[:1].upper() + part[1:] for part in rest)
    return {camel(key): value for key, value in (block or {}).items()}


def rejected_characters(value: str) -> list[str]:
    """Dingbats and emoji, which ASC refuses (unpublished). Why: docs/design/foundations.md#refused-characters-in-listing-text"""
    return list(dict.fromkeys(c for c in value if 0x2700 <= ord(c) <= 0x27BF or ord(c) >= 0x1F000))


def hard_limit_problems(stem: str, value: str | None) -> list[tuple[str, str]]:
    """(rule, message) for each way ASC would refuse `value`; shared by push and lint, and checked
    before any network call so a push never 409s halfway."""
    if not value:
        return []
    problems = []
    if (limit := BY_STEM[stem].limit) and len(value) > limit:
        problems.append(("field-length", f"{len(value)} characters (limit {limit})"))
    if bad := rejected_characters(value):
        problems.append(("rejected-character", f"contains {' '.join(bad)}, which App Store Connect rejects"))
    return problems
