# Changelog

All notable changes to snakelane. Versions follow [semver](https://semver.org); while the
major version is 0, a change that needs new `snakelane.yml` keys or changes a command's
behaviour bumps the minor version. Each release is tagged `vX.Y.Z`.

## Unreleased

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
