# TASK-4516: /sdd-proposal — verify finding citations with sdd-contract-probe before synthesis

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4514 (same file). Cross-feature: **PR #1742 merged into `dev`**.
**Assigned-to**: unassigned

---

## Context

Spec Module 7 (M7), proposal half. Between Phase 2 (canonical findings ready)
and Phase 3 synthesis, the citations in `${STATE_DIR}/findings/F*.md` are turned
into probe checks and run by the shared Haiku `sdd-contract-probe`. Results are
tagged into the findings so synthesis weighs stale/missing evidence.

**Gate**: `test -f .claude/agents/sdd-contract-probe.md` on `origin/dev`; absent → STOP.

## Scope

- New `#### 4d. Citation probe (FEAT-708)` after §4c, before `### 5. Phase 3 — Synthesis`.
- Note in §5a that assembly may proceed while the probe runs; insert a collect step before §5b.

**NOT in scope**: brainstorm (TASK-4515), the existing synthesis linter (leave untouched), twins (TASK-4517).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-proposal.md` | MODIFY | §4d + §5a/§5b hooks |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```markdown
<!-- .claude/commands/sdd-proposal.md (verified 2026-10-20 @ 9e8092778; shifted by 4512/4513/4514 — re-grep) -->
:242  ### 5. Phase 3 — Synthesis
:244  #### 5a. Build the synthesis input
:253  #### 5b. Run the synthesis prompt
```
Probe agent + `/sdd-task` §3 rules: see TASK-4515's contract (PR #1742).

### Does NOT Exist
- ~~a verification fork~~ / ~~`model: "haiku"` on a fork~~
- ~~probe statuses `verified|stale|missing`~~ — caller classifies
- ~~changes to `sdd/templates/finding.md`~~ — tags go in the existing `## Notes`

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
1. Gate check; read the probe agent file.
2. Insert §4d above `### 5. Phase 3 — Synthesis`.
3. Under `#### 5b. Run the synthesis prompt`, add a first paragraph "Before running: collect the §4d probes …".

### `.claude/commands/sdd-proposal.md` (MODIFY) — §4d
```markdown
<!-- occurrences: 1 (verified: grep -c '^### 5. Phase 3 — Synthesis' .claude/commands/sdd-proposal.md) -->
<!-- BEFORE — insert above `### 5. Phase 3 — Synthesis` (after §4c from TASK-4514) -->
#### 4d. Citation probe (FEAT-708)

Extract every citation from `${STATE_DIR}/findings/F*.md` (`## Citations`),
dedupe across findings, and map each to an `sdd-contract-probe` check
(`file` for `path:NN`, `symbol` for a cited class/function — keep the cited
signature as `expected` — `anchor` for a quoted line, `import` for an import,
`absent` for a "does not exist" claim; ids `c0, c1, …`, keep a
check-id → finding-id map). Launch the probes in ONE message
(≤ ~40 checks each, grouped by file):
`Agent({subagent_type: "sdd-contract-probe", description: "Verify finding citations",
prompt: "Repository root: <abs path>\nProbe sheet: <JSON array>"})`
and continue with §5a. With fewer than ~10 citations, or without the Agent
tool, run the same checks inline.
```

### `.claude/commands/sdd-proposal.md` (MODIFY) — §5b collect
```markdown
<!-- occurrences: 1 (verified: grep -c '^#### 5b. Run the synthesis prompt' .claude/commands/sdd-proposal.md) -->
<!-- AFTER — insert directly below `#### 5b. Run the synthesis prompt` -->
**First, collect the §4d probes.** Verify each report with `/sdd-task` §3's
rules for `sdd-contract-probe`, classify every check (FILL IN: table), and
for each `stale` or `missing` check append
`[citation-check: stale|missing] <path:line> — <evidence>` to the owning
finding's `## Notes`. Re-read the tagged findings into the §5a input.
```

### FILL IN checklist
- [ ] Classification table — spec M7 verbatim
- [ ] §5a one-liner: "If §4d probes are running, assemble the input now; tags are applied before §5b."
- [ ] Confirm the synthesis linter section is untouched

## Acceptance Criteria

- [ ] `/sdd-proposal` dispatches `sdd-contract-probe` between Phase 2 and Phase 3
- [ ] Reports verified with `/sdd-task` §3 rules before use
- [ ] Stale/missing citations tagged `[citation-check: …]` in `## Notes`
- [ ] Inline fallback documented
- [ ] No fork, no `model:` override, no new agent file

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
