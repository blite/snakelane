# ship and bump: releasing

## ship

```bash
snakelane ship test                  # the release test gate on its own
snakelane ship beta                  # test → archive → upload to TestFlight from git
snakelane ship release               # … → attach to the version → submit
snakelane ship release --no-submit   # attach the build, don't submit
snakelane ship bump-version --bump minor
```

`release` never pushes text, so what goes to review is the listing App Store Connect already
holds. `release` lints that listing first, and warns when your local files differ from it.

## Build numbers

Every archive, from Xcode or `xcodebuild`, gets `max(project + 1, TestFlight + 1)`, written to
the project file and stamped into the app and every extension. That happens in the scheme's
**[Archive post-action](https://developer.apple.com/documentation/xcode/customizing-the-build-schemes-for-a-project#Run-tasks-before-or-after-scheme-actions)**:

```bash
snakelane bump --post-action     # print the script to paste into the scheme
snakelane bump --dry-run         # the number the next archive would get
```

```text
--8<-- "docs/assets/terminal/bump-post-action.txt"
```

In the scheme editor: Archive → Post-actions → New Run Script Action, paste the script, and
set "Provide build settings from" to the app target. It has to be a post-action, not a build
phase: writing the project file during a build makes Xcode cancel the archive.

In a project with several apps, `build_number_scope: app` keeps one app's archive from moving
the others' numbers.

## Release settings

How `ship release` [lets the version out](https://developer.apple.com/help/app-store-connect/manage-your-apps-availability/select-an-app-store-version-release-option), from the config. It's checked before the tests and the
archive, and applied after the build is attached:

```yaml
release:
  type: scheduled                     # after_approval | manual | scheduled
  date: "2026-11-03T09:00:00-08:00"   # scheduled only; needs a timezone
  phased: true                        # 7-day phased release to automatic updates
```

## status

```bash
snakelane status          # live and pending versions, review, latest build
snakelane status --json
```

Read-only. It shows in one place what you would otherwise piece together from `store show`
and the App Store Connect website.
