# TASK-2329: Wire `run_flow` to the faithful aggregator and enrich `FlowContext`

**Feature**: FEAT-447 — AgentsFlow Result Fidelity
**Spec**: `sdd/specs/agentsflow-result-fidelity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2328
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec (§3). TASK-2328 made `_aggregate_result`
*able* to produce a faithful `FlowResult`; this task actually feeds it the
data and closes the loop on `FlowContext`.

Two wirings:

1. **Aggregator call site** (`flow/flow.py:1926`) — pass `ctx=ctx`,
   `run_started_at=run_started_at`, `skipped=skipped`. All three locals
   already exist in `run_flow` (`flow/flow.py:1430,1436`) and are simply not
   forwarded.
2. **`FlowContext` enrichment** — `run_flow` calls
   `ctx.mark_completed(nid, result=event.result)` (`flow/flow.py:1881`),
   ignoring the `response=` and `metadata=` parameters that
   `mark_completed` already accepts (`core/context.py:181-182`) and already
   documents as populated (`core/context.py:193-194`). So `ctx.responses`
   (`core/context.py:75`) and `ctx.node_metadata` (`core/context.py:78`) stay
   empty for every AgentsFlow run, while `AgentCrew` fills them
   (`crew/crew.py:1964`). A `FlowContext` inspected after a run — including a
   checkpointed and resumed one — should carry the same fidelity as the
   `FlowResult`.

---

## Scope

- At the `_aggregate_result` call site (`flow/flow.py:1926`), pass the three
  new keyword arguments: `ctx=ctx`, `run_started_at=run_started_at`,
  `skipped=skipped`.
- At `ctx.mark_completed` (`flow/flow.py:1881`), also pass `response=` —
  the envelope from `event.result` — so `ctx.responses` is populated.
- Store each node's built `NodeExecutionInfo` into `ctx.node_metadata`.
- Verify the checkpoint round-trip still works with a non-empty
  `ctx.node_metadata` (see Gotchas — this is the main risk of the task).
- Add the 3 integration tests below.

**NOT in scope**:
- Any change to `_aggregate_result`'s internals — that was TASK-2328.
- Any change to `FlowContext`'s schema. `responses` and `node_metadata`
  already exist and are already typed; you are only filling them.
- Changing what `ctx.mark_completed` stores or its signature.
- The crew/flow parity contract test — that is TASK-2330.
- Deciding whether `FlowResult.responses` should hold unwrapped
  `AgentResponse` objects instead of envelopes. That is an OPEN question
  (spec §8); status quo (envelopes) is the default here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | Pass new kwargs at `:1926`; enrich `mark_completed` at `:1881`; fill `ctx.node_metadata` |
| `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` | MODIFY | Add the 3 integration tests below |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ee44c175d` on 2026-08-22. TASK-2326 and TASK-2328
> will have shifted BOTH files — re-`grep -n` every anchor before using it.

### Verified Imports

