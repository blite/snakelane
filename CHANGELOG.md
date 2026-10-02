# Changelog

All notable changes to snakelane. Versions follow [semver](https://semver.org); while the
major version is 0, a change that needs new `snakelane.yml` keys or changes a command's
behaviour bumps the minor version. Each release is tagged `vX.Y.Z`.

## Unreleased

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
