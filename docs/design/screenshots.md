# Design notes: shooting and uploading screenshots

These are the reasons behind decisions in `src/snakelane/screenshots/` (shoot, extract, check, media and upload), moved out of the code's comments so the code stays easy to scan.

## Shooting

### One shared screenshots config

`shoot` replaces the Fastfile's `screenshots` and `cleanup_sims` lanes, and before that eleven drifting copies of `Metadata/scripts/screenshots.py`. Everything that differed between those copies is now data: the `screenshots` object in the app's `snakelane.yml`. A typo'd key is an error rather than a silent fallback to a default, because that fallback is how a deck gets shot on the wrong scheme.

### The default lineup

The default iPhone is the iPhone 17 Pro, which shoots the 6.3" display class (1206x2622, `APP_IPHONE_61`; the iPhone 15, 15 Pro and 16 shoot 1179x2556, the same slot). Apple's screenshot-specifications page names it "iPhone with Dynamic Island (medium display)" and makes it the one required iPhone class ("At least one screenshot for iPhone with Dynamic Island (medium display)"), and ASC's media page now offers "6.1" or 6.3" displays" first. App Store Connect shows every class that was not uploaded natively as a dimmed, scaled copy, so shooting the required class is also what keeps it crisp there.

This was decided on 2026-10-15. Until then the default was the iPhone 14 Plus at 6.5" (1284x2778, `APP_IPHONE_65`), chosen on 2026-10-02 over a 6.9" device because ASC then offered 6.5" as its default slot and Apple scaled a 6.5" deck up to 6.9" but not a 6.9" deck down. Once ASC's media page led with 6.3", a 6.5" deck was the one shown dimmed. A 6.5" or 6.9" deck still uploads, with a warning; switching an app means re-shooting, and the push's stale-set sweep then deletes the old class's set.

The iPad is the 13" iPad Pro, which ASC now requires. The 12.9" (2048x2732) is legacy and no longer an installed simulator on current Xcodes; both file under `APP_IPAD_PRO_3GEN_129`. Switching class means re-shooting, because the push reads the class from the pixels and a stale set left in ASC keeps being preferred. A full `shoot` clears the tree first, so it handles this on its own.

### The Mac lane's window size

App Store Connect accepts Mac screenshots at exactly 1280x800, 1440x900, 2560x1600 or 2880x1800. The app sizes its own window (`--ui-window-size`); 1440x900 points on a 2x display gives the largest of the four.

### Simulators are addressed by UDID

The shoot resolves each lineup entry to one UDID and hands that same UDID to the status-bar pin and to `xcodebuild`. A name-only destination (`name=X`) implies the latest OS, so a device that exists only on an older runtime was "not found" while `simctl` listed it as available, and the shoot died after clearing the deck. A name is also not unique: one "iPad Pro 13-inch (M5)" exists per installed runtime, so the status bar was pinned on one and the test ran on another. Among same-named devices the newest runtime wins, which is what a name-only destination used to mean, unless the entry pins an `os`. `reframe` resolves its host simulator the same way.

### The status bar is pinned to 9:41

