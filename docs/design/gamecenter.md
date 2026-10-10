# Design notes: Game Center

These are the reasons behind decisions in `src/snakelane/gamecenter/`.

## Images

### Xcode syncs the records, not the images

Xcode's Game Center editor keeps achievements, leaderboards and activities in a `*.gamekit`
bundle in the repo and syncs it to App Store Connect. In Solitaire (2026-10-10) the records and
their text arrived and the images didn't: each achievement and leaderboard image had to be
uploaded by hand in the web UI. `gamecenter images push` does that step and nothing else. It
never creates a record, localization or locale: those are Xcode's, and a second writer of them
would be two authorities on identifiers App Store Connect never lets you rename.

### The bundle is read through its localizations

Image entries are keyed by a `localID` such as `grp.game.ach.winOne-en-US`. Splitting that on
the last hyphen works until a vendor identifier or a locale (`zh-Hant-TW`) has one of its own.
The bundle's `achievementLocalizations` and `leaderboardLocalizations` already pair each
`localID` with its record and locale, so those are the map.

### Pixels, not bytes

App Store Connect re-encodes an upload: a PNG sent as RGB comes back RGBA, with a different size
and checksum and identical pixels (checked on Solitaire's live images, 2026-10-10). Bytes or
`sourceFileChecksum` would call every image changed; comparing the downloaded full-size image as
RGB is what says whether the live one is this file. A live image that failed processing has
nothing to download, so it counts as changed and is replaced.

### A live version is not edited in place

Game Center records are versioned (`/v2/gameCenterAchievements/{id}/versions`, state
`PREPARE_FOR_SUBMISSION` … `LIVE`). The image hangs off a version's localization (an activity's
default image off the version), and only the newest version is a candidate. A version in
`PREPARE_FOR_SUBMISSION`, `READY_FOR_REVIEW`, `REJECTED` or `DEVELOPER_REJECTED` takes the image
directly. A `LIVE` one is what players see; changing its art is a new version, which App Review
sees with the next app version. Creating that version is a deliberate act, so it waits for
`--new-version`; without it the image is skipped with the reason. Apple documents that a new
activity version inherits the default image, and the new achievement or leaderboard version is
read again after it is created rather than assumed to have a localization. A version in review
is left alone either way.

### Delete, then upload, and say so if the second half fails

A localization holds one image, so a replacement deletes the old one first. If the upload after
that fails, the record is left with no image, which a player would see as a blank tile; the push
prints that in red with the record's name before the error, and a re-run shows it as new.
