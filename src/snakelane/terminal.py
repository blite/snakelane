"""Terminal output: NO_COLOR/FORCE_COLOR-aware colours, truncation, and `store push`'s word diff."""

from __future__ import annotations

import difflib
import os
import re
import sys
from functools import partial


def truncate(value: str | None, limit: int = 80) -> str | None:
    return value if value is None or len(value) <= limit else f"{value[: limit - 1]}…"


def _wants_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return bool(os.environ.get("FORCE_COLOR")) or sys.stdout.isatty()


def _paint(code: int, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _wants_color() else text


red, green, dim = partial(_paint, 31), partial(_paint, 32), partial(_paint, 2)
DIFF_CONTEXT_LINES = 1
# Words, whitespace runs and single punctuation, so a diff marks "tests" → "readings", not scattered letters.
_DIFF_TOKEN = re.compile(r"\w+|\s+|[^\w\s]")


def _highlight_words(old: str, new: str) -> tuple[str, str]:
    """Mark differing words: reverse video (7/27 stays inside the red line), else git's [-old-]{+new+}."""
    old_tokens, new_tokens = _DIFF_TOKEN.findall(old), _DIFF_TOKEN.findall(new)
    color = _wants_color()
    old_out: list[str] = []
    new_out: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False).get_opcodes():
        old_part, new_part = "".join(old_tokens[i1:i2]), "".join(new_tokens[j1:j2])
        if op == "equal":
            old_out.append(old_part)
            new_out.append(new_part)
            continue
        if old_part:
            old_out.append(f"\033[7m{old_part}\033[27m" if color else f"[-{old_part}-]")
        if new_part:
            new_out.append(f"\033[7m{new_part}\033[27m" if color else f"{{+{new_part}+}}")
    return "".join(old_out), "".join(new_out)


def format_text_diff(old: str | None, new: str, indent: str = "    ") -> list[str]:
    """Line diff of `old` → `new` with changed words highlighted; never truncated."""
    if old is None:
        return [green(f"{indent}+ {line}") for line in new.splitlines() or [""]]
    old_lines, new_lines = old.splitlines(), new.splitlines()
    if old_lines == new_lines:
        same = old.rstrip("\n") == new.rstrip("\n")
        return [dim(f"{indent}  ({'only trailing newlines differ' if same else 'whitespace-only change'})")]
    context = lambda lines: [dim(f"{indent}  {line}") for line in lines]  # noqa: E731
    # A bare `+`/`-` line would hide an added or removed blank line.
    visible = lambda line: line if line.strip() else "(blank line)"  # noqa: E731
    out: list[str] = []
    opcodes = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes()
    for index, (op, i1, i2, j1, j2) in enumerate(opcodes):
        if op == "equal":
            lines = old_lines[i1:i2]
            head = DIFF_CONTEXT_LINES if index > 0 else 0
            tail = DIFF_CONTEXT_LINES if index < len(opcodes) - 1 else 0
            if len(lines) <= head + tail + 1:
                out += context(lines)
            else:
                skipped = len(lines) - head - tail
                out += [*context(lines[:head]), dim(f"{indent}  … {skipped} unchanged line{'s' * (skipped != 1)}"),
                        *context(lines[len(lines) - tail:])]
            continue
        removed, added = old_lines[i1:i2], new_lines[j1:j2]
        # Pair lines for word highlighting: a reworded paragraph is one line in these files.
        paired = min(len(removed), len(added)) if op == "replace" else 0
        pairs = [_highlight_words(a, b) for a, b in zip(removed[:paired], added[:paired], strict=True)]
        out += [red(f"{indent}- {line}") for line, _ in pairs]
        out += [red(f"{indent}- {visible(line)}") for line in removed[paired:]]
        out += [green(f"{indent}+ {line}") for _, line in pairs]
        out += [green(f"{indent}+ {visible(line)}") for line in added[paired:]]
    return out
