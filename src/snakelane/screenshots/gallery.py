"""`snakelane gallery`: one HTML page of every deck and listing, for review before a push.

    snakelane gallery [--app A] [--open]
    snakelane gallery --live              # each deck beside what App Store Connect has now
    snakelane gallery --git               # each deck beside the last commit's
    snakelane gallery --bundle out/       # self-contained folder (CI artifact, sharing)

Writes `/tmp/snakelane-<app>-gallery.html`: per locale, store mocks, lint and translation status,
every deck in upload order, and each shot's new/changed/unchanged/removed. Why: docs/design/framing.md#the-gallery.

snakelane.yml:
    "gallery": {"icon": "App/…/icon.png"}   repo-relative mock icon (default: AppIcon.appiconset, store, DerivedData)
    "primary_locale": "en-US"               the store's primary language (default: first of "locales"; --live checks)
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import typer

from .. import project
from ..args import AppOption, PlatformOption, command_app, resolve_platform
from ..args import run as run_cli
from ..connect import asc
from ..connect.resources import find_app, find_listing_version, source_checksum
from ..listing import lint, translations
from ..listing.fields import LISTING, TEXT_FIELDS, read_field
from . import media

SKIP_DIRS = {"build", "DerivedData", ".build", "Pods", "node_modules", ".git"}
FOLDER_FAMILIES = {"iphone": "iPhone", "ipad": "iPad"}  # device folder -> what the page calls it
THUMB_WIDTH = 400  # live thumbnails: enough to compare, a fraction of the bytes


class Assets:
    """file:// links, or copies under a bundle directory with relative links."""

    def __init__(self, bundle: Path | None) -> None:
        self.bundle, self.copied = bundle, {}
        if bundle is not None:
            (bundle / "img").mkdir(parents=True, exist_ok=True)

    def url(self, path: Path) -> str:
        path = path.resolve()
        if self.bundle is None:
            return path.as_uri()
        if path not in self.copied:
            key = hashlib.sha1(str(path).encode()).hexdigest()[:10]
            self.copied[path] = f"img/{key}-{re.sub(r'[^A-Za-z0-9._-]', '_', path.name)}"
            shutil.copy2(path, self.bundle / self.copied[path])
        return self.copied[path]

    def scratch(self, name: str) -> Path:
        """A place for generated files (HEAD blobs)."""
        root = (self.bundle / "img" / "generated") if self.bundle else Path("/tmp") / "snakelane-gallery-files"
        root.mkdir(parents=True, exist_ok=True)
        return root / name


@dataclass
class Shot:
    path: Path
    dimensions: tuple[int, int] | None = None  # None when unreadable
    status: str = ""           # new / changed / unchanged, when comparing
    before: str | None = None  # URL of the comparison's version, when it differs


@dataclass
class Deck:
    family: str          # iPhone / iPad / Mac
    platform: str        # the store platform it uploads into: ios, macos
    folder: Path
    shots: list[Shot]
    previews: list[Path]
    removed: list[tuple[str, str]] = field(default_factory=list)  # (label, url)


@dataclass
class Live:
    version: str
    primary_locale: str | None
    sets: dict[str, dict[str, list[dict[str, Any]]]]  # locale -> display type -> shots


def local_decks(app: project.App, locale: str) -> list[Deck]:
    """The decks as the push reads them. An empty locale folder is kept: the push deletes its live sets."""
    found = []
    for platform in app.config.get("platforms") or ["ios"]:
        dirs = media.deck_dirs(app.folder / platform, locale)
        for folder in dirs:
            shots = []
            for path in media.deck_files([folder], media.DECK_SUFFIXES, "screenshot", quiet=True):
                try:
                    shots.append(Shot(path, media.screenshot_dimensions(path)))
                except (ValueError, OSError):
                    shots.append(Shot(path))
            previews = media.deck_files([folder], media.PREVIEW_SUFFIXES, "preview", quiet=True)
            is_root = folder == dirs[0]
            if is_root and not shots and not previews and len(dirs) > 1:
                continue  # the locale folder only holds iphone/ and ipad/
            family = ((None if is_root else FOLDER_FAMILIES.get(folder.name))
                      or ("Mac" if platform == "macos" else "iPhone"))
            found.append(Deck(family, platform, folder, shots, previews))
    return found


