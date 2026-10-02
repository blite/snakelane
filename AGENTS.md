# AGENTS.md — working on snakelane

snakelane is a Python CLI (`src/snakelane/`) and an agent skill (`skills/snakelane/`) that
ship together in one repo. Users install the CLI editable from their fork and link the skill
from the same checkout, so an agent that edits this repo changes the tool every app on the
machine runs. Treat edits accordingly.

## Layout

```
src/snakelane/
  cli.py                 `snakelane <command>` → <module>.main(argv); routing only
  args.py                --app / --platform, shared by every command; ASC failures → one line, exit 1
  terminal.py            colours, truncation, the word-level push diff
  xcode.py               running xcodebuild/simctl (echoed, pasteable); sweeping leaked test simulators
  init.py                `init`: snakelane.yml + starter metadata/ from the Xcode project
  project.py             find the repo (walk up to snakelane*.yml), the app config, YAML,
                         DeckTree (where a device's screenshots live), .snakelane/ work dir
  connect/               talking to App Store Connect
    asc.py               REST client: JWT, JSON:API, retries (GETs only); ASCError carries status
    auth.py              `auth`: install and check the one API key every command uses
    resources.py         versions, app info, localizations, uploads + processing waits
  listing/               what the store page says
    store.py             `store`: the command line only — routes to the modules below
    push.py              store push / pull / show
    fields.py            field tables, text lookup through metadata/, limits, categories, age rating
    lint.py              `lint`: listing lint for App Review rejections; gates push/release
    translations.py      `translations`: stale/unreviewed translated fields (translations.json)
  purchases/             what the app sells (metadata/iap.yml)
    catalogue.py         loading and validating iap.yml
    iap.py               store iap show / push
    subscriptions.py     store subs show / pull / push
  screenshots/           making, checking, uploading and reviewing the deck
    shoot.py             `shoot`: shoot the deck from the UI test; the reframe test `frame` runs with frame: test
    extract.py           attachments out of an .xcresult into a DeckTree
    frame.py             `frame`: the command, the deck loop, key art, the banner handoff
    framing/             what `frame` draws: style.py (layout, caption, theme from the config),
                         themes.py (built-in looks), draw.py (bands, callouts, type, shadows),
                         compose.py (the four layouts)
    check.py             `check`: Vision OCR for developer-build HUDs (optional extra)
    media.py             image/video sizes, display types, which files make a deck
    upload.py            store screenshots / previews push
    gallery.py           `gallery`: HTML review page — decks, store mocks, before/after
  release/               getting a build out
    ship.py              `ship`: test → archive → TestFlight → submit; release settings; bump-version
    status.py            `status`: versions, review in progress, latest build (read-only)
    bump.py              `bump`: build number — Archive post-action, pbxproj, stamping
    assetpacks.py        `packs`: Background Assets packaging and upload
skills/snakelane/        the agent skill: SKILL.md, references/, assets/ (templates)
tests/                   offline tests (pytest); CI runs them with ruff
examples/                runnable sample metadata trees; tests/test_examples.py keeps them valid
docs/                    the documentation site (MkDocs Material, mkdocs.yml); pages include
                         README sections and the skill's references rather than copying them
docs/design/             why the code is the way it is: the incidents behind it, by area
CHANGELOG.md             one entry per release
```

`local/` is gitignored: private notes (per-app migration plans and the like) go there, never
into `docs/`. This repo is public.

## Rules

- **Nothing app-specific in code.** No app names, project paths, schemes, device lineups or
  bundle ids. A difference between apps becomes an `snakelane.yml` key, with a default that keeps
  apps without the key working. Document every new key in the owning module's docstring
  **and** in `skills/snakelane/references/config.md`.
- **Never write to App Store Connect while developing.** Verify with `--dry-run`, `show`,
  `shoot --dry-run` and `bump --dry-run`. Never archive, upload,
  submit or run `packs upload` against a real app to test a change.
- **Never push a blank field.** Missing or blank local text means "no opinion". Preserve
  this in any code that builds a request body.
- **One auth method, one place.** Credentials come only from `asc.Credentials.load()`: the
  key `snakelane auth setup` installs. No environment variables, no Apple ID sign-in, no
  second code path that finds a key some other way.
- **Writes are not retried**, only GETs: a timed-out POST may have landed.
- **Every write goes through `asc.Client`**, whose `dry_run` is the dry run: build the client with
  `dry_run=args.dry_run` and write unconditionally; report results with `client.report`. Don't add
  a `--dry-run` branch at a write site, or send a request around the client.
- Product ids and asset pack ids are permanent at Apple. Creation stays behind `--create`
  (IAPs) or a TTY-only confirmation (packs). Do not add a `--yes` to `packs upload`.
- Keep the house style: comments say *why* in a line or two; the incident that taught it (app
  and date) goes in `docs/design/<area>.md`, with a `# Why: docs/design/<area>.md#<anchor>`
  pointer where the code would otherwise look wrong. Keep that history when refactoring; it
  is the reason the code is the way it is. Don't restate the code in a comment.
- Commands keep their flags. Apps' docs and scheme post-actions call them by name.

## Checking a change

```bash
uv run --group dev ruff check src tests
uv run --group dev pytest
uv run --group docs mkdocs build --strict     # the docs site; `mkdocs serve` to preview
uv run snakelane --help
uv run snakelane -C <app repo> store push --dry-run
uv run snakelane -C <app repo> store screenshots push --dry-run
uv run snakelane -C <app repo> bump --dry-run
uv run snakelane -C <app repo> shoot --dry-run
```

Run the dry runs against more than one app. Output should change only where you meant it to.
The installed `snakelane` is editable, so it is already running your change; there is
nothing to reinstall.

## Releasing

Bump `version` in `pyproject.toml` and `__version__` in `src/snakelane/__init__.py`
together, move `CHANGELOG.md`'s "Unreleased" notes under the new version, and tag `vX.Y.Z`.
CI and machines that install from git pin a tag. A change that needs new `snakelane.yml` keys, or
changes a command's behaviour, gets a minor version bump and a `CHANGELOG.md` entry saying
what an app must change.

## The skill

`skills/snakelane/SKILL.md` is read by agents operating snakelane in an app repo. When you
change behaviour, flags or `snakelane.yml` keys, update the skill in the same commit. Keep
`SKILL.md` about operating the tool and its App Store Connect traps; implementation detail
belongs in module docstrings, and the reasons behind it in `docs/design/`.
