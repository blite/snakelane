# store: listing, screenshots, purchases

Everything on the App Store page, pushed from `metadata/` and checked afterwards.

```bash
snakelane store push --dry-run          # the diff against live; without a key, the local plan
snakelane store push                    # diff, confirm, write, re-read
snakelane store pull                    # write the local tree from what is live
snakelane store show                    # print what is live
```

## The listing

`push` reads each locale's text from the most specific file that has any:
`metadata/<platform>/<locale>/`, `metadata/<platform>/default/`, `metadata/<locale>/`, then
`metadata/default/`. If none has any, the field is skipped: a missing or blank file leaves the
live value alone, and snakelane never pushes an empty string. Before writing, it prints a word-level diff of
every field that would change and asks (`--yes` skips the question, for CI). After writing, it
reads App Store Connect back and reports anything that didn't land. `--dry-run` prints the same
diff and stops before the question. Without an API key it can't read what is live, so it prints
every local field instead. With no draft version yet, it diffs against the live version and says
the real push needs a draft first.

[`lint`](lint.md) runs first and stops the push on errors such as an over-long field
or another platform named in the description. `--skip-lint` overrides it for one run.

Categories and the [age-rating questionnaire](https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions) come from the config (`categories`, `age_rating`).
Categories are checked against [Apple's list](https://developer.apple.com/app-store/categories/) before anything is written; age-rating answers are
pushed only where they differ. `snakelane store show --json` prints the live listing, age
rating included, as a starting point.

Fields: `name`, `subtitle`, `description`, `keywords`, `promotional_text`, `release_notes`,
`support_url`, `marketing_url`, `privacy_url`, `privacy_choices_url`, plus
`<platform>/copyright.txt` and the App Review card in `<platform>/review/`.

## Screenshots and App Previews

```bash
snakelane store screenshots push --dry-run
snakelane store screenshots push
snakelane store previews push
snakelane store screenshots show
```

The deck is `metadata/<platform>/screenshots/<locale>/` (in `iphone/` and `ipad/` for iOS),
uploaded in file-name order. The slot each image fills is worked out from its pixel size. 6.3" iPhone and 13" iPad are the
defaults; other [sizes Apple accepts](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications) upload with a warning, and sizes it doesn't are refused.
A push replaces each set wholesale:

- a file starting with `_` is left out (and so removed from App Store Connect);
- a locale with no folder is left alone, and the App Store shows the primary language's
  screenshots there;
- a locale with an empty folder has its live screenshots deleted;
- more than 10 screenshots in a set is refused before anything is deleted.

Run [`gallery --live`](gallery.md) first to see what will be replaced. Without an API key,
the dry run still reads every file and maps it to a slot, but can't say what it would
delete:

```text
--8<-- "docs/assets/terminal/screenshots-push-dry-run.txt"
```

## Creative assets: the product page header and the search result

```bash
snakelane store creative push --dry-run
snakelane store creative push
snakelane store creative show
```

The two [creative assets](https://developer.apple.com/help/app-store-connect/reference/app-information/creative-assets-specifications)
App Store Connect added in October 2026 for iOS 27 and iPadOS 27: the image or video across the top
of the product page, and the one at the top of a search result. Each App Store version localization
holds at most one of each. They go through the App Asset Library: uploaded once, then placed on the
editable version, and reviewed with it.

```text
metadata/creative/<locale>/            this locale, every platform
metadata/creative/default/             every locale without a folder of its own
metadata/<platform>/creative/<locale>/ and metadata/<platform>/creative/default/   per-platform overrides

search-result.{jpg,jpeg,png,mov,m4v,mp4}   the search result (3:2)
product-page-header.{png,mov,m4v,mp4}      the product page header (21:9)
universal.png                              both (16:9, 5244x2950), where a slot has no file of its own
```

The most specific folder with a file for a slot wins, and a slot's own file outranks
`universal.png` at any depth. A slot with no file is left as it is live: removing one is done in
App Store Connect.

Every file is checked against Apple's reference data before anything is written (dimensions,
proportion, format, alpha channel, size, and for video the length and frame rate when `ffprobe` is
installed), so a file Apple would refuse stops the push instead of failing after upload. The specs
are read on every run rather than copied in: Apple's help page lists JPEG for the header, which the
API refuses. An unchanged file is found in the library by a hash of its bytes and placed without
uploading again, and a slot already showing it is left alone. App Store Connect has no API for the
crop preview: check it in App Store Connect's product page preview tool before submitting.

## In-app purchases and subscriptions

`metadata/iap.yml` holds everything the app sells: one-time purchases under
`products` and [subscriptions](https://developer.apple.com/help/app-store-connect/manage-subscriptions/offer-auto-renewable-subscriptions) under `subscription_groups`.

```bash
snakelane store iap push --dry-run
snakelane store iap push --create --product com.example.app.lifetime
snakelane store subs pull                # write subscription_groups from live
snakelane store subs push --dry-run
```

[Product ids are permanent](https://developer.apple.com/help/app-store-connect/reference/in-app-purchase-information) at Apple, so a product is only ever created with `--create`, and an
id used twice in the file is refused. Pushes are additive: matching localizations are not
re-sent (touching one re-opens review), and a one-time purchase's price, availability and
review screenshot are set once at creation and never changed by a sync.

!!! note "Subscription prices are set on the website"
    snakelane creates subscriptions, their localizations, availability and review details, but
    not their price. Through the API a subscription is priced one territory at a time, with no
    safe way to resume a run that fails partway; on App Store Connect's website [one price fills
    in every territory](https://developer.apple.com/help/app-store-connect/manage-subscriptions/manage-pricing-for-auto-renewable-subscriptions). `snakelane store subs show` prints the live price.
