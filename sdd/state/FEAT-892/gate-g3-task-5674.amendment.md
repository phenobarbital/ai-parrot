# Spec amendment — G3 for TASK-5674 · status: ACCEPTED by the owner, 2026-11-16 (Q1-A, Q2-A, Q3-A, Q4-A, Q5 as recommended)

**Feature**: FEAT-892 `agent-memory-mixin` · **Releases**: TASK-5674 only · **Recorded as**: spec rev 0.8,
section "Gate amendment accepted for TASK-5674 — G3 runtime outcome adapter, verified-check schema,
attribution policy".

The accepted text is the spec section; this file keeps the reasoning and the alternatives that were not chosen. Rule numbers differ: the spec's E6 is this file's Q3-A, so E6–E12 here are E7–E13 there. Sources: spec §2 (C1–C10,
review admission order), `sdd/state/FEAT-571/spikes/s3-attribution/` (amendment, REPORT, metrics), and the
code delivered by TASK-5653..5673 on `feat-FEAT-892-agent-memory-mixin` at `19af004944`.

## What the gate asks for

TASK-5674 is blocked on: "concrete runtime outcome adapter and verified-check schema must be accepted;
generic tool return values are not a substitute". Rev 0.5 (C1–C10) already fixed the data shapes. Still
open, and decided below: how a tool execution becomes a `ReviewSignal`, what counts as a verified check,
and the attribution policy.

## Facts the proposal rests on

- `ReviewSignal` (`memory/dynamics/models.py:289`) already rejects a failure without `error_signature`, a
  non-failure with one, and `coder_engine` evidence without `passed_check_ids`. `cancelled` and
  `incomplete` can never review.
- `select_grade` (`memory/dynamics/grade.py:28`) returns AGAIN only when the signal's signature equals the
  normalized signature of the memory under review; success grades need `verified_recovery`,
  `correction_count > 0` or `first_attempt`.
- `EpisodicMemoryStore.review` (`memory/episodic/store.py:353`) compares against
  `episode.error_message or episode.error_type`, and always passes `attribution="cited"`.
- `record_tool_episode` (`store.py:583-585`) still reads `getattr(tool_result, "success", True)` and
  `getattr(tool_result, "status", "success")`. S3 lists exactly these defaults as untrusted.
- `ToolResult` (`tools/abstract.py:252`) defaults to `success=True`, `status="success"`. A tool that sets
  nothing looks successful.
- `ToolManager._observed` (`tools/manager.py:1737`) is the only place a tool body runs, after every guard.
  It already distinguishes returned / raised / cancelled for the FEAT-538 observer.
- `UnifiedMemoryManager.record_event` (`memory/unified/manager.py:217`) returns `ignored` for
  `kind="tool"` events today.
- BaseBot already binds the scope and a context exposure id in `conversation`, `ask` and `ask_stream`
  (`bots/base.py:841-910`, `:1334-1497`, `:2124-2197`). `ContextAssembler.assemble_candidates` already
  returns `delivered_refs` and `packed_digest`.
- The chat runtime has no check mechanism today: nothing in a tool call proves the task succeeded.
- S3 evidence is 50 synthetic cases, 0 real traces.

## Proposed decisions

- **E1 Adapter.** One pure function in `memory/agent_memory/attribution.py` turns one observed execution
  attempt into a signal: `build_tool_signal(attempt, *, scope, evidence_ref) -> ReviewSignal | None`.
  `source` is always `tool_runtime`. It is the only producer of `tool_runtime` signals. It reads the
  attempt record written by `_observed`, never the model's text and never tool arguments.
- **E2 Attempt record.** `_observed` captures, request-locally, for each body that actually ran:
  `tool_name`, `call_id`, `terminal` (`returned` | `raised` | `cancelled`), the exception class and message
  when raised, and the returned object. A guard denial or a body that never ran produces no record. The
  record is in-memory, scoped to the request ContextVar, and dropped at the end of the invocation.
- **E3 Outcome mapping.**

  | Observed | `outcome` | Review possible |
  |---|---|---|
  | Body never ran (guard denial, unknown tool) | no signal | no |
  | `CancelledError` | `cancelled` | no |
  | Body raised any other exception | `failure` | AGAIN only |
  | Returned a `ToolResult` that explicitly reports failure (E4) | `failure` | AGAIN only |
  | Returned anything else | `incomplete` | no |

  A normal return proves execution, not task success, so `tool_runtime` never emits `success` in this
  feature (see Q1).
- **E4 Explicit failure.** A returned `ToolResult` is a failure only when the tool set the field itself:
  `"success" in result.model_fields_set and result.success is False`, or `"status" in
  result.model_fields_set and result.status in {"error", "failed"}`. Field defaults and `getattr(...)`
  fallbacks are never read. A dict or other object with a `success` key is not evidence.
- **E5 Error signature.** `error_signature` is the error text only: `str(exc)` for a raised exception,
  `ToolResult.error` for an explicit failure, and the exception class name or the status when that text is
  empty. The adapter normalizes it as C2 requires and then cuts it to 200 characters, so the model's
  length check never rejects a long message. The tool name is not part of it, because `review` compares it with the episode's stored
  error message (see Q3).
- **E6 Attempt counting.** `first_attempt` is true when no earlier record in the same turn has the same
  `tool_name`. `correction_count` is the number of earlier `failure` records for that `tool_name` in the
  turn. Both are recorded on the signal for the audit trail; under E3 they cannot yet produce a grade.
