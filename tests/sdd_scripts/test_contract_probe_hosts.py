"""sdd-contract-probe ships on every host that can run it (FEAT-708 follow-up).

Claude Code and Antigravity each have their own copy of the agent, with the same
body. The commands that delegate to it say how each host launches it, so the
byte-identical `.agent/workflows` twins never ask Antigravity for Claude's
`Agent` tool. The agent itself names no monorepo path, so it works in any repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_CLAUDE_AGENT = _ROOT / ".claude/agents/sdd-contract-probe.md"
_AGY_AGENT = _ROOT / ".agents/agents/sdd-contract-probe/agent.md"
_CALLERS = ("sdd-task", "sdd-brainstorm", "sdd-proposal")


def _body(text: str) -> str:
    """Drop the leading YAML frontmatter block."""
    assert text.startswith("---\n")
    return text.split("\n---\n", 1)[1].lstrip("\n")


def test_agy_agent_matches_claude_body() -> None:
    """Only the frontmatter differs between the two hosts' copies."""
    claude = _CLAUDE_AGENT.read_text(encoding="utf-8")
    agy = _AGY_AGENT.read_text(encoding="utf-8")
    assert _body(agy) == _body(claude)
    assert "subagent: true" in agy.split("\n---\n", 1)[0]


def test_agent_names_no_monorepo_path() -> None:
    """Module lookup goes through `git ls-files`, never a fixed source root."""
    body = _CLAUDE_AGENT.read_text(encoding="utf-8")
    assert "packages/" not in body
    assert "git ls-files" in body


@pytest.mark.parametrize("name", _CALLERS)
@pytest.mark.parametrize("host_dir", (".claude/commands", ".agent/workflows"))
def test_callers_name_each_host(host_dir: str, name: str) -> None:
    """Every caller tells Claude, Antigravity and other hosts what to do."""
    text = (_ROOT / host_dir / f"{name}.md").read_text(encoding="utf-8")
    assert ".agents/agents/sdd-contract-probe/agent.md" in text
    assert "Codex" in text
    assert "without the Agent tool" not in text
    assert "When the `Agent` tool is available" not in text
