# Gotchas

Each of these cost a debugging session or a rejection round-trip. They're grouped by where
they bite. None is specific to fastlane: they are App Store Connect, Apple ingest, simulator
and Xcode-project behaviours that outlived the tooling that first exposed them.

## Product IDs and the IAP catalogue

**Only alphanumerics, underscores and periods.** Anything else is a 409 at creation:
`A product ID can only contain alphanumeric characters, underscores, and periods`. Hyphens
and spaces are the two that occur naturally. Convert both to underscores, in one derivation
function rather than per name:

```python
def product_safe(name: str) -> str:
    return "".join(c if (c.isascii() and c.isalnum()) or c == "_" else "_" for c in name)
```

Folder names keep their hyphens, because a folder name is often also an **asset pack ID**,
where App Store Connect *does* allow them. The two names diverge for exactly the multi-word
themes; one function in each language should know that, and a test should assert every
generated ID matches `^[A-Za-z0-9_.]+$`.

**A failed push is not atomic.** Products before the failure in file order already exist and
are permanent. Always follow a failed push with `snakelane store iap show` before changing
anything: reconcile against what ASC now holds, not what the file says.

**A product ID is permanent from its first sale.** It cannot be renamed and must never be
repointed at different content: a customer who bought one owns whatever it names, forever.

**Repricing is refused on purpose.** `iap push` will not change the price of a live product,
so a routine catalogue sync cannot reprice something customers are buying. Reprice in the
web UI, deliberately.

