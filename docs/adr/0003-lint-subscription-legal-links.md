# 3. Lint requires privacy and terms links in the description of apps that sell subscriptions

- **Status:** accepted, implemented in `listing/lint.py`
- **Date:** 2026-10-02

## Context

[Guideline 3.1.2](https://developer.apple.com/app-store/review/guidelines/#3.1.2) requires an app
that sells auto-renewable subscriptions to link to its Terms of Use (EULA) and its privacy policy
from its App Store metadata. Apple's wording allows the terms link in the description or the custom
EULA field, and the privacy link in the Privacy Policy URL field. In practice reviewers look for
both links in the description, and an app that only filled in the Privacy Policy URL field gets
rejected under 3.1.2. A rejection costs days, and the fix is two lines of text.

snakelane already knows everything it needs to check this offline:

- `iap.yml` says whether the app sells subscriptions (`subscription_groups`).
- Each locale's `description.txt` and `privacy_url.txt` resolve through the metadata tree.
- `snakelane lint` already gates `store push` and `ship release`.

Today the check is only a warning in the agent skill's gotchas, so it depends on someone reading it.

## Decision

`snakelane lint` gets a rule, `subscription-links`, at **error** severity. When the app sells
subscriptions, every locale's description must contain:

- **the privacy policy URL**, exactly as that locale's `privacy_url.txt` gives it;
- **a terms URL**: the config's `terms_url` if set, otherwise Apple's
  [standard EULA](https://www.apple.com/legal/internet-services/itunes/dev/stdeula/).

"Every locale" means every locale snakelane would push a description for, resolved the way
`store push` resolves text, per platform. A missing URL is reported once per locale, naming the
URL it expected. The check matches URLs only, not the words around them, because translated
descriptions call them "Datenschutz" or "Conditions d'utilisation". With `--check-urls`, both URLs
are requested along with the listing's other URLs.

It applies when `iap.yml` has at least one subscription group. One-time purchases alone don't
trigger it. Like every rule, it can be switched off with `lint: {ignore: [subscription-links]}`.

## Why

- **The rejection is common and cheap to prevent.** About 130 characters of a 4000-character
  description, against a review round-trip.
- **Exact URLs, not "some link".** A description that links the marketing site but not the
  privacy page passes a loose check and still gets rejected. Comparing against `privacy_url.txt`
  also catches a privacy URL changed in one place and not the other.
- **An error, not a warning.** Lint already blocks a push on errors. A warning here would be
  read after the rejection, not before.
- **Offline.** Everything comes from the repo, so the check runs in CI and on `--dry-run`.

## Consequences

- A new optional `snakelane.yml` key, `terms_url`, for an app with its own terms page. It is
  documented in `listing/lint.py`'s docstring and in the skill's `config.md`.
- Apps that sell subscriptions and describe the links in words without the URL will start failing
  lint until their descriptions include the URLs. The changelog says so.
- The skill's gotcha stays as the explanation; the rule is the enforcement.

## Considered

- **Also requiring it for one-time purchases.** Reviewers have asked apps with only a
  non-consumable unlock for the same links. Not included: the guideline doesn't require it, and
  an error that fires on apps Apple accepts would get switched off. Revisit if those rejections
  become regular.
- **Checking the Privacy Policy URL field instead.** It's already required for every app and
  checked by `url-format`. It doesn't stop the description rejection.

## Revisit when

- Apple's review practice changes, for example accepting the EULA field alone without a
  rejection.
- App Store Connect gets a dedicated Terms of Use URL field that reviewers accept.
