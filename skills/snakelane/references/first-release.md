# The first release of a new app

Everything below happens **once per app**, and almost all of it is invisible on every later
release — which is why it bites. Work through it in order; each step names the failure you
see if you skip it. Written from FreeCell's first submission (2026-10), the first app set up
from scratch on snakelane rather than migrated onto it.

## 0. Before App Store Connect

**Version settings on the app target, not the project.** `ship` reads `MARKETING_VERSION`
and `CURRENT_PROJECT_VERSION` from the *app target's* build configurations. Set only at the
project level (the default in a hand-written XcodeGen spec), `ship` stops with:

```text
the app's configurations disagree on MARKETING_VERSION: none set
```

Move both onto the app target.

**XcodeGen (or any generated project).** `bump` writes the new build number into the
`.pbxproj`; regenerating the project from its spec resets it to the spec's value. The number
then only stays monotonic because `bump` also checks TestFlight. Regenerate through a small
script that copies the pbxproj's number back into the spec first when it's higher (FreeCell's
`Apps/FreeCell/generate.sh` is twenty lines), and commit the spec change after each archive.

**Export compliance.** Ask the user, then set `ITSAppUsesNonExemptEncryption` on the app
target — `SKILL.md` → Setting up a new app, step 4. Missing, the build waits at "Missing
Compliance" and no tester ever gets it.

**Pin the test destination to a runtime.** `test.device` by name resolves on the **newest**
installed runtime. A simulator that only exists on an older one fails before any test runs:

```text
xcodebuild: error: Unable to find a device matching the provided destination specifier
```

Use `test.destination` with an OS: `"platform=iOS Simulator,name=iPhone 17 Pro Max,OS=26.5"`
(check `xcrun simctl list devices available`). Screenshot devices take
`{name, os}` for the same reason.

## 1. The App Store Connect record

Create the app in the web UI (bundle id, name, primary language, SKU) — snakelane doesn't
create apps. Then **immediately** set `apple_id` in `snakelane.yml` and run
`snakelane status`: it should name the app, its bundle id and a 1.0 version in
`PREPARE_FOR_SUBMISSION`. Every later command asserts that id.

## 2. The site, before the listing

`privacy_url`, `support_url` and the privacy/terms links in the description must resolve
before review, and a description linking to a 404 is worse than none. Deploy the site first,
`curl` each URL for a 200, then fill the files, then `lint --check-urls`.

## 3. The listing: `store push`

On a first version:

- **Release notes are skipped** (App Store Connect rejects them on version 1.0); they push
  from the next version on.
- **The age-rating questionnaire must be answered in full** — a submission is blocked while
  any question is unanswered, and a new app starts with every one `null`. Answer them all in
  `age_rating`, with App Store Connect's own names in snake_case. Get the current list from
  `snakelane store show --json`; an unknown name is refused before anything is written, with
  the list of real ones (it is `gambling_simulated`, not `simulated_gambling`). For an app with
  none of the content these ask about, as of 2026-10:

  ```yaml
  age_rating:
    alcohol_tobacco_or_drug_use_or_references: NONE
    contests: NONE
    gambling_simulated: NONE
    guns_or_other_weapons: NONE
    horror_or_fear_themes: NONE
    mature_or_suggestive_themes: NONE
    medical_or_treatment_information: NONE
    profanity_or_crude_humor: NONE
    sexual_content_graphic_and_nudity: NONE
    sexual_content_or_nudity: NONE
    violence_cartoon_or_fantasy: NONE
    violence_realistic: NONE
    violence_realistic_prolonged_graphic_or_sadistic: NONE
    advertising: false
    gambling: false
    health_or_wellness_topics: false
    loot_box: false
    messaging_and_chat: false
    parental_controls: false
    age_assurance: false
    social_media: false
    unrestricted_web_access: false
    user_generated_content: false
    age_rating_override_v2: NONE
  ```

  **These are the developer's declarations, not defaults.** Show the user every answer before
  pushing; an honest "yes" (ads, chat, a web view) changes the rating and may change the
  review.