**Every IAP needs an App Review screenshot, and its size rule is folklore, not documentation.**
Without one the product sits at `MISSING_METADATA` and cannot be submitted, however complete
everything else is. The size everyone quotes is **640×920**, the iPhone 4 screen minus its
status bar, which is why it looks so unlike any modern device. Apple's own current
[help page](https://developer.apple.com/help/app-store-connect/reference/in-app-purchase-information) states no dimensions at all; third-party sources split between "exactly 640×920"
and "at least 640×920" (with tvOS 1920×1080 and macOS 1280×800). Treat 640×920 as the floor,
expect the upload to be the real validator, and do not spend long hand-crafting a canvas:
developer-forum threads report "incorrect size" rejections even at documented sizes, so let
the API adjudicate.

The screenshot is for the reviewer's eyes only and never appears on the App Store. It should
show the purchase in context (the sheet or screen where that product is offered, with its
price visible), because its job is to help a reviewer find and exercise the purchase. A
single shot of the store sheet can legitimately serve an entire catalogue of products sold
through the same UI; there is no requirement that each product have a distinct image.

`iap push` uploads one only when none exists, because replacing a screenshot re-opens an
approved product for review.

## Listing text and categories

**Sub-categories must be fully qualified.** `GAMES_PUZZLE`, not `PUZZLE`; a bare name gives
`/data/relationships/primarySubcategoryOne - invalid value`.

**Never push an empty string.** ASC has no "leave this field alone", so `""` clobbers what is
live. A missing or blank local file must mean "no opinion" and be skipped.

**`filter[bundleId]` is a prefix match.** Querying `com.example.App` also returns
`com.example.AppPlus`. Taking the first result once pointed a push at the wrong app's
listing, stopped only by an unrelated name-collision error. Compare bundle ids exactly *and*
assert the numeric `apple_id`.

**Field limits:** name 30, subtitle 30, keywords 100, promotional text 170, description 4000.
Check locally before the call, so an over-length field is a typo rather than a half-applied
push.

**The name, subtitle and keywords must not mention price, not even "free".** [Guideline
2.3.7](https://developer.apple.com/app-store/review/guidelines/#2.3.7) (Accurate Metadata) treats any reference to the app's price or business model as
inappropriate in these fields, and it explicitly names free/discounted claims too: "No ads.
Play free. Buy once." was rejected for exactly this ("Play free" and "Buy once" both read as
price references), even though the app genuinely is free with an optional unlock. The
guideline's own suggested fix is to move that claim into `description.txt`, where Apple's
rejection note says it belongs. Pricing and "free"/"buy" language is fine there, and not in
`name.txt`, `subtitle.txt` or `keywords.txt`. Reject any subtitle draft
containing "free", "price", "buy", "discount", "sale", "% off" or similar before it goes out
for review, not after.

**Reviewers want privacy and terms links inside `description.txt`.** Populating ASC's
`privacyPolicyUrl` attribute is not the whole obligation. [Guideline 3.1.2](https://developer.apple.com/app-store/review/guidelines/#3.1.2) requires functional
links to both the Terms of Use (EULA) and the privacy policy *in the description*, and
reviewers apply it more broadly than the letter: apps with only a non-consumable unlock get
asked too. ~130 characters against a 4000 limit, versus a multi-day rejection round-trip:

```
PRIVACY AND TERMS

Privacy Policy: https://<host>/privacy/
Terms of Use: https://<host>/terms/
```

Check both return 200 before submitting; a dead link reads worse than no link. With no
custom terms page, link Apple's standard EULA:
`https://www.apple.com/legal/internet-services/itunes/dev/stdeula/`.

## Screenshots

**The caption band must not add height.** ASC enforces [exact dimensions per display type](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications)
(2778×1284 for iPhone 6.5", 2752×2064 for iPad 13"), so a band stacked *above* a
full-size capture makes the output ~13 % taller and every shot rejects with "Invalid screen
size". `snakelane frame` keeps the size in every layout: `full-bleed` paints the caption
over the capture's top strip; `stacked` scales the capture into the area below the band
and centres it, letterboxing the sides in the band colour.

**Prefer `stacked` unless the app leaves its top strip empty.** `full-bleed` is the
tidier-looking option, and the one that quietly destroys UI. It was chosen for PuzzleReef
because the top fifth of every shot is sky, which is true of the backdrop and false of the
app. That app is landscape-only, and its top strip carries the mascot, the developer buttons
and the close ×, so 13.5 % of 1284 px cut the close button in half on every shot of the
first real deck. Look at a framed shot before deciding; on a
landscape layout the answer is almost always `stacked`. An app that does leave the strip empty
gets its depth from `shoot` (the banner handoff), so the two never drift.

**Read the sizes off App Store Connect, not off a guide.** ASC names the accepted sizes for
each slot on the media page itself, and that is the only source that is about *your* app.
Third-party articles are confidently wrong in both directions. Several insist the 6.9" iPhone
set is mandatory when ASC offers 6.5" as the default slot, which would have sent a whole deck
to the wrong class.

**Shoot the iPad at 13-inch (2064×2752), not 12.9-inch (2048×2732).** Sixteen pixels apart,
nearly the same physical panel, and ASC lists the 13" as the iPad slot's size while the 12.9"
is legacy. Both upload under the same `APP_IPAD_PRO_3GEN_129` display type, so nothing in the
API name tells you which you have. The pixel size is the only signal, and
`SCREENSHOT_DISPLAY_TYPES` is what has to know both.
Feeding a 13" shot to a table that lists only the 12.9" fails the push with "unknown
screenshot pixel size", which is at least loud. The trap is the simulator naming: the device
is called for its chip ("iPad Pro 13-inch (M5)"), while the legacy one is called for its
inches ("iPad Pro (12.9-inch) (6th generation)"), so the older, wronger device is the one
that reads like the deliberate choice.

**Name the simulator, not the size, when asking for hand-shot captures.** A person shooting
by hand picks a device from a menu, and the size follows from it; asking for "2778×1284"
leaves them to reverse-engineer which device that is, and several devices are one row apart
in the menu with a different size. The two ASC default slots today:

| Slot | Pixels (landscape) | Simulator | Note |
|---|---|---|---|
| iPhone 6.5" | 2778×1284 | **iPhone 14 Plus** | Also iPhone 12/13/14 Pro Max. NOT iPhone 15/16/17: those are 6.3"/6.9" classes at different sizes. |
| iPad 13" | 2752×2064 | **iPad Pro 13-inch (M4)** or later | NOT "iPad Pro (12.9-inch) (6th generation)", which is 2732×2048. |

Verify rather than trust the table: `xcrun simctl list devices available` names what is
installed on this machine, and one capture's pixel size confirms the class in one step.

**Landscape-only apps must be captured with the simulator rotated.** ⌘← / ⌘→ before
capturing, not after; a portrait capture of a landscape app is not a rotated landscape shot,
it is the landscape scene letterboxed into a portrait canvas with black bars, and the usable
band is the wrong aspect ratio for every slot. Cropping can't save it; the shot has to be
retaken.

**Shoot with a Release-configuration scheme, not the debug one.** Otherwise anything gated on
`DEBUG` or a developer flag (an FPS/node HUD, autoplay and flag buttons, a developer menu door)
is in every capture, and it is easy to stop seeing after a week of looking at it.
Set up a scheme whose Run action uses Release before the first deck rather than after.

**Alpha channels are rejected.** Decks are JPEG only, which can't carry one; the push refuses a
PNG in a deck, and `iap.yml` refuses a PNG `review_screenshot`.

**Pixels are not points.** `XCUIScreen.main.screenshot().image` arrives at scale 3;
`UIImage(named:)` loads a bezel PNG at scale 1; `image.size` reports points. Mixing them
produces a tiny screenshot inside a huge bezel. Work in pixels throughout
(`cgImage.width` / `cgImage.height` with a `format.scale = 1` renderer), and re-check on both
iPhone (3×) and iPad (2×) after any change.

**Clip the screenshot to the bezel's corner radius.** Apple's bezel PNGs have a rounded
transparent screen area; a raw rectangular screenshot underneath leaves square corners
poking out at all four. Clip to a `UIBezierPath(roundedRect:cornerRadius:)` matching the
device. A wrong radius is visible within a few pixels.

**Bezel PNGs may not reach the UI-test bundle (Xcode 16 synchronized groups).** Test folders
under `PBXFileSystemSynchronizedRootGroup` bundle only what the target's
`membershipExceptions` lists. A file that is not listed returns nil from
`Bundle.url(forResource:)` and framing silently falls back to the unframed shot. After
adding `<UITestTarget>/DeviceFrames/<Device>-Portrait.png`, add that path to the target's
`membershipExceptions` in `project.pbxproj`. Do the same for `FramedScreenshot.swift` if
the group requires explicit listing for sources.

## App Previews

Raw `simctl io recordVideo` output can't be uploaded. It captures at the simulator's native
pixel size, at its native frame rate (often 60 fps, sometimes 48 or 37), with no audio
track, and Apple rejects all three. Every raw `.mov` needs an ffmpeg pass.

**Resolution must equal [Apple's canonical pair](https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications) for the preview type.** Strict equality, not
"close enough":

| Preview type | Dimensions (portrait) |
|---|---|
| `IPHONE_67` / `IPHONE_65` / `IPHONE_61` / `IPHONE_58` | **886×1920** |
| `IPHONE_55` / `IPHONE_40` | **1080×1920** |
| `IPHONE_47` | **750×1334** |
| `IPAD_PRO_3GEN_129` / `IPAD_PRO_3GEN_11` / `IPAD_105` | **1200×1600** |
| `IPAD_PRO_129` | **1200×1600** or **900×1200** |
| `IPAD_97` | **900×1200** |

Note 886×1920 is *narrower* than the 1320×2868 an iPhone 17 Pro Max captures, so the
transcode is a downscale plus pad. Pick the iPad token by generation as well as inches:
"iPad Pro 12.9-inch 6th gen" is `IPAD_PRO_129`, "iPad Pro 13-inch (M4)" is
`IPAD_PRO_3GEN_129`.

**30 fps cap.** Above that, Apple's ingest rejects with "frame rate is too high", after the
upload has succeeded. `recordVideo` does not honour `-r`; put `fps=30` first in the filter chain.

**An audio track is mandatory**, even for a silent app: "preview contains unsupported or
corrupted audio". Generate silence in the same pass.

**Prefer `.m4v` with `+faststart`** so the moov atom is at the head.

```bash
ffmpeg -y -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
  -i raw.mov -shortest \
  -vf "fps=30,scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2:black,setsar=1" \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart \
  out.m4v
```

**Apple ingests asynchronously and rejects after the fact.** A successful upload means the
bytes arrived, not that Apple accepted them. Ingest runs 5–25 minutes later, and its failures
appear only in the ASC web UI, never in the push log. Check App Information → Preview status
after every previews push, even one that reported success.

**Three previews per locale per device type.** A fourth displaces the oldest.

## Simulators and UI tests

**UI-test clones are invisible to a bare `simctl`.** `xcodebuild test` clones simulators into
`~/Library/Developer/XCTestDevices`, a CoreSimulator set separate from the default one.
Every `simctl` call against a clone needs `--set ~/Library/Developer/XCTestDevices`.

**Record against the clone, not the parent.** Starting `recordVideo` on the parent device
(the one named "iPhone 17 Pro Max") while tests run on a clone captures a black screen or a
0-byte file. Poll the XCTestDevices set for a booted clone and record against its UDID.

**Sandbox StoreKit purchases leak into later test runs.** An app that seeds entitlements from
`Transaction.currentEntitlements` will see packs a developer bought while debugging as owned
in every subsequent run. Guard the seed on a `--ui-tests` launch argument; clear existing state
with Xcode → Debug → StoreKit → Manage Transactions → Delete All.

## The Mac lane

**A dash-less launch argument opens no window.** AppKit reads `-name value` pairs out of the
arguments and takes any word left over as a file to open; a SwiftUI app launched that way
opens no `WindowGroup` window, so every shot fails with "view did not appear". A bare
`UITests` sentinel did it (the templates now pass `--ui-tests`), and so did the `69` a
value-less flag orphans: `-resetProgress -startLevel 69` pairs `-resetProgress` with
`-startLevel`. Pass `-name value` pairs first and value-less flags after them. To check a
launch by hand: `open -g <app> --args …` and look for its window; a windowless app has only a
menu bar in the test's UI hierarchy attachment.

**Capture the window, at a size the app pins.** On a Mac `app.screenshot()` is the whole
display. The template captures the app's largest window and fails a shot that isn't 1280x800,
1440x900, 2560x1600 or 2880x1800 pixels. XCUITest can't size a window, so the app does:
`ScreenshotWindowSizer.swift` (from `assets/`) pins the frame under
`--ui-window-size=1440x900`, which a 2x display captures as 2880x1800.

**`FramedScreenshot` is UIKit.** A Mac deck is framed by snakelane (`frame: snakelane`); the
template attaches only raw shots there.

**Automation Mode reads "disabled" at rest.** After
`sudo automationmodetool enable-automationmode-without-authentication` the tool still says
"Automation Mode is disabled"; XCTest switches it on for each run without a password. The
shoot's check accepts that.

**Quit the app before a shoot.** A copy running from Xcode's debugger can't be terminated by
the test ("Failed to terminate"), and the first shot fails.

## Xcode project

**Nothing may write the `.pbxproj` from a build phase.** Xcode watches the project file and
cancels a build whose project changes underneath it. The symptom points nowhere:
the log ends `Build stopped` after the last task with no error anywhere, nothing lands in
the Organizer, and command-line `xcodebuild archive` keeps succeeding because no IDE is
watching.

**Bump the build number in the scheme's [Archive post-action](https://developer.apple.com/documentation/xcode/customizing-the-build-schemes-for-a-project#Run-tasks-before-or-after-scheme-actions), not a build phase or a
pre-action.** A post-action runs once the archive is finished, so it can write the pbxproj
safely (keeping the pbxproj the single durable record) and stamp the finished archive.
A pre-action is off by one (`xcodebuild` snapshots build settings before pre-actions run); a
build phase either cancels ⌘-Archive (writing the pbxproj) or, with a separate counter file,
leaves two records that drift apart; and a build phase can't stamp the product at all in an
app that embeds an extension. `SKILL.md` → Build numbers has the whole history.

**Check that the hook exists, as well as the script.** An app can use snakelane with
nothing wired to call it (no phase, no post-action), and then every archive silently keeps
the old number. `grep -n PostActions` the app's `.xcscheme`; `/tmp/snakelane-<app>-bump-build.log` gets a
line from every run, even one that bails.

**A post-action needs an Environment Buildable.** Without one set to the app target, the
script runs with `ARCHIVE_PATH` and `PROJECT_DIR` empty. Log unconditionally at the top of
the script, so a post-action that never ran and one that ran and bailed look different.

**Multi-platform schemes need an explicit destination.** Without one, `xcodebuild` can pick
the Mac target in a scheme that supports iOS and macOS. Pass
`-destination 'generic/platform=iOS'` when archiving for iOS.

## Credentials

**`altool` finds the API key by filename, not by path:** `AuthKey_<key_id>.p8`, in a fixed
set of directories. So `snakelane auth setup` installs it under exactly that name in
`~/.appstoreconnect/private_keys`: `xcodebuild`, `altool` and snakelane then share one copy.
Don't copy the key into `~/.private_keys` as well; a second copy of a credential is one more
place for it to leak from.

**Environment variables don't reach Xcode.** An Xcode launched from the Dock has none of a
shell's variables, so a scheme post-action that relies on them silently runs without them.
snakelane reads only files under `$HOME` for this reason.

**One key serves the whole team.** It is [team-scoped](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api), so one `auth setup` covers every app in
the family.
