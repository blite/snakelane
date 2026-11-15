# Design notes: Game Center

These are the reasons behind decisions in `src/snakelane/gamecenter/`.

## Sync

### Xcode leaves a live record's new languages behind

Klondike Solitaire's `.gamekit` gained eight languages for every achievement, leaderboard and
activity (2026-11-14). Xcode's sync reported nothing wrong and App Store Connect still held
en-US alone: every achievement and leaderboard's newest version was live, a localization hangs
off a version, and App Store Connect doesn't edit a live one. Even the activities, whose
version 3 was still being prepared, got none. So the earlier rule that the text is Xcode's (below)
no longer holds. `gamecenter sync` writes each record's localized text and images where they
differ from its newest version, making the next version first when that one is live, since
changed text needs a new version just as a changed image does. It then fills the draft review
submission, because a new version reaches players only through review. Records are still
Xcode's: their ids, points and formatters are set once, and a record App Store Connect doesn't
have is reported and skipped. A locale App Store Connect holds and the bundle doesn't is reported,
never deleted, since deleting text from a live record isn't something a sync should decide.
Only fields the bundle sets are compared or sent: a leaderboard's `description`, which Xcode's
bundle doesn't carry, is left as it is.

### Every achievement language needs a picture

Klondike Solitaire's five achievements, each with eight new languages and a picture in en-US
alone, were refused from the review submission ("not in valid state", 2026-11-15), while its
leaderboards and activities, set up the same way, went in. App Store Connect wants a picture on
every language of an achievement. A Game Center picture in this family carries no words, so a
copy per language in the repo would be the same file nine times. `sync` instead gives an
achievement language without a picture in the bundle the primary locale's (`primary_locale`,
else the first of `locales`), or the record's only one. Leaderboards and activities are left
as they are.

## Images

### Xcode syncs the records, not the images

Xcode's Game Center editor keeps achievements, leaderboards and activities in a `*.gamekit`
bundle in the repo and syncs it to App Store Connect. In Solitaire (2026-10-10) the records and
their text arrived and the images didn't: each achievement and leaderboard image had to be
uploaded by hand in the web UI. `gamecenter images push` does that step and nothing else. It
never creates a record, localization or locale: records are Xcode's, and a second writer of them
would be two authorities on identifiers App Store Connect never lets you rename. Localizations
are `gamecenter sync`'s since 2026-11-15 (above).

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

## Review

### Game Center records go to review in one call

A new achievement or leaderboard reaches players only through App Review, and a first one must go with an app version. App Store Connect's web pages add each record to a submission from its own page, so a first release of Pyramid Solitaire meant thirteen trips through "Add for Review", and Golf's nineteen (2026-10-15). The API takes them as review submission items, one relationship per kind (`gameCenterAchievementVersion`, `gameCenterLeaderboardVersion`, `gameCenterLeaderboardSetVersion`, `gameCenterActivityVersion`, `gameCenterChallengeVersion`; the OpenAPI spec 4.5.1), so `gamecenter submit` adds every record whose newest version is in Prepare for Submission, Rejected or Developer Rejected. Ready for Review means it is already in a draft; anything later is in review or live. It adds the app version being prepared too, and stops at the draft: submitting is a decision, and `ship release` is the command that makes it. `ship release` adds any records still waiting to the submission it sends, so a release can't leave them behind, and skips adding the app version when `gamecenter submit` already put it in the draft (adding it twice is refused).

