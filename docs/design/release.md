# Design notes: releasing, build numbers and purchases

These are the reasons behind decisions in the `release/` and `purchases/` code, moved out of
comments so the code stays short.

## Shipping

### No build-number bump in ship

`snakelane ship` never bumps the build number. The archive runs the scheme's Archive
post-action (`snakelane bump --archive`), which picks the number, writes it to the pbxproj and
stamps the archive, so a bump in `ship` would double-increment. What `ship` does is check the
number landed before uploading: the pbxproj must have moved during the archive, and the app and
every extension must carry it. Comparing the archive with the pbxproj alone is not enough,
because an unstamped archive was built from that same pbxproj and agrees with it. PuzzleReef
shipped the app at 13 and its extension at 4 over three builds; App Store Connect rejects that.

### Explicit archive destination and pinned project

The archive always passes `-destination generic/platform=…`. Without it, a multi-platform
scheme sometimes archives the Mac product for an iOS run: the archive succeeds and the upload
fails later. `-project` is pinned because a workspace beside the project (Jigsaw's holds a dev
tool) must not be what xcodebuild resolves.

### The marketing-version gate

Apple closes a version's train once it is approved, so a build that reuses the live
MARKETING_VERSION is rejected at upload (90062 / 90186), after a full test and archive. Jigsaw
and then PoolLog hit this. `ship beta` and `ship release` refuse before building, and
`ship bump-version` is the way out.

### The release test gate

A red suite stops the upload; that is what makes a one-command release safe. The gate always
runs on one iOS simulator: the suites exercise shared logic, so the iOS run gates the Mac build
too, and some UI test targets do not build for macOS at all (Jigsaw, PoolLog). Tests run
serially because parallel test clones leak into `~/Library/Developer/XCTestDevices` whenever a
run is killed. Serial keeps it to one clone, and any failure sweeps the set anyway.

### TestFlight polling filtered by platform

iOS and macOS share one build counter, and a build number is unique only per platform at Apple,
so `wait_for_build` filters by platform. On a timeout `beta` carries on (the changelog can be
added by hand) and `release` stops, because it needs the processed build.

### Xcode does not manage the build number at export

The export options set `manageAppVersionAndBuildNumber: false`. Otherwise Xcode rewrites
CFBundleVersion to the App Store Connect maximum plus one at export: a second opinion on the job
the post-action already did, and how two machines end up disagreeing about what number shipped.

### /usr/bin first on PATH for the export

`xcodebuild -exportArchive` runs `/usr/bin/rsync`, which finds its server half by PATH lookup.
A Homebrew rsync 3.4 or later ahead of it rejects the flags, and the export fails with "Copy
failed" after a good archive (Jigsaw). The key path passed to the export is absolute because
xcodebuild rejects a relative or tilde'd path with an unhelpful auth error.

### The release lint reads App Store Connect, not the files

`ship release` submits the listing App Store Connect holds and never pushes text itself, so the
lint gate checks the live listing. It also warns when the local files differ: a fix not yet
pushed would not go to review. It runs before the tests and the archive, as does the check of
the `release` block, so a listing problem or a typo costs seconds rather than an archive and an
upload.

### MARKETING_VERSION is scoped by bundle id

`ship bump-version` changes only the configurations of the app and its extensions, not every
MARKETING_VERSION in the file. Test targets carry their own (Jigsaw's sit at 1.0 under an app at
1.6), and a project may hold other apps entirely (SwiftNVR holds six).

## Build numbers

### How the number is picked

The next build is max(the pbxproj's CURRENT_PROJECT_VERSION + 1, the latest TestFlight build +
1). The committed pbxproj is the durable record and travels with the repo, so clones and rebases
cannot regress it; TestFlight is the cross-machine backstop. The git commit count that
fastlane's lane mixed in is gone: it added nothing the pbxproj already guaranteed and caused
meaningless jumps (a project at build 2 leaping to 86 because history had 86 commits). App Store
Connect tracks builds per platform, so archiving iOS then macOS from one commit consumes two
numbers, which nothing objects to. Per-platform counters were built and reverted in Solitaire on
2026-08-27: bookkeeping without correctness.