def upload_checksum(path: Path) -> str:
    return source_checksum(path.read_bytes())


def git(app: project.App, *args: str, binary: bool = False) -> Any:
    result = subprocess.run(["git", "-C", str(app.root), *args], capture_output=True, check=False)
    if result.returncode == 0:
        return result.stdout if binary else result.stdout.decode().strip()


def compare_git(app: project.App, decks: list[Deck], assets: Assets) -> None:
    if git(app, "rev-parse", "HEAD") is None:
        raise SystemExit(f"--git: {app.root} has no commits to compare against")

    def blob_url(blob: str, name: str) -> str:
        if not (path := assets.scratch(f"{blob[:12]}-{name}")).exists():
            path.write_bytes(git(app, "cat-file", "blob", blob, binary=True) or b"")
        return assets.url(path)

    for deck in decks:
        listing = git(app, "ls-tree", "HEAD", f"{deck.folder.relative_to(app.root)}/") or ""
        rows = (line.partition("\t") for line in listing.splitlines())
        head = {Path(path).name: meta.split()[2] for meta, _, path in rows}
        # One `git hash-object` for the whole deck: it prints a hash per path, in order.
        local = (git(app, "hash-object", "--", *(str(s.path) for s in deck.shots)) or "").split() if deck.shots else []
        if len(local) != len(deck.shots):
            raise SystemExit(f"--git: git hash-object failed for {deck.folder}")
        for shot, local_hash in zip(deck.shots, local, strict=True):
            if (blob := head.pop(shot.path.name, None)) is None:
                shot.status = "new"
            elif local_hash == blob:
                shot.status = "unchanged"
            else:
                shot.status, shot.before = "changed", blob_url(blob, shot.path.name)
        deck.removed += [(name, blob_url(blob, name)) for name, blob in sorted(head.items()) if not
                         name.startswith("_") and Path(name).suffix.lower() in media.IMAGE_SUFFIXES]


def fetch_live(app: project.App, platform: str) -> Live:
    """Read-only: the version a push would write to (else the live one) and its screenshot sets."""
    client = asc.Client()
    found = find_app(client, app.config)
    version = find_listing_version(client, found["id"], platform)
    sets: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if version is None:
        return Live("no version", asc.attributes(found).get("primaryLocale"), sets)
    attrs = asc.attributes(version)
    for loc in client.get_all(f"/v1/appStoreVersions/{version['id']}/appStoreVersionLocalizations"):
        for shot_set in client.get_all(f"/v1/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets"):
            shots = client.get_all(f"/v1/appScreenshotSets/{shot_set['id']}/appScreenshots")
            display_type = asc.attributes(shot_set).get("screenshotDisplayType")
            sets.setdefault(asc.attributes(loc).get("locale"), {})[display_type] = list(map(asc.attributes, shots))
    return Live(f"{attrs.get('versionString')} ({attrs.get('appStoreState')})",
                asc.attributes(found).get("primaryLocale"), sets)


def thumb(attrs: dict[str, Any]) -> str | None:
    asset = attrs.get("imageAsset") or {}
    template, width, height = asset.get("templateUrl"), asset.get("width"), asset.get("height")
    if not (template and width and height):
        return None
    w = min(THUMB_WIDTH, width)
    return template.replace("{w}", str(w)).replace("{h}", str(round(height * w / width))).replace("{f}", "jpg")


def compare_live(decks: list[Deck], live_sets: dict[str, list[dict[str, Any]]], platform: str) -> None:
    """Mark each shot against `live_sets` (fetched for `platform`; other platforms' decks stay unmarked)."""
    for deck in (d for d in decks if d.platform == platform):
        by_type: dict[str, list[Shot]] = {}
        for shot in deck.shots:
            if display_type := shot.dimensions and media.SCREENSHOT_DISPLAY_TYPES.get(shot.dimensions):
                by_type.setdefault(display_type, []).append(shot)
            else:
                shot.status = "unmapped"
        for display_type, shots in by_type.items():
            remote = live_sets.get(display_type, [])
            for shot, attrs in zip(shots, remote, strict=False):
                if attrs.get("sourceFileChecksum") == upload_checksum(shot.path):
                    shot.status = "unchanged"
                else:
                    shot.status, shot.before = "changed", thumb(attrs)
            for shot in shots[len(remote):]:
                shot.status = "new"
            deck.removed += [(f"{a.get('fileName')} ({display_type})", thumb(a) or "") for a in remote[len(shots):]]


