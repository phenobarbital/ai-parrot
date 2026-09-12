"""Codex and agy prompt builders carry the conventions block (FEAT-553, spec AC-5)."""

from __future__ import annotations

from parrot.flows.conventions import CONVENTIONS_PREAMBLE
from parrot.flows.dev_loop.dispatchers.codex import CodexCodeDispatcher
from parrot.flows.dev_loop.dispatchers.google_coding import GoogleCodingDispatcher
from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput, TaskScopedBrief
from parrot.flows.dev_loop.models.codex import CodexCodeDispatchProfile
from parrot.flows.dev_loop.models.google_coding import GoogleCodingDispatchProfile


def _brief() -> TaskScopedBrief:
    research = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-553",
        branch_name="feat-553-x",
        worktree_path="/tmp/wt",
        log_excerpts=[],
    )
    return TaskScopedBrief(research=research, task_id="TASK-3179")


def test_codex_prompt_carries_the_conventions(tmp_path):
    d = CodexCodeDispatcher(redis_url="redis://localhost/0", max_concurrent=1, stream_ttl_seconds=60)
    prompt = d._build_codex_prompt(
        CodexCodeDispatchProfile(subagent="sdd-coder"), _brief(), DevelopmentOutput, cwd=str(tmp_path)
    )
    assert CONVENTIONS_PREAMBLE in prompt
    # codex._build_prompt's output starts with "Input brief:" (verified against the current
    # source; the task blueprint's "TASK BRIEF" anchor only matches google_coding._build_prompt).
    assert prompt.index("Subagent instructions:") < prompt.index(CONVENTIONS_PREAMBLE) < prompt.index("Input brief:")


def test_agy_prompt_carries_the_conventions(tmp_path):
    d = GoogleCodingDispatcher(redis_url="redis://localhost/0", max_concurrent=1, stream_ttl_seconds=60)
    prompt = d._build_agy_prompt(
        GoogleCodingDispatchProfile(subagent="sdd-coder"), _brief(), DevelopmentOutput, cwd=str(tmp_path)
    )
    assert CONVENTIONS_PREAMBLE in prompt
    assert prompt.index("Subagent instructions:") < prompt.index(CONVENTIONS_PREAMBLE) < prompt.index("TASK BRIEF")