A deck should hide the status bar outright (the template's `UITestScreenshotScenario.hidesStatusBar`), and then the pin changes nothing. It stays because `simctl` can only override the bar's contents, not hide it, so a screen that escapes the flag shows a canonical 9:41 rather than the machine's clock. One deck went out reading 11:45, 11:46 and 11:47 across three shots, with the simulator's dotted placeholder carrier.

The device is booted first and `bootstatus -b` waits for the boot. `simctl status_bar` against a shut-down device prints "Unable to lookup in current state: Shutdown" to stderr without failing, so the override silently does not apply. That produced a deck with a charging-bolt battery left over from a previous boot's override. Overrides live on the device, and test clones inherit them.

### Tests run serially

`xcodebuild` gets `-parallel-testing-enabled NO`. On iOS this keeps the test on the parent simulator the status-bar pin already booted, rather than a cold test clone: cold clone boots are where XCUITest's launch request races SpringBoard and retries with a huge `wait_for_debugger` dump. `ship` runs its tests the same way. On a Mac the reason is stronger: parallel workers are separate copies of the app on the same desktop, and one's capture can catch another's window.

### A hung shot is cut off and retried

Every shoot's `xcodebuild` gets a three-minute allowance per test (`-test-timeouts-enabled YES`, default and maximum 180 s) and one retry of a failed test (`-retry-tests-on-failure -test-iterations 2`). A screenshot test is a launch, a wait and a capture: under a minute when the simulator is well. On a freshly created simulator, or a Mac busy with other builds, XCUITest's launch spent four to nine minutes "Setting up automation session", and the accessibility server then died (`kAXErrorServerNotFound`) under a query with a 20-second timeout that hung for thirteen minutes (Lamplight's and FreeCell's iOS 27 decks, 2026-10). One such shot failed the pass, and with it the deck, after half an hour. Cut off at three minutes and run again, the same shot passes on a relaunch; a shot that fails twice is a real failure, reported as before. A test that needs longer than three minutes is not a screenshot test.

A retried test leaves both attempts' attachments in the result bundle, and the hung attempt may
already have captured a shot or two in a bad state. The extract keeps the newest capture of each
slot (the attachment's `timestamp`), which is the passing attempt's; it used to keep whichever
the manifest listed last.

### A blank capture fails the shoot

A test can pass with nothing captured. Jigsaw's first Mac shoot (2026-10-28) passed all seven
tests and filed seven 544x340 white rectangles: the runner had no Screen Recording access, so
its window screenshots came back blank and small. A passing shoot discards the deck it set aside,
so the previous hand-made deck was lost with it. The extract now looks at every capture before
filing any: one flat colour, or a Mac capture under 1280x800 (the smallest Mac size App Store
Connect takes), exits the pass, and the failed shoot puts the previous deck back.

### The Mac lane checks for developer mode and Automation Mode

Both switches are administrator actions, so the shoot prints the commands rather than running them. They are once per machine, though an OS upgrade turns Automation Mode back off. Without developer mode the failure arrives after the whole project has built, as "The test runner failed to initialize for UI testing (Underlying Error: Authentication canceled…)", which names a dialog rather than the switch. Without Automation Mode every synthesized click and key is dropped after about five seconds with no error. The no-authentication setting is used because a run that asks for a password part-way through is a run nobody is watching.

The iOS lane needs neither switch, because the simulator is not the host.

### Automation Mode is on only during a run

The check first read only `automationmodetool`'s state line, after reading its password line as "on" once let a disabled Mac through to a build that dropped every click. But the state line says "Automation Mode is disabled" at rest on a correctly set-up Mac: in Word Search (2026-10, macOS 27) it read "disabled" before and after a Mac shoot and "ENABLED" while the test ran, because XCTest switches the mode on for its session once the no-password setting is made. The strict check could never pass, and sent the user back to `sudo` after they had run it. So the check now passes when the mode is on, or when it is off but can be switched on without a password. If clicks are dropped again with the mode reading "disabled" at rest, the earlier failure is back, and this note is where to start.

### The locale travels in a file, not the environment

Every `xcodebuild test` gets `TEST_RUNNER_SNAKELANE_*` variables, but an iOS UI-test runner does not reliably see them. Measured in Jigsaw and Spades: neither `TEST_RUNNER_` variables nor `-testLanguage` reached the UI-test process, and a reframe root passed that way was silently ignored while the run reported success. So the locale also goes through a file on the host's disk, which the simulator can read (`/tmp/<slug>-screenshot-locale`, and `/tmp/<slug>-screenshot-banner.json` for the caption band's depth). The file is removed after the run, because a stale one would make a later test run from Xcode shoot in whatever language this run ended on.

### The reframe test finds its own trees

A reframe test derives the deck trees from `#filePath` rather than being handed a root. A root passed through the runner's environment never arrived in Spades, whose iPad deck was re-framed zero times while every run reported success. Each platform re-frames on its own host because the banner is drawn with that platform's image type (UIKit or AppKit). Nothing is launched, so any booted simulator will do, and the first in the lineup keeps it predictable.

### What a shoot clears

In `framed/`, every image goes, because the push uploads every image there and the two filters have to agree. With `ss-*` an image left from older naming (`<device>-NN.jpg`) survived every re-shoot and shipped beside the fresh deck. That happened in Solitaire (fixed 2026-09-12), and snakelane's first default reintroduced it (2026-10-02). In `raw/`, only the shots go: nothing uploads from `raw/`, and it is where comparison captures are kept on purpose (PuzzleReef's `unused-02-…-alt.png`).