```python
# already imported in packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:39
from ..core.result import build_node_metadata
# FlowResult / NodeExecutionInfo / FlowContext: CHECK the existing import
# block in that file before adding anything — most are already there.
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                        # line 217
    def _aggregate_result(                                 # line 955
        self, nodes, results, errors, completed, failed,
        edges=None, durations=None,
        *, ctx=None, run_started_at=None, skipped=None,    # ← added by TASK-2328
    ) -> FlowResult: ...

    async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult: ...  # line 1059
        # completed: set[str] = set(ctx.completed_tasks)   @1428
        # failed:    set[str] = set()                      @1429
        # skipped:   set[str] = set()                      @1430  ← FORWARD THIS
        # results:   dict     = dict(ctx.results)          @1431
        # errors:    dict     = {}                         @1432
        # loop = asyncio.get_running_loop()                @1434
        # run_started_at = loop.time()                     @1436  ← FORWARD THIS
        # started_at / durations                           @1436-1437
        # durations[nid] = loop.time() - started_at.get(nid, run_started_at)  @1840
        # ctx.mark_failed(nid, event.error)                @1866
        # results[nid] = event.result                      @1879
        # completed.add(nid)                               @1880
        # ctx.mark_completed(nid, result=event.result)     @1881  ← ADD response=
        # self._aggregate_result(                          @1926  ← ADD 3 kwargs
        #     nodes, results, errors, completed, failed,
        #     edges=edges if explicit_mode else None,
        #     durations=durations,
        # )
        # self._notify_node_event("flow_completed", ...)   @1929-1935
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/context.py
@dataclass
class FlowContext:                                         # line 55
    initial_task: str                                      # line 71
    results: Dict[str, Any]                                # line 72
    responses: Dict[str, Any]                              # line 75  ← FILL THIS
    node_metadata: Dict[str, NodeExecutionInfo]            # line 78  ← FILL THIS
    completion_order: List[str]                            # line 81
    errors: Dict[str, Exception]                           # line 84
    active_tasks: Set[str]                                 # line 87
    completed_tasks: Set[str]                              # line 90
    shared_data: Dict[str, Any]                            # line 93

    def mark_completed(                                    # line 177
        self,
        node_id: str,
        result: Any = None,
        response: Any = None,          # line 181  ← ALREADY EXISTS, unused by flow
        metadata: Optional[NodeExecutionInfo] = None,      # line 182  ← ditto
    ) -> None: ...
        # completed_tasks.add / completion_order.append    @196-197
        # if result is not None:  self.results[node_id]    @199-200
        # if response is not None: self.responses[node_id] @201-202
```

```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:321-325
# What event.result IS — the envelope you pass as response=:
{"response": <AgentResponse>, "output": <Any>, "execution_time": <float>, "prompt": <str>}
```

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — REFERENCE, DO NOT EDIT
context.mark_completed(agent_id, result=result, response=response)   # @1964
```

### Does NOT Exist

- ~~`AgentsFlow._build_result`~~ — it is `_aggregate_result` (`flow/flow.py:955`).
- ~~`FlowContext.add_response()` / `.set_metadata()`~~ — no such methods.
  Use `mark_completed(response=..., metadata=...)` (`core/context.py:177`).
- ~~`FlowContext.execution_log` / `.total_time` / `.metadata`~~ — not fields.
  The real field list is `core/context.py:71-111`.
- ~~`ctx.mark_completed` appending to `completion_order` only on success~~ —
  correct, and `mark_failed` does NOT append. TASK-2328 already handles the
  residue; do not "fix" it here.
- ~~A `skipped` parameter on `mark_completed`~~ — does not exist. Skipped IDs
  reach `FlowResult` only via `_aggregate_result(skipped=...)` → `metadata["skipped"]`.

---

## Implementation Notes

### Key Constraints

- Keep the change surgical: three kwargs at one call site, one extra kwarg at
  another, plus the `node_metadata` write. Do not refactor `run_flow`.
- `event.result` is the envelope. Pass it as `response=` verbatim — do NOT
  pre-unwrap it. Consumers read scalars through `FlowResult.node_results`,
  which TASK-2327 made envelope-aware.
- Additive only (spec G6 / AC11): no signature loses a parameter, no field is
  retyped.
- Use `self.logger` — never `print`.

### Known Risks / Gotchas

- **Checkpoint serialisation is the main risk of this task.** Populating
  `ctx.node_metadata` puts `NodeExecutionInfo` dataclasses into a context that
  `FlowContext.to_snapshot()` serialises. Run
  `pytest packages/ai-parrot/tests/flows/checkpoint/ -v` and, if the snapshot
  path needs plain dicts, store via `NodeExecutionInfo.to_dict()`
  (`core/result.py:324`) — but check the declared field type first
  (`core/context.py:78` says `Dict[str, NodeExecutionInfo]`), and prefer
  fixing the snapshot path over violating the declared type.
- **Coordinate with FEAT-399** (`agentsflow-state-checkpointing`, worktree
  `.claude/worktrees/feat-399-checkpointing-example`) if it is still live —
  it owns the snapshot path this task now exercises with non-empty metadata.
- **Resume path**: `completed` is seeded from `ctx.completed_tasks` and
  `results` from `ctx.results` (`flow/flow.py:1428,1431`), but `run_started_at`
  measures only the current process — so `total_time` on a resumed run covers
  the resumed segment only. Already documented by TASK-2328; do not attempt to
  reconstruct the original run's clock here.
- Building `NodeExecutionInfo` for `ctx.node_metadata` inside the event loop
  means it is built twice (once here, once in `_aggregate_result`). That is
  acceptable and keeps the two paths independent — do NOT restructure
  `_aggregate_result` to consume `ctx.node_metadata`, which would couple them.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:1964` — the reference
  `mark_completed` call that populates `responses`.