- **E7 Verified-check schema.** A verified check is an identifier in `ReviewSignal.passed_check_ids`
  (existing C2 field, structural-ref pattern, at most 16) that a trusted adapter obtained from a check
  that ran and passed. For `coder_engine` the identifier comes from the engine's recorded review and
  validation receipts (M5, TASK-5675/5676). For `tool_runtime` there is no such producer in this feature,
  so `passed_check_ids` is always empty there. No new model, no `verified` boolean, no check id accepted
  from a tool argument, a model message or `ToolResult.metadata`.
- **E8 Exposure.** The exposure is minted once per invocation, after final packing, from the
  `delivered_refs` and `packed_digest` the assembler returned for the block actually placed in the model
  request. Its `attempt_id` is the turn id. It is stored as a durable manifest through the store
  (`cite`), and only the id is published with `bind_memory_exposure`. A candidate trimmed by packing is
  not in it. `PandasAgent.ask` mints none (F1). A provider failure or cancellation leaves the manifest
  unusable for review.
- **E9 Attribution policy.** `cited` is the only mode implemented by TASK-5674. A citation is valid when
  its `exposure_id` is the invocation's manifest, every ref is in that manifest, and the ref namespace
  equals the request scope; a failed check reveals nothing about other scopes. Citations travel in the
  structured channel and never appear in the answer text. `overlap` is not implemented here (see Q2).
- **E10 Routing.** `record_event` stops ignoring `kind="tool"`: for a `failure` signal with a valid
  citation it calls `EpisodicMemoryStore.review`; otherwise it returns `ignored` with a reason. It never
  creates an episode from a tool event. The FEAT-538 observer keeps running first and unchanged; memory
  capture is a second, request-local step that cannot alter the tool's result or exception.
- **E11 Evidence reference.** A `tool_runtime` signal's `evidence_ref` is the turn's
  `ChatStorageEvidenceRef` (C3, F7). A request without `user_id` or `session_id` cannot build one and
  earns no review.
- **E12 Not covered.** Success grades from the chat runtime, the overlap heuristic, the numeric U3 target,
  the real-trace re-run of S3, brain reviews (FEAT-889) and PostgreSQL/Redis review paths.

## Decisions the owner has to make

- **Q1 — Success evidence in the chat runtime.**
  - *A (recommended):* none in this feature. `tool_runtime` produces failure, cancelled or incomplete, so
    the chat runtime can only earn AGAIN. GOOD/HARD/EASY come from `coder_engine`, which has real checks.
    Cost: in chat, a memory that helped is never reinforced; only a memory that was cited and did not
    prevent the same error is penalized.
  - *B:* also accept a before/after signature pair as structural recovery: the same tool failed with
    signature S and a later attempt in the same turn returned without explicit failure. That would allow
    HARD/EASY. It treats a normal return as success, which E3 and S3 both reject, and it has no real-trace
    evidence behind it.
- **Q2 — Overlap heuristic.**
  - *A (recommended):* not implemented in TASK-5674. AC wording "overlap opt-in/capped" is satisfied by
    there being no way to turn it on. S3 measured false reinforcement 0.080 at cap 3 on synthetic data.
  - *B:* implement it behind a config flag, cap 3, Jaccard 0.3. This needs a new `AgentMemoryConfig`
    field, and `memory/agent_memory/models.py` and `memory/episodic/store.py` added to the task's files.
- **Q3 — Signatures longer than 200 characters.** `ReviewSignal` caps the signature at 200 characters but
  `select_grade` normalizes the episode's message without cutting it, so an error message longer than 200
  characters can never match and never earns AGAIN.
  - *A (recommended):* cut both sides to 200 characters in `select_grade`. Adds
    `memory/dynamics/grade.py` and `tests/memory/dynamics/test_core.py` to TASK-5674's files.
  - *B:* leave it. Long messages earn no review; documented as a limitation.
- **Q4 — `record_tool_episode` defaults.** It still decides success from `getattr` defaults
  (`store.py:583-585`). It is outside TASK-5674's files.
  - *A (recommended):* leave the method alone in this task and open a ledger issue. The agent path does
    not call it for tool events (E10).
  - *B:* add `memory/episodic/store.py` to the task and apply E4 there too.
- **Q5 — U3 numeric target.** Recommended: none is set. The 0.2 / 8.0 thresholds stay provisional and
  versioned, no promotion is automatic, and re-running S3 on real traces stays a prerequisite before U1/U3
  are final. Accepting this amendment does not accept the S3 numbers as field precision.

## If accepted — release steps

1. Add the accepted section to `sdd/specs/agent-memory-mixin.spec.md` §2, update the G3 row of the gate
   table and §3 M3, add revision row 0.8.
2. TASK-5674: replace the G3 precondition line with "satisfied (spec rev 0.8)", restate the FILL IN items
   against E1–E11, extend the file table per Q2/Q3/Q4, set **Status** to `pending`.
3. Validation Contract: no new path. `tests/memory/dynamics/test_attribution.py` and
   `tests/memory/dynamics/test_core.py` (touched only under Q3-A) are already listed.
4. Regenerate the index test contract with `parrot sdd tests contract`, set TASK-5674 to `pending` in
   `sdd/tasks/index/agent-memory-mixin.json`, and update `planning_notes`.
5. Commit as `sdd: accept G3 amendment for TASK-5674 (FEAT-892 rev 0.8)`.

## Test cases the amendment implies for `test_attribution.py`

- A tool that returns a default `ToolResult` produces `incomplete` and no review.
- A tool that sets `success=False` explicitly, and one that raises, each produce `failure` with the
  normalized signature; a cited episode with the same signature receives AGAIN exactly once.
- A guard denial and a cancelled call produce no review and leave the FEAT-538 observer's records intact.
- A citation of a ref trimmed by packing, of another scope, or against a stale exposure id is rejected
  without revealing content.
- Two concurrent invocations on one `ToolManager` never see each other's attempt records.
- No citation text appears in the stored or returned answer.
