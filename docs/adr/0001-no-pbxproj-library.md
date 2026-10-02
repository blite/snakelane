# 1. Edit project.pbxproj with targeted text edits, not a parsing library

- **Status:** accepted
- **Date:** 2026-10-02 (updated the same day: Xcode 27.2 ships the JSON format)

## Context

`snakelane bump` and `snakelane ship bump-version` change build settings in an Xcode project
file: `CURRENT_PROJECT_VERSION` and `MARKETING_VERSION`, for the app, its extensions, or every
target. `snakelane init` reads a few settings from it (bundle id, team, platforms).

`project.pbxproj` is an old-style ASCII property list: a format Xcode still writes, that
`plutil` can read but no longer writes, and that Python's `plistlib` does not support. Libraries
exist that parse and rewrite it (for example
[`mod-pbxproj`](https://github.com/kronenthaler/mod-pbxproj)).

Today snakelane finds each `XCBuildConfiguration` object by its structure (balanced braces from
its `isa` line), reads `PRODUCT_BUNDLE_IDENTIFIER` inside it to decide whether the
configuration belongs to the app, and rewrites only the matching `KEY = value;` lines. Every
other byte of the file is left as it was. `tests/test_bump.py` exercises this against
a fixture project on every CI run.

## Decision

Keep the targeted text edits. Don't adopt a pbxproj parsing library.

## Why

- **The format is already changing.** Xcode 27.2 introduced a JSON project file,
  `project.xcproj`, inside the `.xcodeproj` package: new projects use it by default, existing
  ones convert with `xcodebuild -convert-project xcproj` (Xcode 27.0 can open it but not convert
  to it). Its build settings are plain keys in each target's `build-settings`, with per-configuration values
  as `KEY[config=Release]`. Python's `json` reads and writes that; a pbxproj library would
  be a dependency for a format on its way out.
- **A library rewrites the file.** Parsing and serialising the whole project risks reordering,
  re-quoting or re-indenting objects Xcode would have left alone. That shows up as noise in
  every diff of a file people review, and as merge conflicts. The text edits change only the
  lines that must change.
- **The surface is small and tested.** snakelane touches two settings and reads three more. The
  structural walk is a few dozen lines with tests, which is less to maintain than a
  dependency's upgrade path.

## Consequences

- Anything beyond reading a setting or replacing a value in place (adding a build phase or a
  target, editing a scheme) is out of scope. snakelane prints instructions instead.
- A pbxproj Xcode itself would refuse to open is not detected. Xcode remains the validator.

## Next

Support `project.xcproj` with the standard library's `json`, alongside the text edits for
`project.pbxproj` until projects have moved over. Writing must keep Xcode's own key order and
formatting, so the change needs a real project converted by Xcode 27.2 as a fixture.

## Revisit when

- Projects stop using `project.pbxproj` altogether: drop the text edits.
- snakelane needs structural edits to the project (adding targets, phases or files).
- The structural walk breaks on a project Xcode writes, and the fix is not a small one.
