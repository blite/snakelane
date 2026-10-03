# Changelog

All notable changes to snakelane. Versions follow [semver](https://semver.org); while the
major version is 0, a change that needs new `snakelane.yml` keys or changes a command's
behaviour bumps the minor version. Each release is tagged `vX.Y.Z`.

## Unreleased

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
