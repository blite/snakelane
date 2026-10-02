# gallery: reviewing before a push

```bash
snakelane gallery --open                  # every deck and listing, on one page
snakelane gallery --live --open           # each shot: new, changed or unchanged vs live
snakelane gallery --git --open            # …or vs the last commit
snakelane gallery --bundle site-preview/  # a self-contained folder, to share
```

![The gallery page for the example app: search-result and product-page mocks above the iPad deck](../assets/gallery.png){ .shot }

The page shows, for every locale:

- an App Store search-result and product-page mock: icon, name, subtitle, the first three
  screenshots, and the description and release notes cut at the "more" fold, so you see the
  truncation before it ships;
- the lint findings and translation status for that locale;
- every deck in upload order, each shot with its size and any warning the push would print,
  plus what the push would delete;
- which locales inherit the primary language's screenshots, and deck folders for locales the
  config doesn't list.

`--live` is read-only and needs the API key. The page is written to `/tmp` and links your
images where they are, so it opens instantly but only on your Mac. `--bundle` copies the
images in.

Use the gallery to review anything an agent changed, translated captions in particular,
before `store screenshots push`.
