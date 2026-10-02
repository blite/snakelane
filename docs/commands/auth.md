# auth: the API key

snakelane talks to Apple with one credential: a [team App Store Connect API key](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api) with the App
Manager role. Create it under Users and Access → Integrations → App Store Connect API → Team
Keys, download the `.p8`, then:

```bash
snakelane auth setup --issuer-id <issuer id> \
  --key ~/Downloads/AuthKey_ABC123DEF4.p8
snakelane auth check      # one read-only request, proving Apple accepts the key
```

`setup` moves the key to `~/.appstoreconnect/private_keys/` (readable only by you) and records
the key id and issuer id in `~/.config/snakelane/credentials.json`. Every command reads those
two files and nothing else, whether it runs in a terminal, in Xcode's Archive post-action or
in CI. There are no environment variables and no Apple ID sign-in.

!!! tip "Files instead of environment variables"
    An Xcode launched from the Dock never sees your shell's variables, so a key in the
    environment is silently missing from the Archive post-action.

## In CI

Install the key from secrets before running snakelane:

```bash
printf '%s' "$ASC_KEY_P8" | snakelane auth setup --key - \
  --key-id "$ASC_KEY_ID" --issuer-id "$ASC_ISSUER_ID"
```