Only images are cleared, because the deck folders also hold the App Preview (`ap-01.*`), which takes minutes to record. Without the clear, a device change left the old set beside the new one, and the next push uploaded both: twelve near-duplicate shots in one ASC set. A full run sweeps every locale folder so a dropped locale stops shipping its old shots; a `--locales` run touches only the locales it re-shoots.

### Two devices cannot share a deck folder

Extracted filenames carry no device label, because the folder is the device class. Two devices mapped to the same folder would silently overwrite each other's `ss-NN` files and produce a deck that is half one phone and half another, so the shoot refuses.

### A failed shoot puts the previous deck back

Until 2026-10-02 the clear deleted every old shot up front. A UI test failing on locale three left the earlier locales empty or half-shot, and `store screenshots push` reads an empty locale folder as "delete the live sets" and a half one as the new deck. Now the previous deck is moved to `App.shoot_stash` (`.snakelane/<app>/previous-shoot/`) and moved back if anything fails. The stash is on the same volume, so moves are renames, and it survives a hard kill. A stash left by a killed run is refused rather than overwritten, since it may hold the only copy of the last good deck, and `store screenshots push` refuses too while it exists.

### The plan and the dry run share one code path

`shoot` builds its whole plan first and then executes it, and `--dry-run` prints that same plan. One code path for both is the only way the dry run can be trusted to say what a real run would do.

### Framing runs after every pass

With `"frame": "snakelane"` the captions are drawn last, over the raws that just landed, and only after every device has shot, so a half-shot deck is never framed. It is the same call `reframe` makes, so a shoot and a reframe cannot drift. `reframe` exists because the banner is a pure image-to-image transform: redrawing it takes seconds, where a shoot takes ten minutes and re-rolls every timing-sensitive fixture.

### No launch mode

Until 2026-10-02 there was a second way to shoot, for Picnic Defense: launch the app once per
stage with a `-ScreenshotStage <name>` argument and capture the simulator with `simctl io
screenshot`, no UI test. It was removed so there is one way to shoot. An app that stages its
own screens passes the same launch argument from a UI test and attaches a screenshot per stage;
the staging code in the app doesn't change.

## Extracting

### Extraction is a function, not a script

Extraction used to be `Scripts/extract_screenshots.py`, copied into every app repo and run as a subprocess. The shoot passed it a script path that moved whenever a repo reorganised its Scripts folder. It is one importable function now, which `shoot` calls after every pass.

### Shot names may contain hyphens

The attachment name pattern allows hyphens and digits after the first letter of a shot's name. PoolLog's shot names are hyphenated, where the card games' are single words, and the stricter single-word pattern silently counted PoolLog's whole deck as "unknown". An underscore still cannot appear in a name, which keeps the `_framed` and `_<seq>_` tails unambiguous.

### Files are named by slot only

`01-MidTrick` becomes `ss-01`. The deck's order is the whole filename: each device class already has its own folder, so a device label in the name is redundant, and the shot's name lives in the UI test where it can be read rather than in a filename that has to be parsed. An App Preview sits beside the shots as `ap-01`.

### Extraction writes JPEG

Attachments arrive as PNG and are written as JPEG at quality 90 (see [ADR 0002](../adr/0002-jpeg-only-screenshot-decks.md)). JPEG has no alpha channel, and ASC rejects screenshots that carry one, which XCUIScreen captures always do. The files are also about 5 to 10 times smaller. Quality 90 is what `snakelane frame` writes too, so a deck framed by the UI test and one framed afterwards match. JPEGs are written with no chroma subsampling, so caption text keeps sharp coloured edges.

Until 2026-10-02 shots went through macOS's `sips`. Pillow makes extraction and framing one code path.

### An empty extraction stops the run

A shoot that "succeeded" but produced no recognisable shot raises, rather than handing an empty folder to the push, which would read it as "delete the live sets".

## The developer-chrome check

### Why the check exists

On 2026-09-11 PuzzleReef's whole deck (7 iPhone shots, 5 iPad, raw and framed) was shot from the plain Debug scheme instead of the Release one, and uploaded. Every shot carried SpriteKit's `nodes:… fps` HUD in the bottom-right corner and the developer buttons down the top-left. Nothing caught it: the framer drew a caption over the top and the push uploaded whatever bytes it found, so the first reviewer of those pixels was App Review. The listing doc already said, in bold, to use the Release scheme. The check is the mechanical version of that sentence, on the path the files actually travel.

