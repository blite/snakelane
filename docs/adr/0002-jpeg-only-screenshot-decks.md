# 2. Screenshots are JPEG only

- **Status:** accepted
- **Date:** 2026-10-02

## Context

App Store Connect accepts screenshots as `.jpeg`, `.jpg` or `.png`. It does not accept HEIC,
and it rejects any image with an alpha channel, even one that is fully opaque
([Apple: screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications)).

Screenshots usually start as PNGs with an alpha channel. `XCUIScreen.main.screenshot()` writes
them, and so does Core Graphics compositing in a UI test (a caption banner, for example). Until
now snakelane accepted PNG and JPEG in a deck. It removed the alpha channel from each PNG as it
uploaded, and `gallery --live` had to repeat that step before it could compare checksums with
what was live. `screenshots.framing.format` could also be set to `png`.

The deck is committed: `metadata/<platform>/screenshots/<locale>/…`. A deck has up to ten shots
per device, for every locale that has its own screenshots, and each re-shoot adds a new copy to
git history.

## Decision

Every screenshot snakelane uploads is `.jpg` or `.jpeg`: the deck (what `store screenshots
push` uploads and `gallery` shows) and the App Review screenshot of each in-app purchase and
subscription. `iap.yml` naming a PNG `review_screenshot` is refused when the catalogue loads. A `.png` in a deck folder stops the push before anything is sent and says how to
fix it; an `_`-prefixed file is excluded as before and can be anything. `snakelane shoot` and
`snakelane frame` always write JPEG at quality 90 with 4:4:4 chroma (no subsampling).
`framing.format` is gone; a config that still sets it gets an error telling you to delete it.

Raw captures in `.snakelane/<app>/raw/` stay PNG. They are what framing reads, and they are not
committed.

## Why

- **No alpha channel.** A JPEG cannot carry one, so the most common upload rejection cannot
  happen. Stripping the alpha channel during upload meant the bytes sent differed from the bytes
  in git, and every tool that checks what is live had to strip it the same way.
- **Size.** A framed shot is about 5 to 10 times smaller as JPEG than as PNG, about 1 MB a
  shot at 6.9" sizes. Across devices, locales and re-shoots, that decides
  whether the repo stays small enough to clone (see `local/issues/06`). Uploads are faster too.
- **Quality holds up.** At quality 90, keeping full chroma resolution keeps coloured caption
  text sharp, and each shot is encoded only once: framing reads the PNG raw, never an
  earlier JPEG.
- **One format, one code path.** Extraction and framing share `save_jpeg`. The
  push, the gallery and the checksum comparison read files exactly as they are on disk.
- **HEIC isn't an option.** App Store Connect doesn't accept it.

## Consequences

- A hand-made PNG deck must be converted once, either by re-running `snakelane frame` from its
  raws or with any tool that flattens the alpha channel and writes JPEG.
- The checksum `gallery --live` compares is the MD5 of the file on disk, the same bytes the
  push sends.
- Review screenshots for in-app purchases and subscriptions are the clearest case. Only App
  Review sees them, so quality hardly matters, yet they have the same alpha-channel rule. With
  them JPEG too, snakelane has no alpha-stripping code at all.
- Pixel-exact output is not possible. Nobody has needed it for store marketing images.

## Revisit when

- App Store Connect accepts a format that is smaller at the same quality (HEIC, AVIF).
- A shot turns out to need lossless output, for example fine line art that shows JPEG
  artefacts at quality 90. A per-slot quality setting would be the first thing to try.
