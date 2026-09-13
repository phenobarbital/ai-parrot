"""Prompt-contract tests for the sdd-worker Orchestrator Loop (FEAT-549, TASK-3124)."""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

TOOLS = [
    f"mcp__parrot-sdd-coder__coder_{n}"
    for n in ("plan", "run_chunk", "prepare_native", "merge", "wait", "status", "cleanup")
]


def _repo_agents_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".claude" / "agents"
        if candidate.is_dir():
            return candidate
    raise AssertionError("`.claude/agents/` not found relative to this test file")


def test_worker_prompt_has_orchestrator_loop():
    body = load_subagent_definition("sdd-worker")
    assert "## Orchestrator Loop (FEAT-549)" in body
    assert "## Fallback: Sequential Loop" in body
    assert "writer_generate" not in body
    assert "Seats:" in body
    assert "Seat: " in body


def test_worker_prompt_tools_list_mcp_names():
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    tools_line = next(line for line in text.splitlines() if line.startswith("tools:"))
    assert all(tool in tools_line for tool in TOOLS)
    assert "Agent" in tools_line


def test_worker_prompt_no_delegation_contract_step():
    body = load_subagent_definition("sdd-worker")
    assert "writer_apply" not in body
    assert "parrot-targeted-writer" not in body
    assert "Delegation Contract" not in body
    assert "### b2)" not in body


def test_worker_prompt_still_has_per_spec_index_wording():
    """Regression guard: the orchestrator rewrite must not drop the FEAT-145
    wording `test_worker_prompt_has_per_spec_index_instructions` depends on."""
    body = load_subagent_definition("sdd-worker")
    assert "FEAT-145" in body
    assert "per-spec index" in body


def test_worker_prompt_has_new_stop_conditions():
    body = load_subagent_definition("sdd-worker")
    stop_section = body.split("## STOP Conditions", 1)[1]
    assert "roster_empty" in stop_section
    assert "dependency_cycle" in stop_section
    assert "merge_conflict" in stop_section


def test_orchestrator_loop_describes_background_native_agents():
    """Regression (FEAT-555 incident): the loop must tell the orchestrator that a native `Agent`
    runs in the background, that its result arrives as a notification, that it must never be
    re-dispatched, and that `coder_cleanup` waits for every native task to go through `coder_merge`."""
    body = load_subagent_definition("sdd-worker")
    loop = body.split("\n## Orchestrator Loop (FEAT-549)", 1)[1].split("\n## Fallback: Sequential Loop", 1)[0]
    assert "background" in loop
    assert "notification" in loop
    assert "Never call `Agent` again for the same task" in loop
    assert "branch_not_merged" in loop
    assert "every native task of the chunk has gone through `coder_merge`" in loop
