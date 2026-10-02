"""`snakelane lint`: lint the listing for what App Review rejects, before a push.

    snakelane lint [--check-urls] [--strict] [--json]   # every locale in snakelane.yml, offline

Reads the same resolved text `store push` sends; `store push` (and `--dry-run`) stops on its errors and
`ship release` runs it over the live listing. `--skip-lint` on either overrides it for one run.

Rules (error = blocks the push; warning = printed):

    field-length          error    over ASC's limit (name/subtitle 30, keywords 100, …)
    rejected-character    error    dingbats/emoji ASC refuses with a 409 mid-push
    other-platform        error    Android, Google Play, … (guideline 2.3.10)
    placeholder           error    TODO, FIXME, TBD, XXX, lorem ipsum, {{…}}
    profanity             error    obviously objectionable words (guideline 1.1)
    url-format            error    a URL field that isn't an absolute http(s) URL
    url-unreachable       error    only with --check-urls: no 2xx/3xx answer
    subscription-links    error    sells subscriptions without privacy and terms URLs in every description (3.1.2)
    future-functionality  warning  "coming soon", "in a future update" (guideline 2.1)
    test-word             warning  "beta", "trial version", "pre-release" framing
    apple-sentiment       warning  disparaging Apple or its platforms (guideline 3.2.2)
    keyword-format        warning  spaces after commas, duplicates, empty entries, words in the name/subtitle

Phrases are bounded by Latin letters rather than `\\b`; placeholders are case-sensitive.
Why: docs/design/foundations.md#lint-matching-rules

## snakelane.yml

    "lint": {"ignore": ["test-word", …]}   rules to skip for this app; default none
    "terms_url": "https://…/terms/"         Terms of Use subscription-links looks for; default Apple's EULA
Why subscription-links: docs/adr/0003-lint-subscription-legal-links.md
"""

from __future__ import annotations

import functools
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from .. import project
from ..args import AppOption, PlatformOption, command_app, resolve_platform
from ..args import run as run_cli
from .fields import (
    TEXT_FIELDS,
    URL_FIELDS,
    hard_limit_problems,
    read_listing,
    read_review,
)

# Outside English only the note form ("TODO:", "TODO(", line end) counts: TODO is Spanish for "all".
TODO_ANY = re.compile(r"(?<![A-Za-z])TODO(?![A-Za-z])")
TODO_NOTE = re.compile(r"(?<![A-Za-z])TODO(?=\s*[:(\]]|\s*$)", re.MULTILINE)
PLACEHOLDER = 'placeholder "{}" in shipped copy'
# (phrases, rule, severity, message, case-sensitive)
PHRASE_RULES = [
    (["android", "google play", "play store", "blackberry", "windows phone", "kindle fire", "galaxy store",
      "huawei appgallery"], "other-platform", "error",
     'mentions "{}"; App Review rejects listings naming other platforms (2.3.10)', False),
    (["FIXME", "TBD", "XXX"], "placeholder", "error", PLACEHOLDER, True),
    (["lorem ipsum", "{{", "}}", "[insert"], "placeholder", "error", PLACEHOLDER, False),
    (["fuck", "fucking", "shit", "cunt", "motherfucker", "bullshit", "asshole"], "profanity", "error",
     'objectionable word "{}" (1.1)', False),
    (["coming soon", "in a future update", "in an upcoming update", "in the next update", "will be added soon",
      "stay tuned"], "future-functionality", "warning", '"{}" promises unshipped features (2.1)', False),
    (["beta", "trial version", "pre-release", "prerelease", "test version", "demo version"], "test-word", "warning",
     '"{}" reads as unfinished software (2.2)', False),
]
APPLE_TERMS = r"(?:apple|ios|ipados|iphone|ipad|app store|macos|mac)"
APPLE_NEGATIVE = re.compile(
    rf"(?i)(?<![a-z])(?:{APPLE_TERMS}\s+(?:\w+\s+){{0,2}}(?:sucks?|is terrible|is awful|is broken|"
    rf"is garbage|rip-?off)|(?:hate|screw|ditch)\s+(?:the\s+)?{APPLE_TERMS})(?![a-z])"
)
APPLE_EULA = "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/"


@dataclass
class Finding:
    severity: str  # "error" | "warning"
    rule: str
    where: str     # "en-US/description" or "review/notes"
    message: str
    excerpt: str = ""


