# Contributing

Thanks for helping. The full rules are in [AGENTS.md](https://github.com/blite/snakelane/blob/main/AGENTS.md). The ones that come up most:

- **Nothing app-specific in code.** A difference between apps becomes an `snakelane.yml` key with
  a default, documented in the module docstring and in
  [`skills/snakelane/references/config.md`](https://github.com/blite/snakelane/blob/main/skills/snakelane/references/config.md).
- **Never write to App Store Connect to test a change.** Use `--dry-run`, `show`,
  `shoot --dry-run` and `bump --dry-run`.
- **Credentials come only from `snakelane auth setup`'s files**, through
  `asc.Credentials.load()`. Don't add environment-variable or Apple ID auth.
- **Never push a blank field**, and never retry a write.
- Update the skill (`skills/snakelane/`) in the same change when behaviour, flags or keys
  change, and add a line to `CHANGELOG.md`.
- **Comments say why, briefly.** The longer story behind a decision (the app and the date it
  went wrong) goes in `docs/design/`, with a one-line pointer in the code.
- **If you changed how frames look**, regenerate the showcase images:
  `SNAKELANE_WRITE_SHOWCASE=1 uv run --group dev pytest tests/test_showcase.py`.
- **If you changed a command's output**, regenerate the command output the docs show:
  `uv run python scripts/terminal_shots.py` (add names, such as `lint gallery`, to redo only
  those). It runs offline against copies of `examples/`, with `HOME` pointed at an empty
  folder so no API key is found. The gallery screenshot needs Google Chrome.

Before opening a pull request:

```bash
uv run --group dev ruff check src tests
uv run --group dev pytest
uv run --group docs mkdocs build --strict
```

and, if you touched a command, its dry run against an app repo of your own.

Bug reports are most useful with the command, its `--dry-run` output, and the App Store
Connect error text (with ids and keys removed).

Security problems go through
[private vulnerability reporting](https://github.com/blite/snakelane/security/advisories/new),
not a public issue; [SECURITY.md](https://github.com/blite/snakelane/blob/main/SECURITY.md)
has the details.
