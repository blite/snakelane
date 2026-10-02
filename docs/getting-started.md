# Getting started

## Install

`store`, `lint`, `translations`, `gallery` and `packs` need only Python 3.11+, and run on
Linux CI runners too. `ship`, `shoot`, `bump` and `check` drive Xcode, so they need macOS.

Fork snakelane, clone your fork, and install it editable, so the installed command runs your
checkout:

```bash
git clone git@github.com:<you>/snakelane.git
uv tool install --editable ./snakelane
```

With an editable install, a fix you (or your agent) make in the checkout reaches every app on
the machine straight away. Commit it to your fork.

Optional extra: `--with pyobjc-framework-Vision --with pyobjc-framework-Quartz` for
`snakelane check` (macOS). Without cloning: `uv tool install git+https://github.com/blite/snakelane`.

!!! note "After pulling a change that adds a dependency"
    An editable install doesn't pick up new dependencies by itself. Re-run
    `uv tool install --editable ./snakelane --force`.

`snakelane --help` lists the commands:

```text
--8<-- "docs/assets/terminal/help.txt"
```

## Connect to App Store Connect

Create a [team API key](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api) with the App Manager role and install it once per machine. See
[auth](commands/auth.md). Every `--dry-run` works without one.

## Describe your app

From the app's repo, let snakelane read the Xcode project and write the config:

```bash
snakelane init --dry-run      # what it found: scheme, bundle id, team, platforms
snakelane init                # snakelane.yml + placeholder listing files
snakelane init --pull --force # for an app on the store: fill them from the live listing
```

The placeholders contain TODOs, which `lint` refuses, so a half-written listing can't be
pushed. You can also write the files by hand: a `snakelane.yml` at the root of the app's repo
and the listing in `metadata/`:

```yaml
# snakelane.yml
name: Trailhead
bundle_id: com.example.trailhead
locales: [en-US]
platforms: [ios]
```

```
metadata/default/name.txt
metadata/default/subtitle.txt
metadata/default/description.txt
…
```

[The config and the metadata tree](configuration.md) covers the full layout, and
`snakelane store pull` writes the files from what is live today.

## First run

Nothing talks to App Store Connect until you drop `--dry-run`:

```bash
snakelane lint
snakelane store push --dry-run
snakelane store push          # shows the diff, asks, writes, re-reads to verify
```

The dry run prints every field it would send. Here it is for the paid edition in
`examples/two-apps`:

```text
--8<-- "docs/assets/terminal/store-push-dry-run.txt"
```