- `packages/ai-parrot/tests/flows/checkpoint/test_flow_export.py` — the
  snapshot round-trip test you must keep green.

---

## Acceptance Criteria

- [ ] `_aggregate_result` is called with `ctx=`, `run_started_at=`, `skipped=` (spec AC4-AC7 become observable end-to-end)
- [ ] After `run_flow()`, every `result.nodes[i].usage` is non-`None` for agents returning usage (spec AC2)
- [ ] After `run_flow()`, `repr(result)` no longer shows `time=0.00s` (spec AC4)
- [ ] After `run_flow()`, `ctx.responses` and `ctx.node_metadata` are non-empty (spec AC10)
- [ ] `FlowResult.node_results` returns scalars, not envelopes, end-to-end (spec AC8)
- [ ] Checkpoint round-trip green with non-empty `node_metadata`: `pytest packages/ai-parrot/tests/flows/checkpoint/ -v`
- [ ] All 3 integration tests pass: `pytest packages/ai-parrot/tests/bots/flows/test_agents_flow.py -v`
- [ ] Flow suites green (spec AC14): `pytest packages/ai-parrot/tests/bots/flows/ packages/ai-parrot/tests/test_flow_primitives/ packages/ai-parrot/tests/flows/checkpoint/ -v`
- [ ] `ruff check` and `mypy` clean on `flow/flow.py` (spec AC16)

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_agents_flow.py

async def test_flow_run_populates_usage():
    """End-to-end run_flow with a mock agent: every nodes[i].usage is non-None."""

async def test_flow_run_total_time_nonzero():
    """result.total_time > 0 and repr() no longer prints time=0.00s."""

