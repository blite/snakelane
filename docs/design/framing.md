# Design notes: framing and the gallery

These are the reasons behind decisions in `snakelane frame`, `framing/` and `snakelane gallery`,
moved out of code comments. [Framing: layout, caption, theme](../reference/framing.md) lists the
keys; this page says why the code behaves as it does.

## Framing

### Three independent choices

On 2026-10-02 the flat framing keys (`band_fraction`, `band_color`, `layout: overlay` and the
rest) were split into layout, caption and theme, so that any layout takes any caption shape and
any theme. Old keys are refused with their new name rather than translated. That keeps one
spelling in configs and docs, at the cost of a one-time edit per app.

### A missing captioned shot fails the run

A caption is a slot the deck promises. If no platform produced it, a stage never ran or a file
went missing, and the deck would ship a shot short while `frame` reported success. TowerDefense's own
captioner exited 1 on exactly this, and `frame` keeps that behaviour. The check runs across
platforms, because an iPad deck may leave out a phone-only shot.

### Captures are made upright first

A landscape XCUIScreen capture keeps portrait pixels and records the turn in EXIF (Solitaire's
raw `ss-02`). The capture is transposed by its EXIF before anything else, so a slot's `rotate`
counts from what a viewer sees. `rotate` is anticlockwise, as Pillow counts.

### Beside scales rather than painting over

PuzzleReef's old framer (2026-09-11) painted the band over the top of the capture and beheaded
the close button on every shot. `stacked` scales the capture into the rest of the canvas, so the
caption costs no content.

### Fill-width crops the far end

`stacked` with `fit: crop` fills the width and crops the end away from the caption. A game's
lives, cash and wave row sits near the top, and it is what makes a screenshot read as a game in
progress (Picnic Defense). What is lost is a button and a sliver of lawn.

### The plain band's extra pixel row

The plain band's colour runs one row into the capture beneath it. PuzzleReef's framer drew the
band with an inclusive rectangle, and keeping that row means a reframe reproduces its committed
JPEGs byte for byte instead of changing every file by one pixel row.

### Caption sizing follows Solitaire's arch

Without `caption.size`, a multi-line caption is sized the way Lamplight Solitaire's arch sizes
its headline: from the band's depth above the crown, shrunk until the widest line fits, with the
type's area stopping a little above the crown. Fonts differ in where their ink sits (Rockwell's
capitals reach above the ascent line, Avenir's sit well below it), so when Solitaire's placement
would push the ink out of the area the code centres the ink instead.

### The arch is one shape

The arch's body, lip and rule all follow one parabola, so they read as one shape, as
Solitaire's does. An arch that sags (a negative `caption.arch`, used by Jigsaw Puzzles) puts the
type above its sides rather than its crown. A bottom band is drawn as a top band and mirrored,
so every layer faces the capture, and its shadow falls up onto the capture.

### Why there is a callout

The callout exists for Solitaire's landscape shot. A band along the top of a turned table would
read sideways, so the caption hangs in a box off one side instead. The box runs past its edge by
twice its radius, so only its inner corners are round.


### Caption marks follow Markdown

Until 2026-10-02 a word between single asterisks took the accent colour, the convention of
Picnic Defense's captioner. Adding bold and italic, as storescreens has, meant `*word*` had to
mean italic, as it does everywhere else. The accent moved to `==word==`, Markdown's highlight
mark, and a second colour to Pandoc's `[word]{colour}`. A deck whose theme has an accent but
whose captions only use single asterisks gets a note, since that is almost certainly the old
meaning. Italic is a real face or an error: a slanted copy of the upright face looks wrong
next to a font's own italic.

### `frame` honours `--platform`

`snakelane frame --platform macos` used to frame every deck with raws, because the flag reached
only the `frame: test` path. In Word Search (2026-10) it re-framed the committed iPhone and iPad
decks from stale raws while framing the first Mac deck, and they had to be restored from git.
`--platform` now limits the run to that platform's decks; with neither `--platform` nor `--deck`
every deck with raws is framed, as before.

## Themes

### Taken over number for number

The built-in themes are the looks that the apps snakelane grew out of drew in their own UI tests
and scripts: felt (Lamplight Solitaire), ruby (Spider Solitaire, Spades), evergreen (Euchre),
parchment (Jigsaw Puzzles), indigo (Puzzle Reef), campfire (Picnic Defense), azure (Pool Log)
and dusk (Cloudless Cam). Their values were copied exactly so each app could drop its own
framing code without its deck changing. There is one theme per distinct look. A recolour, such
as Hearts' coral rim or Spades on the Mac, is a variation shown in the docs, not a built-in.

