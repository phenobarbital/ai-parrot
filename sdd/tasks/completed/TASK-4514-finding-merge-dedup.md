# TASK-4514: Finding merge — citation-identity dedup into canonical F001+

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4513
**Assigned-to**: unassigned

---

## Context

Spec Module 3 (M3) + S5/S6. After lanes finish, Phase 3 must see only canonical
`F001`+ findings. Lane originals are kept for audit. Dedup is by citation
identity `(path, symbol, line_range)`, never by file path alone.

## Scope

- New `#### 4c. Merge lane findings (parallel mode only)` after `#### 4b. Stop conditions`
  and before `### 5. Phase 3 — Synthesis`.
- Merge receipt in `phases.research.parallel.merge`.

**NOT in scope**: dispatch (TASK-4513), citation probing (TASK-4516).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-proposal.md` | MODIFY | add §4c merge subsection |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```markdown
<!-- .claude/commands/sdd-proposal.md (verified 2026-10-20 @ 9e8092778; shifted by TASK-4512/4513 — re-grep) -->
:232  #### 4b. Stop conditions
:242  ### 5. Phase 3 — Synthesis
:248  - All `${STATE_DIR}/findings/*.md` digests, wrapped in `<finding id="F00N">` tags
```
`sdd/templates/finding.md` has a `## Citations` section (read it to confirm the citation line shape before writing the grouping rule).

### Does NOT Exist
- ~~`merge_findings()`~~ — no merge code anywhere; this is agent-executed text
- ~~`findings/.audit/`~~ — created by this step
- ~~changes to `sdd/templates/finding.md`~~ — format is frozen (spec Non-Goal)

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [{"path": ".claude/commands/sdd-proposal.md", "action": "MODIFY"}],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)
1. `Read sdd/templates/finding.md` — confirm citation line format (path, symbol, line range).
2. Insert §4c above `### 5. Phase 3 — Synthesis`.
3. Amend §5a's findings bullet: "only canonical `F<NNN>` digests (never `findings/.audit/`)".

### `.claude/commands/sdd-proposal.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^### 5. Phase 3 — Synthesis' .claude/commands/sdd-proposal.md) -->
<!-- BEFORE — insert above `### 5. Phase 3 — Synthesis` -->
#### 4c. Merge lane findings (parallel mode only)

Skip when Phase 2 ran sequentially (findings are already `F<NNN>`).

1. Read every `${STATE_DIR}/findings/{FC,FG,FW}-*.md` and extract each
   citation as a `(path, symbol, line_range)` tuple from its `## Citations`.
2. **Group by citation identity**: two findings merge when they share a
   `(path, symbol)` and their line ranges overlap. Same path but different
   symbols → separate findings (never merge on path alone).
3. **Merge** a group: union of citations (overlapping ranges collapsed),
   summaries concatenated, the deeper `depth` kept, `## Notes` combined
   (cross-lane notes preserved verbatim).
4. **Renumber** the merged set `F001`, `F002`, … in lane order codebase → git → wiki,
   then by original number. Write them to `${STATE_DIR}/findings/F<NNN>-<slug>.md`.
5. **Archive** the lane originals: move every `FC-*`, `FG-*`, `FW-*` to
   `${STATE_DIR}/findings/.audit/`.
6. **Validate**: no two canonical findings share a `(path, symbol)`; IDs run
   `F001..F<N>` with no gaps. A failure here is fixed before Phase 3, never skipped.
7. **Checkpoint** `phases.research.parallel.merge` = `{started_at, completed_at,
   input_count, output_count, merged_count: input_count − output_count,
   audit_dir: "findings/.audit"}`, then set `phase: "research_complete"`.
```
**Why**: M3 algorithm verbatim; S5 keeps lane files out of Phase 3 input.

### FILL IN checklist
- [ ] Findings with **no** citations (e.g. a pure wiki overview): define them as never merging — each stays its own canonical finding (bounded by "never merge on path alone")
- [ ] §5a amendment wording
- [ ] Confirm the renumber order sentence matches what TASK-4518's reference implementation will assert

## Acceptance Criteria

- [ ] Dedup by `(path, symbol, line_range)`; distinct symbols preserved (S6)
- [ ] Canonical IDs sequential, no gaps
- [ ] Lane originals in `findings/.audit/` (S5); Phase 3 reads only `F<NNN>`
- [ ] Merge receipt fields match `research.parallel.merge` in the schema

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

**Completed by**: sdd-worker (orchestrator) — coder seat qwen.qwen3-coder-480b-a35b-instruct (nova), attempt 1
**Date**: 2026-10-20
**Notes**: added §4c finding merge/dedup and Phase 3 input rule to sdd-proposal.md. Orchestrator read the full diff (518022b67); merge-tier validation green. Seat: qwen.qwen3-coder-480b-a35b-instruct · Backend: nova · Attempts: 1 · Duration: 41.2s. Closed via close_task.sh (finalize_task unavailable: no review EvidenceRef resolvable from the engine store).

**Deviations from spec**: none
