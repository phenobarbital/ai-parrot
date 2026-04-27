"""Loader for SDD subagent definitions used by the dev-loop dispatcher.

The dev-loop flow binds one of three subagents per dispatch:

* ``sdd-research`` — bug triage, Jira ticket, ``/sdd-spec``, ``/sdd-task``,
  worktree creation.
* ``sdd-worker`` — feature implementation inside the worktree.
* ``sdd-qa`` — deterministic acceptance verification under
  ``permission_mode="plan"``.

The Markdown files for each subagent are dual-sourced (per spec §7
"Patterns"):

1. **Repo-level**: ``.claude/agents/<name>.md`` — loaded by Claude Code
   from the project source tree when ``setting_sources=["project"]``.
2. **Package-shipped**: ``_subagent_data/<name>.md`` — bundled with the
   ``ai-parrot`` wheel so dispatches keep working when the package is
   installed outside the repo.

This module exposes a single helper, :func:`load_subagent_definition`,
that returns the **body** of a definition (with the YAML frontmatter
stripped) suitable for use as a plain ``system_prompt`` string when
constructing a programmatic ``claude_agent_sdk.AgentDefinition``.
"""

from __future__ import annotations

from importlib.resources import files

_VALID_NAMES: frozenset[str] = frozenset(
    {"sdd-research", "sdd-worker", "sdd-qa"}
)


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
    body = "\n".join(lines[closing + 1:]).lstrip("\n")
    return body


def load_subagent_definition(name: str) -> str:
    """Return the system-prompt body of an SDD subagent.

    Args:
        name: One of ``"sdd-research"``, ``"sdd-worker"``, ``"sdd-qa"``.

    Returns:
        The Markdown body of the subagent definition with the YAML
        frontmatter stripped.

    Raises:
        ValueError: If ``name`` is not one of the three known subagents.
        FileNotFoundError: If the package-bundled data file is missing
            (indicates a packaging error).
    """
    if name not in _VALID_NAMES:
        raise ValueError(
            f"Unknown subagent name {name!r}. Expected one of "
            f"{sorted(_VALID_NAMES)}."
        )
    data_dir = files("parrot.flows.dev_loop") / "_subagent_data"
    target = data_dir / f"{name}.md"
    text = target.read_text(encoding="utf-8")
    return _strip_frontmatter(text)


__all__ = ["load_subagent_definition"]