## 4. In-app purchases

- `store iap push --create` makes the product. **The id is permanent** — the user runs it, or
  approves it explicitly.
- It stays `MISSING_METADATA` until it has a **review screenshot** (`review_screenshot` in
  `iap.yml`, JPEG, 640×920 minimum) showing the purchase sheet *with its price*. A UI-test
  launch shows "Loading price…" unless the screenshot scheme's test action has a StoreKit
  configuration file; set one, or the shot is useless.
- **That priced shot goes in `iap.yml`, never in the screenshot deck.** A paywall in the App
  Store screenshots is a Guideline 2.3.7 rejection, as is a caption saying "free" or "one
  purchase". If the deck's UI test shoots the paywall for the review screenshot, keep it out
  of the deck (an underscore-prefixed file is excluded from the push).
- **A first IAP is submitted together with an app version**: attach it on the version page
  ("In-App Purchases and Subscriptions") before submitting the build. It can't go to review
  alone the first time.

## 5. The first build: signing

**`ship beta` cannot do a new app's first upload with a standard App Manager key.** The
archive succeeds and the export fails:

```text
error: exportArchive Cloud signing permission error
error: exportArchive No profiles for 'com.example.app' were found
  Xcode couldn't find any iOS App Store provisioning profiles matching 'com.example.app'.
```

A new bundle id has no App Store provisioning profile. The key signs only with an Apple
Distribution certificate in this Mac's keychain that the profile includes; Apple's
**cloud-managed** certificate, which Xcode's own uploads use, is off limits to an App Manager
key. The same rule produces two more failures on apps that are *not* new, and `ship` names
each one:

- **No certificate** (`No signing certificate "iOS Distribution" found`): every upload so far
  went through Xcode, so the Mac never needed one.
- **Profile without the certificate** (`Provisioning profile … doesn't include signing
  certificate`): the certificate was made after Xcode built the profile.

All three also print `Cloud signing permission error`; that line alone names none of them.
Check `~/Library/Developer/Xcode/UserData/Provisioning Profiles/` to see what a profile holds.

The fix is in Xcode, and it's the user's account so the user does it:

1. **No certificate on this Mac:** Xcode → Settings → Accounts → the team → Manage Certificates
    → + → Apple Distribution.
2. **Upload the archive from Organizer.** `ship beta` leaves it at `build/<App>-ios.xcarchive`:
    `open` it, then Distribute App → App Store Connect → Upload. Xcode signs as the user's Apple
    ID and remakes its managed App Store profile with every Apple Distribution certificate the
    team has, this Mac's included, so the next `ship beta` can sign. Each platform has its own
    profile: a Mac build needs its own Organizer upload once.

Or **give the key cloud signing**: in App Store Connect → Users and Access → Integrations, an
Admin-role team key can use the cloud-managed certificate. That changes what a leaked key could
do; let the user weigh it.

The archive's build number was already bumped and stamped; uploading it from Organizer uses
that number, and the next `ship beta` picks the following one from TestFlight.

## 6. Stays in the web UI, the first time

- **App Privacy** (the nutrition label) — answer it to match the privacy policy.
- **Price and availability** of the app itself (an IAP's are in `iap.yml`).
- **App Review contact**: `snakelane.yml`'s `review.contact` (`first_name`, `last_name`, `email`,
  `phone` with `+` and the country code), pushed by `store push` with the notes.
  App Store Connect refuses the notes until the contact is set, so `store push` stops early
  without them.
- **Content rights** and, for a game using Game Center, enabling Game Center on the version.
- **CloudKit**: if the app syncs, deploy the development schema to Production in the CloudKit
  Console before release, or every production install syncs nothing.

## 7. Submit

`snakelane status` should show the build processed and the listing in place; attach the IAP
to the version; then `ship release --no-submit` to stage, or `ship release` to submit.
