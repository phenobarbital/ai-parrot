"""Prompt-contract tests for the sdd-worker Orchestrator Loop (FEAT-549, TASK-3124)."""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition

TOOLS = [
    f"mcp__parrot-sdd-coder__coder_{n}"
    for n in ("plan", "run_chunk", "prepare_native", "merge", "wait", "status", "cleanup")
]


def _orchestrator_loop(body: str) -> str:
    """Return just the `## Orchestrator Loop (FEAT-549)` section of the prompt.

    The absence assertions below are scoped to this section rather than to the
    whole document. FEAT-562 Module 4 restored FEAT-543's `### b2) Delegated
    implementation` step to the "## Fallback: Sequential Loop" — the branch
    where this agent implements a task ITSELF, and where delegating patch
    drafting to `parrot-targeted-writer` (with mandatory hunk review) is the
    point. TASK-3124 had asserted those strings were absent from the entire
    body, which silently made the FEAT-543 contract unrestorable; what that
    test actually means to guard is that the ORCHESTRATOR path dispatches
    `sdd-coder` seats and never the writer route. Scoping preserves that
    guarantee without re-breaking `test_sdd_contracts.py`.
    """
    return body.split("\n## Orchestrator Loop (FEAT-549)", 1)[1].split("\n## Fallback: Sequential Loop", 1)[0]


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
    assert "writer_generate" not in _orchestrator_loop(body)
    assert "Seats:" in body
    assert "Seat: " in body


def test_worker_prompt_tools_list_mcp_names():
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    tools_line = next(line for line in text.splitlines() if line.startswith("tools:"))
    assert all(tool in tools_line for tool in TOOLS)
    assert "Agent" in tools_line


def test_worker_prompt_no_delegation_contract_step_in_the_orchestrator_loop():
    """The dispatch path uses `sdd-coder` seats — never the targeted writer.

    Scoped to the Orchestrator Loop on purpose: the Fallback loop legitimately
    carries `### b2)` again (FEAT-562 Module 4 / FEAT-543), which
    `test_sdd_contracts.py` asserts. See `_orchestrator_loop`.
    """
    loop = _orchestrator_loop(load_subagent_definition("sdd-worker"))
    assert "writer_apply" not in loop
    assert "parrot-targeted-writer" not in loop
    assert "Delegation Contract" not in loop
    assert "### b2)" not in loop


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


def test_worker_prompt_preserves_read_only_ledger_findings():
    """Shared-ledger failures must be reported without bypassing the sandbox."""
    body = load_subagent_definition("sdd-worker")
    assert "shared ledger is read-only" in body
    assert "worktree-local" in body


def test_orchestrator_loop_describes_background_native_agents():
    """Regression (FEAT-555 incident): the loop must tell the orchestrator that a native `Agent`
    runs in the background, that its result arrives as a notification, that it must never be
    re-dispatched, and that `coder_cleanup` waits for every native task to go through `coder_merge`."""
    loop = _orchestrator_loop(load_subagent_definition("sdd-worker"))
    assert "background" in loop
    assert "notification" in loop
    assert "Never call `Agent` again for the same task" in loop
    assert "branch_not_merged" in loop
    assert "every native task of the chunk has gone through `coder_merge`" in loop


def test_worker_prompt_routes_retry_native_handoff():
    """FEAT-588 R4: the orchestrator must know what to do with `retry_native`."""
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    assert "`retry_native`" in text
    # AC-1: reservation comes from `native_retry`, not a second `coder_prepare_native` call.
    assert "native_retry" in text
    assert "do NOT call `coder_prepare_native` again" in text
    # AC-1: dispatched via `Agent`, same as a planned native coder, and merged on notification.
    assert 'Agent(subagent_type="sdd-coder"' in text
    assert "never call `Agent` twice for the same task" in text
    assert "`coder_merge(task_id)` on its notification" in text
    # AC-1: attributed as a retry (attempt 2) with backend `native` and its own `attempt_uid`,
    # never conflated with a planned native attempt.
    assert "backend `native`" in text
    assert "native_retry.attempt_uid" in text
    assert "record it as a RETRY (attempt 2), never as a planned native" in text
    assert "the two stay separable" in text


def _fallback_loop(body: str) -> str:
    """Return just the `## Fallback: Sequential Loop` section (up to `## Completion`)."""
    return body.split("\n## Fallback: Sequential Loop", 1)[1].split("\n## Completion", 1)[0]


def _completion_section(body: str) -> str:
    """Return just the `## Completion` section (to end of file)."""
    return body.split("\n## Completion", 1)[1]