def find_icon(app: project.App, live: Live | None = None) -> Path | str | None:
    if configured := (app.config.get("gallery") or {}).get("icon"):
        return path if (path := app.root / configured).is_file() else None
    pngs = []
    for here, dirs, _files in os.walk(app.root):
        # Prune while walking: .git and build products are most of a repo's files.
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        if Path(here).name == "AppIcon.appiconset":
            pngs += Path(here).glob("*.png")
            dirs[:] = []
    if pngs:
        return max(pngs, key=lambda p: p.stat().st_size)
    apple_id = str(app.config.get("apple_id") or "")
    if live is not None and apple_id.isdigit():
        try:
            with urllib.request.urlopen(f"https://itunes.apple.com/lookup?id={apple_id}", timeout=10) as response:
                if (results := json.load(response).get("results") or []) and results[0].get("artworkUrl512"):
                    return results[0]["artworkUrl512"]
        except (OSError, ValueError):
            pass
    # Xcode's render of an Icon Composer icon: the largest AppIcon PNG in a DerivedData build.
    try:
        project_name = app.project.stem
    except SystemExit:
        return None
    derived = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    return max((p for d in derived.glob(f"{project_name}-*")
                for p in d.glob("Build/Products/*-iphonesimulator/*.app/AppIcon*.png")),
               key=lambda p: p.stat().st_size, default=None)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def mocks(text: dict[str, str | None], icon_tag: str, strip: list[str], note: str) -> str:
    name, subtitle = text.get("name"), text.get("subtitle")
    shots = "".join(f'<img src="{esc(u)}" alt="">' for u in strip[:3])

    def block(title: str, body: str | None, cls: str = "") -> str:
        return f'<h4>{title}</h4><p class="clamp {cls}">{esc(body)}</p><span class="more">more</span>' if body else ""

    return f"""
<div class="mocks">
 <div class="phone">
  <div class="label">Search result</div>
  <div class="row">{icon_tag}
   <div class="titles"><div class="name">{esc(name or "(no name.txt)")}</div>
    <div class="subtitle">{esc(subtitle or "")}</div><div class="stars">★★★★★ <span>1.2K</span></div></div>
   <div class="get">Get</div></div>
  <div class="strip">{shots or '<div class="muted">no iPhone shots</div>'}</div>
  <div class="muted">{esc(note)} · name {len(name or "")}/{LISTING["name"].limit} · subtitle {len(subtitle or "")}/{LISTING["subtitle"].limit}</div>
 </div>
 <div class="phone page">
  <div class="label">Product page</div>
  <div class="row">{icon_tag.replace('class="icon', 'class="icon big')}
   <div class="titles"><div class="name">{esc(name or "")}</div><div class="subtitle">{esc(subtitle or "")}</div></div></div>
  {f'<p class="promo">{esc(text["promotional_text"])}</p>' if text.get("promotional_text") else ""}
  {block("What's New", text.get("release_notes"), "two")}
  {block("Description", text.get("description"))}
  {'' if any(text.get(k) for k in ("description", "release_notes", "promotional_text")) else '<p class="muted">no description, promotional text or release notes</p>'}
 </div>
</div>"""


def review_panel(findings: list[Any], translation: dict[str, str]) -> str:
    items = "".join(f'<li class="{f.severity}"><b>{esc(f.where.split("/", 1)[-1])}</b> [{esc(f.rule)}] '
                    f'{esc(f.message)}</li>' for f in findings)
    chips = "".join(f'<span class="chip {esc(v)}">{esc(k)}: {esc(v)}</span>'
                    for k, v in translation.items() if v in ("stale", "unreviewed", "untracked"))
    if not items and not chips:
        return '<div class="review ok">lint clean · translations current</div>'
    return f'<div class="review"><ul>{items or "<li>lint clean</li>"}</ul>{f"<div>{chips}</div>" if chips else ""}</div>'


