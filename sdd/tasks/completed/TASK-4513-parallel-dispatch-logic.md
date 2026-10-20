# TASK-4513: Phase 2 parallel dispatch layer (partition, fork, collect, fallback)

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4511, TASK-4512
**Assigned-to**: unassigned

---

## Context

Spec Module 1 (M1) + design-research S1, S2, S4, S7, S10. Wraps the existing
sequential iteration loop (`#### 4a. Iteration loop`) with a dispatch layer that
partitions the approved plan into 3 lanes and runs them as Claude Code forks.
The existing loop text stays — it becomes both the sequential path and the
per-lane procedure each fork follows.

## Scope

- New `#### 4a. Dispatch (parallel or sequential)` before the existing loop; rename the
  existing loop heading to `#### 4a-seq. Iteration loop` **only if** needed — prefer keeping
  `#### 4a. Iteration loop` and inserting the dispatch as `#### 4.0 Dispatch` above it (see blueprint).
- Partition rules, fork prompt template, collect/partial-failure handling,
  cross-lane notes, idempotent resume, `research.parallel` checkpoint.
- Lane-prefixed IDs `FC-NNN` / `FG-NNN` / `FW-NNN` for fork-written findings.

**NOT in scope**: the merge/dedup step (TASK-4514), contract probe (TASK-4516), twins (TASK-4517).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-proposal.md` | MODIFY | dispatch subsection in §4 |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```markdown
<!-- .claude/commands/sdd-proposal.md (verified 2026-10-20 @ 9e8092778; TASK-4512 adds ~25 lines above — re-grep) -->
:199  ### 4. Phase 2 — Execute Research
:201  #### 4a. Iteration loop
:203  For each query in the approved plan, in priority order:
:223  3. **Persist a digest** at `${STATE_DIR}/findings/F<NNN>-<slug>.md` ...
:232  #### 4b. Stop conditions
```
Query `type` values in the plan: `wiki_query`, `wiki_page`, `wiki_related`, `grep`, `glob`, `read`, `git_log`, `tree` (verified :210-221).
`sdd/templates/state.schema.json` `research.parallel` + `$defs/lane_record` — created by TASK-4511.

### Does NOT Exist
- ~~`subagent_type: "fork"` in any SDD skill~~ — this is the first
- ~~a `model:` override on a fork~~ — forks ignore it; do not write one
- ~~`sdd/templates/lane.md`~~ — lanes use `sdd/templates/finding.md`
- ~~a separate capability-probe call~~ — S7: the dispatch itself is the probe

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": ".claude/commands/sdd-proposal.md", "action": "MODIFY"}],
  "contract_symbols": []
}
```

## Implementation Notes

### Key Constraints
- **Parent is the sole `state.json` writer** (S1). Forks write only `FC-*`/`FG-*`/`FW-*` files and report counts in their final message.
- **Fork prompt carries no raw source text** (S10): query list JSON, lane limits, `${STATE_DIR}`, prefix. Never paste `source.md`/Jira content.
- **Partition** (S4): codebase = `grep|glob|read|tree`; git = `git_log`; wiki = `wiki_query|wiki_page|wiki_related`. A query whose `parent_id` points into another lane goes to its parent's lane.
- All 3 forks launch in ONE message (three Agent calls) so they run concurrently.
- Partial failure: keep finished lanes; re-run the failed lane's queries sequentially with the 4a loop; if that also fails mark the lane `failed` and continue.
- Cross-lane follow-ups: never dispatched; written into the finding's `## Notes` as `[cross-lane: type=<type>, intent=<text>]`.
- Resume (S2): lane with findings on disk but no `completed_at` → re-dispatch; with `completed_at` → skip.

## Implementation Blueprint

### Steps (in order)
1. Re-grep the `#### 4a. Iteration loop` anchor (TASK-4512 shifted lines).
2. Insert the dispatch block between `### 4. Phase 2 — Execute Research` and `#### 4a. Iteration loop`.
3. Add one sentence at the top of 4a: "This loop is the sequential path and the per-lane procedure each fork follows." — because forks reuse it.
4. Amend step 3 of 4a: inside a fork, the digest is `${STATE_DIR}/findings/<PREFIX>-<NNN>-<slug>.md`.
5. Amend step 5 of 4a: inside a fork, do NOT write `state.json` (S1).

### `.claude/commands/sdd-proposal.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^#### 4a. Iteration loop' .claude/commands/sdd-proposal.md) -->
<!-- BEFORE — insert above `#### 4a. Iteration loop` -->
#### 4.0 Dispatch — parallel lanes or sequential (FEAT-708)

