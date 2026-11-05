# SDD execution optimization — operation and rollout

This is the FEAT-584 operational record. It separates offline contract verification from a real-host receipt and pilot result. It does not claim that a host compacted a conversation, resumed review, or reduced field cost.

## Capability and configuration matrix

| Capability | Contract | Default | Rollout state |
| --- | --- | --- | --- |
| Bounded inspection | `source_inspect_batch`: 1–8 read-only operations, instance concurrency ≤4, 24 KiB response. | Explicit call | Available; measure in pilot. |
| Purposeful reads | `coder_task_context` and `coder_delivery_report` are bounded and read-only. | Explicit call | Available; retain unknown evidence. |
| Compact views | `coder_plan`, `coder_wait`, and `coder_status` support `response_mode="compact"`. | `full` | Opt-in only. |
| Background validation | `coder_run_validation` emits a handle; `coder_bg_status` reads registered authority. | Explicit call | Available. |
| Checkpoint boundary | One durable receipt per checkpoint/context. | Explicit boundary | Policy available. |
| Host compaction | Requires a concrete receipt-reading driver and real host evidence. | `auto` policy; `off` rollback | Not enabled by this record. |

`auto` is not a capability assertion. `off` records `skipped` and is the rollback/control setting. Unsupported contexts must return `unsupported`; missing or late evidence is never completion.

## Inspection and compact-view examples

Batch only operands that are already independent. The response preserves IDs and partial failures; it is not a transactional snapshot.

```json
{
  "requests": [
    {"id": "state", "kind": "git_status"},
    {"id": "toolkit", "kind": "read", "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py", "start_line": 51, "end_line": 90},
    {"id": "waiters", "kind": "search", "paths": ["packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder"], "text": "coder_wait", "max_matches": 20}
  ],
  "concurrency": 4,
  "max_output_bytes": 24576
}
```

```text
coder_plan(feature, worktree, execution_id, response_mode="compact")
coder_wait(job_id, timeout_seconds=90, response_mode="compact")
coder_read_artifact(execution_id, artifact_id, offset=0, limit=8192)
```

The server caps waits at 300 seconds. Do not issue another MCP call in the same message as `coder_wait`: the stdio server is sequential. Compact output does not relax routing, ownership, coverage, fidelity, or required overflow-page recovery.

## Background authority, receipts and recovery

`coder_bg_status` accepts only opaque handles emitted by `coder_run_chunk`, `coder_prepare_native`, or `coder_run_validation`; never a PID, path, command, or inferred process. `finished` means a terminal receipt exists, not that validation passed: inspect outcome and exit code. After loss of authority, `unknown` and a null exit code block cleanup/checkpoint rather than recreating success from an empty log. Use a stable request id and explicit timeout for protected validation; logs are bounded evidence, not authority.

## Deterministic finalization and checkpoint lifecycle

The engine settles admitted work before `coder_end_execution`. The finalizer validates task identity, expected SHA, scope, validation references, and review evidence; it never manufactures a review decision. The boundary is fixed:

```text
settle execution → persist checkpoint → request at most one supported between-turn compaction → record actual receipt → reload/validate checkpoint → start fresh independent reviewer
```

An `in_progress` receipt requires reconciliation, not retry. A stale checkpoint/context receipt blocks handoff.

## Compaction outcomes and verified host integration

`PhaseBoundaryDriver` is host-specific. The portable coordinator asks `supports(context_id)`, invokes a supplied driver once, and validates the returned `CompactionReceipt` identity. It does not call a host compaction API itself.

TASK-3555 established that `compaction_status(worktree_root)` is per-worktree installation diagnostics, not a capability handshake; there is no Python-side MCP/Bash route to `$.session.compact()`; a synthetic direct Jev-library run is not host smoke; and subagent/fork targeting remains `unsupported_context` pending Q1b runtime proof. Parent compaction is never child evidence.

No completed host receipt is recorded here. TASK-3577 is the concrete driver dependency, and a maintainer-operated live-host pilot remains necessary for AC11.

## Reproducible benchmark environment and results

The post-fix baseline must correlate attempts, background spans, and fallback autoimplementation by identity. Do not sum overlap, treat partial messages as requests, or associate duration with the next temporal merge. Report p50/p95 time to acceptance, request count, observed context bytes/tokens, compaction elapsed time, failure rate, quality findings, exclusions, and cohort definition.

No controlled matched pilot or real-host smoke was run for this document. Accordingly, there are no sample size, p50/p95, quality, failure, request, or compaction-cost values to publish. Offline tests are contract evidence, not pilot measurements.

## Matched pilot protocol and observations

Run at least ten comparable task pairs, or an isolated replay with an equivalent fixture and acceptance rubric. Freeze host/plugin versions, feature revision, roster, validation selection, and rules before collection. Retain redacted logs and durable checkpoint/receipt, validation, and review references for every pair. Compare `off` to the candidate configuration; retain unsupported and failed runs.

Activate a default only with at least 20% fewer requests and at least 15% lower median time to acceptance, with no agreed quality-rubric deterioration. Include recovery/compaction cost. Fewer than ten pairs, missing receipts, unmatched workloads, or quality regression keep opt-in and Q2 pending. There are no observations yet.

## Acceptance matrix AC1–AC23

| Criteria | Evidence | Status |
| --- | --- | --- |
| AC1–AC4 | R1 implementation and bounded-source tests | Offline contract evidence; pilot pending. |
| AC5 | response-mode schemas and worker regression | Offline; `full` remains default. |
| AC6–AC10 | evidence, finalizer, checkpoint tests | Offline contract evidence. |
| AC11 | real supported-host receipt and review continuation | **Pending; no exception asserted.** |
| AC12–AC13 | phase-boundary policy and capability record | Offline policy evidence. |
| AC14 | execution profiler tests/results | Offline; controlled baseline pending. |
| AC15 | offline suites plus versioned host smoke | **Pending; no host smoke exists.** |
| AC16 | controlled matched pilot report | **Pending; no pilot values exist.** |
| AC17–AC21 | worker/twin and background regressions | Offline contract evidence. |
| AC22 | post-fix profiler/report | Offline; pilot baseline pending. |
| AC23 | hook regression/benchmark | Offline; rollout remains disabled absent R9 target evidence. |

Offline evidence is not an acceptance waiver; the per-spec index remains authoritative for task validation.

## Rollout decision and rollback

Decision: **do not activate a general default**. Keep compact views opt-in, preserve API `full` defaults, and retain `pre_review_compaction="off"` for rollback/control. Do not claim field savings.

Reconsider only after TASK-3577 settles, a supported host produces one versioned receipt with fresh-review continuation from a validated checkpoint, and the matched pilot meets request/time/quality thresholds. Otherwise retain `off`, preserve evidence, and leave Q2 pending.
