"""Markdown that GitHub renders but MkDocs (Python-Markdown) doesn't: caught here, since a
README or a skill reference looks fine on GitHub and breaks on the docs site."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from .helpers import ROOT

PAGES = sorted([*ROOT.glob("docs/**/*.md"), ROOT / "README.md", ROOT / "CONTRIBUTING.md", ROOT / "CHANGELOG.md",
                *ROOT.glob("skills/snakelane/*.md"), *ROOT.glob("skills/snakelane/references/*.md")])


def prose(path: Path):
    """(line number, line, previous line), outside fenced code blocks."""
    fence, previous = False, ""
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            yield number, line, previous
        previous = line


@pytest.mark.parametrize("path", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_lists_render_as_lists(path: Path) -> None:
    problems = []
    in_step = False
    for number, line, previous in prose(path):
        if re.match(r"^\d+\. ", line):
            in_step = True
            if previous.strip() and not re.match(r"^\d+\. ", previous) and not previous.startswith(" "):
                problems.append(f"{number}: a numbered list needs a blank line before it")
        elif line and not line.startswith(" "):
            in_step = False
        if in_step and re.match(r"^ {1,3}\S", line):
            problems.append(f"{number}: indent a numbered item's continuation by 4 spaces, not {len(line) - len(line.lstrip())}")
        if (re.match(r"^- ", line) and previous.strip() and not previous.startswith((" ", "-", "|", "#", "<", ">", "!!!"))):
            problems.append(f"{number}: a list needs a blank line before it ({previous[:40]!r})")
    assert not problems, f"{path.relative_to(ROOT)}:\n" + "\n".join(problems)