def deck_html(deck: Deck, assets: Assets, comparing: str | None) -> str:
    cards = []
    for shot in deck.shots:
        if shot.dimensions is None:
            size, warning = "unreadable", "the push cannot read this image's size"
        else:
            size = "{}×{}".format(*shot.dimensions) + (f" ({inches})" if (inches := media.SCREEN_SIZES.get(
                shot.dimensions)) else "")
            warning = (media.size_advice(shot.dimensions) if shot.dimensions in media.SCREENSHOT_DISPLAY_TYPES
                       else "no App Store slot takes this size; the push refuses it")
        before = (f'<div class="before"><img loading="lazy" src="{esc(shot.before)}" alt=""><span>{esc(comparing)}</span></div>'
                  if shot.before else "")
        badge = f'<span class="badge {esc(shot.status)}">{esc(shot.status)}</span>' if shot.status else ""
        cards.append(f"""<figure class="{esc(shot.status)}">{badge}<img loading="lazy" src="{esc(assets.url(shot.path))}" alt="">{before}
<figcaption>{esc(shot.path.name)}<br><span>{esc(size)}</span>{f'<br><b>{esc(warning)}</b>' if warning else ''}</figcaption></figure>""")
    cards += [f"""<figure><video src="{esc(assets.url(path))}" controls muted preload="metadata"></video>
<figcaption>{esc(path.name)}<br><span>App Preview</span></figcaption></figure>""" for path in deck.previews]
    cards += ['<figure class="removed"><span class="badge removed">removed</span>'
              + (f'<img loading="lazy" src="{esc(url)}" alt="">' if url else "")
              + f'<figcaption>{esc(label)}<br><span>in {esc(comparing)}, not on disk — the push deletes it</span></figcaption></figure>'
              for label, url in deck.removed]
    n = len(deck.shots)
    limit = media.MAX_SCREENSHOTS_PER_SET
    over = f' <b>— {n} shots, over the limit of {limit}</b>' if n > limit else ""
    if not deck.shots and not deck.previews:
        over = " <b>— empty folder: the push deletes this locale's live screenshots</b>"
    return (f'<h3>{esc(deck.family)} · {n} shot(s){over}</h3>'
            f'<div class="deck {esc(deck.family.lower())}">{"".join(cards)}</div>')


