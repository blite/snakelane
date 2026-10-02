# Security policy

## Reporting a vulnerability

Please report security problems privately, through GitHub's
[private vulnerability reporting](https://github.com/blite/snakelane/security/advisories/new)
(the **Report a vulnerability** button on the repository's Security tab). Don't open a public
issue or pull request for a vulnerability.

Include what you can of:

- the snakelane version (`snakelane --version`, or the tag or commit you installed from);
- the command you ran and what happened;
- how to reproduce it, ideally with `--dry-run`;
- what an attacker could do with it.

Remove key ids, issuer ids, `.p8` contents, bundle ids and anything else that identifies an
account before you attach logs.

snakelane is maintained by one person in their spare time. Expect an acknowledgement within a
week, and a fix or a plan within 30 days for a confirmed issue. Once a fix is released, the
advisory is published with credit to you, unless you'd rather not be named.

## Supported versions

Only the latest release gets security fixes. While snakelane is at 0.x, a fix ships as a new
patch or minor release, and the [changelog](CHANGELOG.md) says which.

## What's in scope

snakelane holds an App Store Connect API key that can change an app's listing, upload builds,
submit for review and create in-app purchases. The areas that matter most:

- **The API key.** `snakelane auth setup` moves the `.p8` into
  `~/.appstoreconnect/private_keys/` with mode `0600` (the folder `0700`), and every command
  reads it from there. Anything that leaks the key, writes it somewhere readable, prints it,
  or sends it anywhere but Apple's token signing is in scope.
- **Requests to App Store Connect.** A way to make snakelane write to an app, version or
  product the user didn't ask for, to skip a confirmation (`store push`, `packs upload`), or
  to create a product id or asset pack id without `--create` or the terminal prompt.
- **Files from a repository.** snakelane reads `snakelane.yml`, `iap.yml` and listing text
  from the repo it runs in. A config or metadata file that makes it run commands, read or
  write files outside the repo and its `.snakelane/` work folder, or exfiltrate data is in
  scope.
- **The `gallery` page.** It renders listing text and file names into HTML. Script injection
  through that text is in scope.
- **Dependencies**, where snakelane's use of them is exploitable.

Out of scope: App Store Connect, Xcode and Apple's services themselves (report those to
[Apple](https://security.apple.com)), and problems that need an attacker who already controls
your machine or your API key.
