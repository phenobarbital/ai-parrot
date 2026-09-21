# TASK-3604: Reference documentation — recovery model, additive schema migration, exactly-once limitation, injection fix

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3589, TASK-3601
**Assigned-to**: unassigned

---

## Context

Implements the documentation half of spec §3 **Module 7** and AC12 / AC17.

`docs/toolkits/execution_plan_toolkit.md` (225 lines) currently: tells users to register
`working_memory` by hand because "`BasicAgent._inject_answer_memory_into_toolkits()` does not
match wrapped `ToolkitTool`s" (lines 49-52 — fixed by TASK-3589, so the workaround text must
go); states "There is **no `plan_resume(run_id)`**" and that flow checkpointing is disabled
(lines 194-202 — no longer true); describes recovery as re-issue + `skip_existing` only
(203-210); and documents `plan_status`/`plan_artifacts` without the recovery envelope
(95-104). It must now document the two new tools, the constructor inputs, the recovery
capability table, the stable error codes (including the capability-scoped `unknown_run` vs
`missing_or_expired`), the additive terminal-schema change and its migration for strict
consumers, and the exactly-once limitation for interrupted external calls.

---

## Scope

- Rewrite/extend `docs/toolkits/execution_plan_toolkit.md`: Wiring (constructor inputs; remove
  the workaround comment), Tools (add `plan_resume`, `plan_repair`; envelope on all four run
  tools), new section "Recovery model" (capability table, lineage, repair budget, error codes),
  new section "Response schema migration" (additive `PlanRunManifest`; strict `extra="forbid"`
  consumers), update "v1 caveats" (rename to "Caveats and limitations": exactly-once, RAM cap
  vs raw-read cap, memory-mode limits), "See also" (add the new test files).