@functools.cache
def phrase_pattern(phrase: str, cased: bool = False) -> re.Pattern[str]:
    """Bounded by Latin letters only, so unspaced scripts (ja, zh, ko, th) still match."""
    edge_l = "(?<![A-Za-z])" if phrase[0].isalpha() else ""
    edge_r = "(?![A-Za-z])" if phrase[-1].isalpha() else ""
    return re.compile(edge_l + re.escape(phrase) + edge_r, 0 if cased else re.IGNORECASE)


def excerpt(text: str, match: re.Match[str], width: int = 30) -> str:
    start, end = max(0, match.start() - width), min(len(text), match.end() + width)
    return ("…" if start else "") + text[start:end].replace("\n", " ") + ("…" if end < len(text) else "")


def keyword_findings(keywords: str, where: str, name: str | None, subtitle: str | None) -> list[Finding]:
    entries = [k.strip() for k in keywords.split(",")]
    messages = []
    if re.search(r",\s", keywords):
        messages.append("spaces after commas spend the 100-character budget")
    if not all(entries):
        messages.append("empty entry (doubled or trailing comma)")
    seen: set[str] = set()
    for entry in (k.casefold() for k in entries if k):
        if entry in seen:
            messages.append(f'repeats "{entry}"')
        seen.add(entry)
    title_words = {w.casefold() for w in re.findall(r"\w+", f"{name or ''} {subtitle or ''}")}
    if wasted := [k for k in dict.fromkeys(k.casefold() for k in entries if k) if k in title_words]:
        messages.append(f"already indexed from the name/subtitle: {', '.join(wasted)}")
    return [Finding("warning", "keyword-format", where, m) for m in messages]


def text_findings(text: str, where: str, english: bool = True) -> list[Finding]:
    found = []
    if todo := (TODO_ANY if english else TODO_NOTE).search(text):
        found.append(Finding("error", "placeholder", where, 'placeholder "TODO" in shipped copy', excerpt(text, todo)))
    for phrases, rule, severity, message, cased in PHRASE_RULES:
        found += [Finding(severity, rule, where, message.format(m.group(0)), excerpt(text, m))
                  for phrase in phrases if (m := phrase_pattern(phrase, cased).search(text))]
    if match := APPLE_NEGATIVE.search(text):
        found.append(Finding("warning", "apple-sentiment", where,
                             "disparages Apple or its platforms (3.2.2)", excerpt(text, match)))
    return found


def legal_terms_url(app: project.App, platform_dir: Path) -> str | None:
    """The Terms of Use URL descriptions must carry, or None when the app sells no subscriptions."""
    from ..purchases.catalogue import catalogue_path, read_catalogue

    if not catalogue_path(platform_dir).exists() or not read_catalogue(platform_dir)[1].get("subscription_groups"):
        return None
    return app.config.get("terms_url") or APPLE_EULA


def links_to(text: str, url: str) -> bool:
    """`url` appears as a whole URL, with or without its trailing slash."""
    return re.search(re.escape(url.rstrip("/")) + r"/?(?=$|[\s)\]>.,;:!?'\"])", text) is not None


def legal_link_findings(values: dict[str, dict[str, str | None]], terms_url: str) -> list[Finding]:
    """Each description must link its privacy policy and the Terms of Use; no description, no check (as push)."""
    found = []
    sells = "the app sells subscriptions, so"
    for locale, fields in values.items():
        if not (description := fields.get("description")):
            continue
        where = f"{locale}/description"
        privacy = fields.get("privacy_url")
        if not privacy:
            found.append(Finding("error", "subscription-links", where, f"{sells} this locale needs a privacy "
                                 "policy URL (privacy_url.txt), linked from the description"))
        elif not links_to(description, privacy):
            found.append(Finding("error", "subscription-links", where,
                                 f"{sells} the description must link the privacy policy: {privacy}"))
        if not links_to(description, terms_url):
            found.append(Finding("error", "subscription-links", where,
                                 f"{sells} the description must link the Terms of Use: {terms_url}"
                                 + (" (set terms_url in snakelane.yml for your own terms page)"
                                    if terms_url == APPLE_EULA else "")))
    return found