def build(app: project.App, platform: str = "ios", assets: Assets | None = None, live: Live | None = None,
          compare_git_head: bool = False) -> str:
    assets, locales, configured_primary = assets or Assets(None), app.locales, app.primary_locale
    primary = live.primary_locale if live and live.primary_locale else configured_primary
    comparing = "App Store Connect" if live else ("HEAD" if compare_git_head else None)
    icon = find_icon(app, live)
    icon_tag = (f'<img class="icon" src="{esc(icon if isinstance(icon, str) else assets.url(icon))}" alt="">'
                if icon is not None else None)
    findings = lint.run(app, platform)
    translation = translations.statuses(app.folder, locales)
    on_disk = {p.name for pf in app.config.get("platforms") or ["ios"]
               for p in (app.folder / pf / "screenshots").glob("*") if p.is_dir()}
    decks_by_locale = {locale: local_decks(app, locale) for locale in [*locales, *sorted(on_disk - set(locales))]}
    for locale, decks in decks_by_locale.items():
        if live is not None:
            compare_live(decks, live.sets.get(locale, {}), platform)
        elif compare_git_head:
            compare_git(app, decks, assets)

    def iphone_urls(locale: str) -> list[str] | None:
        deck = next((d for d in decks_by_locale.get(locale, []) if d.family == "iPhone"), None)
        return [assets.url(s.path) for s in deck.shots] if deck else None

    notices = []
    if live and live.primary_locale and live.primary_locale != configured_primary:
        notices.append(f"App Store Connect's primary language is {live.primary_locale}, but snakelane.yml implies "
                       f'{configured_primary}: set "primary_locale": "{live.primary_locale}".')
    sections = []
    for locale in locales:
        if (own_strip := iphone_urls(locale)) is None and locale != primary:
            strip, note = iphone_urls(primary) or [], f"no deck — shows {primary}'s"
        else:
            strip = own_strip or []
            note = ("own deck" if own_strip else "no iPhone deck" if own_strip is None
                    else "empty iPhone folder — the push deletes the live iPhone shots")
        text = {f: read_field(app.folder / platform, locale, f) for f in TEXT_FIELDS if f != "keywords"}
        tag = icon_tag or f'<div class="icon placeholder">{esc((text["name"] or "?")[:1])}</div>'
        body = "".join(deck_html(d, assets, comparing) for d in decks_by_locale[locale]) \
            or f'<p class="muted">No screenshots: the App Store shows {esc(primary)}\'s.</p>'
        sections.append(
            f'<section id="{esc(locale)}"><h2>{esc(locale)}{" · primary" if locale == primary else ""}</h2>'
            f'{review_panel([f for f in findings if f.where.startswith(f"{locale}/")], translation.get(locale, {}))}'
            f'{mocks(text, tag, strip, note)}{body}</section>')
    if unlisted := [loc for loc in decks_by_locale if loc not in locales and decks_by_locale[loc]]:
        body = "".join(f'<h3>{esc(loc)}</h3>' + "".join(deck_html(d, assets, comparing) for d in decks_by_locale[loc])
                       for loc in unlisted)
        sections.append(f'<section id="unlisted"><h2>Not in snakelane.yml — never pushed</h2>'
                        f'<p class="muted">These deck folders exist, but "locales" doesn\'t list them, so '
                        f'<code>store screenshots push</code> ignores them.</p>{body}</section>')
    notices += [f"review notes: [{f.rule}] {f.message}" for f in findings if f.where.startswith("review/")]
    nav = " · ".join(f'<a href="#{esc(loc)}">{esc(loc)}</a>' for loc in locales) + \
        (' · <a href="#unlisted">not in snakelane.yml</a>' if unlisted else "")
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    mode = (f" · compared with App Store Connect version {esc(live.version)}" if live
            else " · compared with git HEAD" if compare_git_head else "")
    notice_html = "".join(f'<p class="notice">{esc(n)}</p>' for n in notices)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(app.name)} screenshots</title>