### What it looks for

It looks for SpriteKit's frame-rate HUD: the literal `nodes:<count>` and `<n> fps` that `SKView.showsNodeCount` and `.showsFPS` paint. The SpriteKit apps set both inside `#if DEBUG`, and in those projects DEBUG and the developer-menu flag are never set apart. So a HUD also means the developer buttons were compiled in and every scene laid itself out around them. A HUD-bearing shot therefore cannot be rescued by cropping, because the composition underneath is not the one that ships. It has to be re-shot.

`nodes:107` is the reliable half of the HUD. Vision reads `fps` inconsistently against busy artwork (`60.0 fps` came back as `60.0 fosi` on ss-02), so `fps` is a supporting match. Both patterns tolerate the space Vision inserts after the colon. Language correction is off because it turns `nodes:107` into prose.

### It reads only an enlarged corner

Reading the full-width bottom 15% at native resolution missed 2 of the 7 known-bad iPhone shots. Vision returned nothing for ss-05 and only the "Change" pill for ss-04, because the HUD is a few small glyphs in a 2778x192 strip. Cropping to the corner the HUD occupies (45% by 6%) and enlarging 3x reads all 12 known-bad shots. A guard that calls a dirty file clean is worse than no guard, so prefer a crop that is too tight and an upscale that is too generous. Reading only the corner also keeps caption copy and in-game text away from the matcher.

### A missing Vision install refuses rather than passes

The check needs macOS's Vision framework through pyobjc, an optional extra. Without it, `snakelane check` exits 3 rather than passing: a guard that cannot run has to stop the push, not wave it through. Exit 3 is distinct because the push reads 1 as "developer chrome found" and 2 as "unreadable file", and a missing dependency is neither.

### The push runs the check up front, as a subprocess

`store media push` runs the check before its first App Store Connect call, over every locale at once. The push deletes each set before uploading its replacement, so a refusal partway through would leave ASC empty. It runs under `--dry-run` too, because a dry run is how the deck gets eyeballed. It runs `snakelane check` as a subprocess so the optional pyobjc dependency stays out of the base install. Availability is checked before running rather than inferred from the exit code, because an import failure inside the subprocess also exits 1, the code for "developer chrome found", and would blame the deck for a broken install. Any exit code other than 1 or 2 is reported as the checker failing, not as evidence about the deck.

## Display types and sizes

### The display-type table

The display type is read from the image's pixel size. Both orientations are listed because a device rotated for a landscape shot still maps to the same slot. Which slot a deck fills is decided by what was shot, never by a config key. Sizes were verified against ASC on 2026-09-11 and Apple's screenshot-specifications page on 2026-10-02; the 6.3" class (1179x2556, 1206x2622) on 2026-10-15, from both. Apple moves this (the iPad slot already went from 12.9" to 13"), so ASC's own media page is the arbiter.

1290x2796, the third accepted 6.9" size (iPhone 14, 15 and 16 Pro Max and Plus), was missing until 2026-10-02, so a deck shot on one of those simulators failed the push as an unknown size. The legacy 12.9" iPad sizes stay mapped so an older deck still pushes until its next re-shoot. The iPad naming is a trap: the current device is named for its chip and the legacy one for its inches, so the older simulator is the one that reads like the deliberate choice.

