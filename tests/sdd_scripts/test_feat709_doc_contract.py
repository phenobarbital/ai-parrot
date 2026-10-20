"""FEAT-709: agent prompts and docs describe run_validation, the gate and the same-seat repair."""

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
VALIDATION_RUNNER_FILES = [
    ".claude/agents/sdd-coder.md",
    f"{SUBAGENT}/sdd-coder.md",
    ".claude/agents/sdd-worker.md",
    f"{SUBAGENT}/sdd-worker.md",
    ".claude/agents/qa-runner.md",
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
    # The phrase was updated in FEAT-709
    text = _text(rel)
    assert "verdict" in text and ("engine re-runs" in text or "same seat" in text)


# FEAT-709 specific tests


@pytest.mark.parametrize("rel", [".claude/agents/sdd-coder.md", f"{SUBAGENT}/sdd-coder.md"])
def test_coder_validation_instructions(rel):
    text = _text(rel)
    assert "run_validation" in text
    assert "verdict" in text
    assert "engine re-runs" in text


@pytest.mark.parametrize("rel", [".claude/agents/sdd-worker.md", f"{SUBAGENT}/sdd-worker.md"])
def test_worker_validation_failed_outcome(rel):
    text = _text(rel)
    assert "validation_failed" in text
    assert "same seat" in text.lower()
    assert "verdict" in text


@pytest.mark.parametrize("rel", [".claude/agents/qa-runner.md"])
def test_qa_non_pytest_runners(rel):
    text = _text(rel)
    assert "non-pytest runners" in text.lower()
    assert "gate" in text.lower()
    assert "unknown" in text.lower()


@pytest.mark.parametrize("rel", [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md"])
def test_sdd_done_runner_rows(rel):
    text = _text(rel)
    assert "<runner>:<distribution>" in text
    assert "n/a" in text and "cache" in text and "baseline" in text


@pytest.mark.parametrize("rel", [".agents/skills/sdd-done/SKILL.md"])
def test_skill_sdd_done_runner_rows(rel):
    text = _text(rel)
    assert "<runner>:<distribution>" in text
    assert "n/a" in text


def test_validation_runners_doc_exists():
    assert (ROOT / "docs/dev_loop/validation-runners.md").exists()


@pytest.mark.parametrize("rel", VALIDATION_RUNNER_FILES)
def test_mentions_run_validation_tool(rel):
    # At least some of the files should mention the run_validation tool or validation concepts
    text = _text(rel)
    # This is a weak test but ensures the topic is covered somewhere
    assert "run_validation" in text or "run validation" in text.lower() or "verdict" in text
