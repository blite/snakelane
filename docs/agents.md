# Using snakelane with a coding agent

snakelane ships an [Agent Skill](https://agentskills.io) in `skills/snakelane/`. It tells an
agent (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot and others) how to run
snakelane, which App Store Connect traps it guards against, and how to fix snakelane itself
when it's wrong.

**Linked from your checkout (recommended).** The agent reads the skill from the checkout the
command runs from, so it can change snakelane in place:

```bash
# the shared agent skills folder, and Claude Code's
ln -s "$PWD/snakelane/skills/snakelane" ~/.agents/skills/snakelane
ln -s "$PWD/snakelane/skills/snakelane" ~/.claude/skills/snakelane
```

**Copied, with the skills CLI:** `npx skills add blite/snakelane` installs it into every
agent it detects. A copy can operate snakelane but not change it.

With the skill loaded, an agent will:

- dry-run first, and never write to App Store Connect to test a change;
- translate captions and listing text within each field's limit, record it with
  `translations mark`, and leave `--reviewed` to you;
- show you `gallery --live` before a screenshot push;
- not create a [product id](https://developer.apple.com/help/app-store-connect/reference/in-app-purchase-information) or asset pack id unless you ask, because both are permanent.
