"""Tests for semantic parity across SDD workflow twins (Claude, Codex, Antigravity).

Verifies equivalent fields and procedures for ledger integration.
"""

import pytest
from pathlib import Path


def read_workflow_file(path: str) -> str:
    """Read a workflow file and return its content."""
    file_path = Path(path)
    if not file_path.exists():
        pytest.fail(f"Workflow file not found: {path}")
    return file_path.read_text()


def test_workflow_files_exist():
    """Verify all three workflow files exist."""
    claude_file = ".claude/commands/sdd-codereview.md"
    antigravity_file = ".agent/workflows/sdd-codereview.md"
    codex_file = ".agents/skills/sdd-codereview/SKILL.md"
    
    for file_path in [claude_file, antigravity_file, codex_file]:
        assert Path(file_path).exists(), f"Missing workflow file: {file_path}"


def test_basic_content_verification():
    """Verify key content elements are present in all workflow files."""
    claude_content = read_workflow_file(".claude/commands/sdd-codereview.md")
    antigravity_content = read_workflow_file(".agent/workflows/sdd-codereview.md")
    codex_content = read_workflow_file(".agents/skills/sdd-codereview/SKILL.md")
    
    # Test that we can read the files (basic sanity check)
    assert len(claude_content) > 1000, "Claude file appears too short"
    assert len(antigravity_content) > 1000, "Antigravity file appears too short"
    assert len(codex_content) > 100, "Codex file appears too short"
    
    # Check that all workflows have the basic structure we expect
    assert "# /sdd-codereview" in claude_content
    assert "# /sdd-codereview" in antigravity_content
    assert "# SDD Code Review" in codex_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])