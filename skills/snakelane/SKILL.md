---
name: snakelane
description: Operate and set up snakelane, a fastlane-free App Store Connect CLI (`snakelane auth|store|ship|shots|bump|packs|check|frame`) that pushes listing text, screenshots, App Previews, in-app purchases and subscriptions from a plain-text `metadata/` tree, ships test → archive → TestFlight → review, and sets CFBundleVersion from an Archive post-action. Use when a user asks to push metadata, update the App Store listing, sync or create IAPs, shoot or upload screenshots, push an App Preview, submit for review, upload to TestFlight, bump the build number or set up App Store automation; or names `snakelane`, `snakelane.yml`, `iap.yml`, or the old per-app `Metadata/scripts/*.py` it replaces. Also use when naming an IAP or asset pack (ids are permanent) and when an ASC push fails with a 409, an invalid field, a rejected screenshot size or a bounced preview. Never use fastlane.
---

# snakelane: App Store Connect without fastlane

snakelane is one installed command over a tree of plain text files that *is* the listing.
The app repo holds only data — `snakelane.yml`, the listing text, `iap.yml`, the
screenshot deck. The code lives in the snakelane package, installed once per machine, so a
fix lands in every app at once.

It exists because fastlane's screenshot toolchain assumed an older simctl and device list,
`deliver` tried to JSON-parse a `.p8` key, and every Xcode release broke something. The
parts that have to work moved into the UI-test process and a small amount of Python that
nothing outside your control can regress.

## Is it installed?

```bash
snakelane --version
```

If not: `uv tool install git+https://github.com/<owner>/snakelane` — or, to be able to
change snakelane itself (see the end of this file), clone it and
`uv tool install --editable <clone>`. Optional extra: `[check]` (macOS
Vision, for the developer-build check).

snakelane finds the app repo the way git finds `.git`: it walks up from the working
directory to the first folder holding a `snakelane.yml` (or `snakelane.<name>.yml`, one per
app in a repo with several). `snakelane -C <repo>` or `--config <file>`
overrides that. `--app <name>` picks among several configs; with one it is not needed.

## The tree

```
<repo>/
├── snakelane.yml            identity, categories, locales, platforms, per-app settings (YAML)
├── .snakelane/              snakelane's working files: raw captures, a killed shoot's stash (gitignored)
└── metadata/                (the config's `metadata` key; default `metadata`)
    ├── default/             the listing for every platform: name, subtitle, description,
    │                        keywords, promotional_text, release_notes, marketing_url,
    │                        support_url, privacy_url, privacy_choices_url (.txt each)
    ├── <locale>/            per-locale overrides of any single field
    ├── copyright.txt, review/   one for every platform (a platform folder may override)
    ├── iap.yml              everything the app sells — source of truth: one-time
    │                        purchases (`products`) and subscriptions (`subscription_groups`)
    ├── iap/                 their review screenshots
    ├── translations.json    what each translation was made from
    └── ios/  macos/         only what differs per platform, plus screenshots:
        ├── default/, <locale>/       version-level overrides (a Mac description, say)
        └── screenshots/<locale>/     the deck: ss-NN.jpg + ap-NN.m4v previews — in iphone/
                                      and ipad/ for iOS, directly in the locale folder for Mac
```

Text resolves most specific first: `<platform>/<locale>/`, `<platform>/default/`, `<locale>/`,
`default/`. Name, subtitle and the privacy URLs are app-level at App Store Connect, so a
platform copy of them is refused; put them in the shared listing.

A repo with several apps has one `snakelane.<name>.yml` per app at the root, each with its own
`metadata: metadata/<name>`. YAML is read with 1.2 rules and decimals kept as text, so don't
"fix" an unquoted `9.90` or `NO`; both are read as written. JSON is valid YAML, so an old
`app.json` works renamed.

iPad shots upload into the iOS version — App Store Connect has no iPadOS platform.

