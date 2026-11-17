"""Body checks for dispatched dev-loop subagent prompts.

Covers FEAT-377 Module 1 / TASK-1906. `load_subagent_definition()` reads the
packaged asset under `parrot/sdd/_assets/claude/agents/` (FEAT-633 C2). Byte
parity with the repo-level `.claude/agents/<name>.md` is no longer a test: it
is enforced by `scripts/sdd/check_asset_sync.py --check` (CI) and
`tests/sdd_scripts/test_check_asset_sync.py::test_repo_assets_in_sync`.
"""
from __future__ import annotations

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
