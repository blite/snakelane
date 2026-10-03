# `snakelane.yml`: every key snakelane reads

One YAML file per app at the repo root: `snakelane.yml`, or `snakelane.<name>.yml` for each app
in a repo with several (pick one with `--app <name>` or `--config <file>`). Everything that
differs between apps is here; nothing app-specific lives in snakelane's code. Unknown keys
inside `screenshots` fail loudly. Each module's docstring is the authority
(`python -m pydoc snakelane.<package>.<module>`, e.g. `snakelane.screenshots.shoot`; AGENTS.md
maps commands to modules).

Read with YAML 1.2 rules (only `true`/`false` are booleans, so `NO` and `yes` stay text), and
decimals are kept as written: `9.90` is `"9.90"`. JSON is valid YAML, so an old `app.json`
works renamed.

## Identity and listing (`store`)

| Key | Meaning |
|---|---|
| `name` | Display name, for log lines (default: the `<name>` of `snakelane.<name>.yml`) |
| `bundle_id` | Finds the app in ASC, matched **exactly** (Apple's own filter is a prefix match) |
| `apple_id` | Numeric App Store id, asserted when set. Empty until the record exists |
| `metadata` | The app's metadata folder, repo-relative. Default `metadata` |
| `scheme` | The app scheme, for test and archive |
| `team_id` | Signing team, for export |
| `locales` | Which locales are pushed (not whichever folders exist) |
| `primary_locale` | The App Store's primary language, which locales without a deck inherit; `gallery` uses it. Default: the first of `locales`. `gallery --live` reads the real one and warns on a mismatch |
| `platforms` | Legal `--platform` values: `ios`, `macos`. iPad screenshots are part of `ios` (`screenshots/<locale>/ipad/`) |
| `categories` | `primary`, `primary_subcategory_one`/`_two`, `secondary`, `secondary_subcategory_one`/`_two`; Apple's ids, `null` = unset. Checked before any write: a dry run against [Apple's list](https://developer.apple.com/app-store/categories/) as of 2026-10, a real push against the live list. Subcategories exist only under `GAMES` and `STICKERS` |
| `age_rating` | The [age-rating questionnaire](https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions), pushed by `store push`: Apple's question names in snake_case, e.g. `violence_cartoon_or_fantasy: INFREQUENT_OR_MILD`, `gambling: false`, `age_rating_override_v2: NONE`. Only answers that differ are sent; a real push refuses names App Store Connect doesn't ask. `snakelane store show --json` prints the live answers to start from |
| `aliases` | Extra names `--app` accepts (the file's `<name>` always works) |
| `project` | The `.xcodeproj`, repo-relative. Only needed when the repo root has more than one |
| `terms_url` | The Terms of Use URL an app that sells subscriptions must link in every description (`lint`'s `subscription-links`). Default: Apple's [standard EULA](https://www.apple.com/legal/internet-services/itunes/dev/stdeula/) |
| `lint` | `ignore: [test-word, …]`: `lint` rules to skip for this app, so a heuristic's false positive never forces a code change |
| `gallery` | `icon: path/to/icon.png`: repo-relative icon for `gallery`'s mocks. Default: the repo's `AppIcon.appiconset`, else (with `--live`) the App Store's icon, else a DerivedData build's |
| `developer_chrome_check` | `true`: `screenshots push` must OCR the deck for a DEBUG HUD (refuses if the `[check]` extra is missing). `false`: never. Absent: run if available |

## Release (`ship`, `bump`)

```yaml
test:
  scheme: AppTests               # default: scheme
  test_plan: App                 # -testPlan
  skip_testing: [AppUITests]     # keep slow screenshot suites out of the release gate
  env: {RUN_CONTENT_TESTS: "1"}  # for the tests; TEST_RUNNER_ is added (opt-in test suites)
  device: iPhone 17 Pro Max      # default
  destination: "…"               # full -destination, overrides device
  mac: {}                        # present = `--platform macos` tests on this Mac, not the
                                 #   simulator; {destination: …} overrides platform=macOS,arch=arm64
build_number_scope: project      # or app: only configs whose bundle id is this app's or an
                                 # extension's; for projects holding several apps
extension_bundle_ids: [com.example.app.downloader]
```

```yaml
release:                         # how `ship release` lets the version out (absent: leave as is)
  type: scheduled                # after_approval | manual | scheduled
  date: "2026-11-03T09:00:00-08:00"   # scheduled only; needs a timezone
  phased: true                   # 7-day phased release to automatic updates; false = everyone
```

## Screenshots (`shoot`, `frame`, `check`)

```yaml
screenshots:
  scheme: App (Screenshots)      # default: scheme; a Release-config scheme is recommended
  test: AppUITests/AppUITestsScreenshotsUITests   # -only-testing; null = whole scheme/plan
  test_plan: null
  devices:                       # name, UDID, or {name|id, os, deck: iphone|ipad}
    - iPhone 14 Plus             # 6.5", the default size
    - iPad Pro 13-inch (M5)      # 13"
  locales: [en-US]               # or a mapping {es-MX: es-MX, de-DE: de} → the language key
                                 #   written to /tmp/<slug>-screenshot-locale for the test
  env: {}                        # extra TEST_RUNNER_ variables
  frame: test                    # test (UI test draws captions) | snakelane | none
  reframe_test: null             # UI test that re-frames raws on disk
  mac: {}                        # present = enable --platform macos
  framing: {…}                   # `snakelane frame`: captions ({"1": …}, or per locale
                                 #   {en-US: {"1": …}, de-DE: {…}}; a locale without one gets the
                                 #   primary's), targets (keyed iphone/ipad/mac), and three
                                 #   independent choices: layout (full-bleed|stacked|device, fit),
                                 #   caption {shape band|arch|callout|headline, position, depth, …},
                                 #   theme (a built-in name, or {base, fill, text, accent, font, lip, …});
                                 #   slots.N: layout, fit, caption, rotate, bias.
                                 #   Every key: docs/reference/framing.md
  check: {patterns: […], corner: [0.45, 0.06], upscale: 3, advice: "…"}
```

Every `xcodebuild test` gets `TEST_RUNNER_SNAKELANE_LOCALE`, `…_LANGUAGE`,
`…_PLATFORM` (ios, macos) and `…_DEVICE` (iphone, ipad, or empty for the Mac), plus
`…_BANNER` with `frame: snakelane` and `…_REFRAME_LOCALE` for reframes. iOS UI-test runners don't
reliably see them, so the language key also goes through `/tmp/<slug>-screenshot-locale`, and
with `frame: snakelane` the band depth through `/tmp/<slug>-screenshot-banner.json`. A shoot
first sets aside every image in the deck and the `ss-*` shots in `raw/`, and puts them back if
it fails.

## Background Assets packs (`packs`)

[Background Assets](https://developer.apple.com/documentation/backgroundassets) is Apple-hosted
content an app downloads after install instead of shipping it in the binary. These keys
describe where the app's packs are and how they are built:

```yaml
asset_packs:
  manifests: Content/packs/pictures      # required: <theme>/pack.json per pack
  bundle_path: packs/pictures/{theme}    # required: in-app path the archive mirrors
  content_root: Content
  record: ios/asset_packs.json           # upload record, in the metadata folder
  build_dir: build/asset-packs
```
