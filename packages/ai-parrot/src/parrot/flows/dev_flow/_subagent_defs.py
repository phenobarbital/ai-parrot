"""Loader for SDD subagent definitions used by the dev-flow dispatcher.

The dev-flow owns its own prompt set — it deliberately does NOT extend
``dev_loop._subagent_defs``'s name set (spec §3 Module 3), so the ops flow
and the development flow can evolve their prompts independently:

* ``sdd-ideation`` — turns a natural-language request into a committed SDD
  document (FEAT-412). **Dual-mode**: the dispatch payload's ``mode`` field
  selects a full ``.brainstorm.md`` (intent ``new_feature``) or a light
  ``.proposal.md`` (intent ``enhancement``). Resolves Open Questions with
  the human across bounded rounds and emits one ``IdeationOutput`` JSON.

Everything downstream of ideation (``sdd-planner``, ``sdd-worker``,
``sdd-qa``, ``sdd-codereview``, ``sdd-feedback``, …) is dispatched by the
reused ``dev_loop`` nodes and therefore loaded by ``dev_loop``'s own
loader — not this one.

:func:`load_subagent_definition` reads **only** the package-shipped copy at
``dev_flow/_subagent_data/<name>.md``, mirroring the ``dev_loop`` loader's
contract: that copy is the canonical, always-available source for dispatch
(it keeps working when ``ai-parrot`` is installed as a wheel outside the
repo). It does NOT read ``.claude/agents/`` at runtime — the repo-level
twin at ``.claude/agents/sdd-ideation.md`` exists for interactive Claude
Code use with ``setting_sources=["project"]``.
"""

from __future__ import annotations

from importlib.resources import files

_VALID_NAMES: frozenset[str] = frozenset({"sdd-ideation"})


def _strip_frontmatter(text: str) -> str:
    """Strip a leading YAML frontmatter block (``---\\n...\\n---``).

    Mirrors ``dev_loop._subagent_defs._strip_frontmatter`` exactly, including
    its conservative failure mode.

    Args:
        text: Raw markdown file contents.

    Returns:
        The body with the frontmatter removed, or ``text`` unchanged when
        there is no frontmatter block or the block is malformed (never
        silently drops the whole file).
    """
    if not text.startswith("---"):
        return text
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
    return "\n".join(lines[closing + 1:]).lstrip("\n")


def load_subagent_definition(name: str) -> str:
    """Return the system-prompt body of a dev-flow SDD subagent.

    Args:
        name: Currently only ``"sdd-ideation"``.

    Returns:
        The Markdown body of the subagent definition with the YAML
        frontmatter stripped, suitable for use as a plain ``system_prompt``
        when constructing a programmatic ``AgentDefinition``.

    Raises:
        ValueError: If ``name`` is not a known dev-flow subagent.
        FileNotFoundError: If the package-bundled data file is missing
            (indicates a packaging error).
    """
    if name not in _VALID_NAMES:
        raise ValueError(
            f"Unknown subagent name {name!r}. Expected one of "
            f"{sorted(_VALID_NAMES)}."
        )
    data_dir = files("parrot.flows.dev_flow") / "_subagent_data"
    target = data_dir / f"{name}.md"
    text = target.read_text(encoding="utf-8")
    return _strip_frontmatter(text)


__all__ = ["load_subagent_definition"]
