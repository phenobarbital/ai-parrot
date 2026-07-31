"""Loader for SDD subagent definitions used by the dev-loop dispatcher.

The dev-loop flow binds one of several subagents per dispatch:

* ``sdd-research`` — bug triage, Jira ticket, ``/sdd-spec``, ``/sdd-task``,
  worktree creation.
* ``sdd-worker`` — feature implementation inside the worktree.
* ``sdd-qa`` — deterministic acceptance verification under
  ``permission_mode="plan"``.
* ``sdd-codereview`` — read-only qualitative code-review gate (FEAT-250)
  under ``permission_mode="plan"``.
* ``sdd-secondopinion`` — read-only adversarial second-opinion review
  (FEAT-375): advisory findings only, never modifies files.
* ``sdd-planner`` — feature-mode document-driven planning (FEAT-378):
  generates missing SDD artifacts (spec/task index) and the feature
  worktree from a brainstorm/proposal/spec document.
* ``sdd-feedback`` — feature-mode QA-failure feedback routing (FEAT-378):
  read-only, proposes ``retry``/``escalate``/``accept_with_notes`` over a
  QAReport + judge-panel verdicts; the deterministic envelope and stop
  rule are enforced in Python, never trusted from the proposal alone.

``load_subagent_definition`` reads **only** the package-shipped copy at
``_subagent_data/<name>.md`` — this is the canonical, always-available
source for dispatch (it keeps working when ``ai-parrot`` is installed as
a wheel outside the repo). It does NOT read ``.claude/agents/`` at
runtime.

Four of the five prompts (``sdd-research``, ``sdd-worker``, ``sdd-qa``,
``sdd-secondopinion``) additionally have a repo-level twin at
``.claude/agents/<name>.md``, used by Claude Code interactively when
``setting_sources=["project"]``. ``sdd-codereview`` is dev-loop-internal
only and has no repo-level counterpart. Byte-parity between the two
copies of each dual-sourced prompt (repo is the newer, edited-by-humans
copy; package is what dispatch actually uses) is enforced by
``tests/flows/dev_loop/test_subagent_parity.py`` — keeping them in sync
is a review/test discipline, not a runtime behavior.

This module exposes a single helper, :func:`load_subagent_definition`,
that returns the **body** of a definition (with the YAML frontmatter
stripped) suitable for use as a plain ``system_prompt`` string when
constructing a programmatic ``claude_agent_sdk.AgentDefinition``.
"""

from __future__ import annotations

from importlib.resources import files

_VALID_NAMES: frozenset[str] = frozenset(
    {
        "sdd-research",
        "sdd-worker",
        "sdd-qa",
        "sdd-codereview",
        "sdd-secondopinion",
        "sdd-planner",
        "sdd-feedback",
    }
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
        name: One of ``"sdd-research"``, ``"sdd-worker"``, ``"sdd-qa"``,
            ``"sdd-codereview"``, ``"sdd-secondopinion"``, ``"sdd-planner"``,
            ``"sdd-feedback"``.

    Returns:
        The Markdown body of the subagent definition with the YAML
        frontmatter stripped.

    Raises:
        ValueError: If ``name`` is not one of the known subagents.
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