async def test_flow_context_carries_metadata():
    """After run_flow, ctx.responses and ctx.node_metadata are populated."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-result-fidelity.spec.md` (§2 Layer 2, §6, §7)
2. **Check dependencies** — TASK-2328 MUST be in `sdd/tasks/completed/` (and TASK-2326 before it)
3. **Verify the Codebase Contract** before writing ANY code — every line number above has shifted
4. **Update status** in `sdd/tasks/index/agentsflow-result-fidelity.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** every acceptance criterion, especially the checkpoint round-trip
7. **Move this file** to `sdd/tasks/completed/TASK-2329-run-flow-context-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5)
**Date**: 2026-08-24
**Notes**:

Module 4 landed as three surgical edits inside `run_flow`, no refactor:

1. The `_aggregate_result` call site now passes `ctx=ctx`,
   `run_started_at=run_started_at`, `skipped=skipped`.
2. `ctx.mark_completed(...)` now also passes `response=event.result` (the
   envelope **verbatim**, not pre-unwrapped) and `metadata=<NodeExecutionInfo>`.
3. `ctx.mark_failed(...)` likewise passes `metadata=<NodeExecutionInfo>` with
   `status="failed"` and the error string.

Note on (3): the task's scope said "store each node's built
`NodeExecutionInfo` into `ctx.node_metadata`" without prescribing the
mechanism. `mark_failed` **already** accepts an optional `metadata`
parameter (`core/context.py:206-225`), exactly like `mark_completed`, so both
writes go through the existing documented API — no direct
`ctx.node_metadata[...] = ...` poking, and no signature change anywhere. This
also means a failed node appears in `ctx.node_metadata` (marked `"failed"`)
even though it is deliberately absent from `completion_order`.

As the task required, the `NodeExecutionInfo` is built here *in addition to*
`_aggregate_result` building its own; the two paths stay independent and
`_aggregate_result` was NOT restructured to consume `ctx.node_metadata`.

Tests: 4 added to `tests/bots/flows/test_agents_flow.py` — the 3 named plus
`test_flow_context_metadata_for_failed_node` (covers the `mark_failed` metadata
path and the completion_order-residue interaction). A new `UsageAgent` stub
returns a REAL `AgentResponse`/`AIMessage`/`CompletionUsage`/`ToolCall` (a
`MagicMock` would make the `usage.model_dump()` assertions vacuous) and exposes
an `llm` so `NodeExecutionInfo.client` is exercised end-to-end. It needs
`invoke()` as well as `ask()` — the `AgentLike` protocol is `runtime_checkable`
and `AgentNode`'s pydantic validation rejects a stub without it.

One test detail worth flagging: `test_flow_run_total_time_nonzero` runs the
flow with a 15 ms per-agent delay. `FlowResult.__repr__` formats `total_time`
with `:.2f`, so a sub-5ms stub run prints `time=0.00s` **even when
`total_time > 0`** — the delay keeps the "no longer shows time=0.00s"
assertion a genuine check instead of something rounding could defeat.

**Checkpoint round-trip**: **no change to the snapshot path was needed, and
`node_metadata` is not serialised by it.** Verified by reading
`FlowContext.to_snapshot()` (`core/context.py:261-320`): it captures
`initial_task`/`results`/`responses`/`completed_tasks`/`completion_order`/
`shared_data`/`errors` and never touches `node_metadata`, so the declared
`Dict[str, NodeExecutionInfo]` type is honoured as-is (no `to_dict()`
downgrade required). The one path that *does* read it is
`FlowCheckpointer._build_checkpoint`, which maps it to
`NodeStateSnapshot(fsm_state=info.status)`; since `status` is a plain `str`
literal this validates cleanly. Proved empirically with a probe that runs a
real 2-node flow, builds a checkpoint from the resulting ctx, and does a full
`model_dump_json()` -> `model_validate_json()` round trip:
`node_metadata keys: ['a','b']`, `node_states: [('a','completed'),
('b','completed')]`, round trip OK at 1600 JSON bytes. Net effect: checkpoints
now carry real per-node FSM states where the list used to be **empty**.

Verification:
- `tests/bots/flows/test_agents_flow.py`: 18 passed (14 pre-existing + 4).
- `tests/bots/flows/` + `tests/test_flow_primitives/`: 722 passed.
- `tests/flows/checkpoint/`: 70 passed, 2 skipped, 2 failed — the 2 failures
  are `test_durable_store.py`'s Postgres tests failing on
  `password authentication failed for user "postgres"`, and the identical
  result (2 failed / 70 passed / 2 skipped) is reproduced on clean `dev` in
  the main checkout. Environmental, not caused by this task.
  `test_flow_export.py` (the snapshot round-trip) is green.
- Crew regression suites: 32 passed, unchanged.
- `ruff` on `flow/flow.py` and `test_agents_flow.py`: finding sets **byte-for-
  byte identical** to before this task (zero new findings). `mypy` on
  `flow/flow.py`: 28 errors before, 28 after, identical set.

**Deviations from spec**: none. `FlowResult.responses` still holds raw
envelopes (spec §8 open question left at status quo, as this task's scope
directed).
