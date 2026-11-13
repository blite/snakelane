# packs: Background Assets

[Background Assets](https://developer.apple.com/documentation/backgroundassets) is content
Apple hosts and your app downloads after install, instead of shipping it in the binary:
levels, picture sets, models. Each pack is its own App Store Connect resource with its own
review. It isn't an in-app purchase, though a purchase may be what unlocks one.

```bash
snakelane packs list                 # packs and their upload state
snakelane packs package <theme>      # build one pack's .aar, locally; adds its record row
snakelane packs package <theme> --available-from 1.9
snakelane packs upload --dry-run
snakelane packs upload <theme>       # asks in a terminal; there is no --yes
snakelane packs status [<theme> …]   # each pack's versions and processing state
```

`package` gives a pack with no row in the record (`metadata/release/asset_packs.json`) a new
row: its item count, the archive's size, `uploaded: false`. The release that enables the pack,
`available_from_version`, is never guessed. Pass `--available-from`, or set it in the record
afterwards; `upload` refuses a row without one, because the id freezes there. A row that
already exists is left as it is, apart from filling a null `available_from_version` from
`--available-from`.

`status` asks App Store Connect (read-only) for every recorded pack's versions, latest first:

```text
  villages1  v1   READY_FOR_TESTING      10/27/26, 1:24:00 PM
  unicorns1  v2   READY_FOR_TESTING      11/13/26, 7:56:47 AM
             v1   SUPERSEDED             8/17/26, 9:27:24 AM
  houses1    no versions at App Store Connect
```

A pack is ready for review once its latest version is `READY_FOR_TESTING`. If it is still
processing, don't submit the build: a reviewer would see a failed download.

!!! warning "Pack ids are permanent"
    An asset pack id freezes at its first upload, and a pack's platforms only ever grow. So
    `upload` only runs from a terminal, after a confirmation.

Settings: `asset_packs` in [the config](../reference/config.md#background-assets-packs-packs).
