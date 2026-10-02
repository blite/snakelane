# shoot, frame, check: making the deck

## Shooting from your UI test

```bash
snakelane shoot --dry-run           # the plan: devices, locales, what's replaced
snakelane shoot                     # every device × screenshot locale
snakelane shoot --device "iPhone 14 Plus" --locales de-DE
snakelane shoot --platform macos    # the Mac deck, from this Mac
```

`shoot` runs the app's screenshot UI test on each simulator in the config's
`screenshots.devices`, once per screenshot locale, and files the captures as
`metadata/ios/screenshots/<locale>/iphone/ss-NN.jpg` (and `ipad/`, or straight in the locale
folder for the Mac). The raw captures, before captions, go to `.snakelane/`, which you should
gitignore. The status bar is pinned to 9:41.
If any run fails, the previous deck is put back as it was, so a push never uploads a
half-empty deck from a failed shoot.

Templates for the UI test are in the agent skill's `assets/`. Settings: `screenshots` in
[the config](../reference/config.md#screenshots-shoot-frame-check).

## Captions

Captions ("Every hike, logged") are drawn either by the UI test itself (`frame: test`) or by
snakelane after the shoot (`frame: snakelane`). `snakelane frame` redraws them over the raw
captures without shooting again, with whichever of the two the config names: snakelane's own
drawing, or the app's reframe UI test (`reframe_test`).

```bash
snakelane frame                  # every deck, en-US
snakelane frame --locale de-DE   # one locale
```

`frame` stops when a captioned shot has no capture, so a stage that never ran can't ship
unnoticed.

### Styling the caption

`screenshots.framing` makes three separate choices: the layout (where the capture goes), the
caption (band, arch, callout or headline, at the top or the bottom) and the theme (colours,
font and ornaments, starting from a built-in look). Per slot, `rotate` turns a
capture before framing, so a landscape shot can sit in a portrait deck.
[Framing screenshots](../reference/framing.md) explains each setting and lists every key, and
the [Screenshot showcase](../showcase.md) shows every theme, layout and caption shape.

This reproduces Lamplight Solitaire's deck, which its UI test used to draw in Swift:

```yaml
screenshots:
  frame: snakelane
  framing:
    captions: {"1": "No ads.\nNot one.", "2": "Play in\nlandscape"}
    layout: full-bleed        # the app leaves the top of each screen empty for the arch
    caption: {shape: arch, depth: 0.158}
    theme: felt
    slots:
      "2":
        rotate: 90            # anticlockwise: the landscape table on its side
        caption: {shape: callout, callout: {lip: 15}}
```

`snakelane frame --list-themes` prints the built-in themes:

```text
--8<-- "docs/assets/terminal/frame-list-themes.txt"
```

To try one on the same raw captures without touching the deck, run
`snakelane frame --theme ruby`. It writes to `.snakelane/<app>/themes/ruby/`.

### Making room for the band

With `layout: full-bleed`, the caption lies over the top (or bottom) of the capture, so the app
should leave that strip empty while it is being screenshotted. `snakelane shoot` tells
it how deep the strip is. Before each pass it writes the band's depth for that device, per slot, to
`/tmp/<slug>-screenshot-banner.json` (and inline in `SNAKELANE_BANNER`):

```json
{"version": 1, "deck": "iphone", "position": "top", "depth": 0.1699,
 "slots": {"1": {"position": "top", "depth": 0.1699}, "2": {"position": "none", "depth": 0}}}
```

The depth is a share of the capture's height. A slot with nothing to keep clear gets `none`: a
callout, a turned capture, key art, or a layout where the caption doesn't overlap the capture.
The skill ships the Swift for both ends:

- `SnakelaneBanner.swift` (UI-test target) reads the file and returns
  `--ui-banner-position=` and `--ui-banner-depth=` launch arguments for a slot.
- `ScreenshotBannerReserve.swift` (app target) is a view modifier that pads the screen by that
  much on that edge, and does nothing on a normal launch.

Change `caption.depth` or the theme's lip, and the app's reserve follows on the next shoot.
You don't keep two numbers in step by hand.

## Catching developer builds

```bash
snakelane check
```

OCRs every framed shot's corner for debug overlays (a SpriteKit `nodes … fps` HUD, developer
buttons) and exits non-zero if it finds one. macOS only, with the `[check]` extra.
`store screenshots push` runs it too; set `developer_chrome_check: true` to make the push
refuse when the check can't run.

