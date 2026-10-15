# gamecenter: Game Center images and review

Xcode's Game Center editor writes a `*.gamekit` bundle and syncs its achievements, leaderboards
and activities to App Store Connect, but not their images. `gamecenter images` uploads them.

```bash
snakelane gamecenter images show                # each image against live (read-only)
snakelane gamecenter images push --dry-run      # the same, plus every write it would send
snakelane gamecenter images push                # compare, confirm (--yes skips), upload, verify
snakelane gamecenter images push --new-version  # also for records whose newest version is live
```

What is pushed, from `gameCenterResources.json`:

| Image | Size | On App Store Connect |
|---|---|---|
| Achievement, per locale | 1024×1024 | the newest achievement version's localization |
| Leaderboard, per locale | 1024×1024 | the newest leaderboard version's localization |
| Activity default image | 3840×2160 | the newest activity version |

All must be RGB with no transparency; the push checks every file before it reads App Store
Connect. An app in a Game Center group keeps its records on the group, and snakelane looks there.

Each image is marked:

- **new**: the record has no image yet;
- **changed**: the live image's pixels differ (App Store Connect re-encodes uploads, so bytes
  never match);
- **unchanged**: same pixels, nothing sent;
- **skipped**, with the reason: the file is missing, Xcode hasn't synced the record or the locale
  yet, or the record's newest version is live or in review.

A live version is not edited in place. `--new-version` creates the next version of a record
whose newest is live and puts the image there; that version is reviewed with the next app
version. A replacement deletes the old image first (App Store Connect keeps one per
localization); if the upload then fails, the push says so in red. After uploading it waits for
Apple's processing and reads each image back, comparing pixels again.

Settings: `gamecenter.gamekit` in [the config](../reference/config.md#game-center-gamecenter),
only needed when the repo has more than one bundle. Why it works this way:
[design notes](../design/gamecenter.md).

## Sending the records to review

```bash
snakelane gamecenter submit --dry-run     # every record waiting for review, and the writes
snakelane gamecenter submit               # add them to the draft review submission (--yes skips the prompt)
snakelane gamecenter submit --without-version   # leave the app version out
```

App Store Connect's web pages add each achievement or leaderboard to a submission one at a
time ("Add for Review"). `submit` adds them all: every achievement, leaderboard, leaderboard set,
activity and challenge whose newest version is in Prepare for Submission or was rejected, to the
app's draft review submission (a new one if there is none). The app version being prepared joins
the same draft, since a first achievement or leaderboard must go to review with an app version.
It never submits: check the draft in App Store Connect and submit it there, or with
`ship release`, which adds any records still waiting to the submission it sends.

Records already in a draft (Ready for Review), in review or live, and archived records, are
listed and left alone.

