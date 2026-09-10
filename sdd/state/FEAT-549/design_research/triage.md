# Design research triage — FEAT-549 sdd-worker-subagents

Model: `gpt-5.6-luna` · codex-cli 0.154.0 · reasoning high · 2026-09-10 19:58:08 → 20:03:13 UTC · exit 0
Brief: `brief.md` (accepted brainstorm sections + 20 code-context paths; no spec text, no author reasoning)
Path check: 28 distinct `affected_paths`, all inside the repository and present (`test -e`).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Introduce task-attempt worktree primitives (architecture, high) | CONFIRM | Verified `DevAgentPool.run_wave` passes `cwd=cwd_for(worker.worker_id)` (agent_pool.py:337, :358) and its retry dispatches into the retry worker's cwd; with per-task worktrees a retry would land in another task's tree. Engine dispatches directly per attempt with a fresh `…-a<attempt>` sub-worktree; FEAT-323 modules untouched. | spec §2 step 2, §3 M4 `_run_attempt`, §6 Does NOT Exist, §7, AC-20 |
| S2 | Reservation, idempotency, crash recovery (risk, high) | CONFIRM (partial) | `task_already_running` guard + write-only job journal `<worktree>/.sdd-coder/jobs/<job_id>.json`. Full job persistence rejected: the per-spec index and git branches are the reconciliation source (brainstorm Q6: orphans listed, never auto-merged). | §2 step 5, §3 M4, AC-21 |
| S3 | Stable wave ordering before rotating seats (risk, medium) | CONFIRM | `TaskScheduler.next_wave()` documents "no particular order" (task_scheduler.py:176-192). Engine sorts by task id before chunking; determinism test added. | §3 M4 `plan`, §4, §6 |
| S4 | Background jobs at the transport boundary (architecture, high) | CONFIRM | `StdioMCPServer.start()` awaits `_handle_request` inline (local_server.py:63). `coder_run_chunk` returns right after validation; sub-worktree creation and dispatch run inside the asyncio task. | §2 steps 2/5, §3 M4, §7, AC-21 |
| S5 | Reject dirty/untracked coder worktrees before merge (risk, high) | CONFIRM | New `dirty_task_worktree` precondition in `_consolidate` (`git status --porcelain` must be empty); fidelity stays on committed diff. | §2 step 4, §3 M4, AC-22 |
| S6 | Explicit Pydantic arg/result models per tool (api, medium) | CONFIRM | `adapter.py:79` calls `tool._execute(**arguments)` without validation; `_pre_execute` (toolkit.py:455) is the hook `OptimizationToolkitBase` uses. `arg_models` + `_pre_execute` added to `SddCoderToolkit` (core re-implementation; core cannot import parrot_tools). | §2 Data Models, §3 M5, AC-23 |
| S7 | Separate roster seats from `DevAgentSpec` (architecture, medium) | CONFIRM (already largely so) | `RosterSeat` was already a distinct model; the real gap was every dispatch profile defaulting `subagent="sdd-worker"` — the engine now forces `"sdd-coder"` via `model_copy`. | §3 M4, AC-24 |
| S8 | First-class per-attempt telemetry record (risk, medium) | CONFIRM | Usage is only published as a `dispatch.completed` event (llm.py:373, `_completion_usage_payload` :585) reaching `host.apply(action)` (_shared.py:92-117). `AttemptTelemetryCollector` (duck-typed session host) captures it per attempt. | §3 M4, §6, §7 |
| S9 | Gemini tool-call wire-format regression test (testing, medium) | CONFIRM | Multi-turn synthetic test added; asserts base dispatcher emits no `extra_content`. | §4 |
| S10 | Test native Haiku through the same merge contract (testing, medium) | CONFIRM | Already planned; extended with dirty-status/fidelity cases. | §4 |
| S11 | Move sync index reads off the async path (risk, medium) | CONFIRM | `TaskScheduler.from_index_file` is sync; wrapped in `asyncio.to_thread`. | §3 M4 `plan`, §7 |
| S12 | Wire probe/cleanup to server lifecycle (risk, medium) | CONFIRM (probe) / ESCALATE (close) | `auto_open` fires on the first tool call (toolkit.py:169-172); `StdioMCPServer.stop()` only flips `_running` (local_server.py:80-82). Probe-on-first-call accepted (`coder_plan` is always first). Adding `_open`/`_close` hooks to `parrot/mcp/` is a shared-code decision for the user. | §3 M4/M5, §7, §8 Q4 |

Summary: 12 confirmed (2 partial) · 0 rejected · 1 escalated (S12 shutdown half → §8 Q4).

Note on the first attempt (`skipped-*/`): the probe hung on an open stdin (`codex exec` prints "Reading additional input from stdin..." without a TTY) and timed out at 120 s; fixed in `/sdd-spec` §3b.1 with `< /dev/null` (commit 7ce31c9ef).
