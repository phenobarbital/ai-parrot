"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_CLOSURE_HEADING = "## Deterministic task inspection and closure (FEAT-584)"

_MARKDOWN_TWINS = (
    ".claude/commands/sdd-start.md",
    ".agent/workflows/sdd-start.md",
    ".agents/skills/sdd-start/SKILL.md",
    ".agent/agents/sdd-worker/agent.md",
)

_CODEX_TOML = ".codex/agents/sdd-worker.toml"


def _repo_root() -> Path:
    """Walk up from this test file to the repo root that owns `.claude/agents/`."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".claude" / "agents").is_dir():
            return parent
    raise AssertionError("repo root (containing .claude/agents/) not found relative to this test file")


def test_start_twins_preserve_semantic_gates(tmp_path: Path) -> None:
    """Every start variant requires semantic green evidence before deterministic closure."""
    repo_root = _repo_root()

    for rel_path in _MARKDOWN_TWINS:
        body = (repo_root / rel_path).read_text(encoding="utf-8")
        assert _CLOSURE_HEADING in body, f"{rel_path} is missing the deterministic closure block"

        section = body.split(_CLOSURE_HEADING, 1)[1]
        for marker in (
            "wiki-first",
            "Prefer task-context inspection when the engine is present; fallback keeps explicit checks.",
            "declared test selector",
            "python -m scripts.sdd.finalize_task",
            "inspect returned staged paths and commit explicitly",
            "Reject stale evidence and divergent active/completed twins",
            "never reset unrelated staging",
        ):
            assert marker in section, f"{rel_path} closure block is missing {marker!r}"

    # AC8/AC17: the deterministic closure block augments the existing closing section --
    # it must not remove the pre-existing per-spec index / close_task.sh references that
    # gate a mechanical done state on the current SHA and a clean active/ directory.
    for rel_path in (
        ".claude/commands/sdd-start.md",
        ".agent/workflows/sdd-start.md",
        ".agents/skills/sdd-start/SKILL.md",
    ):
        body = (repo_root / rel_path).read_text(encoding="utf-8")
        assert "close_task.sh" in body, f"{rel_path} lost its close_task.sh reference"
        assert "sdd/tasks/index" in body, f"{rel_path} lost its per-spec index reference"

    agent_md = (repo_root / ".agent/agents/sdd-worker/agent.md").read_text(encoding="utf-8")
    assert "sdd/tasks/index" in agent_md, "agent.md lost its per-spec index reference"
    # No-MCP host: the deterministic closure guidance must not invent an MCP tool that
    # this host cannot call.
    assert "mcp__" not in agent_md


def test_host_variants_remain_honest(tmp_path: Path) -> None:
    """Codex TOML parses and unsupported hosts do not advertise Claude compaction."""
    repo_root = _repo_root()

    toml_path = repo_root / _CODEX_TOML
    with toml_path.open("rb") as fh:
        parsed = tomllib.load(fh)

    instructions = parsed["developer_instructions"]
    assert _CLOSURE_HEADING in instructions
    assert "never call Claude /compact" in instructions
    assert "unsupported_host" in instructions
    # AC12/AC13: never advertise compaction per task, and never require an MCP tool this
    # sandboxed Codex host does not have.
    assert "Do not compact for every task." in instructions
    assert "mcp__" not in instructions

    agent_md = (repo_root / ".agent/agents/sdd-worker/agent.md").read_text(encoding="utf-8")
    section = agent_md.split(_CLOSURE_HEADING, 1)[1]
    assert "unsupported_host" in section
    assert "never call Claude /compact" in section
    assert "Do not compact for every task." in section
