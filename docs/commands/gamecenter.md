# gamecenter: Game Center images

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