### One record: the pbxproj

`Metadata/build_number.txt` existed from 2026-09-09 to 2026-09-15, because a build phase that
writes the project file makes Xcode cancel the archive ("Build stopped", no error, no archive in
the Organizer). Two records drift apart, and that shipped a broken build in PuzzleReef: the
stamp silently failed, the archive fell back to the other record, and the app went out at 13
with its extension at 4. snakelane no longer reads a leftover `build_number.txt`; the TestFlight check keeps a number
from being reissued.

### Why an Archive post-action

Writing the pbxproj is safe only because nothing writes it during a build. The post-action runs
once the archive is finished, under `xcodebuild archive` as well as Cmd-Archive, so `ship` and
the IDE share one mechanism. The alternatives were measured. A scheme pre-action is off by one:
xcodebuild snapshots build settings before pre-actions run, so the archive carries the old
number. A build phase with `--stamp-product` (the 2026-09 Spades, Hearts, Euchre, Solitaire and
WordSearch design) works only without an extension: embedding one orders the app's
ProcessInfoPlistFile after every build phase, forcing the order is a dependency cycle, and the
phase also needs ENABLE_USER_SCRIPT_SANDBOXING = NO (SwiftNVR, 2026-09-18).

### Stamping a signed archive

The post-action cannot influence the build it follows, so it stamps the finished archive: the
app, every nested `.appex` (an extension whose CFBundleVersion differs from its container is
rejected at submission), and the archive's `ApplicationProperties`, which the Organizer lists.
This breaks the archive's signature. That is what Xcode's own `manageAppVersionAndBuildNumber`
does too: `xcodebuild -exportArchive` re-signs every bundle on the way out, and export is the
only way an archive is consumed. Do not hand an unexported `.xcarchive` to a device.

### Text edits, not agvtool or a library

The projects configure no VERSIONING_SYSTEM, so agvtool would no-op or demand a setting nothing
else needs. Why the pbxproj is edited by targeted text rather than a parsing library is in
[ADR 0001](../adr/0001-no-pbxproj-library.md).

### The TestFlight check degrades, never fails

The key lives in files under `$HOME`, not environment variables, because an Xcode launched from
the Dock has no shell variables: before snakelane the check quietly stepped aside on exactly those
archives. Requests time out at 10 seconds with no retries, and use `get` rather than `get_all`
(with limit 1, `get_all` follows `next` through every build the app ever uploaded). Any failure
falls back to local arithmetic: a number higher than necessary is harmless, an archive whose
post-action died is not.

### Post-action logging and repo discovery

Xcode shows nothing from a post-action unless it fails, and then only in the Report navigator.
So everything `bump` prints is also appended, timestamped, to
`/tmp/snakelane-<app>-bump-build.log`, and a failure before the app is known goes to
`/tmp/snakelane-bump-build.log`. Xcode does not run post-actions from the project folder, so the
repo is found from the working directory, then `$PROJECT_DIR` and `$SRCROOT`, which Xcode sets.

## Background Assets packs

### Path equivalence and the staging tree

A file's path inside the archive must equal the path it would have if the pack were bundled.
That lets the app resolve a file the same way whether it shipped in the binary or was
downloaded, and no manifest is rewritten when a pack moves between the two. `ba-package`
resolves selectors against its working directory, and the source folder rarely matches the
in-app path (PuzzleReef: `Content/approved/animals/` on disk, `packs/pictures/animals/` in the
app). So `package` hardlinks the files into a staging tree that mirrors the bundle and runs
`ba-package` from there.

### Manifest rules

Selectors are explicit `file` entries, never a `directory`: pack contents are immutable once
uploaded, so a directory selector makes a stray `.DS_Store` permanent, and listing what
`pack.json` names catches a manifest that has drifted from disk. Packs are `onDemand`, because
an `essential` or `prefetch` pack counts toward the product page's download size and takes the
timing away from the user. Apple-hosted packs reject `userInfo`. The archive carries no version;
App Store Connect assigns one at upload.