iPhone Duo got its own slot on 2026-10-28: 1398x2034 for the outer (closed) display and 2007x2853 for the inner (open) one, per Apple's screenshot-specifications page, both in `APP_IPHONE_DUO`. That value is not in Apple's OpenAPI (4.5.1); another ASC client (App-Store-Connect-CLI#2926) created a set with it and uploaded the outer size, and nobody has uploaded the inner size yet. A Duo is a device of its own rather than a bigger iPhone, so it gets its own `duo/` deck, which a simulator named "Duo" files into by default; filed into `iphone/`, its shots would overwrite the phone deck's `ss-NN` names. Duo sets are optional until April 2027, when apps built with the iOS 27.1 SDK must have them. There is no Duo App Preview slot in `ACCEPTED_PREVIEW_SIZES` until one is confirmed, so `store media push` refuses a video in `duo/` rather than guessing.

Apple TV got its slot on 2026-10-28, when Flipperworks moved onto snakelane: 1920x1080 and 3840x2160 in `APP_APPLE_TV`, landscape only, as Apple's screenshot-specifications page lists them. Flipperworks' own copy of the old scripts had added the same two sizes; snakelane refused a tvOS deck as an unknown size until then.

### Non-default sizes are a warning

Any accepted size uploads. A size other than the default (6.3" iPhone, 13" iPad) gets a warning, because the class that was shot is the one ASC shows as uploaded rather than dimmed.

### At most ten screenshots per set

ASC takes 1 to 10 screenshots per set, and snakelane checks this locally. The push replaces each set wholesale, so Apple refusing the 11th file would land after the live set was deleted and ten were re-uploaded, and the deck would silently lose its last shot. Jigsaw's iPhone decks had 11.

### Pillow replaced the hand-rolled image decoders

Until 2026-10-02 snakelane carried its own PNG decoder (scanline unfiltering, Paeth prediction) and JPEG marker walk to keep Pillow out of the base install. That was about 150 lines of binary-format code to maintain, and the pure-Python alpha strip took about 1.6 s per screenshot. Pillow is a standard prebuilt wheel, and `frame` needed it anyway.

### An App Preview's slot comes from the screenshots beside it

Apple accepts 886x1920 for the 6.3", 6.5" and 6.9" preview slots alike, so a video's own pixels cannot say which deck it belongs to. The `ss-NN` shots in the same folder can: their display class is unambiguous, and one folder is one device class. The video's dimensions are then validated against what that slot accepts, so a wrong encode fails in seconds rather than at Apple's end hours later. An earlier version mapped 886x1920 straight to the 6.9" slot and invented a 1080x1920 entry for 6.5" that appears nowhere in Apple's table, which would have uploaded every 6.5" deck's preview into the 6.9" slot.

886x1920 looks invented but is 1920 on the long edge at 19.5:9, the shape of every notched iPhone. 1080x1920 is the 16:9 size and belongs to the 5.5" and 4.0" slots. The iPad slot accepts 1200x1600 only; 900x1200 belongs to the 2nd-generation 12.9" preview type (`IPAD_PRO_129`). The table is a local pre-check from Apple's [app preview specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications); ASC is the arbiter.

### Preview slot names have no APP_ prefix

`AppScreenshotSet.screenshotDisplayType` for a device is `APP_IPHONE_67`, while `AppPreviewSet.previewType` for the same device is plain `IPHONE_67`. Passing the screenshot spelling is rejected with a bare 409 that names neither field.

### Video dimensions are read without ffprobe

The MP4 reader is hand-rolled because Pillow reads images, not video, and shelling out to ffprobe would make an upload depend on a Homebrew install that only the encode step needs. It walks `moov > trak` and reads, per track, the handler (`vide`/`soun`), `tkhd`'s width and height, `mdhd`'s length, `stts`'s frame count and the first `stsd` entry's codec, channels and sample rate. Only a track's first `hdlr` counts: a QuickTime `.mov` (what `simctl` writes) has a second inside `minf`, the data handler, which otherwise hid the video track (2026-10-16).

### A preview is checked before it uploads

Apple ingests a preview minutes after the upload "succeeds", and its rejections (too long, frame rate too high, unsupported audio) appear only in the web UI. Every one of them is readable from the file, so `store previews push` refuses a preview outside 15–30 s, above 30 fps, or with audio that isn't stereo AAC at 44.1 or 48 kHz, before it deletes anything live. A file with no audio track only warns: audio is allowed rather than required, but a silent-trackless preview was bounced once with "unsupported or corrupted audio", and the research of 2026-10-16 found tools shipping both ways. The re-encode hint looks for an `encode_app_preview.sh` script rather than naming one, because the old per-repo copies kept it in different places or not at all.

### Underscore-prefixed files are excluded

A file whose name starts with an underscore is left out of the push. Because a push replaces each set wholesale, excluding a file also removes it from ASC on the next run, so the skip is printed. The check, the PNG refusal and the upload all apply the same rule, so an excluded file can neither block a push nor be mistaken for an uploaded one.

### A PNG in a deck is an error

A deck is JPEG only ([ADR 0002](../adr/0002-jpeg-only-screenshot-decks.md)). A PNG left in one is an error rather than a silent skip, because a push replaces each set wholesale and an ignored file would quietly vanish from the store.

### iPhone and iPad share one tree

Until 2026-10-02 the iPad deck was a separate `ipados/` tree pretending to be a platform. Now iPhone and iPad shots of one iOS version sit side by side in `iphone/` and `ipad/`. The folders only keep same-named shots apart; the slot each file fills is still read from its pixels. Files are uploaded in name order, because ASC shows a set in the order its files were added and the `ss-NN` names are the order.

## Recording a preview

`snakelane preview` replaced the per-app `record_gameplay_video.sh` and `encode_app_preview.sh` (Hearts' were about 450 lines of bash) on 2026-10-16. It builds the video test once per simulator, runs it, records while it plays, and encodes the deck's `ap-01.m4v`. The recordings (`master.mov`, `master.caf`, `master.json`) stay in `.snakelane/<slug>/previews/<deck>/<locale>/`, so `--encode-only` can change the overlay or the mix without recording again.

### The masters are replaced together, and a long clip keeps its end

A recording is written under `master.partial.*` and moved over the masters only when the test passes. The first failed run (Hearts, 2026-10-16) overwrote the video and the sound but left the previous run's `master.json`, and `--encode-only` would have cut the new video by the old run's marks. A clip longer than `max_seconds` loses its beginning rather than its end, because the test's "end" mark is where it put the payoff: Hearts' clip ends on "You win!".

### A passed test is a pass even if xcodebuild hangs

On Spades (2026-10-16) `xcodebuild test-without-building` logged XCTest's "Test Suite 'Selected tests' passed" and then did not exit for more than two minutes, and the run was reported as a failure with a good recording in hand. After the test's "end", snakelane waits two minutes for xcodebuild; if it is still running and its log already says the tests passed (that line, or "** TEST EXECUTE SUCCEEDED **"), it is stopped and the run counts as passed. A log with neither is still a failure.

### The display stays awake while recording

A simulated app plays its sound through the Mac's default output device. On a Mac whose output is a Studio Display's speakers, the speakers sleep with the display, and with nobody at the Mac every simulator audio start failed (Core Audio `StartIO` error 35, after a five-second wait). The recordings came out silent, and those blocked starts stalled the game's animation (Hearts, 2026-10-16, a run driven over Remote Control). `preview` wakes the display (`caffeinate -u`) and holds it awake (`caffeinate -d -i`) until it finishes recording.

### A preview is recorded without a UI test attached

Even a test that only slept while recording cost the app frames on the iPad: 6 to 14 stalls a take, where the same fixture launched by hand and recorded by `simctl` had none (Hearts, 2026-10-16). An attached UI test keeps the app under automation, with its accessibility tree live. So `previews.launch` records the app with no test at all: snakelane starts the recorder, launches the app with `simctl launch` and the fixture's arguments, taps its pid, and stops when the app marks "end". The app marks its own "start" (its scene is up) and "end" (its payoff has played). The `test` mode stays for an app that can't mark its own moments.

### A stall in the recording is a warning

Three of the first four previews (Hearts and Spades, 2026-10-16) each had one 165–263 ms hitch: a card skipping half its flight, a "Made it!" fade pausing. They were the simulator dropping frames on a busy Mac (other sessions building and testing), not the games: the same game hitched at different moments in two takes, and a take recorded with nothing else running was smooth. After encoding, `preview` reads the recording's frames as `simctl` wrote them and warns about any stall in the clip. simctl writes a frame only when the screen changes, so a gap alone is a still table; a stall is a gap of more than 50 ms with the picture moving on both sides and a bigger jump across the gap than the steps around it. It is a warning, not an error, because only a re-record fixes it and a person should judge whether it shows.

Most of those stalls turned out to be the video test's own doing. It waited for the game-over dialog with `waitForExistence`, which snapshots the app's accessibility tree about once a second, on the app's main thread; recordings of the same autoplay without the test had no stalls at all. So a video test must not query the app while recording: the app marks its own moments in the events file (Hearts' and Spades' `PreviewMarks`) and the test waits on the file.

### The test and the recorder shake hands

Starting the recorder before the test caught minutes of home screen while the app built and launched, and a fixed `sleep` in the test never matched how long `simctl` took to attach. The test appends `{"event", "t"}` lines to `/tmp/<slug>-preview-events.jsonl`: "ready" when its scene is up. snakelane then starts the recorder, waits for `simctl`'s "Recording started", and writes `/tmp/<slug>-preview-rolling`; the test waits for that file before it lets the app play, then marks "start" and "end". The clip is what lies between the two marks, so black first frames and teardown are cut, and any other event name is a moment a caption can be timed to. The idea of a timeline the test writes came from lotti's `ios_preview.sh` and Snaptake. Files on the Mac's disk work because the simulator shares it: the screenshot locale already travelled that way (see "The locale travels in a file"), and writing from the test runner was confirmed on Hearts (2026-10-16). Events older than the run's start are ignored, since the file survives a killed run.

### The recorder is simctl itself

Stopping a recording means sending SIGINT, which is what makes `simctl` write the movie's index; SIGTERM leaves an unplayable file. Started through `xcrun`, or from a shell function, the signal lands on a wrapper and `simctl` records forever, which Hearts' script hit. snakelane resolves `xcrun --find simctl` and runs that binary.

### A preview's sound is tapped from the app's process

`simctl` records no audio. A simulated app is an ordinary Mac process with its own Core Audio process object (its bundle id shows up in `kAudioHardwarePropertyProcessObjectList`), so a Core Audio process tap (macOS 14.2+) on its pid records exactly its sound: not the Mac's, not another simulator's. Found on 2026-10-16 with Safari playing on the same Mac: the tap held only Hearts' card sounds. The tap API has no Python binding, so `audiotap.swift` ships in the package and is built with `swiftc` on first use, cached by its source's hash. The tap delivers nothing until the app first plays a sound, so the file's frame 0 is that moment (2.4 s after the start in the first test); the helper reports its wall-clock time and the encode shifts the audio by it. A gap in the app's output is written as silence, so the file stays on the wall clock. No permission prompt appeared on the development Mac; another Mac may ask for audio-capture access for the terminal.

### The poster frame is chosen, not left to Apple

The poster frame is all a viewer sees of the preview with autoplay off or in Low Power Mode, and App Store Connect won't change it once the version is approved: that needs a new version ([Apple, App Previews](https://developer.apple.com/app-store/app-previews/); [Set an app preview poster frame](https://developer.apple.com/help/app-store-connect/manage-app-information/set-an-app-preview-poster-frame)). Research for Hearts, Spades and Euchre (2026-10-16) found the poster frame and the first seconds beside ss-01 and ss-02 in search results matter most, since most people never watch the video, and snakelane set neither. So `previews.poster` names the frame as a moment the app already marks ("won": the payoff, not a frame mid-deal) or as seconds into the clip. The encode resolves it against this recording's marks, rounds it to a frame at 30 fps, and writes it into the clip's sidecar `ap-01.json` as `HH:MM:SS:FF`, the format of Apple's examples (`"00:00:05:00"`). It isn't written into the movie, because the push sends it as the preview's `previewFrameTimeCode` when it reserves it, and it can't sit in `master.json`, because the push reads only the committed deck. A sidecar whose poster lies past the end of the clip beside it is refused, since that clip was encoded later. Left unset, the frame is Apple's.

### In search results the preview sits beside ss-01 and ss-02

In App Store search results a portrait preview takes the first of the three tiles and plays beside ss-01 and ss-02 (a landscape one fills the row alone). A caption the preview shares with either shot is the same claim twice, in a row that holds three. Hearts' preview opened on "SHOOT THE MOON", which ss-02 also says (2026-10-16); the configs already avoided repeating ss-01 by hand, and missed ss-02. `preview --dry-run`, each encode, and the gallery's search-result mock compare each preview caption with ss-01's and ss-02's, as whole words with case and punctuation ignored. Where snakelane frames the deck, the captions come from `screenshots.framing.captions`. Where the UI test draws them (`frame: test`, Hearts and Spades), they are read off the framed shots with Vision, as `check` reads the developer HUD. Without that extra the check says it can't run, rather than passing. A caption found anywhere in a shot's text counts as a repeat: a phrase from a caption showing up in the game's own text is rare enough to be worth the occasional false warning. The gallery's mock shows the preview's poster frame (pulled with ffmpeg at the sidecar's time) where the store shows it.

### The band is the screenshots' band

The overlay is drawn by `frame`'s own `compose()`, so the preview's band matches the deck's look and any theme works. compose() draws a whole framed shot, not a layer, so it runs twice over a black and a white stand-in capture; where the two canvases differ is where the capture shows through, which gives the band's exact alpha, its arch and shadow included, without a second renderer to keep in step. A full-phone frame was tried first and rejected (2026-10-16): it shrank the game, where a thin band covers only the status bar and the edge of the top seat.

## Uploading

### Remote mirrors local

A push empties each set it uploads to and deletes any set whose slot the local folders no longer produce. ASC has no replace-in-place call, only add and remove, so this matches fastlane's `overwrite_screenshots`. Without the stale-set sweep, changing the shoot's device class (6.9" to 6.5") left the old class's set live, and since ASC prefers a native set over scaling, the stale 6.9" deck kept being shown.

### An empty local deck deletes the live sets

An empty locale folder is an instruction, not a no-op. Skipping it once left a locale whose previews had all been deleted showing the old ones on the product page forever. A locale with no folder at all has no opinion and is skipped.

### The whole plan is built before the first delete

Every file's size is mapped to a slot, every video read, and the size and count limits checked across all locales before anything is deleted. A bad file in the last locale then fails while ASC still holds every locale's current deck.

### A killed shoot blocks the push

Both pushes refuse, dry run included, while a killed shoot's stash exists. A killed shoot leaves a deck that may be half done, and mirroring it would replace the live sets with it.

### A dry run without credentials still shows the local plan

The per-repo copies created the API client first and died on missing credentials, so a dry run, which is how a deck gets eyeballed, showed nothing offline. The local half (every file read, every size mapped to a slot) is most of what a dry run is for. The live half (which sets would be emptied or deleted) needs credentials, and is named as missing rather than silently skipped.

### Previews and screenshots are separate resources

App Previews are separate ASC resources (`appPreviewSets` and `appPreviews`, with their own slot enum), so they are mirrored on their own, after the screenshots. They share the deck folder so one folder is everything a device class needs. Apple transcodes a preview and can reject it after the bytes land, so the push waits for processing with a 20-minute budget instead of the 10 minutes used for images.

### One media push, every local plan first

Screenshots, previews and creative assets were three commands (`store screenshots push`, `store previews push`, `store creative push`) until 2026-10-21, when they became `store media push` with `--only` to pick some. Run one after another by hand, a bad preview encode was found after the screenshots had already been replaced. The combined push reads every kind's files, and checks the creative assets against Apple's reference data, before its first write; a failure partway stops the run and prints the `--only` command for the kinds not yet pushed, rather than carrying on and burying the failure above a 20-minute preview wait. The old commands stay, hidden, because apps' docs and scripts call them.

### A kind with no files anywhere is skipped unless named

A deck folder with no previews deletes the live previews: that was safe while previews had a command of their own. Run with everything by default, it would delete the previews of an app that never kept them in the repo whenever its screenshots were pushed; Solitaire was one on 2026-10-21, with previews live and none in its deck. So a `media push` without `--only` skips a kind that has no file in any locale and says so; `--only previews` still mirrors an empty deck and deletes them.

### Processing is verified, and rejects are retried once

Without waiting for Apple's ingest, "push complete" only means the bytes arrived. A rejected screenshot is deleted and re-uploaded once: transient ingest failures are real, and deterministic rejects fail again immediately. Uploads are tracked by Apple's resource id, never the file name. Every locale and device has an `ss-01.jpg`, and matching by name once retried an English rejection with the German file into the German set (found in review, 2026-10-02).

### Creative assets are checked against Apple's reference data

The product page header and search-result asset (October 2026) have exact sizes, a no-alpha rule and per-format limits that App Store Connect enforces after upload. Apple's guide to the App Asset Library asks integrations to read them from `GET /v1/appAssetLibraryRefData` instead of hard-coding them, and the two sources already disagree: the help page lists JPEG for the 21:9 header, and the reference data takes PNG only (2026-10-18). So `creative push` reads the specs on every run and checks each file against them before the first write; a file Apple would refuse stops the push with the spec it missed.

### Creative assets are found by content

A placement doesn't say which asset backs it, and the library takes no checksum, so neither side can tell whether a slot already shows the local file. Each upload's `referenceName` carries a hash of its bytes: a re-run finds the asset in the library, asks it which placements it backs, and writes nothing when the slot's placement is among them. The same file in two slots or locales is uploaded once. A slot holds one placement per localization, so a changed file's old placement is deleted before the new one is made.

### `media show`

The fastlane migration tables mapped `show_screenshots` to this command before any copy implemented it. It answers the question the stale-set sweep raises: which display classes ASC holds right now, and how many files are in each.
