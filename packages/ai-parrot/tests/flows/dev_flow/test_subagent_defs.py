"""Tests for the dev-flow subagent loader and the sdd-ideation prompt.

Covers FEAT-412 TASK-2124: the ``dev_flow``-owned
:func:`load_subagent_definition` (same contract as ``dev_loop``'s) and the
content guarantees the ``IdeationNode`` round-trip depends on — both dispatch
modes, the resume/extend policy, the FEAT-145 frontmatter, the
Open-Questions convention, the explicit-path commit, and JSON-only output.

The prompt-content assertions are deliberately behavioral rather than
cosmetic: each one guards an instruction whose loss would silently break the
flow (e.g. a prompt that stops mandating ``committed`` reporting makes
``IdeationNode``'s fail-fast check meaningless).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest
from parrot.flows.dev_flow._subagent_defs import (
    _strip_frontmatter,
    load_subagent_definition,
)


@pytest.fixture(scope="module")
def body() -> str:
    return load_subagent_definition("sdd-ideation")


# ---------------------------------------------------------------------------
# Loader contract
# ---------------------------------------------------------------------------


def test_loader_returns_ideation_body(body: str):
    assert body
    # Frontmatter stripped: the body starts at the first heading.
    assert not body.startswith("---")
    assert "name: sdd-ideation" not in body
    assert body.lstrip().startswith("# SDD Ideation")


def test_loader_unknown_name_raises():
    with pytest.raises(ValueError, match="Unknown subagent name"):
        load_subagent_definition("sdd-planner")  # dev_loop's, not ours
    with pytest.raises(ValueError, match="Unknown subagent name"):
        load_subagent_definition("nope")


def test_loader_reads_package_data_dir():
    """The loader reads the package copy, not `.claude/agents/`."""
    pkg_copy = (
        resources.files("parrot.flows.dev_flow")
        / "_subagent_data"
        / "sdd-ideation.md"
    )
    assert pkg_copy.is_file()
    assert load_subagent_definition("sdd-ideation") == _strip_frontmatter(
        pkg_copy.read_text(encoding="utf-8")
    )


def test_strip_frontmatter_edge_cases():
    assert _strip_frontmatter("# no frontmatter") == "# no frontmatter"
    assert _strip_frontmatter("---\na: 1\n---\nbody") == "body"
    # Malformed (never closed) → returned unchanged, never truncated.
    unclosed = "---\na: 1\nbody"
    assert _strip_frontmatter(unclosed) == unclosed


# ---------------------------------------------------------------------------
# Dual-mode behavior
# ---------------------------------------------------------------------------


def test_prompt_mentions_both_modes_and_output_fields(body: str):
    """One definition, two modes — and the full IdeationOutput contract."""
    assert 'mode="brainstorm"' in body or "mode = \"brainstorm\"" in body
    assert 'mode="proposal"' in body or "mode = \"proposal\"" in body
    assert "new_feature" in body
    assert "enhancement" in body

    for field in (
        "document_path",
        "document_kind",
        "slug",
        "resumed_existing",
        "open_questions",
        "summary",
        "committed",
    ):
        assert field in body, f"prompt must document the {field!r} output field"


def test_prompt_binds_mode_to_document_suffix(body: str):
    """brainstorm → .brainstorm.md, proposal → .proposal.md."""
    assert "sdd/proposals/<slug>.brainstorm.md" in body
    assert "sdd/proposals/<slug>.proposal.md" in body
    # The mode, not the agent's judgement, decides the format.
    assert "`mode` decides the format" in body


def test_prompt_keeps_enhancement_proposal_light(body: str):
    """The enhancement path must NOT become the deep /sdd-proposal artifact."""
    lowered = body.lower()
    assert "light" in lowered
    assert "/sdd-proposal" in body  # explicitly disclaimed
    assert "options analysis" in lowered
    # The light format's required sections.
    for section in ("## Scope", "## Rationale", "## Impact"):
        assert section in body


def test_prompt_brainstorm_requires_options_and_recommendation(body: str):
    assert "## Options Explored" in body
    assert "## Recommendation" in body
    assert "Option A" in body and "Option B" in body


# ---------------------------------------------------------------------------
# Resume/extend policy (spec §8 resolution)
# ---------------------------------------------------------------------------


def test_prompt_mandates_resume_extend_policy(body: str):
    lowered = body.lower()
    assert "resume" in lowered and "extend" in lowered
    assert "resumed_existing" in body
    # Never overwrite, never suffix.
    assert "never overwrite" in lowered or "never overwrites" in lowered
    assert "-2" in body  # the forbidden suffixed-copy pattern
    assert "forbidden" in lowered


def test_prompt_handles_slug_collision_as_open_question(body: str):
    """A mismatched pre-existing document must not be extended silently."""
    lowered = body.lower()
    assert "collision" in lowered
    assert "problem statement" in lowered
    assert "committed: false" in lowered


# ---------------------------------------------------------------------------
# SDD conventions the downstream planner depends on
# ---------------------------------------------------------------------------


def test_prompt_carries_feat145_frontmatter(body: str):
    assert "type: feature" in body
    assert "base_branch: dev" in body
    assert "FEAT-145" in body


def test_prompt_documents_open_questions_convention(body: str):
    """The exact convention /sdd-spec §2b parses."""
    assert "- [ ]" in body
    assert "- [x]" in body
    assert "*Resolved*:" in body
    assert "*Owner: user*" in body or "*Owner:" in body
    # The parser's rule: answer is the text after the final colon.
    assert "final `:`" in body
    # Unanswered questions must survive the round, not be deleted/rephrased.
    lowered = body.lower()
    assert "do not delete them" in lowered


def test_prompt_requires_explicit_path_commit(body: str):
    """Never `git add -A` — other SDD sessions share the base branch."""
    assert "git add sdd/proposals/" in body
    # Case-sensitive on purpose: lowercasing would mangle the `-A` flag.
    assert "never `git add -A`" in body
    assert "never `git add .`" in body
    assert "sdd:" in body  # commit-message convention


def test_prompt_mandates_json_only_final_turn(body: str):
    lowered = body.lower()
    assert "one json object" in lowered
    assert "no markdown fences" in lowered
    assert "no prose" in lowered


def test_prompt_forbids_code_and_jira_writes(body: str):
    lowered = body.lower()
    assert "you write documents, not code" in lowered
    assert "jira" in lowered
    assert "never invent" in lowered  # anti-hallucination on Code Context


# ---------------------------------------------------------------------------
# Repo-level twin parity
# ---------------------------------------------------------------------------


def _repo_agents_dir() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".claude" / "agents"
        if candidate.is_dir():
            return candidate
    return None


def test_prompt_parity_with_repo_twin():
    """The `.claude/agents/` mirror stays byte-identical to what we dispatch."""
    agents_dir = _repo_agents_dir()
    if agents_dir is None:
        pytest.skip("`.claude/agents/` not found — installed package, not a checkout.")

    repo_copy = agents_dir / "sdd-ideation.md"
    pkg_copy = (
        resources.files("parrot.flows.dev_flow")
        / "_subagent_data"
        / "sdd-ideation.md"
    )
    assert repo_copy.is_file(), f"Expected a repo-level twin at {repo_copy}."
    assert pkg_copy.read_text(encoding="utf-8") == repo_copy.read_text(
        encoding="utf-8"
    ), "sdd-ideation.md drifted between _subagent_data/ and .claude/agents/."


def test_repo_twin_has_agent_frontmatter():
    agents_dir = _repo_agents_dir()
    if agents_dir is None:
        pytest.skip("`.claude/agents/` not found — installed package, not a checkout.")
    text = (agents_dir / "sdd-ideation.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    head = text.split("---")[1]
    assert "name: sdd-ideation" in head
    assert "description:" in head
    assert "tools:" in head
    assert "model:" in head