### Sizes under 1 are shares of the canvas height

Ornament sizes (lip, rule, shadow, outline) below 1 are a share of the canvas height, so a theme
keeps its proportions on every device. Whole numbers stay pixels.

### Fonts and colours come from the Mac and the app

A theme uses only fonts every Mac ships with, because a theme cannot bundle one. An app that
wants another sets `font` to a file in its repo. A `{"colorset": path}` colour is read from the
app's own asset catalog, so the band is the colour the app draws rather than a copy that can
drift. A `.ttc` font is searched by face name because a collection's face order is not
documented.

### App art is the app's code

Cloudless Cam's hand-made deck (2026-10) had three badge cards on its Add Camera shot ("Works
with ONVIF", "RTSP", "H.265"), drawn by the app's own caption script. Moving the app onto
snakelane dropped them, because framing had no way to draw them. A badge option in the theme
would have been one app's art in shared code, with a schema to keep growing for the next app's
idea. `framing.decorate` instead hands each framed shot, and where its capture landed, to a Python
file in the app's repo. The art, the placement and the translations stay with the one app that
wants them. The hook gets the capture's box rather than fixed coordinates, so art pinned to the
screen stays put when the layout or theme moves the card.

## The banner handoff

### Why snakelane tells the app the band's depth

With `layout: full-bleed` the caption lies over the capture, so the app has to leave that strip
empty while it is screenshotted. Solitaire, Spider and Spades did this by pushing every screen
down by the band's depth, and kept that number equal by hand in two targets. Since snakelane
draws the band, it hands the depth over instead: `shoot` writes it to `/tmp/<slug>-screenshot-banner.json` before
each pass, and the UI test passes it to the app. The depth includes the lip and rule.
[Making room for the band](../commands/screenshots.md#making-room-for-the-band) shows the file.

### Slots that reserve nothing

A slot with a callout, a turned capture, key art (a slot with a `bias`), or any layout other than
full-bleed gets `none`. In the other layouts the caption doesn't overlap the capture, so there
is nothing to keep clear, and key art isn't a screen the app lays out.

### Key art is a full-bleed slot, not a layout

There was a `cover` layout for Picnic Defense's key art: fill the canvas, crop toward the
bottom. It was full-bleed with a different crop position, so it became the slot's `bias`.
A slot with a `bias` is key art, which reserves nothing. The
file's top-level position and depth are the most common slot's, for apps that read only one.

## The gallery

### Where the idea came from

The search preview and gallery idea came from storescreens-cli, on 2026-10-02. The before/after
comparison and the review panel (lint and translation status per locale) are snakelane's own.

### The page lives outside the repo

The page is written to `/tmp` because it is a view, not a source. Without `--bundle` it links
images by `file://` URL, which is instant and always current but only opens on this Mac.
`--bundle` copies every image beside `index.html` for CI artifacts or sending to someone. Live
thumbnails stay links to Apple's CDN. A bundle inside the app's metadata folder is refused,
because the push would then read the copied images as decks.

### The gallery reads decks as the push does

Decks are found with the push's own folder rules, exclusions and order, so the page shows what
would be uploaded. An empty locale folder is kept, because the push reads it as "delete this
locale's live sets". Deck folders for locales not in `snakelane.yml` get their own section: they
exist on disk but the push ignores them.

### How `--live` matches screenshots

Live screenshots are matched by display type and order, and compared by the MD5 App Store
Connect stores, computed the same way the push uploads. What the live set has beyond the deck is
shown as removed, because the push deletes it. A deck of another platform than the fetched
version is left unmarked rather than shown as all new.

### Inheritance follows the store

A locale with no deck shows the primary locale's, as the App Store does. With `--live` the
primary locale is App Store Connect's own, and the page warns when `snakelane.yml` implies a
different one.

### The icon search

The icon comes from, in order: `gallery.icon`, the largest PNG in the repo's
`AppIcon.appiconset`, the App Store's icon (with `--live`), the largest AppIcon PNG of a build in
Xcode's DerivedData, then a lettered placeholder. Icon Composer `.icon` bundles are SVG layers
only Xcode renders, so apps using one get the store or DerivedData icon.