**Locale resolution**, per (locale, field): `<locale>/<field>.txt` if non-blank, else
`default/<field>.txt` if non-blank, else **skip the field entirely**. App Store Connect has
no "leave this alone": pushing `""` clobbers what is live, so a blank file means "no
opinion". Which locales are pushed comes from `snakelane.yml`'s `locales`, never from which
folders exist.

## Commands

```bash
snakelane init [--pull]                   # snakelane.yml + metadata/ from the Xcode project
snakelane status [--json]                 # what ASC holds now: versions, review, latest build
snakelane lint [--check-urls]         # lint the listing for App Review rejections, offline
snakelane store push --dry-run            # offline, no credentials: the whole plan
snakelane store push                      # diff vs live, confirm (--yes), write, re-read
snakelane store show | pull
snakelane store screenshots push [--dry-run]
snakelane store previews push [--dry-run]
snakelane store iap show | iap push [--dry-run] [--create] [--product ID]
snakelane store subs show | subs push [--dry-run] [--create]

snakelane shoot [--dry-run]         # generate the deck from the UI test
snakelane frame                   # redraw captions over raw/ without re-shooting
snakelane gallery --open                  # review page: decks, store mocks, lint, translations
snakelane gallery --live | --git          # …each shot marked new/changed/unchanged vs ASC or HEAD
snakelane gallery --bundle <dir>          # self-contained copy (CI artifact, sharing)
snakelane translations status             # stale / unreviewed translated listing fields
snakelane translations mark <locale>… [--reviewed]
snakelane check                           # refuse a deck shot from a DEBUG build
snakelane frame                           # caption raw shots in Python (Pillow)
snakelane frame --theme <name>            # try a look; writes .snakelane/, not the deck

snakelane ship test | beta | release [--no-submit] | bump-version
snakelane bump --dry-run                  # the number the next archive would get
snakelane bump --post-action              # print the scheme's Archive post-action
snakelane packs list | package | upload --dry-run   # Background Assets packs (Apple-hosted
                                                    # downloadable content; not IAPs)
```

Every command has `--help`. Everything app-specific is a key in `snakelane.yml`;
`references/config.md` lists them all.

## What this skill must not do

- **Do not run anything that writes to App Store Connect without being asked** — `store push`,
  `screenshots push`, `previews push`, `iap push`, `subs push`, `ship beta|release`. They
  mutate a live listing, and `iap push --create` makes identifiers that are permanent.
  `--dry-run`, `show` and `shoot --dry-run` are always safe.
- **Do not create or rename products.** Propose the identifier, explain the permanence, and
  let the user run it.
- `packs upload` refuses without a terminal and has no `--yes`, on purpose: an asset pack
  upload starts a review that replaces live content with no TestFlight-style hold. Hand the
  command to the user.
- Do not reintroduce fastlane. If something is missing, add it to snakelane.

## Names that freeze — read before creating anything

This is the part that costs money. Everything else is recoverable.

**Product IDs: alphanumerics, underscores and periods only.** Anything else is a 409 —
*"A product ID can only contain alphanumeric characters, underscores, and periods"* — and
it rejects exactly what a human writes: `baby-animals` must be `baby_animals`. Derive every
product id through one function that maps `[^A-Za-z0-9_]` to `_`. Folder names are often
also **asset pack ids**, which *do* allow hyphens, so the folder keeps its hyphen and the
product does not. snakelane checks the character set before `--create`.

