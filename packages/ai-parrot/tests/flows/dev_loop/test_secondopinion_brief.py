"""Unit tests for FEAT-375 `sdd-secondopinion` neutral subagent brief.

Covers TASK-1900 (Module 2: sdd-secondopinion subagent brief).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

_REPO_ROOT = Path(__file__).resolve().parents[5]


def test_secondopinion_brief_loads():
    body = load_subagent_definition("sdd-secondopinion")
    assert body and not body.startswith("---")


def test_secondopinion_unknown_name_still_raises():
    with pytest.raises(ValueError, match="Unknown subagent name"):
        load_subagent_definition("sdd-nonexistent")


def test_dual_source_bodies_identical():
    pkg = (
        _REPO_ROOT
        / "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md"
    )
    repo = _REPO_ROOT / ".claude/agents/sdd-secondopinion.md"
    assert pkg.read_text() == repo.read_text()


def test_brief_is_advisory_only():
    body = load_subagent_definition("sdd-secondopinion").lower()
    assert "advisory" in body
    assert "do not fix" in body or "not fix" in body


def test_frontmatter_permission_mode_is_a_valid_claude_value():
    """FEAT-375 code-review fix: the frontmatter previously declared
    `permissionMode: read-only`, which is not a valid
    `claude_agent_sdk.types.PermissionMode` value (only 'default',
    'acceptEdits', 'plan', 'bypassPermissions', 'dontAsk', 'auto' are) — a
    real Claude Code session picking this file up as a project subagent
    would choke on it. `sdd-qa.md` uses 'plan' for the equivalent
    read-only-intent case; this brief must match that convention."""
    pkg = (
        _REPO_ROOT
        / "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-secondopinion.md"
    )
    frontmatter_lines = pkg.read_text().split("---")[1].splitlines()
    permission_mode_lines = [ln for ln in frontmatter_lines if ln.startswith("permissionMode:")]
    assert permission_mode_lines == ["permissionMode: plan"]
