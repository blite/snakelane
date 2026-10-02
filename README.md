# snakelane

[![CI](https://github.com/blite/snakelane/actions/workflows/ci.yml/badge.svg)](https://github.com/blite/snakelane/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-blite.github.io%2Fsnakelane-green.svg)](https://blite.github.io/snakelane/)

**Documentation: [blite.github.io/snakelane](https://blite.github.io/snakelane/)**

> [!NOTE]
> **This repo shouldn't exist.** Keeping your store listing, screenshots and purchases in your
> repo, and shipping them alongside the build, should be core functionality in Xcode. Apple has
> shown it can do this: [Game Center configuration](https://developer.apple.com/documentation/gamekit/initializing-and-configuring-game-center) lives in a `.gamekit` file in your project and
> syncs both ways with App Store Connect. Until the rest of the listing works like that, there's
> snakelane.

An opinionated App Store Connect CLI for indie Apple developers and coding agents. Keep
listings, screenshots, and purchase catalogues in your repo, review changes, and ship with a
focused Python workflow.

`snakelane store push` sends listing text, categories, screenshots, [App Previews](https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications), in-app
purchases and subscriptions to the [App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi) from plain-text files.
`snakelane ship` runs test → archive → TestFlight → review. An [Archive post-action](https://developer.apple.com/documentation/xcode/customizing-the-build-schemes-for-a-project#Run-tasks-before-or-after-scheme-actions) keeps
build numbers right.

It covers the parts of fastlane a small app uses, without Ruby, lanes or a `Fastfile`. It
comes with an agent skill, so a coding agent can run it, and fix it when it's wrong.

Once per machine, install an App Store Connect API key with `snakelane auth setup`. Then:

```bash
snakelane lint                     # what App Review would reject
snakelane store push --dry-run     # everything that would change, offline
snakelane store push               # diff against live, confirm, write, verify
snakelane shoot                    # the screenshot deck, from your UI test
snakelane gallery --live --open    # every deck beside what's live
snakelane store screenshots push
snakelane ship beta                # test → archive → TestFlight
```

![The gallery page for the example app: search-result and product-page mocks above the iPad deck](docs/assets/gallery.png)

## Features

<!-- --8<-- [start:features] -->
**Listing**

- [x] Push, pull and show listing text, categories, copyright and App Review details from plain
   text files, with per-locale overrides over a shared `default/`
- [x] A word-level diff of every change before you confirm, then a re-read that verifies it
   landed
- [x] Never pushes a blank: a missing or empty file leaves the live field alone
- [x] Pre-review lint (`lint`): over-limit fields, other platforms named, placeholders,
   beta and "coming soon" wording, keyword waste, dead URLs; gates `store push` and
   `ship release`
- [x] Translation tracking (`translations`): which translated fields are stale or unreviewed
- [x] [Age rating](https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions) questionnaire and categories from the config, categories checked against
   [Apple's list](https://developer.apple.com/app-store/categories/) before anything is written
- [ ] Release notes drafted from the commits since the last release, for the agent to rewrite
   and you to edit
- [ ] Pre-review checks for release notes left unchanged since the last version, and for
   locales with screenshots but no translated text

**Screenshots and previews**

- [x] Shoot the deck from your own UI test across devices and locales, on simulators or the Mac
- [x] A failed shoot leaves the previous deck exactly as it was
- [x] Redraw caption banners without re-shooting (`frame`)
- [x] Caption styles from three separate settings (layout, caption shape and theme), with 8
   built-in themes and a preview that leaves the deck alone (`frame --theme`)
- [x] The app leaves room for the caption: `shoot` hands it the band's depth
- [x] Push screenshots and App Previews, with the slot worked out from [pixel size](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications), the
   10-per-set limit enforced, and Apple's processing waited on
- [x] Warnings for sizes other than the 6.5" iPhone and 13" iPad defaults
- [x] OCR check that refuses a deck shot from a debug build (`check`)
- [x] HTML review page (`gallery`): every deck against what's live or the last commit, App Store
   search-result and product-page mocks, lint and translation status per locale
- [ ] Caption-only localization: translated banners over the primary language's shots, with
   per-locale captions and fonts

**In-app purchases**

- [x] One-time purchases and [subscription groups](https://developer.apple.com/help/app-store-connect/manage-subscriptions/offer-auto-renewable-subscriptions) from one `iap.yml`; creation only behind
   `--create`, because [product ids are permanent](https://developer.apple.com/help/app-store-connect/reference/in-app-purchase-information), and an id used twice is refused. Subscription
   prices are set once on App Store Connect's website, where one price covers every territory

**Downloadable content**

- [x] [Background Assets](https://developer.apple.com/documentation/backgroundassets) packs:
   content Apple hosts and your app downloads after install, instead of shipping it in the
   binary. Package, verify and upload with `packs`

**Shipping**

- [x] `ship test | beta | release`: test, archive, upload, [TestFlight changelog](https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers) from git, attach,
   submit for review
- [x] [Build numbers](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleversion) from an Archive post-action: `max(project + 1, TestFlight + 1)`, stamped
   into the app and every extension
- [x] `ship bump-version` for the [marketing version](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundleshortversionstring)
- [x] [Release controls](https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/select-an-app-store-version-release-option): after approval, manual or scheduled, and [phased release](https://developer.apple.com/help/app-store-connect/update-your-app/release-a-version-update-in-phases), from the config
- [x] `status`: versions, review in progress and the latest TestFlight build, in one view
- [x] One auth method: a [team API key](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api) installed once with `snakelane auth setup`; no environment
   variables, no Apple ID sign-in
- [ ] Upload dSYMs to Sentry after a ship
- [ ] Slack notification when a ship finishes or fails
- [ ] Code signing for CI runners (under discussion: Xcode's automatic signing covers a Mac
   today)

**Setup and scripting**

- [x] `init` reads the Xcode project (scheme, bundle id, team, platforms) and writes the config
   and starter listing files
- [x] `--json` on `status`, `store show`, `lint` and `translations status`

**Agents**

- [x] An agent skill that knows how to drive snakelane, its App Store Connect traps, and how to
   fix snakelane itself
<!-- --8<-- [end:features] -->

## Install

Requires macOS with Xcode for `ship`, `shoot`, `bump` and `check`; `store` and `packs` need
only Python 3.11+ and an App Store Connect API key.

Fork this repo, clone your fork, and install it editable, so the installed command runs
your checkout:

```bash
git clone git@github.com:<you>/snakelane.git
uv tool install --editable ./snakelane
```

With an editable install, a fix you (or your agent) make in the checkout reaches every app
on the machine straight away. Commit it to your fork.

Optional extra: `--with pyobjc-framework-Vision --with pyobjc-framework-Quartz` for
`snakelane check` (macOS). Without cloning: `uv tool install git+https://github.com/blite/snakelane`.

## The agent skill

`skills/snakelane/` is an [Agent Skill](https://agentskills.io): a `SKILL.md` plus
references and templates. Any agent that reads skills can use it, including Claude Code,
Codex, Cursor, Gemini CLI and GitHub Copilot.

**Linked from your checkout (recommended).** The agent reads the skill from the checkout the
command runs from, so it can change snakelane in place:

```bash
# the shared agent skills folder, and Claude Code's
ln -s "$PWD/snakelane/skills/snakelane" ~/.agents/skills/snakelane
ln -s "$PWD/snakelane/skills/snakelane" ~/.claude/skills/snakelane
```

Use whichever skills folder your agent reads.

**Copied, with the skills CLI:** `npx skills add blite/snakelane` installs it into every
agent it detects. A copy can operate snakelane but not change it.

## How to configure

<!-- --8<-- [start:configure] -->
An app is one YAML config at the repo root, `snakelane.yml`, plus a `metadata/` folder of plain
text files. [`examples/`](https://github.com/blite/snakelane/tree/main/examples) has two complete, runnable repositories to copy from.

```
your-repo/
├── snakelane.yml                 bundle id, locales, platforms, categories, …
└── metadata/
    ├── default/*.txt             the listing for every platform: name, subtitle, …
    ├── <locale>/*.txt            per-locale overrides of any single field
    ├── copyright.txt
    ├── review/                   App Review notes + contact
    ├── iap.yml                   one-time purchases and subscriptions
    ├── iap/                      their review screenshots (JPEG)
    ├── ios/
    │   └── screenshots/<locale>/{iphone,ipad}/ss-NN.jpg
    └── macos/                    a second platform: only what differs
        ├── default/description.txt
        └── screenshots/<locale>/ss-NN.jpg
```

```yaml
# snakelane.yml
name: Trailhead
bundle_id: com.example.trailhead
locales: [en-US, de-DE]
platforms: [ios]
categories:
  primary: HEALTH_AND_FITNESS
```

The listing is written once and every platform uses it; a platform folder holds only what
differs, plus its screenshots. Name, subtitle and the privacy URLs [belong to the app](https://developer.apple.com/help/app-store-connect/reference/app-information/app-information) at App
Store Connect, so they can only be set in the shared listing. Raw captures (screenshots before
their captions are drawn) are regenerated by every shoot and live in `.snakelane/`, which you
gitignore, so everything in `metadata/` is something you edit or something that ships.

snakelane finds the config the way git finds `.git`, walking up from the working directory
(or from `-C <repo>`). A blank or missing text file means "no opinion": snakelane never pushes
an empty string over a live value. [`config.md`](https://github.com/blite/snakelane/blob/main/skills/snakelane/references/config.md) lists
every key.

YAML is read with YAML 1.2 rules, so `NO` (Norway) and `yes` stay text, and decimals are kept
exactly as written: a price of `9.90` stays `"9.90"`.

### Several apps in one repository

A repo can hold more than one app, for example a free and a paid edition built from one Xcode
project. Give each its own config at the root, named `snakelane.<name>.yml`, and point each at
its own metadata folder:

```
your-repo/
├── snakelane.free.yml            metadata: metadata/free
├── snakelane.pro.yml             metadata: metadata/pro
└── metadata/
    ├── free/ios/…
    └── pro/ios/…
```

Pick one on any command with `--app <name>` (the `<name>` from the file name, or any of the
config's `aliases`), or with `--config <file>`:

```bash
snakelane store push --app pro --dry-run
snakelane --config snakelane.pro.yml store push --dry-run
```

With a single `snakelane.yml`, neither is needed. Per-app keys keep the apps apart:

- `metadata` names the app's folder (default `metadata`).
- `project` names the `.xcodeproj` when the repo root has more than one.
- `build_number_scope: app` numbers only that app's targets (and its `extension_bundle_ids`),
  so one app's archive doesn't move the others' build numbers. The default, `project`, keeps
  one counter for every target in the project.
- `bundle_id` is matched exactly, so `com.example.trailhead` never resolves to
  `com.example.trailhead.pro`.
<!-- --8<-- [end:configure] -->

## Credentials

snakelane talks to Apple with one credential: a team App Store Connect API key with the App
Manager role. Create it under Users and Access → Integrations → App Store Connect API → Team
Keys, download the `.p8`, then:

```bash
snakelane auth setup --issuer-id <issuer id> \
  --key ~/Downloads/AuthKey_ABC123DEF4.p8
snakelane auth check
```

`setup` moves the key to `~/.appstoreconnect/private_keys/` (readable only by you) and writes
the key id and issuer id to `~/.config/snakelane/credentials.json`. Every command reads those
two files and nothing else, whether it runs in a terminal, in Xcode's Archive post-action or
in CI.
There are no environment variables to set, and no Apple ID sign-in. `--dry-run` needs no key.

In CI, install the key from secrets before running snakelane:

```bash
printf '%s' "$ASC_KEY_P8" | snakelane auth setup --key - \
  --key-id "$ASC_KEY_ID" --issuer-id "$ASC_ISSUER_ID"
```

## Build numbers

Add the Archive post-action that `snakelane bump --post-action` prints to your app scheme,
with "Provide build settings from" set to the app target. Every archive, from Xcode or
`xcodebuild`, then gets `max(pbxproj + 1, TestFlight + 1)`, written to the pbxproj and
stamped into the app and every extension. The skill explains why it is a post-action and
not a build phase.

## Contributing

Issues and pull requests are welcome. [`AGENTS.md`](AGENTS.md) has the rules for changing
snakelane, for people and coding agents both; [`CONTRIBUTING.md`](CONTRIBUTING.md) has the
short version. Changes are listed in [`CHANGELOG.md`](CHANGELOG.md).

snakelane is not affiliated with Apple or with fastlane.

## License

[MIT](LICENSE)
