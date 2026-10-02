# Examples

Two small repositories for a fictional hiking app, Trailhead, laid out the way snakelane reads
them. Copy one as a starting point, or run snakelane against it to see what each command does.
Nothing here needs an App Store Connect key: every command below runs offline.

## `trailhead/`: one app

```
trailhead/
├── snakelane.yml                  bundle id, locales, platforms, categories, screenshot lineup
└── metadata/
    ├── default/                   the listing, for every platform
    │   ├── name.txt  subtitle.txt  description.txt  keywords.txt
    │   ├── promotional_text.txt  release_notes.txt
    │   └── support_url.txt  marketing_url.txt  privacy_url.txt  privacy_choices_url.txt
    ├── de-DE/                     a full translation: overrides everything but the name
    ├── en-AU/                     overrides only keywords.txt ("bushwalking"); the rest is default/
    ├── copyright.txt              one per version, not per locale
    ├── review/                    App Review contact and notes, not localized
    ├── iap.yml                    everything it sells: one-time purchases and subscriptions
    ├── iap/offline_maps.jpg       the IAP's review screenshot
    ├── translations.json          what each translation was made from (written by `snakelane translations`)
    └── ios/                       only screenshots: the listing above is shared by every platform
        └── screenshots/
            ├── en-US/iphone/ss-01.jpg …   the iPhone deck, in upload order
            ├── en-US/ipad/ss-01.jpg …     the iPad deck (uploads into the same iOS version)
            └── de-DE/iphone/ss-01.jpg …   a German deck; en-AU has none, so it shows en-US's
```

Things to notice:

- **A missing or empty file means "leave the live value alone".** en-AU has no `name.txt`, so it
  gets the default; nothing ever pushes a blank over App Store Connect.
- **Screenshots are found by pixel size,** not by folder or file name: 1284×2778 is the 6.5"
  iPhone slot, 2064×2752 the 13" iPad. The names only set the order.
- **A locale with no screenshot folder inherits** the primary language's shots on the App
  Store (en-AU here). An *empty* folder is different: the push reads it as "delete this
  locale's screenshots".
- A platform folder holds only what differs. An app that also ships on the Mac adds
  `metadata/macos/screenshots/…`, and `macos/default/description.txt` only if the Mac
  description really is different. Name and subtitle can't differ: Apple stores one per app.
- Raw captures (before captions are drawn) live in `.snakelane/`, not here: `snakelane shoot`
  regenerates them, so they're gitignored. The example's shots are placeholder images.

Try it from the snakelane checkout:

```bash
snakelane -C examples/trailhead lint
snakelane -C examples/trailhead store push --dry-run
snakelane -C examples/trailhead store screenshots push --dry-run
snakelane -C examples/trailhead store iap push --dry-run
snakelane -C examples/trailhead translations status
snakelane -C examples/trailhead gallery --open
```

## `two-apps/`: several apps in one repository

```
two-apps/
├── snakelane.free.yml             metadata: metadata/free
├── snakelane.pro.yml              metadata: metadata/pro
└── metadata/
    ├── free/default/…
    └── pro/default/…
```

A free and a paid edition built from one Xcode project. Each has its own config at the root,
named `snakelane.<name>.yml`, pointing at its own metadata folder. Pick one with `--app <name>`
or `--config <file>`:

```bash
snakelane -C examples/two-apps lint --app pro
snakelane -C examples/two-apps store push --app free --dry-run
snakelane --config examples/two-apps/snakelane.pro.yml store push --dry-run
```

Both set `build_number_scope: app`, so archiving one edition never moves the other's build
number, and `project`, which names the shared `.xcodeproj`.

Every `snakelane.yml` key is documented in
[`skills/snakelane/references/config.md`](../skills/snakelane/references/config.md).