**NOT in scope**:
- Any code change. Any spec change (the spec is the SSOT; the docs summarize it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/toolkits/execution_plan_toolkit.md` | MODIFY | Recovery model, new tools, migration, limitations, injection fix |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Anchors in the doc
```markdown
# docs/toolkits/execution_plan_toolkit.md
L1   # ExecutionPlanToolkit — Reference
L30  ## Wiring                 — code block L32-54; the WRONG comment is L49-52:
       # Also register `working_memory` with the agent so the analyst can read
       # back artifacts under the keys the plan chose — constructor injection,
       # never auto-detected: `BasicAgent._inject_answer_memory_into_toolkits()`
       # does not match wrapped `ToolkitTool`s.
L66  ## Tools ; L68 ### `plan_execute(...)` ; L95 ### `plan_status(run_id)` ; L100 ### `plan_artifacts(run_id)` ; L105 ### `plan_validate(...)`
L119 ## The plan file + `{params.<name>}` contract
L159 ## Soft-timeout / `run_id` flow
L183 ## v1 caveats (read before relying on this in production)   — bullets L185-216; "no plan_resume" bullet L194-202; recovery bullet L203-210
L218 ## See also
```

### Facts to document (verified in code / fixed by the spec)
```text
Constructor (spec §2 New Public Interfaces; TASK-3598): recovery: PlanRecoveryConfig | None, checkpoint_store: CheckpointStore | str | None,
  durable_store: CheckpointStore | str | None, task_memory_runtime: TaskMemoryRuntime | None, scope: TaskScope | None. Borrowed, never closed.
PlanRecoveryConfig: max_repair_rounds 0–2 default 2 (host-only, §8 D1); max_restore_bytes 67108864; checkpoint_probe_timeout 2.0
Capability table (spec §2): none / process / cross_restart × refusal codes checkpoint_unavailable / artifacts_unavailable
Error codes (spec §2): unknown_run, checkpoint_unavailable, checkpoint_invalid, checkpoint_write_failed, run_busy, run_not_resumable, run_not_repairable,
  no_repairable_nodes, repair_limit_reached, repair_interrupted, delta_invalid, planner_unavailable, scope_mismatch, policy_mismatch,
  artifacts_unavailable, artifact_alias_conflict, restore_budget_exceeded, missing_or_expired
§8 D3: durable tier configured + latest() None → unknown_run (DurableCheckpointStore has no TTL, store/durable.py:12); ephemeral-only → missing_or_expired
  (RedisCheckpointStore TTL = FLOW_CHECKPOINT_REDIS_TTL 86400s, conf.py:309)
Frozen ExecutionManifest (bots/flows/plan/models.py:450) is extra="forbid"; PlanRunManifest adds run_id, root_run_id, parent_run_id, checkpoint_enabled,
  artifact_mode, resume_level, resumable, recovery_reason, repair_attempts_used, max_repair_rounds, active_child_run_id, status (TASK-3590)
Injection: get_toolkit_owner in tools/manager.py; BasicAgent injects once per actual toolkit (TASK-3589) — explicit answer_memory still wins
Raw-read ceiling: default 2,000,000 bytes (tool.py:272 / config.py:131); plan memory is activated only for plans (WorkingMemoryToolkit default unchanged)
```

### Does NOT Exist
- ~~automatic startup recovery / automatic retries~~ — never document them; both are §1 Non-Goals.
- ~~byte-identical terminal JSON~~ — the schema is additive; say so explicitly (spec §2 Data Models last paragraph).
- ~~exactly-once external effects across a crash~~ — document the limitation, not a promise (AC17).
- ~~`plan_resume(run_id, scope=...)` / `plan_repair(run_id, max_rounds=...)`~~ — both tools take `run_id` only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/toolkits/execution_plan_toolkit.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Keep every existing heading that is still true; add headings rather than reshuffling.
- Every stated default/number must appear in the "Facts to document" table above or in the
  spec; do not invent numbers.
- Code examples must construct the toolkit with the real keyword names and run under the
  activated venv at least as an import smoke (`python -c "from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanRecoveryConfig"`).

### References in Codebase
- `sdd/specs/plan-then-execute-hardening.spec.md` §2 — source of every table.
- `docs/memory/per-turn-conversation-compaction.md` — house style for a "limitations" section.

---

## Implementation Blueprint

### Steps (in order)
1. Fix the Wiring block — *why*: AC12 explicitly requires the wrapper-workaround text to be removed.
2. Add the two tool sections + envelope note — *why*: agents read this to know the tools exist.
3. Add "Recovery model" and "Response schema migration" — *why*: AC5/AC17 need the capability table and the additive-schema statement in user-facing form.
4. Rewrite the caveats — *why*: two bullets are now false and one limitation (exactly-once) is mandatory (AC17).

### `docs/toolkits/execution_plan_toolkit.md` (MODIFY — wiring comment)
```markdown
<!-- occurrences: 1 (verified: grep -c 'does not match wrapped `ToolkitTool`s' docs/toolkits/execution_plan_toolkit.md) -->
<!-- REPLACE lines 49-52 (the four comment lines) with: -->
# Also register `working_memory` with the agent so the analyst can read back
# artifacts under the keys the plan chose. `BasicAgent` auto-injects its
# `answer_memory` into the toolkit once (FEAT-585); an explicit
# `WorkingMemoryToolkit(answer_memory=...)` still takes precedence.
```

### `docs/toolkits/execution_plan_toolkit.md` (MODIFY — wiring inputs, after the code block)
```markdown
<!-- occurrences: 1 (verified: grep -c '^Both `planner_llm` and `plans_dir` are optional' docs/toolkits/execution_plan_toolkit.md) -->
<!-- BEFORE — insert ABOVE the paragraph starting `Both \`planner_llm\` and \`plans_dir\` are optional` (verified: L56) -->
### Recovery inputs (FEAT-585)

| Keyword | Type | Meaning |
|---|---|---|
| `recovery` | `PlanRecoveryConfig \| None` | `max_repair_rounds` (0–2, default 2, host-only), `max_restore_bytes` (64 MiB), `checkpoint_probe_timeout` (2.0 s). `None` = defaults. |
| `checkpoint_store` | `CheckpointStore \| str \| None` | Ephemeral tier (e.g. `"redis"`). `None` = no checkpointing; runs report `resume_level: "none"`. |
| `durable_store` | `CheckpointStore \| str \| None` | Durable tier (`"sqlite"`/`"postgres"`/`"mongodb"`). Required for `cross_restart`. |
| `task_memory_runtime` | `TaskMemoryRuntime \| None` | An already-started runtime to share; with `scope` it enables durable artifacts. Borrowed, never closed. |
| `scope` | `TaskScope \| None` | Trusted host scope. A durable runtime without a scope is a configuration error. |

<!-- FILL IN: two sentences on what happens with none of these set (in-memory plan memory, process-local scope, fresh execution) — bounded by spec §2 "Plan memory binding". -->
```

### `docs/toolkits/execution_plan_toolkit.md` (MODIFY — new tool sections)
```markdown
<!-- occurrences: 1 (verified: grep -c '^### `plan_validate' docs/toolkits/execution_plan_toolkit.md) -->
<!-- BEFORE — insert ABOVE `### \`plan_validate(objective=None, plan_name=None, params=None)\`` (verified: L105) -->
### `plan_resume(run_id)`

Continue an interrupted **checkpointed** run — in this process or, with a durable tier and a
host-supplied scope, in a fresh one. Completed nodes are never re-dispatched; their exact
`artifact_id@version` evidence is restored under a host-only byte budget. Never calls a
planner. Refuses with `run_not_resumable`, `checkpoint_unavailable`, `artifacts_unavailable`,
`scope_mismatch`, `policy_mismatch` or `run_busy`.

### `plan_repair(run_id)`

Spend **one** repair attempt on a terminal `failed`/`partial` run: the planner may replace only
nodes that errored or were never dispatched (never `ok`/`skipped`/`partial` nodes, never new
ids), the delta is validated against the original allowlist ∩ current policy, and the child
run inherits every successful result. At most one structural correction call per attempt;
the attempt is persisted **before** the planner is called, so a crash consumes it.
Refuses with `no_repairable_nodes`, `repair_limit_reached`, `planner_unavailable`,
`run_not_repairable`, `delta_invalid`, `repair_interrupted` or `run_busy`.

All four run tools (`plan_status`, `plan_artifacts`, `plan_resume`, `plan_repair`) return the
recovery envelope: `run_id`, `root_run_id`, `parent_run_id`, `checkpoint_enabled`,
`artifact_mode`, `resume_level`, `resumable`, `recovery_reason`, `repair_attempts_used`,
`max_repair_rounds`, `active_child_run_id`.
```

### `docs/toolkits/execution_plan_toolkit.md` (MODIFY — recovery model + migration, before caveats)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## v1 caveats' docs/toolkits/execution_plan_toolkit.md) -->
<!-- BEFORE — insert ABOVE `## v1 caveats (read before relying on this in production)` (verified: L183); then RENAME that heading to `## Caveats and limitations` -->
## Recovery model (FEAT-585)

| Checkpoints acknowledged | Artifact configuration | `resume_level` | Fresh-process `plan_resume` |
|---|---|---|---|
| No | any | `none` | refused: `checkpoint_unavailable` |
| Yes | in-memory / process-local scope | `process` | refused: `artifacts_unavailable` |
| Yes | durable backend + stable trusted scope | `cross_restart` | allowed after validation and lease acquisition |

<!-- FILL IN: (a) "unknown vs missing_or_expired" paragraph from spec §8 D3 with the TTL facts; (b) lineage paragraph (root/child ids, consolidated
manifest, counters recomputed); (c) the full stable error-code list as a table — bounded by the "Facts to document" table above. -->

## Response schema migration

Terminal responses keep every `ExecutionManifest` key at the top level and **add** the
recovery envelope plus `status`. The frozen `parrot.bots.flows.plan.ExecutionManifest` is
unchanged and remains `extra="forbid"`, so a strict consumer that validated the raw JSON into
that model must now either select the manifest fields or validate into
`parrot.tools.execution_plan.PlanRunManifest`. The JSON is additive, not byte-identical.
```

### `docs/toolkits/execution_plan_toolkit.md` (MODIFY — caveats)
```markdown
<!-- REPLACE the two bullets at L194-210 ("The run registry is lost…" and "Recovery is re-issue + skip_existing…") with: -->
- **Recovery is explicit.** Nothing resumes on its own after a restart; the agent calls
  `plan_resume(run_id)`. Without a checkpoint store, runs execute exactly as before and say so
  (`resume_level: "none"`).
- **No exactly-once for interrupted external calls.** A completed, checkpointed node is never
  replayed, but a tool invocation interrupted between its external effect and the checkpoint
  acknowledgement has no acknowledgement to consult. Such tools need their own idempotency
  contract; `for_each` nodes still get `skip_existing` on stored item keys.
- **Two different byte limits.** The analyst's raw-read ceiling (`max_rehydrate_bytes`, default
  2,000,000) bounds what `wm_get_result` returns; the executor's `max_restore_bytes` (64 MiB,
  host-only) bounds exact-version restoration during a continuation. Neither is a process RAM cap.
