# Changelog

All notable changes to snakelane. Versions follow [semver](https://semver.org); while the
major version is 0, a change that needs new `snakelane.yml` keys or changes a command's
behaviour bumps the minor version. Each release is tagged `vX.Y.Z`.

## Unreleased

- **`asset_packs.items` names pack.json's list of entries.** `packs package` read the files to
  archive from `items[].resourceName` only, so an app whose manifests call the list something
  else (`puzzles`) packaged nothing. The key defaults to `items`; apps already using it change
  nothing.

## 0.5.0

- **The credential config moved to `~/.appstoreconnect/config.json`**, beside the key, and is
  shared with other tools (ASCStats): `{"issuer_id": …, "snakelane": {"key_id": …}}`, with each
  tool choosing its own key under its own name. The key id is the `AuthKey_<id>.p8` filename;
  without a `snakelane.key_id` the only key in `private_keys/` is used. `auth setup` merges into
  the file, keeping other tools' entries. **A machine set up before this must** re-run
  `snakelane auth setup` (or write the file by hand); `~/.config/snakelane/` is no longer read.
- **`snakelane preview` records the App Preview** from the app's video UI test, with the app's own
  sound, and encodes it into the deck as `ap-01.m4v` for `store previews push`. It replaces the
  per-app `record_gameplay_video.sh` / `encode_app_preview.sh` pair. The test and snakelane shake
  hands through `/tmp/<slug>-preview-events.jsonl` and `/tmp/<slug>-preview-rolling`; the sound
  comes from a Core Audio tap on the app's process (macOS 14.2+), with an optional music bed
  (`previews.audio.bed`), and `previews.overlay: {style: band}` draws the screenshots' caption band
  as a thin strip over the top. New `previews` keys; see `references/config.md`. **An app must**
  move its video test to the new handshake (`assets/ios/VideoPreviewUITests.swift.template`) and
  add `previews.test` if its test isn't named `<Scheme>UITestsVideoPreviewUITests`;
  `assets/ios/record_gameplay_video.sh.template` is gone.

- **`previews.launch` records the app with no UI test attached**: snakelane launches it into its
  video fixture and the app marks "start" and "end" itself (`assets/ios/PreviewMarks.swift.template`).
  An attached UI test made the iPad recordings stutter. Prefer it to `previews.test`.

- **`preview` warns when a recording stalls mid-motion** (a dropped-frame hitch from a busy
  Mac), and when the app's sound tap heard nothing. Re-record the clip it names.

- **`store previews push` checks what Apple's ingest rejects** before it deletes anything: length
  outside 15–30 s, more than 30 fps, or audio that isn't stereo AAC at 44.1/48 kHz. A preview
  with no audio track warns.

- **`previews.poster` sets the App Preview's poster frame**: a moment the app marks (`won`) or
  seconds into the clip. `preview` writes it beside the clip in `ap-01.json` (with the captions it
  drew) and `store previews push` sends it as `previewFrameTimeCode` when it reserves the preview;
  the dry runs show it. Unset, the frame stays Apple's. **An app should** set it and commit
  `ap-01.json` with `ap-01.m4v`: the poster can't be changed after the version is approved.

- **`preview` warns when a preview caption repeats ss-01's or ss-02's**, which a portrait preview
  plays beside in search results, in the dry run, after each encode and in the gallery's
  search-result mock (which now shows the preview's poster beside ss-01 and ss-02). With
  `frame: test` the shots' captions are read with Vision (`snakelane[check]`); without it the check
  says it can't run.

- **`store media push | show` uploads screenshots, App Previews and creative assets in one run**,
  with `--only screenshots|previews|creative` (repeatable) to pick some. Every kind's files, and the
  creative assets against Apple's specs, are checked before the first write, so a bad preview stops
  the run before any screenshot is replaced. A failure partway prints the `--only` command for what
  wasn't pushed. Without `--only`, a kind with no files in any deck is left alone live (previews
  kept only in App Store Connect survive a screenshot push); `--only previews` clears them. `store screenshots push | show`, `store previews push` and `store creative
  push | show` still work but no longer appear in `--help`; nothing in an app has to change.

## 0.4.0

- **`snakelane store creative push | show`: the product page header and the search-result asset**,
  App Store Connect's creative assets for iOS 27 and iPadOS 27 (October 2026), through the App
  Asset Library (API 4.5.1). Files go in `metadata/creative/<locale>/` or `creative/default/`
  (`<platform>/creative/` overrides): `search-result.*`, `product-page-header.*`, or a
  `universal.png` for both. Each file is checked against Apple's live reference data before
  anything is written; an unchanged file is reused from the library rather than uploaded again;
  a slot with no file is left as it is. No `snakelane.yml` keys; nothing changes for an app
  without a `creative/` folder.

## 0.3.0

- **A missing metadata folder stops every command that reads the listing**, naming the
  `metadata` key, instead of reading as an empty listing: `lint` reported clean for
  TowerDefense while its files were still in `Metadata/PicnicDefense/` (2026-10-16). `bump`'s log
  line now names the app, not the folder, so it doesn't need one.

- **`snakelane frame` frames a deck at one size.** Without `framing.targets`, a deck whose captures
  differ in size (key art beside screen captures) is framed at its most common App Store size, and
  the files that differ are named; it used to frame each at its own size, which left Picnic
  Defense's slot 9 at 1456x816. A target that fits no App Store slot is now a warning.

- **A hung screenshot test is cut off at three minutes and retried once** (`-test-timeouts-enabled
  YES`, a 180 s allowance, `-retry-tests-on-failure -test-iterations 2`). On a fresh simulator or a
  busy Mac a single XCUITest launch could hang for 13 minutes and fail the whole pass; Lamplight's
  and FreeCell's iOS 27 decks lost half an hour each that way (2026-10-15). A shot that fails twice
  still fails the shoot. When a retried shot leaves captures from both attempts, the newest of
  each slot, the passing attempt's, is the one filed into the deck.

- **`screenshots.mac.frame`** sets who captions the Mac deck, overriding `screenshots.frame` for
  it: an app whose UI test draws its iOS banners (`frame: test`) can have snakelane frame its Mac
  deck with `mac: {frame: snakelane}` and `snakelane frame --platform macos` (or plain `snakelane
  frame` for a Mac-only app). Jigsaw's Mac deck
  is captured by hand and had no captions at all (2026-10-15).

- **Fixed: a `stacked` capture scaled to fit now sits on the theme's `background`.** It was
  padded out to the full width in the caption's fill colour first, which covered the background
  the docs promise behind a scaled capture, so a Mac window in a cream band's theme came out on
  cream instead of the colour asked for.

- **`store iap push` reports a change to an approved localization instead of stopping on it.**
  App Store Connect refuses any API edit to an approved in-app purchase localization (HTTP 409,
  "Cannot edit InAppPurchaseLocalization when it is in ACTIVE state"); only its website changes
  one. The push used to die on the first, so nothing after it in the catalogue ran, new locales
  included. Now it skips each one, carries on, and ends with the list of changes to make on the
  website. A 409 on a localization that isn't approved is listed the same way, with Apple's
  words rather than "approved". Jigsaw's first push stopped at one French name before reaching the Italian and Russian
  localizations of nine packs (2026-10-15). Subscriptions are unchanged.

- **`asset_packs.source_under`** restricts `packs package` to pictures under one folder, e.g.
  `approved` when only reviewed content may ship: a pack whose `pictureSource` sits anywhere else
  is refused before anything is staged; the path is normalised first, so `approved/../raw` is
  refused too. A pack's contents freeze at first upload, and Puzzle Reef
  uploaded two packs from its pre-review folder before it had this gate (2026-09-12).

- **`gamecenter submit`** adds every Game Center record waiting for review (achievements,
  leaderboards, leaderboard sets, activities, challenges) to the app's draft review submission,
  with the app version being prepared, in one run; `--dry-run` shows it and `--without-version`
  leaves the version out. It never submits. App Store Connect's web pages take them one page at
  a time, thirteen for Pyramid Solitaire's first release. **`ship release` now sends any records
  still waiting with the version**, and no longer adds a version already in the draft. A record
  App Store Connect refuses (409) is left out and named: `ship release` still submits the version
  and lists it, `gamecenter submit` adds the rest and then stops with it. A version in Metadata
  Rejected joins the draft too.

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