### Platforms are a ratchet

A pack's platforms come from the record and may be added, never removed. Declaring a platform
the app record does not list is ITMS-91139, which is cosmetic. Dropping one an earlier version
declared is ITMS-91148, and that stops the pack appearing on that platform (PuzzleReef's
`animals`, v1 then v2, 2026-09-11/12). snakelane.yml's `platforms` is not used, because a pack
should not stop reaching a platform just because no listing has been written for it.

### Upload needs a person at a terminal

`packs upload` exists so the `altool` command is not retyped from a doc, and it does what a
retyped command skips: passes the API key the way altool resolves it, refuses a pack no release
enables, enforces ten packs per submission, and records the upload. The confirmation is read
from a terminal and there is no `--yes`, so an agent or CI job cannot run it. An upload starts a
review that replaces live content for every user with no TestFlight-style hold. altool will not
take a path to the `.p8`; it scans fixed directories for `AuthKey_<key_id>.p8`, which is why
`auth setup` installs the key where it does and `API_PRIVATE_KEYS_DIR` is set explicitly.

### Only unsent packs by default

With no themes named, `upload` sends only archives not yet marked `uploaded`. It used to send
every archive in the build folder. On the first real run (PuzzleReef, 2026-09-11) that put a
pack delivered an hour earlier first in line; altool answered "already delivered" (-19247), the
loop stopped, and the pack that needed sending never was.

### contentVersion is Apple's asset pack version

Since PuzzleReef on 2026-09-12, the version Apple assigns at upload is written back as the
pack's `contentVersion`, so there is one number for one thing. This works because `pack.json`
ships in the binary, not the archive: the next build carries the new number, and the app can
invalidate caches exactly when the content was replaced. `archive_bytes` is also recorded at
upload rather than at package time, so it names the size of what is live.

## In-app purchases and subscriptions

### Creation behind --create

Product ids, like Game Center ids, can never be reused once they have existed, even after
deletion. The IAP sync began as a localization-only script that stopped short of creation
because a new product also needs a price, availability and a review screenshot. snakelane does
all of that, but only with `--create`, and checks the id's character set (letters, digits,
underscores and periods) only at creation, the one moment a wrong id becomes permanent.
`--product` takes full ids only, and an unknown one stops the run so a typo cannot look like a
successful push of nothing.

### One catalogue file

One-time purchases and subscriptions shared two files until 2026-10-02 and now live in one
`iap.yml`. To whoever sells them they are one list, App Store Connect files both under In-App
Purchases, and they share one id space, so a duplicate id is caught before `--create` could
spend it. Unknown keys warn, because a misspelt optional key is otherwise silently ignored: one
app's catalogue said `review_notes` and its review note never reached App Review.

### Set-once price, availability and review screenshot

Localizations are additive: missing ones are created, changed ones patched, identical ones left
alone, because touching an approved localization re-opens the product for review. Price,
availability and the review screenshot are set only when none exists. Repricing a live product
has customer-facing timing and belongs in the App Store Connect website, and replacing a review
screenshot re-opens review, so a rejected screenshot is reported rather than retried. A
subscription's period and family sharing are terms of a live subscription, so a mismatch is
reported and never changed by a sync.

### Subscriptions are priced on the website

Since 2026-10-02 `subs push` never sets a price. Through the API a subscription is priced one
territory at a time (about 175 POSTs), and a run that failed partway left the rest unpriced with
no safe way to resume. The website prices every territory from one price. `subs show` reads the
price back, and a failed read stops the push rather than reading as "unpriced".

### Dry runs without credentials

`iap push --dry-run` is a diff against App Store Connect, so without credentials the per-repo
copies died before printing anything. snakelane still validates the catalogue locally (limits,
keys, ids), lists it, and says that nothing was compared.
