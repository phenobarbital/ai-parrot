"""SDD flow-type frontmatter parser shared across SDD commands and agents.

This module is the single source of truth for reading and emitting the
YAML frontmatter block that brainstorm/proposal/spec documents carry to
declare their SDD flow type and base branch.

The contract is intentionally tiny: a Pydantic model with a cross-field
validator, a forgiving ``parse`` that returns sensible defaults when no
frontmatter is present (so legacy specs keep working), and a symmetric
``emit`` used by generation commands when scaffolding new documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator


#: Canonical long-lived branches in the Git Parrot Flow (FEAT-187).
#: Commands use this for a soft warning when ``base_branch`` falls
#: outside the set; ``FlowMeta`` itself accepts any string so
#: sub-feature branches keep working (see CLAUDE.md).
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})


class FlowMeta(BaseModel):
    """SDD flow metadata derived from a doc's YAML frontmatter."""

    type: Literal["feature", "hotfix"]
    base_branch: str

    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta":
        if self.type == "hotfix" and self.base_branch != "main":
            raise ValueError(
                "type='hotfix' requires base_branch='main' "
                f"(got base_branch={self.base_branch!r})"
            )
        return self


def parse(doc_path: Path) -> FlowMeta:
    """Parse YAML frontmatter from a brainstorm/proposal/spec markdown file.

    The frontmatter block, when present, must be the first thing in the
    file: a line containing only ``---``, the YAML body, and a closing
    ``---`` line. Anything before the opening ``---`` (including a UTF-8
    BOM or leading whitespace) means the file is treated as having no
    frontmatter and the defaults are returned.

    Args:
        doc_path: Path to the markdown file to inspect.

    Returns:
        ``FlowMeta(type="feature", base_branch="dev")`` when no
        frontmatter is present (backwards-compat for in-flight specs);
        otherwise a fully-validated ``FlowMeta``.

    Raises:
        pydantic.ValidationError: When frontmatter is present but
            invalid (e.g. ``type: hotfix`` without ``base_branch: main``).
    """
    text = doc_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return FlowMeta(type="feature", base_branch="dev")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return FlowMeta(type="feature", base_branch="dev")
    block = yaml.safe_load(parts[1]) or {}
    if not isinstance(block, dict):
        return FlowMeta(type="feature", base_branch="dev")
    return FlowMeta(**block)


def emit(meta: FlowMeta) -> str:
    """Render a ``FlowMeta`` as a Jekyll-style frontmatter block.

    The returned string is suitable for prepending to a brainstorm,
    proposal, or spec markdown file. It always ends with a newline so
    the existing document body can be concatenated directly.

    Args:
        meta: The flow metadata to serialize.

    Returns:
        A string of the form ``"---\\n<yaml>\\n---\\n"``.
    """
    body = yaml.safe_dump(meta.model_dump(), sort_keys=False).rstrip()
    return f"---\n{body}\n---\n"
