---
id: FC-011
query_id: Q026
type: read
intent: "Read the sdd state schema fields that identify the current task/attempt, so a hook can resolve cwd -> feat_id -> task_id deterministically."
executed_at: 2026-10-30T23:02:00Z
duration_ms: 200
parent_id: null
depth: 0
---

# FC-011 — REFUTED: `sdd/state/<FEAT-ID>/state.json` holds no current task and no attempt; the task mapping lives in the per-spec index

## Summary

The source names `sdd/state/<FEAT-ID>/state.json` as "the authoritative `feat_id → current
task` mapping on the `dev` branch" and designs the hook join around it ("the plane reads
`current_task` / `attempt` to fill keys"). **That file has no such fields.**
`sdd/templates/state.schema.json` declares exactly fourteen top-level properties —
`schema_version, feat_id, feature_slug, started_at, updated_at, source, mode, phase,
phases, budget, consumed, detected_mode, errors, resume_hint` — and a grep for
`current_task`, `attempt_uid` or `task_id` across the whole schema returns **nothing**.
This state directory belongs to `/sdd-proposal`'s own research pipeline, not to the
implementation lane.

The real `feat_id → task → status` mapping is the per-spec index
`sdd/tasks/index/<feature-slug>.json` (FEAT-145), whose `tasks[]` entries carry `id`,
`feature_id`, `feature`, `status`, `depends_on`. A hook that must resolve
`cwd → feat_id → task_id` has to read *that* file — and even there, "current task" is
inferred from `status == "in-progress"`, not stated. `attempt_uid` exists nowhere in SDD
state at all: it is minted inside the sdd-coder engine
(`engine.py:482` — "attempt branch -> (attempt_uid, execution_id or "", attempt path,
attempt number)") and is visible to a hook only if the coder reports it.

## Citations

- path: `sdd/templates/state.schema.json`
  lines: n/a
  symbol: `top-level properties`
  excerpt: |
    budget, consumed, detected_mode, errors, feat_id, feature_slug, mode,
    phase, phases, resume_hint, schema_version, source, started_at, updated_at
    -- grep for current_task | attempt_uid | task_id -> no matches

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  lines: 482-496
  symbol: `attempt bookkeeping`
  excerpt: |
    # FEAT-709: attempt branch -> (attempt_uid, execution_id or "", attempt path, attempt number)
    # FEAT-709: (execution_id or "", task_id) -> (red branch, attempt, rendered verdict)
    # FEAT-559: manager key (worker id, see `_worker_id`) -> owning execution_id,
    # FEAT-559: (execution_id, task_id) -> attempt_uid, so a duplicate
    # (execution_id, task_id) -> lock serialising `_reserve_native_attempt`

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`
  lines: 623-667
  symbol: `begin_execution`
  excerpt: |
    async def begin_execution(
        ...
        execution_id: str,
        """Reads durable suspension history BEFORE probing. Binds execution_id
            execution_id: Caller-generated UUID for this execution.
        if existing_id != execution_id: ... owner_execution_id=existing_id
        # Check for resume case: same execution_id already exists in memory

## Notes

- `execution_id` is **caller-generated** (engine.py:638), so an orchestrator already has it
  before the engine does — it can be published to a hook environment without a round trip.
- The engine enforces exclusive worktree ownership per `execution_id`
  (`_execution_owners: canonical worktree path -> execution_id`, engine.py:508). That means
  **`cwd` → `execution_id` is a genuinely deterministic lookup inside the engine** — a much
  stronger join than reading SDD state from a hook.