**A product ID is [permanent from first sale](https://developer.apple.com/help/app-store-connect/reference/in-app-purchase-information)** — even after deletion. It can never be renamed
or reused for different content: a customer who bought "Cats 1" silently owns whatever it is
repointed at. That is why creation needs `--create`.

**A failed `iap push` still created everything before the failure.** Products are created
one at a time; after any failure run `snakelane store iap show` and fix the catalogue to
match what now exists. Only GETs are retried — a timed-out POST may have landed.

**Asset pack ids freeze at first upload**, and a pack's platforms only ever grow.

## App Store Connect facts that bite

- `filter[bundleId]` is a **prefix** match — `com.x.Solitaire` also returns
  `com.x.SolitairePlus`. Set `apple_id` in `snakelane.yml` as soon as the record exists; snakelane
  matches the bundle id exactly *and* asserts the numeric id.
- Sub-categories must be fully qualified: `GAMES_PUZZLE`, not `PUZZLE`.
- Field limits are enforced locally before any call: name 30, subtitle 30, keywords 100,
  promotional text 170, description 4000; IAP name 30, IAP description 45.
- Dingbats (✓ ✗ ✦) and emoji in listing text are a 409; • × — « » ° are fine.
- Release notes (`whatsNew`) are rejected on an app's first version, so `push` skips them there.
  `push` needs an editable version — press "+" next to the current version in ASC if there is
  none; `pull` and `show` fall back to the live one.
- Every IAP needs an App Review screenshot (640×920 is the floor) or stays
  `MISSING_METADATA`. Show the purchase sheet with the price visible.
- Touching an approved IAP localization or review screenshot re-opens it for review, so
  snakelane sends nothing when values already match.
- Repricing an existing IAP is web-UI only; `iap push` refuses, so a sync can never reprice a
  live product.
- Reviewers expect privacy **and** terms links inside `description.txt`, and no price/"free"
  claims in name, subtitle or keywords ([Guideline 2.3.7](https://developer.apple.com/app-store/review/guidelines/#2.3.7)).

## Pre-review checks

`store push` (and `--dry-run`) runs `snakelane lint` on the local text, and `ship release`
on the live listing it will submit (warning when local text hasn't been pushed); both stop on
errors:
over-limit fields, other platforms named (Android, Google Play), placeholders, profanity,
malformed URLs. Warnings (beta wording, "coming soon", keyword waste) print and continue.
Fix the copy; if a rule is wrong for this app, add it to `snakelane.yml`'s
`"lint": {"ignore": [...]}` rather than passing `--skip-lint` every time. Run
`lint --check-urls` before a release: a dead support URL is a rejection.

## Translating the listing

snakelane tracks translations; you write them. The source is `default/<field>.txt`, a
translation is `<locale>/<field>.txt`.

1. Translate each field into `<locale>/<field>.txt`, within the field's limit (name and
    subtitle 30, keywords 100, promotional text 170). Use the words the app's own localized UI
    uses for features, not a fresh translation of them. Keywords are researched per market,
    not translated: no spaces after commas, no words already in the name or subtitle.

2. `snakelane translations mark <locale>` records what you translated from.

3. Show the user, and after they (or a review pass) accept it,
    `snakelane translations mark <locale> --reviewed`. A hand edit after marking also counts
    as reviewed.

4. When `default/` changes, `translations status` lists the now-stale locales; re-translate
    only those.

Don't mark `--reviewed` on your own translation without the user's go-ahead.

## Screenshots and previews

- The display slot is inferred from **pixel size**; filenames set order only. A leading `_`
  excludes a file — and so removes it from ASC on the next push, because a push makes the
  remote set mirror the local folder (an *empty* locale folder deletes that locale's sets).
- `shoot` sets the previous deck aside in `screenshots/.previous-shoot/` and puts it
  back if any pass fails, so a failed shoot never leaves a half or empty deck for a push to
  upload. A `.previous-shoot/` left behind means a shoot was killed: it holds the last good
  deck; restore it before shooting again (the shoot refuses until you do).
- Before pushing a deck, `snakelane gallery --live --open` shows every locale's shots marked
  new/changed/unchanged against App Store Connect, what the push would delete, search-result
  and product-page mocks, and each locale's lint and translation status. It is the
  review step for translated captions; show it to the user before a screenshot push.
- An app that sells subscriptions must link its privacy policy URL and Terms of Use (`terms_url`,
  default Apple's standard EULA) in every locale's description; lint's `subscription-links`
  enforces it (Guideline 3.1.2). Keep both URLs when translating a description.
- Caption marks: `**bold**`, `*italic*`, `==accent==`, `[word]{colour}`. `*word*` is italic,
  not the accent colour. Keep the marks when translating a caption; an unclosed one stops `frame`.
  `--bundle <dir>` (outside `metadata/`) makes a copy that works off this Mac, e.g. as a CI
  artifact on a pull request that changes screenshots.
- 1–10 screenshots per set (locale × display type); the push refuses an 11th before deleting
  anything. A locale with no folder at all inherits the primary language's screenshots on the
  store — nothing is copied, and that is a valid way to ship a locale.
- iPhone 6.5" (1284×2778) is the default size on purpose, not an oversight: a 6.5" set shows
  in ASC's media page as uploaded, not dimmed as a scaled derivative. Apple's [spec page](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications) lists
  6.9" first and accepts either; don't "upgrade" an app's lineup to 6.9" unprompted.
- iPad 13" (2064×2752, the `iPad Pro 13-inch (M5)` simulator) is the default and the size to
  shoot. It shares the 12.9" slot; 12.9" decks are legacy, so move an app to 13" at its next
  re-shoot. Confirm device names against `xcrun simctl list devices available`.
- Any other size ASC accepts still uploads; the push prints a warning naming it. A size ASC
  doesn't accept (an 11" iPad, say) is an error, since it maps to no slot.
- snakelane picks simulators by UDID on the newest runtime (a name exists once per runtime);
  pin with `{"name": …, "os": "26.5"}`. Boot before `simctl status_bar` or the 9:41 override
  silently does nothing.
- iOS UI-test runners do not reliably see `TEST_RUNNER_*` variables or `-testLanguage`; the
  locale goes through a host file (`/tmp/<slug>-screenshot-locale`), and tests find their tree via `#filePath`.
- Shoot from a Release/Screenshots scheme. A DEBUG build's SpriteKit `nodes/fps` HUD once
  shipped in a whole deck; `snakelane check` OCRs for it and `screenshots push` runs it when
  `"developer_chrome_check"` is set.
- Screenshots are JPEG only: decks (`ss-NN.jpg`) and IAP `review_screenshot`s. ASC rejects alpha
  channels and HEIC. Captions must **overlay** or be
  **inset** into the final size — stacking changes the dimensions and every shot rejects.
- [App Previews](https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications) are a separate resource. "Uploaded" is not "accepted": Apple transcodes for up
  to ~20 minutes and can reject afterwards, visible only in the web UI. Raw `simctl`
  recordings are not uploadable as-is.

`references/gotchas.md` has the full list — simulator clone sets, preview specs, the
Xcode-project traps — read it when a push fails or an upload bounces later.

## Build numbers

`snakelane bump` sets the number to `max(pbxproj CURRENT_PROJECT_VERSION + 1, latest
TestFlight build + 1)`. **The pbxproj is the one record.** The hook is the app scheme's
**[Archive post-action](https://developer.apple.com/documentation/xcode/customizing-the-build-schemes-for-a-project#Run-tasks-before-or-after-scheme-actions)** — `snakelane bump --post-action` prints it; set "Provide build
settings from" to the app target. It writes the pbxproj once Xcode has stopped building,
then stamps the finished archive: the app, every `.appex`, and the archive summary.
`-exportArchive` re-signs, so stamping a signed archive is fine. `ship` verifies the number
moved and that every bundle agrees before uploading. Log:
`/tmp/snakelane-<app>-bump-build.log`.

Every other placement was tried and fails: a build phase writing the pbxproj makes Xcode
cancel ⌘-Archive silently; a separate counter file drifts (an archive shipped app 13 /
extension 4, which ASC rejects); a build phase can't see the app's Info.plist when an
extension is embedded; a pre-action is off by one. A project with several independently
numbered apps needs `"build_number_scope": "app"`.

Archive only from the app scheme; turn Archive off in helper schemes.

## Setting up a new app

1. `snakelane.yml` at the repo root from `assets/snakelane.yml.template` (fill every `{{…}}`),
    and `metadata/default/*.txt` from `assets/metadata/` (or `snakelane init`, which writes both).

2. UI-test templates into the UI-test target: the shared ones at the top of `assets/`, and the
    iOS-only ones in `assets/ios/` (caption drawing, App Preview recording); substitute `{{APP_NAME}}`,
    `{{PROJECT_NAME}}`, `{{SCHEME_NAME}}`, `{{BUNDLE_IDENTIFIER}}`, `{{UI_TEST_TARGET_NAME}}`,
    `{{UI_TEST_BUNDLE_IDENTIFIER}}`, `{{APP_SLUG}}` (the config's name, lowercased and hyphenated;
    `shoot --dry-run` prints the paths built from it), then `grep -r '{{'` to prove none
    survived. With `frame: snakelane`, add `SnakelaneBanner.swift` to the UI-test target and
    `ScreenshotBannerReserve.swift` to the app, so the app leaves the caption band's space empty;
    the test passes `SnakelaneBanner.launchArguments(slot:)` when it launches the app.

3. Add the Archive post-action (`snakelane bump --post-action`) and remove any old bump build
    phase.

    For a Mac deck as well: list `macos` in `platforms`, add `"mac": {}` under `screenshots`, use
    `frame: snakelane`, and add `ScreenshotWindowSizer.swift` from `assets/macos/` to the **app**
    target (its header shows where to attach it). The shared UI test template already captures
    the window on a Mac.
    `references/gotchas.md` → The Mac lane has the traps.

4. `snakelane store push --dry-run` should print the whole listing with no network access;
    `snakelane shoot --dry-run` shows the screenshot plan.

5. Record in the app's `AGENTS.md` anything deliberately different about it.


## Credentials

One method, one place: a [team API key](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api) (App Manager role, generated at
<https://appstoreconnect.apple.com/access/integrations/api>), installed once per machine:

```bash
snakelane auth setup --issuer-id <uuid> --key ~/Downloads/AuthKey_<KEYID>.p8
snakelane auth check            # read-only request proving Apple accepts it
```

The key lands at `~/.appstoreconnect/private_keys/AuthKey_<KEYID>.p8` (0600) and the ids in
`~/.config/snakelane/credentials.json`. Team-scoped: one key serves every app. Dry runs need
none of it.

- **No environment variables.** `APP_STORE_CONNECT_API_KEY_*` are ignored. Do
  not add them back or read them in an app's scripts: Xcode launched from the Dock never sees
  them.
- **Never handle the `.p8`'s contents yourself.** Don't print, copy or commit it. `auth setup`
  moves the file and refuses to overwrite a different installed key; if it refuses, ask the
  user — replacing a key means the old one may need revoking in App Store Connect.
- A 401 from any command: run `snakelane auth check` before suspecting anything else.

## Stays manual in App Store Connect

The [privacy nutrition label](https://developer.apple.com/app-store/app-privacy-details/), the app's own price and availability, repricing an existing IAP,
and **[every subscription price](https://developer.apple.com/help/app-store-connect/manage-subscriptions/manage-pricing-for-auto-renewable-subscriptions)**: through the API a subscription is priced one territory at a
time with no safe resume, so `subs push` creates a subscription unpriced and says so; set the
price once on the website, where it fills in every territory. (The age rating is no longer
manual: `age_rating` in the config.)

## Changing snakelane itself

When snakelane is wrong or missing something, fix snakelane — never patch around it in the
app repo, and never copy its code into one.

If this skill folder sits inside a snakelane checkout (`<checkout>/skills/snakelane/`), that
checkout is the source: `uv tool install --editable <checkout>` makes the installed command
run it directly, so an edit takes effect immediately in every app. Make the change there,
prove it with dry runs against a real app (`snakelane -C <app repo> store push --dry-run`),
and follow `<checkout>/AGENTS.md`. Commit to the user's fork; offer a pull request upstream
only if the user wants one.

If the skill was installed as a copy (e.g. by `npx skills add`), there is no source here —
tell the user the change belongs in snakelane and offer to clone their fork.
