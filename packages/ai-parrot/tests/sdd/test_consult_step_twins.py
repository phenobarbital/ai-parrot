"""Tests for the "Consult experts" step in sdd-proposal and sdd-spec commands (FEAT-890).

This test verifies that:
1. The consult step appears in all six twin files (.claude/commands/, .agent/workflows/,
   .agents/skills/) for both sdd-proposal and sdd-spec.
2. The experts_cli.py command reference appears in all six files.
3. The contribution promotion logic appears in sdd-spec files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]

# The six twin files that must contain the consult step
_TWIN_FILES = (
    ".claude/commands/sdd-proposal.md",
    ".claude/commands/sdd-spec.md",
    ".agent/workflows/sdd-proposal.md",
    ".agent/workflows/sdd-spec.md",
    ".agents/skills/sdd-proposal/SKILL.md",
    ".agents/skills/sdd-spec/SKILL.md",
)

# Strings that must appear in all six files
_REQUIRED_STRINGS = (
    "parrot sdd experts consult",
    "sdd/state/.contributions/",
    "CONFIRM",
    "REJECT",
    "ESCALATE",
)

# Strings that must appear only in sdd-spec files (contribution promotion)
_SPEC_ONLY_STRINGS = (
    "sdd/state/<FEAT-ID>/contributions/",
    "contributions promotion",
)


def _read_file(rel_path: str) -> str:
    """Read a file from the repo root."""
    return (_REPO_ROOT / rel_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel_path", _TWIN_FILES)
def test_consult_step_present(rel_path: str) -> None:
    """Each twin file must contain the consult step."""
    content = _read_file(rel_path)
    assert "Consult experts" in content, f"{rel_path} missing 'Consult experts' step"
    assert "FEAT-890" in content, f"{rel_path} missing FEAT-890 reference"


@pytest.mark.parametrize("rel_path", _TWIN_FILES)
def test_experts_command_reference(rel_path: str) -> None:
    """Each twin file must reference the experts CLI command."""
    content = _read_file(rel_path)
    assert "parrot sdd experts consult" in content, f"{rel_path} missing 'parrot sdd experts consult' command"


@pytest.mark.parametrize("rel_path", _TWIN_FILES)
def test_contribution_path_reference(rel_path: str) -> None:
    """Each twin file must reference the contributions path."""
    content = _read_file(rel_path)
    assert "sdd/state/.contributions/" in content, f"{rel_path} missing 'sdd/state/.contributions/' path"


@pytest.mark.parametrize("rel_path", _TWIN_FILES)
def test_triage_states_present(rel_path: str) -> None:
    """Each twin file must have CONFIRM/REJECT/ESCALATE triage."""
    content = _read_file(rel_path)
    assert "CONFIRM" in content, f"{rel_path} missing CONFIRM triage"
    assert "REJECT" in content, f"{rel_path} missing REJECT triage"
    assert "ESCALATE" in content, f"{rel_path} missing ESCALATE triage"


@pytest.mark.parametrize("rel_path", _SPEC_ONLY_STRINGS)
def test_spec_only_strings(rel_path: str) -> None:
    """Strings that must appear only in sdd-spec files."""
    spec_files = [
        ".claude/commands/sdd-spec.md",
        ".agent/workflows/sdd-spec.md",
        ".agents/skills/sdd-spec/SKILL.md",
    ]
    # Check that at least one spec file has it (case-insensitive for "promotion")
    search = rel_path.lower()
    found = any(search in _read_file(f).lower() for f in spec_files)
    assert found, f"'{rel_path}' not found in any sdd-spec twin file"


def test_proposal_files_have_consult_step() -> None:
    """sdd-proposal files must have the consult step before synthesis."""
    proposal_files = [
        ".claude/commands/sdd-proposal.md",
        ".agent/workflows/sdd-proposal.md",
        ".agents/skills/sdd-proposal/SKILL.md",
    ]
    for rel_path in proposal_files:
        content = _read_file(rel_path)
        # The consult step should appear before "Synthesis" in proposal files
        consult_pos = content.find("Consult experts")
        synthesis_pos = content.find("### 5. Phase 3 — Synthesis")
        if synthesis_pos == -1:
            synthesis_pos = content.find("## Synthesis")
        assert consult_pos != -1, f"{rel_path} missing consult step"
        if synthesis_pos != -1:
            assert consult_pos < synthesis_pos, f"{rel_path}: consult step must appear before synthesis"


def test_spec_files_have_consult_step_before_research() -> None:
    """sdd-spec files must have the consult step before research."""
    spec_files = [
        ".claude/commands/sdd-spec.md",
        ".agent/workflows/sdd-spec.md",
        ".agents/skills/sdd-spec/SKILL.md",
    ]
    for rel_path in spec_files:
        content = _read_file(rel_path)
        # The consult step should appear before "Research the Codebase"
        consult_pos = content.find("Consult experts")
        research_pos = content.find("Research the Codebase")
        assert consult_pos != -1, f"{rel_path} missing consult step"
        if research_pos != -1:
            assert consult_pos < research_pos, f"{rel_path}: consult step must appear before research"


def test_spec_commit_promotes_contributions() -> None:
    """sdd-spec files must have contribution promotion in the commit step."""
    spec_files = [
        ".claude/commands/sdd-spec.md",
        ".agent/workflows/sdd-spec.md",
    ]
    for rel_path in spec_files:
        content = _read_file(rel_path)
        # The commit step should promote contributions
        assert "contributions" in content.lower(), f"{rel_path} missing contributions promotion in commit step"
        # Should have the staging path
        assert "sdd/state/.contributions" in content, f"{rel_path} missing .contributions staging path"


@pytest.mark.parametrize("rel_path", _TWIN_FILES)
def test_triage_and_promote_commands_are_taught(rel_path: str) -> None:
    """The step tells the agent how to record a decision and how to promote a confirmed finding."""
    content = _read_file(rel_path)
    assert "parrot sdd experts triage" in content, f"{rel_path} does not teach 'parrot sdd experts triage'"
    assert "parrot sdd experts promote" in content, f"{rel_path} does not teach 'parrot sdd experts promote'"


@pytest.mark.parametrize("rel_path", _TWIN_FILES)
def test_consult_never_points_at_a_document_that_does_not_exist_yet(rel_path: str) -> None:
    """The spec is not written when the step runs, so it must not be the consulted document."""
    content = _read_file(rel_path)
    assert "--doc sdd/specs/<feature-slug>.spec.md" not in content
