"""Project conventions injected into every external ``sdd-coder`` seat (FEAT-553).

Stdlib-only LEAF module: it must never import ``parrot.flows.dev_loop`` (that
package's ``__init__`` eagerly imports every dispatcher, ~2.2 s) so that
``parrot.knowledge.wiki.coding_agents`` and the parity tests stay cheap.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Sequence

CODER_RULE_NAMES: tuple[str, ...] = ("codebase-conventions", "python-development")  # v1 Python only (spec §8 Q5)
RULES_DIRNAME: str = ".agent/rules"
CONVENTIONS_PREAMBLE: str = (
    "Project conventions — binding for every file you touch; a banned import fails " "this attempt at the merge gate:"
)
_SEPARATOR: str = "\n\n---\n\n"


def _strip_frontmatter(text: str) -> str:
    """Strip a leading YAML frontmatter block (``---\\n...\\n---``).

    If the file does not start with a frontmatter block, returns ``text``
    unchanged.
    """
    if not text.startswith("---"):
        return text
    # Find the closing fence on its own line.
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    closing = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing = idx
            break
    if closing is None:
        # Malformed frontmatter — return text unchanged rather than
        # silently dropping the whole file.
        return text
    body = "\n".join(lines[closing + 1 :]).lstrip("\n")
    return body


def _package_rule(name: str) -> str:
    """Read the package-shipped copy ``_rules_data/<name>.md``; FileNotFoundError means a packaging error."""
    return (files("parrot.flows") / "_rules_data" / f"{name}.md").read_text(encoding="utf-8")


def load_project_conventions(
    cwd: str | os.PathLike[str] | None = None,
    *,
    names: Sequence[str] = CODER_RULE_NAMES,
) -> str:
    """Return the coder rule set as ONE Markdown block for prompt injection.

    Lookup order per name: ``<cwd>/.agent/rules/<name>.md`` when ``cwd`` is given and the file
    exists (the worktree copy wins), else the package copy. Frontmatter is stripped; each rule
    becomes ``## Project rule: <name>\\n\\n<body>``; blocks are joined by ``\\n\\n---\\n\\n``.

    Raises:
        ValueError: ``name`` not in ``CODER_RULE_NAMES``.
        FileNotFoundError: a package copy is missing (packaging error).
    """
    blocks: list[str] = []
    for name in names:
        if name not in CODER_RULE_NAMES:
            raise ValueError(f"Unknown rule {name!r}; expected one of {CODER_RULE_NAMES}")
        text: str | None = None
        if cwd is not None:
            candidate = Path(cwd) / RULES_DIRNAME / f"{name}.md"
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
        if text is None:
            text = _package_rule(name)
        blocks.append(f"## Project rule: {name}\n\n{_strip_frontmatter(text).strip()}")
    return _SEPARATOR.join(blocks)


__all__ = ["CODER_RULE_NAMES", "RULES_DIRNAME", "CONVENTIONS_PREAMBLE", "load_project_conventions"]