def lint(values: dict[str, dict[str, str | None]], review_notes: str | None,
         terms_url: str | None = None) -> list[Finding]:
    """Every rule but URL reachability over {locale: {stem: text}}; `terms_url` turns on subscription-links."""
    found: list[Finding] = []
    for locale, fields in values.items():
        for stem in TEXT_FIELDS:
            if not (text := fields.get(stem)):
                continue
            where = f"{locale}/{stem}"
            found += [Finding("error", rule, where, message) for rule, message in hard_limit_problems(stem, text)]
            found += text_findings(text, where, english=locale.startswith("en"))
            if stem == "keywords":
                found += keyword_findings(text, where, fields.get("name"), fields.get("subtitle"))
        found += [Finding("error", "url-format", f"{locale}/{stem}", f"{url!r} is not an absolute http(s) URL")
                  for stem in URL_FIELDS
                  if (url := fields.get(stem)) and not re.match(r"https?://[^\s/]+\.[^\s]+$", url)]
    if review_notes:
        found += [f for f in text_findings(review_notes, "review/notes") if f.rule in ("placeholder", "profanity")]
    if terms_url:
        found += legal_link_findings(values, terms_url)
    return found


def url_findings(values: dict[str, dict[str, str | None]], terms_url: str | None = None) -> list[Finding]:
    """One request per distinct URL; reachable means any answer below 400."""
    import requests  # only --check-urls needs the network stack

    urls: dict[str, str] = {terms_url: "terms_url"} if terms_url else {}
    for locale, fields in values.items():
        for stem in URL_FIELDS:
            if (url := fields.get(stem)) and url.startswith(("http://", "https://")):
                urls.setdefault(url, f"{locale}/{stem}")
    found = []
    for url, where in urls.items():
        try:
            response = requests.get(url, timeout=15, allow_redirects=True, headers={"User-Agent": "snakelane-lint"})
            ok, why = response.status_code < 400, f"HTTP {response.status_code}"
        except requests.RequestException as error:
            ok, why = False, type(error).__name__
        if not ok:
            found.append(Finding("error", "url-unreachable", where, f"{url} did not answer ({why})"))
    return found


def run(app: project.App, platform: str, check_urls: bool = False) -> list[Finding]:
    platform_dir, locales = app.platform_dir(platform), app.locales
    terms_url = legal_terms_url(app, platform_dir)
    values = read_listing(platform_dir, locales)
    found = lint(values, read_review(platform_dir).get("notes"), terms_url)
    if check_urls:
        found += url_findings(values, terms_url)
    return ignored(app, found)


def report(found: list[Finding]) -> None:
    for f in sorted(found, key=lambda f: (f.where, f.severity != "error", f.rule)):
        print(f"{'✗' if f.severity == 'error' else '!'} {f.where}  [{f.rule}]  {f.message}")
        if f.excerpt:
            print(f"      > {f.excerpt}")
    errors = sum(f.severity == "error" for f in found)
    print(f"lint: {errors} error(s), {len(found) - errors} warning(s)")


def ignored(app: project.App, found: list[Finding]) -> list[Finding]:
    rules = set((app.config.get("lint") or {}).get("ignore", []))
    return [f for f in found if f.rule not in rules]


def gate(app: project.App, platform: str, found: list[Finding] | None = None) -> None:
    """Print findings and stop on errors (for `store push` and `ship release`)."""
    found = run(app, platform) if found is None else found
    if not found:
        print("lint: clean")
        return
    report(found)
    if any(f.severity == "error" for f in found):
        raise SystemExit("lint found listing problems App Review rejects — fix them, add the rule "
                         'to snakelane.yml\'s "lint": {"ignore": […]}, or pass --skip-lint')


cli = command_app("Lint the listing for what App Review rejects, offline.")


@cli.command()
def lint_command(
    app: AppOption = None,
    platform: PlatformOption = None,
    check_urls: Annotated[bool, typer.Option(help="also request every URL field")] = False,
    strict: Annotated[bool, typer.Option(help="exit non-zero on warnings too")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="print findings as JSON")] = False,
) -> None:
    resolved = project.resolve_app(app)
    found = run(resolved, resolve_platform(resolved.config, platform), check_urls=check_urls)
    if json_output:
        json.dump([asdict(f) for f in found], sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        report(found)
    if any(f.severity == "error" or strict for f in found):
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane lint")
