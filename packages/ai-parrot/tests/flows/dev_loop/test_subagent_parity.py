"""Generic full-body parity sweep for dual-sourced dev-loop subagent prompts.

Covers FEAT-377 Module 1 / TASK-1906. `load_subagent_definition()` reads
ONLY the package-shipped copy under `_subagent_data/` (see
`parrot.flows.dev_loop._subagent_defs` docstring) — this test guards that
the four prompts which ALSO have a repo-level `.claude/agents/<name>.md`
twin (used by Claude Code interactively) stay byte-identical to what
dev-loop actually dispatches. `sdd-codereview` is dev-loop-internal only
and has no repo-level counterpart, so it is intentionally excluded from
the byte-parity assertion (covered instead by
`test_subagent_codereview.py`).
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[5]

# Prompts that are NOT expected to have a `.claude/agents/<name>.md` twin.
# `sdd-codereview` is a dev-loop dispatch-only subagent (never exposed as
# a Claude Code interactive project agent) — verified via `git log --all`
# on `.claude/agents/sdd-codereview.md` returning zero history.
_NO_REPO_TWIN = frozenset({"sdd-codereview"})


def _repo_agents_dir() -> Path | None:
    """Walk up from this file to find `.claude/agents/`; None if absent."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".claude" / "agents"
        if candidate.is_dir():
            return candidate
    return None


def _package_prompts() -> list[str]:
    pkg = resources.files("parrot.flows.dev_loop") / "_subagent_data"
    return sorted(p.name[:-3] for p in pkg.iterdir() if p.name.endswith(".md"))


@pytest.mark.parametrize("name", _package_prompts())
def test_prompt_parity(name: str) -> None:
    """Every dual-sourced packaged prompt is byte-identical to its
    `.claude/agents/` twin; prompts with no repo twin are skipped."""
    agents_dir = _repo_agents_dir()
    if agents_dir is None:
        pytest.skip(
            "`.claude/agents/` not found relative to this test file — "
            "running against an installed package, not the repo checkout."
        )
    if name in _NO_REPO_TWIN:
        pytest.skip(f"{name!r} is dev-loop-internal only; no repo-level twin expected.")

    repo_copy = agents_dir / f"{name}.md"
    pkg_copy = (
        resources.files("parrot.flows.dev_loop") / "_subagent_data" / f"{name}.md"
    )
    assert repo_copy.is_file(), (
        f"Expected a repo-level twin at {repo_copy} for dual-sourced prompt {name!r}."
    )
    assert pkg_copy.read_text(encoding="utf-8") == repo_copy.read_text(encoding="utf-8"), (
        f"{name}.md drifted between _subagent_data/ (package) and .claude/agents/ (repo)."
    )


def test_research_prompt_has_wiki_block() -> None:
    """Dispatched sdd-research contains the wiki-first triage instructions
    (G2 seam 1) — a fixable defect otherwise causes dev-loop research
    dispatches to grep blind while interactive sessions query the wiki."""
    from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

    body = load_subagent_definition("sdd-research")
    assert "wikitoolkit query" in body
    assert "Wiki-first" in body or "wiki-first" in body.lower()
    # Must degrade gracefully when the wiki plane isn't built.
    assert "Wiki not built" in body or "skip this step" in body.lower()


def test_worker_prompt_has_per_spec_index_instructions() -> None:
    """Dispatched sdd-worker contains the FEAT-145 per-spec-index
    instructions (code and state committed together in the worktree)."""
    from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

    body = load_subagent_definition("sdd-worker")
    assert "FEAT-145" in body
    assert "per-spec index" in body
