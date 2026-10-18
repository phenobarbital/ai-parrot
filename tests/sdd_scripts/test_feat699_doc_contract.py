"""FEAT-699: agent/command prompts describe contract-driven, new-red-gated validation."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUBAGENT = "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data"
SELECT_FILES = [
    ".claude/commands/sdd-done.md",
    ".agent/workflows/sdd-done.md",
    ".claude/agents/sdd-worker.md",
    ".agent/agents/sdd-worker/agent.md",
    f"{SUBAGENT}/sdd-worker.md",
    ".claude/agents/qa-runner.md",
]
ALL_FILES = SELECT_FILES + [
    ".agents/skills/sdd-done/SKILL.md",
    ".claude/agents/sdd-coder.md",
    f"{SUBAGENT}/sdd-coder.md",
]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", ALL_FILES)
def test_no_ten_task_skip(rel):
    assert "<= 10 tasks" not in _text(rel)


@pytest.mark.parametrize("rel", SELECT_FILES)
def test_index_flag_on_every_select_tests_tier_call(rel):
    text = _text(rel)
    # Join continuation lines so a call split across lines is judged as one command.
    flat = re.sub(r"\\\n\s*", " ", text)
    calls = [m.group(0) for m in re.finditer(r"select_tests --tier (?:feature|merge)[^\n`]*(?:\n\s+--[^\n`]*)?", flat)]
    assert calls, rel
    for call in calls:
        assert "--index" in call, (rel, call)


@pytest.mark.parametrize(
    "rel",
    [
        ".claude/commands/sdd-done.md",
        ".agent/workflows/sdd-done.md",
        ".agents/skills/sdd-done/SKILL.md",
        ".claude/agents/qa-runner.md",
    ],
)
def test_new_red_gate_phrase(rel):
    assert "new red" in _text(rel).lower()


@pytest.mark.parametrize("rel", [".claude/agents/sdd-worker.md", f"{SUBAGENT}/sdd-worker.md"])
def test_worker_merge_gate_wording(rel):
    text = _text(rel)
    assert "cached" in text and "NEW red" in text and "never a suite" in text


@pytest.mark.parametrize("rel", [".claude/agents/sdd-coder.md", f"{SUBAGENT}/sdd-coder.md"])
def test_coder_task_tier_sentence(rel):
    assert "file-level mirror tests" in _text(rel)
