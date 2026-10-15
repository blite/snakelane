# Changelog

All notable changes to snakelane. Versions follow [semver](https://semver.org); while the
major version is 0, a change that needs new `snakelane.yml` keys or changes a command's
behaviour bumps the minor version. Each release is tagged `vX.Y.Z`.

## Unreleased

- **`gamecenter submit`** adds every Game Center record waiting for review (achievements,
  leaderboards, leaderboard sets, activities, challenges) to the app's draft review submission,
  with the app version being prepared, in one run; `--dry-run` shows it and `--without-version`
  leaves the version out. It never submits. App Store Connect's web pages take them one page at
  a time, thirteen for Pyramid Solitaire's first release. **`ship release` now sends any records
  still waiting with the version**, and no longer adds a version already in the draft.

- **`lint` checks Game Center achievement points** (`gamecenter-points`, an error): an
  achievement in the `.gamekit` worth more than 100, or more than 1,000 in all. App Store
  Connect refuses either, and Xcode's Game Center sync then creates nothing and shows no
  error. Pyramid Solitaire's 150-point achievement kept all thirteen of its records off App
  Store Connect through five syncs (2026-10-15). The bundle is `gamecenter.gamekit`, else the
  repo's only one.

- **The default iPhone size is 6.3"** (1206×2622, shot on the iPhone 17 Pro), the class Apple's
  screenshot specifications now require ("iPhone with Dynamic Island, medium display") and
  ASC's media page offers first. It was 6.5" (iPhone 14 Plus). The 6.3" slot, `APP_IPHONE_61`,
  is new: its sizes (1179×2556 and 1206×2622) used to fail the push as unknown, and its App
  Preview slot takes 886×1920. A 6.5" or 6.9" deck still uploads, now with a warning; re-shoot
  to move an app, and the push deletes the old class's live set. `frame`'s default iPhone
  canvas follows. An app that names `iPhone 14 Plus` in `screenshots.devices` keeps shooting
  6.5" until it changes the name.

- **A callout's placement can differ per deck.** `edge`, `centre`, `width`, `height` and
  `radius` under `framing.caption.callout` take a mapping by deck, as `caption.position` does:
  `centre: {iphone: 0.09, ipad: 0.88}`. A landscape table on its side leaves its bare felt in
  different places on a phone and a tablet, and one centre covered cards on one of them.

- **`lint` flags "free" as a price reference** in the name, subtitle, keywords and screenshot
  captions. It was left out as too common in honest copy, until App Review rejected FreeCell
  for the caption "A free deal, every day" (2026-10-14), after Spider Solitaire's "Free to
  play every day". A word with "free" inside it (FreeCell) doesn't match; a phrase that only
  looks like a price, such as a "free cell" keyword, goes in `lint.allow`.

- **Screenshot captions can differ per deck.** A deck key in `framing.captions` (`iphone`,
  `ipad`, `mac`) holds that deck's own captions, one map or per locale; every other deck uses the
  rest. A Mac deck can say "click" and "window" while keeping its shots numbered from `ss-01`.
  The missing-shot check now runs per caption set, against the decks that use it, so an iOS-only
  shoot no longer needs Mac captures to exist (and the reverse). Cloudless Cam had numbered its
  Mac shots 05-07 to get Mac wording, and then neither platform could finish a shoot in a fresh
  checkout. `lint`'s price check covers each deck's captions.

- **`framing.device` values can differ per deck.** Any key (`width`, `radius`, `gap`, `bleed`)
  takes a mapping by deck, as `caption.position` already did: `radius: {iphone: 0.07, mac:
  0.012}`. The radius is a share of the capture's width, so the 7% that suits a portrait phone
  rounded a landscape Mac window's corners off its traffic lights and toolbar buttons. A deck
  left out of the mapping gets the default.

- **`bump` in a repo with several Xcode projects asks TestFlight only about its own.** In
  `"project"` scope the next build number took the highest TestFlight build of every app in the
  repo, so a second app in its own project (FreeCell's repo taking Pyramid) started from the first
  app's numbers. It now considers only the apps whose `project` is this app's.

- **`gamecenter images push`: Game Center images from Xcode's `.gamekit`.** Xcode's Game Center
  editor syncs achievements, leaderboards and activities to App Store Connect but not their
  images. The new command reads every achievement and leaderboard image (per locale) and each
  activity's default image from the bundle, checks size and alpha offline, compares each with
  the live image by pixels (new, changed, unchanged), confirms (`--yes` skips it), uploads, waits
  for Apple's processing and reads every image back. Records Xcode hasn't synced yet are reported
  and skipped, never created. A record whose newest version is LIVE can't take a new image in
  place; `--new-version` makes the next version for it. `gamecenter images show` is the read-only
  view. The bundle is the repo's only `*.gamekit`, or new `snakelane.yml` key
  `"gamecenter": {"gamekit": <path>}`; nothing to change for an app without Game Center.

- **`store push` checks the App Review contact before writing.** App Store Connect refuses any
  write to the review card (the notes included) until it has a first name, last name, email and
  phone, and that refusal used to arrive after the listing text was already written. Now a push
  that changes the review card stops first, naming the missing `review/first_name.txt`,
  `last_name.txt`, `email_address.txt` or `phone_number.txt`; a field already set on App Store
  Connect counts. The phone must start with `+` and a country code, and the email must look like
  one; both are checked offline with the other limits.

- **`lint` rejects price references (Guideline 2.3.7).** New `price-reference` rule, an error:
  "buy", "purchase", "sale", "one-time", "subscription", a currency amount and similar, in the
  name, subtitle, keywords or any `framing.captions` caption. `store push` stops on it. "free"
  is deliberately not flagged. A phrase that only looks like a price goes in `snakelane.yml`'s
  new `"lint": {"allow": [...]}`; `lint.ignore` still turns the rule off entirely.

- **`store push --dry-run` shows the diff.** With an API key set up it reads App Store Connect and
  prints the same coloured word diff the real push asks about, then stops; it used to list every
  local field without reading anything. With no draft version it diffs against the live one.
  Without a key it still prints the local plan.

- **`framing.decorate`: app-only art over framed shots.** Name a repo-relative Python file whose
  `decorate(image, shot)` snakelane calls for every framed shot, after the caption, with the
  slot, locale, deck, the capture's box on the canvas and the theme's colours. It returns the
  image to save (same size) or `None`. For art one app wants and no other (badge cards), so it
  lives in that app's repo. Without the key nothing changes.

- **Per-locale captions.** `screenshots.framing.captions` also takes a map keyed by ASC locale,
  each value today's `{"1": "Caption", …}` map, so `frame` and `shoot` (with `frame: snakelane`)
  caption each locale's deck in its own language. A locale without an entry gets the primary
  locale's captions, and `frame` / `shoot --dry-run` say so. The banner handoff is worked out
  per locale. Mixing shot numbers and locales in one map is an error. The one-map form is
  unchanged; nothing to do for an app that keeps it.

## 0.2.0

- `gallery` labels each shot with the display App Store Connect files it under, e.g.
  `1284×2778 (6.5")`, `2064×2752 (13")`.
- **`ship beta|release` explains a new app's first export.** When the export fails because the
  bundle id has no App Store provisioning profile and the API key can't make one (cloud
  signing), `ship` stops with the two ways past it, uploading the built archive from Xcode's
  Organizer once or giving the key the Admin role, instead of xcodebuild's error and a
  traceback. The skill gains `references/first-release.md`, a walkthrough of everything a first
  submission needs that later releases don't.
- **The skill covers export compliance**: setting `ITSAppUsesNonExemptEncryption` on the app
  target is a setup step (the agent asks the user which answer applies), so builds don't wait at
  "Missing Compliance".
- **`test.mac`** gates a Mac release on this Mac: with it set, `ship beta|release --platform
  macos` and `ship test --platform macos` run the tests with `platform=macOS,arch=arm64` (or
  `test.mac.destination`) instead of the iOS simulator. Absent, nothing changes.
- **The skill's templates are split by platform**: shared ones at the top of `assets/`,
  iOS-only ones (`FramedScreenshot`, `VideoPreviewUITests`, `record_gameplay_video.sh`) in
  `assets/ios/`, Mac-only ones in `assets/macos/`.
- **The Mac lane works from the templates.** `ScreenshotsUITests.swift.template` builds for macOS:
  it captures the app's window, fails a shot that isn't an App Store Connect Mac size, and
  attaches only the raw shot (frame the Mac deck with `frame: snakelane`). A new
  `macos/ScreenshotWindowSizer.swift.template` pins the app's window under `--ui-window-size`.
  `FramedScreenshot.swift.template` is UIKit-only behind `#if canImport(UIKit)`.
- **Apps must change:** the UI-test templates' launch sentinel is now `--ui-tests`, not a bare
  `UITests`, which on a Mac AppKit opened as a file, so the app launched with no window. An app
  that copied the templates should rename it in its tests and anywhere it reads the argument.
- **`frame --platform macos`** frames only the Mac deck. It used to re-frame every deck with
  raws, iOS included.
- **UI tests stay serial in the templates too.** `ios/record_gameplay_video.sh` runs its test with
  `-parallel-testing-enabled NO` on the named simulator and records that one, instead of waiting
  for a parallel-testing clone; it writes to the repo's `build/previews/`, not `/build/previews`.
  The skill says to keep "Execute in parallel" off.
- **The Mac lane's Automation Mode check** passes on a Mac where the mode can be switched on
  without a password: the tool reads "disabled" at rest, and XCTest turns it on for the run.

## 0.1.0

First release.

- **`store`**: the listing, categories, age rating and App Review card from plain-text
  `metadata/`, diffed against App Store Connect, confirmed, written and read back. Also
  screenshot decks, App Previews, one-time purchases and subscriptions (`iap.yml`).
- **`lint`**: listing checks for common App Review rejections, run before every push and release.
- **`shoot`**, **`frame`**, **`check`** and **`gallery`**: shoot the deck from the app's UI
  test, caption it (three layouts, four caption shapes, eight built-in themes), OCR it for
  developer HUDs, and review it as an HTML page.
- **`ship`**: test, archive, upload to TestFlight and submit for review; **`bump`**: the build
  number, set by the scheme's Archive post-action; **`status`**: what's live and in review.
- **`packs`**: Background Assets packaging and upload. **`translations`**: stale and unreviewed
  translated fields.
- **`auth`**: one App Store Connect API key per machine, read from fixed paths, never from the
  environment.
- `--dry-run` on every push reads App Store Connect and prints each request it would send,
  without sending any.
- The `snakelane` agent skill, shipped in the same repo.
