# lint and translations

## lint: what App Review would reject

```bash
snakelane lint
snakelane lint --check-urls      # also load every URL in the listing
snakelane lint --strict --json   # warnings fail too; machine-readable
```

`lint` checks every locale's listing offline. `store push` runs it on the local text and
`ship release` on the listing it is about to submit. Both stop on errors.

```text
--8<-- "docs/assets/terminal/lint.txt"
```

| Rule | Severity | Catches |
|---|---|---|
| `field-length` | error | over Apple's limits (name and subtitle 30, keywords 100, …) |
| `rejected-character` | error | dingbats and emoji App Store Connect refuses mid-push |
| `other-platform` | error | Android, Google Play, … ([guideline 2.3.10](https://developer.apple.com/app-store/review/guidelines/#2.3.10)), in any script |
| `placeholder` | error | TODO, FIXME, TBD, lorem ipsum, `{{…}}` |
| `profanity` | error | [guideline 1.1](https://developer.apple.com/app-store/review/guidelines/#1.1) |
| `url-format` / `url-unreachable` | error | a URL that isn't one, or (with `--check-urls`) doesn't answer |
| `subscription-links` | error | an app that sells subscriptions without its privacy policy and Terms of Use URLs in every description ([3.1.2](https://developer.apple.com/app-store/review/guidelines/#3.1.2), [why](../adr/0003-lint-subscription-legal-links.md)) |
| `future-functionality` | warning | "coming soon", "in a future update" ([2.1](https://developer.apple.com/app-store/review/guidelines/#2.1)) |
| `test-word` | warning | "beta", "trial version" |
| `apple-sentiment` | warning | disparaging Apple ([3.2.2](https://developer.apple.com/app-store/review/guidelines/#3.2.2)) |
| `keyword-format` | warning | spaces after commas, duplicates, words already in the name or subtitle |

To turn a rule off for one app, put it in that app's config:

```yaml
lint:
  ignore: [test-word]
```

## translations: what is stale or unreviewed

snakelane doesn't translate; you or your agent do. It records what each translation was made
from, so when the source text changes it can name the locales that need redoing.

```bash
snakelane translations mark de-DE              # translated (by an agent, say)
snakelane translations mark de-DE --reviewed   # a person has checked it
snakelane translations status
```

The source of a field is `default/<field>.txt`, its translation `<locale>/<field>.txt`. Each
translated field is stale (the source changed since), unreviewed, current (reviewed, or
edited by hand after marking) or untracked. `store push` warns about stale and unreviewed
ones. Here the English description and subtitle changed after the German translation was
marked:

```text
--8<-- "docs/assets/terminal/translations-status.txt"
```