Decide the execution mode first. Run **sequentially** (skip to §4a, record
`phases.research.parallel = {"enabled": false, "fallback_reason": "<why>"}`)
when the per-lane allocation in §1 says so (tight, custom, `--no-parallel`).
Otherwise:

1. **Partition** the approved plan by query `type`:
   | Lane | Prefix | Query types |
   |---|---|---|
   | codebase | `FC` | `grep`, `glob`, `read`, `tree` |
   | git | `FG` | `git_log` |
   | wiki | `FW` | `wiki_query`, `wiki_page`, `wiki_related` |
   A query with a `parent_id` stays in its parent's lane, so `wiki_query → wiki_page`
   chains never split. An empty lane is not dispatched (status `completed`, 0 findings).
2. **Allocate** each lane its quota from the §1 per-lane table.
3. **Dispatch** all non-empty lanes in ONE message — one `Agent` call per lane:
   ```
   Agent({
     subagent_type: "fork",
     description: "<lane> research lane",
     prompt: "Lane: <lane>. Prefix: <FC|FG|FW>. STATE_DIR: <abs path>.
              Limits: <lane quota JSON>. Queries: <lane query list JSON>.
              Follow §4a of /sdd-proposal for each query. Write findings ONLY as
              ${STATE_DIR}/findings/<PREFIX>-<NNN>-<slug>.md. Do NOT write state.json.
              Record any follow-up that belongs to another lane as a Notes line
              `[cross-lane: type=<type>, intent=<text>]`. End with a JSON line:
              {\"lane\":..., \"queries_executed\":N, \"queries_skipped\":N,
               \"files_read\":N, \"grep_calls\":N, \"git_calls\":N, \"findings\":[ids]}"
   })
   ```
   The prompt carries no `source.md`/Jira text — forks read the state dir on disk.
   **If the Agent call errors** (tool unavailable, fork not supported), this IS the
   capability probe: record `fallback_reason: "agent-unavailable"` and run §4a sequentially.
4. **Collect** each fork's completion. FILL IN (see checklist).
5. **Checkpoint** `state.json` (parent only): set `phases.research.parallel.lanes.<lane>`
   (`lane_record`), add every lane's counters into `consumed.*`, then go to §4c (merge).

**Resume.** On `--resume` in Phase 2: a lane whose `<PREFIX>-*` findings exist AND whose
`lanes.<lane>.completed_at` is set is skipped; a lane with findings but no
`completed_at` is re-dispatched (its partial `<PREFIX>-*` files are moved to
`findings/.audit/partial/` first).
```
**Why**: encodes M1 + S1/S2/S4/S7/S10 in one place; §4c is created by TASK-4514.

### FILL IN checklist
- [ ] Step 4 Collect: partial-failure rule — keep finished lanes; re-run a failed/timed-out lane's queries sequentially via §4a; if the retry fails set `status: failed`, `error: <msg>` and continue (bounded by spec §7 "Fork failure modes")
- [ ] Lane wall clock: tell the parent to stop waiting at `floor(0.85 × wall_seconds)` and treat a still-running lane as failed (bounded by M2 merge window)
- [ ] 4a step 3 and step 5 amendments (forks: prefixed IDs, no state.json)

## Acceptance Criteria

- [ ] Partition table, fork prompt and fallback conditions match spec M1
- [ ] Fork prompt contains no raw source text (S10)
- [ ] Parent-only state writes stated explicitly (S1)
- [ ] Resume rule for incomplete lanes (S2)
- [ ] Cross-lane follow-up note format `[cross-lane: type=…, intent=…]`
- [ ] Sequential §4a path unchanged in behavior

## Validation Commands

- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-proposal-parallel-research --feature-id FEAT-708`)
2. **Read the spec** at `sdd/specs/sdd-proposal-parallel-research.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/sdd-proposal-parallel-research.json`
4. **Verify the Codebase Contract** — re-run every `grep -c` anchor check before editing;
   if an anchor moved, fix the blueprint first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `FILL IN`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (`.claude/` paths need `git add -f`)
9. **Close** with `scripts/sdd/close_task.sh <TASK-ID> sdd-proposal-parallel-research verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) — coder seat gpt-5.6-terra (codex), attempt 1
**Date**: 2026-10-20
**Notes**: added §4.0 parallel dispatch subsection and fork-lane notes to sdd-proposal.md. Orchestrator read the full diff (e59c0f7f9); merge-tier validation green. Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 47.9s. Closed via close_task.sh (finalize_task unavailable: no review EvidenceRef resolvable from the engine store).

**Deviations from spec**: none