<!-- FILL IN: keep the remaining original bullets (RAM WorkingMemory note updated to mention versioned plan memory; run-registry bounds; allowed_tools=None) -->
```

### FILL IN checklist
- [ ] recovery-inputs paragraph
- [ ] §8 D3 paragraph, lineage paragraph, error-code table
- [ ] caveats: remaining bullets reconciled
- [ ] "See also": add `test_run_resolution.py`, `test_checkpoint_resume.py`, `test_runtime_repair.py`, `test_integration_recovery.py`, `test_integration_repair.py`

---

## Acceptance Criteria

- [ ] AC-1 — The string "does not match wrapped" no longer appears; the Wiring block explains auto-injection with explicit precedence (AC12).
- [ ] AC-2 — `plan_resume` and `plan_repair` have their own sections; the envelope fields are listed once.
- [ ] AC-3 — The capability table, the `unknown_run`/`missing_or_expired` rule with the TTL facts, the repair budget (0–2, default 2, host-only) and the full error-code list are present (AC5, AC16).
- [ ] AC-4 — "Response schema migration" states additive-not-byte-identical and names both models (AC17).
- [ ] AC-5 — "Caveats and limitations" contains the exactly-once limitation and no longer claims "no `plan_resume`" or "checkpointing disabled" (AC17).
- [ ] The import smoke command in Implementation Notes succeeds.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_owner.py -q`; `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_recovery.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -q`

---

## Test Specification

Documentation task — the Validation Commands re-run the two suites whose behaviour the doc
now describes (injection and recovery envelope). Additionally run:
```bash
grep -c "does not match wrapped" docs/toolkits/execution_plan_toolkit.md   # expect 0
grep -c "plan_resume" docs/toolkits/execution_plan_toolkit.md               # expect >= 3
```

---

## Agent Instructions

1. Read spec §2 (all tables), §8 D1–D3, AC12, AC17; then the current doc end to end.
2. Apply the blueprint blocks; fill the FILL INs from the spec only.
3. Run the Validation Commands and the two greps.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
