# packs: Background Assets

[Background Assets](https://developer.apple.com/documentation/backgroundassets) is content
Apple hosts and your app downloads after install, instead of shipping it in the binary:
levels, picture sets, models. Each pack is its own App Store Connect resource with its own
review. It isn't an in-app purchase, though a purchase may be what unlocks one.

```bash
snakelane packs list                 # packs and their upload state
snakelane packs package <theme>      # build one pack's .aar, locally
snakelane packs upload --dry-run
snakelane packs upload <theme>       # asks in a terminal; there is no --yes
snakelane packs status               # what App Store Connect holds
```

!!! warning "Pack ids are permanent"
    An asset pack id freezes at its first upload, and a pack's platforms only ever grow. So
    `upload` only runs from a terminal, after a confirmation.

Settings: `asset_packs` in [the config](../reference/config.md#background-assets-packs-packs).