<style>{CSS}</style></head><body>
<header><h1>{esc(app.name)}</h1><p>{esc(app.folder.name)} · generated {esc(stamp)} by snakelane gallery{mode} · nothing here is uploaded</p>{notice_html}</header>
<nav>{nav}</nav>
{"".join(sections)}
</body></html>
"""


CSS = """
:root { --bg:#f5f5f7; --card:#fff; --ink:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7; --warn:#b25000; --bad:#d70015; --good:#248a3d; --accent:#0071e3; }
@media (prefers-color-scheme: dark) { :root { --bg:#000; --card:#1c1c1e; --ink:#f5f5f7; --muted:#a1a1a6; --line:#38383a; --warn:#ff9f0a; --bad:#ff453a; --good:#30d158; --accent:#0a84ff; } }
* { box-sizing:border-box; }
body { margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--ink); font:15px/1.4 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }
header, nav { max-width:1200px; margin:0 auto 8px; } header p { color:var(--muted); margin:4px 0; } nav { margin-bottom:24px; }
a { color:var(--accent); } code { font-size:13px; }
.notice { color:var(--warn) !important; font-weight:600; }
section { max-width:1200px; margin:0 auto 40px; background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px; }
h2 { margin:0 0 12px; } h3 { font-size:15px; margin:24px 0 8px; color:var(--muted); } h3 b, figcaption b { color:var(--warn); font-weight:600; }
h4 { margin:12px 0 2px; font-size:15px; }
.muted { color:var(--muted); font-size:12px; margin-top:8px; }
.review { border:1px solid var(--line); border-radius:12px; padding:8px 12px; margin-bottom:16px; font-size:13px; }
.review.ok { color:var(--good); } .review ul { margin:0; padding-left:18px; }
.review li.error { color:var(--bad); } .review li.warning { color:var(--warn); }
.chip { display:inline-block; border:1px solid var(--line); border-radius:999px; padding:1px 8px; margin:6px 6px 0 0; font-size:12px; }
.chip.stale { color:var(--bad); } .chip.unreviewed { color:var(--warn); } .chip.untracked { color:var(--muted); }
.mocks { display:flex; flex-wrap:wrap; gap:16px; }
.phone { width:min(390px,100%); border:1px solid var(--line); border-radius:14px; padding:14px; }
.label { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:8px; }
.row { display:flex; align-items:center; gap:12px; }
.icon { width:64px; height:64px; border-radius:14px; object-fit:cover; flex:none; } .icon.big { width:96px; height:96px; border-radius:22px; }
.placeholder { display:grid; place-items:center; background:var(--line); font-size:28px; font-weight:600; }
.titles { flex:1; min-width:0; }
.name, .subtitle { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } .page .name { white-space:normal; font-size:20px; }
.name { font-weight:600; } .subtitle, .stars span { color:var(--muted); font-size:13px; } .stars { font-size:12px; color:var(--muted); }
.get { background:var(--line); color:var(--accent); font-weight:700; border-radius:999px; padding:5px 18px; }
.strip { display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-top:12px; }
.strip img { width:100%; border-radius:8px; border:1px solid var(--line); }
.promo { margin:12px 0 0; }
.clamp { margin:0; white-space:pre-line; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.clamp.two { -webkit-line-clamp:2; } .more { color:var(--accent); font-size:13px; }
.deck { display:flex; gap:12px; overflow-x:auto; padding-bottom:8px; }
figure { margin:0; flex:none; width:180px; position:relative; } .deck.ipad figure { width:240px; } .deck.mac figure { width:320px; }
figure img, figure video { width:100%; border-radius:8px; border:1px solid var(--line); background:var(--bg); display:block; }
figure.removed img { opacity:.45; } figure.changed > img { outline:3px solid var(--warn); } figure.new > img { outline:3px solid var(--good); }
.before { margin-top:6px; } .before img { opacity:.8; } .before span { font-size:11px; color:var(--muted); }
.badge { position:absolute; top:6px; left:6px; z-index:1; font-size:11px; font-weight:600; padding:1px 7px; border-radius:999px; background:var(--card); border:1px solid var(--line); }
.badge.new { color:var(--good); } .badge.changed { color:var(--warn); } .badge.removed, .badge.unmapped { color:var(--bad); } .badge.unchanged { color:var(--muted); }
figcaption { font-size:12px; color:var(--muted); margin-top:4px; } figcaption span { font-variant-numeric:tabular-nums; }
"""


cli = command_app("Write an HTML review page of every deck and listing.")


@cli.command()
def gallery_command(
    app: AppOption = None,
    platform: PlatformOption = None,
    live: Annotated[bool, typer.Option("--live", help="compare each deck with App Store Connect (read-only; needs the key)")] = False,
    git: Annotated[bool, typer.Option("--git", help="compare each deck with the last commit")] = False,
    bundle: Annotated[str | None, typer.Option("--bundle", help="write a self-contained folder (index.html + images) here")] = None,
    out: Annotated[str | None, typer.Option("--out", help="page path without --bundle (default: /tmp/snakelane-<app>-gallery.html)")] = None,
    open_page: Annotated[bool, typer.Option("--open", help="open it in the default browser")] = False,
) -> None:
    if live and git:
        raise SystemExit("--live and --git are alternatives: pick one comparison")
    resolved = project.resolve_app(app)
    folder = Path(bundle) if bundle else None
    if folder is not None and folder.resolve().is_relative_to(resolved.folder.resolve()):
        raise SystemExit(f"--bundle must be outside {resolved.folder}: the push would read copied images as decks")
    platform = resolve_platform(resolved.config, platform)
    page = build(resolved, platform, Assets(folder), live=fetch_live(resolved, platform) if live else None,
                 compare_git_head=git)
    path = folder / "index.html" if folder else Path(out) if out else Path("/tmp") / f"snakelane-{resolved.slug}-gallery.html"
    path.write_text(page)
    print(path)
    if open_page:
        subprocess.run(["open", str(path)], check=False)


def main(argv: list[str] | None = None) -> None:
    run_cli(cli, argv, "snakelane gallery")
