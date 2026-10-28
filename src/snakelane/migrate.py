"""`snakelane migrate-layout`: move a flat metadata folder to the kind-first layout (see layout.py).

    snakelane migrate-layout [--app A] [--dry-run]

Tracked files move with `git mv`, so `git log --follow` keeps their history; ignored ones (a gitignored
deck) are moved as they are. The review contact and demo account leave their files for snakelane.yml's
`review` section, a `.gitignore` rule for `<metadata>/*/screenshots/` becomes `<metadata>/screenshots/`,
iap.yml's `review_screenshot` paths lose their `iap/` prefix, since they are now relative to
purchases/, and an `asset_packs.record` naming the moved file follows it. Anything it does not recognise stays where it is and is listed. Commit the result on its
own, so the move is one commit and nothing else.
Why: docs/design/foundations.md#metadata-is-sorted-by-kind
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer

from . import layout, project
from .args import AppOption, command_app, run
from .listing.fields import CONFIG_REVIEW, LISTING, read_text

PLATFORMS = ("ios", "macos", "tvos", "visionos")
LOCALE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*")
# Top-level entries that stay put: already sorted by kind, or not metadata.
STAYS = {"creative", "README.md", "SCREENSHOTS.md"}
REVIEW_FILES = {f"{stem}.txt" for stem in CONFIG_REVIEW}


@dataclass
class Plan:
    moves: list[tuple[Path, Path]] = field(default_factory=list)   # file -> file
    empty: list[tuple[Path, Path]] = field(default_factory=list)   # empty folder -> folder (a deck's
                                                                   # empty locale means "delete what's live")
    review: dict[str, str] = field(default_factory=dict)           # stem -> value, for snakelane.yml
    copyright: str | None = None                                   # for snakelane.yml
    dropped: list[Path] = field(default_factory=list)              # contact files the config now holds
    left: list[Path] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def move_tree(self, src: Path, dst: Path) -> None:
        for path in sorted(src.rglob("*")) if src.is_dir() else [src]:
            if path.is_file() and path.name != ".DS_Store":
                self.moves.append((path, dst / path.relative_to(src) if src.is_dir() else dst))
        for path in [src, *src.rglob("*")] if src.is_dir() else []:
            if path.is_dir() and not [p for p in path.iterdir() if p.name != ".DS_Store"]:
                self.empty.append((path, dst / path.relative_to(src)))


def plan_review(plan: Plan, review_dir: Path, notes_to: Path, shared: dict[str, str] | None) -> None:
    """notes.txt joins the listing; contact files go to snakelane.yml (a platform's must match the shared ones)."""
    for path in sorted(review_dir.iterdir()):
        stem = path.stem
        if path.name == "notes.txt":
            plan.moves.append((path, notes_to))
        elif path.name in REVIEW_FILES:
            value = read_text(path)
            if shared is None:
                if value:
                    plan.review[stem] = value
                plan.dropped.append(path)
            elif value and shared.get(stem) not in (None, value):
                plan.problems.append(f"{path}: {value!r} differs from the shared review/{path.name} "
                                     f"({shared[stem]!r}); snakelane.yml has one contact. Make them agree first.")
            else:
                if value and stem not in shared:
                    plan.review[stem] = value
                plan.dropped.append(path)
        elif path.name != ".DS_Store":
            plan.left.append(path)


def is_locale(path: Path, locales: list[str]) -> bool:
    """A configured locale, or a locale-shaped folder holding listing text: a short name alone
    is not enough (Solitaire's freecell/ppo/ holds product page art, not Portuguese text)."""
    if not path.is_dir():
        return False
    return path.name in locales or bool(LOCALE.fullmatch(path.name)
                                        and any(p.stem in LISTING for p in path.glob("*.txt")))


def plan_platform(plan: Plan, folder: Path, platform_dir: Path, locales: list[str]) -> None:
    platform = platform_dir.name
    own = folder / layout.LISTING / platform
    for path in sorted(platform_dir.iterdir()):
        name = path.name
        if name == "screenshots":
            plan.move_tree(path, folder / "screenshots" / platform)
        elif name == "creative":
            plan.move_tree(path, folder / "creative" / platform)
        elif name == "default":
            plan.move_tree(path, own / "default")
        elif name == "review":
            plan_review(plan, path, own / "default" / layout.REVIEW_NOTES, plan.review)
        elif name == "copyright.txt":
            if read_text(path) in (None, plan.copyright):  # the same as the shared one: the config has it
                plan.dropped.append(path)
            else:
                plan.moves.append((path, own / "copyright.txt"))
        elif name == "asset_packs.json":
            plan.moves.append((path, folder / "release" / "asset_packs.json"))
        elif is_locale(path, locales):
            plan.move_tree(path, own / "locales" / name)
        elif name != ".DS_Store":
            plan.left.append(path)


def plan_copyright(plan: Plan, app: project.App, path: Path) -> None:
    """The shared copyright.txt becomes snakelane.yml's `copyright`."""
    shared, configured = read_text(path), app.config.get("copyright")
    if shared is not None and configured not in (None, "") and str(configured).strip() != shared:
        plan.problems.append(f"{path.name} says {shared!r} and snakelane.yml says {configured!r}; make them agree")
    elif configured in (None, ""):
        plan.copyright = shared
    plan.dropped.append(path)


def build_plan(app: project.App) -> Plan:
    folder = app.folder
    plan = Plan()
    if layout.kind_first(folder):  # moved before copyright joined the config: that file is all that's left
        if not (path := folder / layout.LISTING / "copyright.txt").is_file():
            raise SystemExit(f"{folder} already has listing/: it is in the kind-first layout")
        plan_copyright(plan, app, path)
        return plan
    platforms = set(PLATFORMS) | set(app.config.get("platforms") or [])
    listing = folder / layout.LISTING
    if (folder / "copyright.txt").is_file():  # first, as a platform's is checked against it
        plan_copyright(plan, app, folder / "copyright.txt")
    if (review := folder / "review").is_dir():  # first: a platform's contact is checked against it
        plan_review(plan, review, listing / "default" / layout.REVIEW_NOTES, None)
    for path in sorted(folder.iterdir()):
        name = path.name
        if name in STAYS or name == "review" or name == ".DS_Store":
            continue
        if name == "default":
            plan.move_tree(path, listing / "default")
        elif name == "copyright.txt":
            continue  # into snakelane.yml, above
        elif name == "translations.json":
            plan.moves.append((path, listing / name))
        elif name == "iap.yml":
            plan.moves.append((path, folder / "purchases" / "iap.yml"))
        elif name == "iap":
            plan.move_tree(path, folder / "purchases")
        elif path.is_dir() and name in platforms:
            plan_platform(plan, folder, path, app.locales)
        elif is_locale(path, app.locales):
            plan.move_tree(path, listing / "locales" / name)
        else:
            plan.left.append(path)
    targets = [dst for _, dst in plan.moves]
    if clashes := sorted({str(t) for t in targets if targets.count(t) > 1}):
        plan.problems.append(f"two files would land on {clashes[0]}" + (f" (and {len(clashes) - 1} more)" if len(clashes) > 1 else ""))
    return plan


def tracked(root: Path, folder: Path) -> set[Path]:
    """The files git tracks under `folder`; empty outside a repo."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", str(folder)],
                         capture_output=True, text=True)
    return {root / p for p in out.stdout.split("\0") if p} if out.returncode == 0 else set()


def config_yaml(plan: Plan) -> str:
    """What the move adds to snakelane.yml: the copyright and the review section, or ""."""
    text = (f"\n# One per version, the same on every platform.\ncopyright: {quote(plan.copyright)}\n"
            if plan.copyright else "")
    return text + (review_yaml(plan.review) if plan.review else "")


def review_yaml(review: dict[str, str]) -> str:
    """snakelane.yml's review section, one key per line."""
    lines = ["", "# The App Review contact (and demo account): settings, not listing text.", "review:"]
    for group in ("contact", "demo"):
        keys = [(key, review[stem]) for stem, (g, key) in CONFIG_REVIEW.items() if g == group and stem in review]
        if keys:
            lines.append(f"  {group}:")
            lines += [f"    {key}: {quote(value)}" for key, value in keys]
    return "\n".join(lines) + "\n"


def quote(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z][\w .@'-]*", value) and not value.endswith(" ") else '"' + value.replace('"', '\\"') + '"'


def gitignore_edits(app: project.App) -> tuple[Path, str, str] | None:
    """(file, old line, new line) for the deck rule, when the repo's .gitignore has the flat one."""
    path = app.root / ".gitignore"
    rel = app.folder.relative_to(app.root).as_posix()
    if not path.is_file():
        return None
    for line in path.read_text().splitlines():
        if line.strip().rstrip("/") in (f"{rel}/*/screenshots", f"/{rel}/*/screenshots"):
            return path, line, line.replace("*/screenshots", "screenshots")
    return None


def record_edit(app: project.App, plan: Plan) -> tuple[str, str] | None:
    """(old, new) for `asset_packs.record` when it names a file the move takes elsewhere."""
    named = (app.config.get("asset_packs") or {}).get("record")
    if not named:
        return None
    moved = {src: dst for src, dst in plan.moves}
    if (dst := moved.get(app.folder / named)) is None:
        return None
    return named, dst.relative_to(app.folder).as_posix()


def record_config_edits(text: str, old: str, new: str) -> str:
    return re.sub(rf"(^\s+record:\s*['\"]?){re.escape(old)}(['\"]?)", rf"\g<1>{new}\2", text, count=1, flags=re.M)


def iap_screenshot_edits(text: str) -> str:
    return re.sub(r"(review_screenshot:\s*['\"]?)iap/", r"\1", text)


def stale_references(app: project.App) -> list[str]:
    """Files outside the metadata folder that name a path the move changes, for fixing by hand."""
    rel = app.folder.relative_to(app.root).as_posix()
    # POSIX ERE for git grep: no (?:…) and no \b.
    names = ["\\*", "<platform>", "<locale>", "ios", "macos", "default", "review", "iap", "copyright",
             "translations", *app.locales]
    pattern = rf"{re.escape(rel)}/({'|'.join(names)})([/.]|$)"
    moved = [f":(exclude){rel}/{kind}/**" for kind in ("listing", "purchases", "screenshots", "creative", "release")]
    out = subprocess.run(["git", "-C", str(app.root), "grep", "-nE", pattern, "--", ".", *moved],
                         capture_output=True, text=True)
    return out.stdout.splitlines()


def execute(app: project.App, plan: Plan) -> None:
    if plan.review and "review" in app.config:
        raise SystemExit(f'{app.config_path.name} already has a "review" section; nothing moved. Merge the '
                         "files' contact into it by hand, delete the files, and run this again:" + review_yaml(plan.review))
    files = tracked(app.root, app.folder)
    moved = by_git = 0
    for src, dst in plan.moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src in files:
            subprocess.run(["git", "-C", str(app.root), "mv", str(src), str(dst)], check=True)
            by_git += 1
        else:
            shutil.move(src, dst)
        moved += 1
    for path in plan.dropped:
        if path in files:
            subprocess.run(["git", "-C", str(app.root), "rm", "-q", str(path)], check=True)
        else:
            path.unlink()
    if (catalogue := app.folder / "purchases" / "iap.yml").is_file():
        catalogue.write_text(iap_screenshot_edits(catalogue.read_text()))
    if record := record_edit(app, plan):
        app.config_path.write_text(record_config_edits(app.config_path.read_text(), *record))
    if added := config_yaml(plan):
        app.config_path.write_text(app.config_path.read_text().rstrip("\n") + "\n" + added)
    if edit := gitignore_edits(app):
        path, old, new = edit
        path.write_text(path.read_text().replace(old, new, 1))
    for _, dst in plan.empty:
        dst.mkdir(parents=True, exist_ok=True)
    # Only folders the move emptied: an empty deck folder that stays may mean "delete what's live".
    emptied = [src for src, _ in plan.empty] + [p.parent for p in [*(src for src, _ in plan.moves), *plan.dropped]]
    sources = {a for d in emptied for a in (d, *d.parents) if a.is_relative_to(app.folder) and a != app.folder}
    for directory in sorted(sources, key=lambda p: -len(p.parts)):
        if directory.is_dir() and not [p for p in directory.iterdir() if p.name != ".DS_Store"]:
            shutil.rmtree(directory)
    print(f"moved {moved} file(s), {by_git} of them with git mv")


def report(app: project.App, plan: Plan, dry_run: bool) -> None:
    root = app.root
    def rel(p: Path) -> str:
        return str(p.relative_to(root))
    verb = "would move" if dry_run else "moving"
    groups: dict[tuple[str, str], int] = {}
    for src, dst in plan.moves:  # one line per folder pair, not per file
        key = (rel(src.parent), rel(dst.parent))
        groups[key] = groups.get(key, 0) + 1
    print(f"{verb} {len(plan.moves)} file(s):")
    for (src, dst), n in groups.items():
        print(f"  {src}/ → {dst}/  ({n})")
    if added := config_yaml(plan):
        print(f"→ {app.config_path.name}, replacing {len(plan.dropped)} file(s):")
        print("  " + added.strip().replace("\n", "\n  "))
    if edit := gitignore_edits(app):
        print(f".gitignore: {edit[1].strip()} → {edit[2].strip()}")
    if record := record_edit(app, plan):
        print(f"{app.config_path.name}: asset_packs.record {record[0]} → {record[1]}")
    if (catalogue := app.folder / "iap.yml").is_file() and iap_screenshot_edits(text := catalogue.read_text()) != text:
        print("purchases/iap.yml: review_screenshot paths lose their iap/ prefix")
    if plan.left:
        print("left where they are (not recognised):")
        print("".join(f"  {rel(p)}\n" for p in plan.left), end="")


cli = command_app("Move a flat metadata folder to the kind-first layout: listing/, purchases/, "
                  "screenshots/, release/.", no_args_is_help=False)


@cli.command()
def migrate_layout(
    app: AppOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="print the plan; move nothing")] = False,
) -> None:
    """Move this app's metadata into the kind-first layout."""
    resolved = project.resolve_app(app)
    plan = build_plan(resolved)
    report(resolved, plan, dry_run)
    if plan.problems:
        raise SystemExit("nothing moved:\n" + "\n".join(f"  ! {p}" for p in plan.problems))
    if dry_run:
        return
    resolved.refuse_if_shoot_was_killed()
    execute(resolved, plan)
    if refs := stale_references(resolved):
        print("\nthese files outside metadata/ still name the old paths; fix them by hand:")
        print("".join(f"  {line}\n" for line in refs), end="")
    print("\nCheck it: `snakelane store push --dry-run` and `snakelane store media push --dry-run` should plan "
          "what they did before. Then commit the move on its own.")


def main(argv: list[str] | None = None) -> None:
    run(cli, argv, "snakelane migrate-layout")