def test_worker_prompt_execution_optimization_tools_invoked_in_loop():
    """FEAT-584 M6: the FEAT-549 allow-list gained `coder_task_context`, `coder_delivery_report`,
    `coder_bg_status`, `coder_run_validation` and `source_inspect_batch` over TASK-3556/3561/3562/
    3565/3566/3568, but those ripple patches only ever touched the frontmatter `tools:` line
    (never the prompt body) -- the tools must actually be invoked in the Orchestrator Loop, not
    merely declared as available."""
    loop = _orchestrator_loop(load_subagent_definition("sdd-worker"))
    assert "## Execution optimization (FEAT-584)" in loop
    for tool in (
        "coder_task_context",
        "coder_delivery_report",
        "source_inspect_batch",
        "coder_bg_status",
        "coder_run_validation",
        "finalize_task",
    ):
        assert tool in loop, f"{tool!r} is allow-listed but never invoked in the Orchestrator Loop"


def test_worker_prompt_frontmatter_lists_bounded_source_tool():
    """R1: `source_inspect_batch` ships on the independent `parrot-bounded-source` MCP server
    (not `parrot-sdd-coder`), so it needs its own frontmatter allow-list entry. Checked against
    the installed repo copy, mirroring `test_worker_prompt_tools_list_mcp_names` above."""
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    tools_line = next(line for line in text.splitlines() if line.startswith("tools:"))
    assert "mcp__parrot-bounded-source__source_inspect_batch" in tools_line


def test_worker_prompt_boundary_sequence_is_checkpoint_then_compaction_then_outcome_then_revalidate_then_reviewer():
    """R5/R6/R7: the development-to-review boundary is a fixed order -- persist a checkpoint,
    request (at most) one between-turn compaction, record its actual outcome, reload/validate
    the checkpoint, THEN start a fresh reviewer -- never just these words present anywhere in
    the packaged prompt in any order."""
    body = load_subagent_definition("sdd-worker")
    markers = [
        "persist checkpoint",
        "request one supported between-turn compaction",
        "record actual outcome",
        "reload/validate checkpoint",
        "start a fresh independent reviewer",
    ]
    positions = [body.index(marker) for marker in markers]
    assert positions == sorted(positions), "checkpoint -> compaction -> outcome -> revalidate -> reviewer order broken"


def test_worker_prompt_fallback_does_not_assume_engine():
    """The Fallback loop (no `parrot-sdd-coder` server) must never assume an engine-only
    execution_id/settlement exists: `coder_run_validation`, `coder_end_execution` and
    `review_checkpoint prepare` all require a durably-closed engine execution that the
    Fallback loop -- which never calls `coder_begin_execution` -- never produces."""
    fallback = _fallback_loop(load_subagent_definition("sdd-worker"))
    assert "coder_run_validation" not in fallback
    assert "coder_end_execution" not in fallback
    assert "review_checkpoint prepare" not in fallback


def test_worker_prompt_completion_has_explicit_no_engine_variant():
    """M6 Interface Skeleton requires the sequence to 'specify a variant without the engine':
    the Completion boundary must explicitly branch for hosts/contexts where checkpoint/
    compaction cannot run, rather than silently assuming the MCP engine settled."""
    completion = _completion_section(load_subagent_definition("sdd-worker"))
    assert "No-engine variant" in completion
    assert "unsupported_host" in completion
    assert "review_checkpoint validate" in completion


def test_worker_prompt_never_invokes_compact_via_bash():
    """R6: `/compact` must never be run as a Bash command, and a native child's context is
    never assumed compacted just because the parent was."""
    body = load_subagent_definition("sdd-worker")
    assert "Never invoke `/compact` through Bash" in body
    assert "native child" in body


def test_worker_prompt_uses_finalize_task_not_manual_jq_close_in_orchestrator_loop():
    """R4: the Orchestrator Loop's own merged-task close must route through the deterministic
    `scripts.sdd.finalize_task` CLI instead of delegating to the Fallback loop's manual
    Edit/Write/jq/mv dance -- the two used to describe different, contradictory closing
    mechanics for the same `merged` outcome."""
    loop = _orchestrator_loop(load_subagent_definition("sdd-worker"))
    assert "python -m scripts.sdd.finalize_task" in loop
    assert "manual Edit/Write/jq/mv dance" in loop
    assert "step (g) of the Fallback loop for this task" not in loop


def test_worker_prompt_frontmatter_lists_ledger_filing_tools():
    """Deferred findings are filed through the unsandboxed `wikitoolkit` MCP server when present,
    so the ledger tools the prompt names must be allow-listed in the installed repo copy."""
    text = (_repo_agents_dir() / "sdd-worker.md").read_text(encoding="utf-8")
    tools_line = next(line for line in text.splitlines() if line.startswith("tools:"))
    assert "mcp__wikitoolkit__ledger_open" in tools_line
    assert "mcp__wikitoolkit__ledger_context" in tools_line
    assert "mcp__wikitoolkit__ledger_open" in load_subagent_definition("sdd-worker")
