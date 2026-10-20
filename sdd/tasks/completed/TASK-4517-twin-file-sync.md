# TASK-4517: Twin-file sync + parity coverage for sdd-proposal and sdd-brainstorm

**Feature**: FEAT-708 — sdd-proposal-parallel-research
**Spec**: `sdd/specs/sdd-proposal-parallel-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4515, TASK-4516
**Assigned-to**: unassigned

---

## Context

Spec Module 5 (M5) + S8. Each SDD command has two twins: the Codex skill
(`.agents/skills/<name>/SKILL.md`, abbreviated) and the legacy workflow
(`.agent/workflows/<name>.md`, a **body copy** of the command). Verified
2026-10-20: both `.agent/workflows/sdd-proposal.md` and
`.agent/workflows/sdd-brainstorm.md` are already byte-identical to their
commands except one line each:
`- Worktree policy: … CLAUDE.md … → AGENTS.md and sdd/WORKFLOW.md`.
So the workflow twins are regenerated from the final command bodies, and both
commands join the parity test.

## Scope

- `.agent/workflows/sdd-proposal.md` and `.agent/workflows/sdd-brainstorm.md`: replace body with the command body (keep each twin's own frontmatter), re-apply the one substitution line.
- `.agents/skills/sdd-proposal/SKILL.md`: add `--no-parallel` to the invocation line, a per-lane note under the budget table, a parallel-dispatch note under `5. Execute research:`. Codex has no forks — state that Codex runs sequentially.
- `tests/sdd_scripts/test_command_twin_parity.py`: add `sdd-proposal`, `sdd-brainstorm` to `_TWINNED` and their substitution pairs.

**NOT in scope**: `.agents/skills/sdd-brainstorm/SKILL.md` (Codex runs checks inline — current behavior); any command text change.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.agent/workflows/sdd-proposal.md` | MODIFY | body = command body + substitution |
| `.agent/workflows/sdd-brainstorm.md` | MODIFY | body = command body + substitution |
| `.agents/skills/sdd-proposal/SKILL.md` | MODIFY | flag + 2 notes |
| `tests/sdd_scripts/test_command_twin_parity.py` | MODIFY | extend `_TWINNED` + `_SUBSTITUTIONS` |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# tests/sdd_scripts/test_command_twin_parity.py (verified 2026-10-20)
_TWINNED = ("sdd-next", "sdd-spec", "sdd-status", "sdd-task")       # line 22
_SUBSTITUTIONS: dict[str, tuple[str, str]] = { ... }                 # line 29
```

### Existing Signatures to Use
```markdown
<!-- substitution lines (verified 2026-10-20) -->
sdd-proposal  command: "- Worktree policy:          `CLAUDE.md` (section \"Worktree Policy\")"   (note the aligned spaces)
              twin:    "- Worktree policy:          `AGENTS.md` and `sdd/WORKFLOW.md`"
sdd-brainstorm command: "- Worktree policy: `CLAUDE.md` (section \"Worktree Policy\")"
               twin:    "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`"

<!-- .agents/skills/sdd-proposal/SKILL.md -->
:20   Codex invocation: `$sdd-proposal <source> [--mode=investigation|enrichment] [--budget=tight|default|loose] [--no-gate]`.
:59   | Profile | Files | Greps | Git | Depth | Seconds |
:88   5. Execute research:
```
Spec §6 Edit Sites lists the :20 anchor as `$sdd-proposal <source> [--mode=...] [--budget=...]` — **stale**; use the line above.

### Does NOT Exist
- ~~"Phase 2" heading in SKILL.md~~ — it is `5. Execute research:`
- ~~fork support in Codex~~ — the Codex twin always runs sequentially

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".agent/workflows/sdd-proposal.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-brainstorm.md", "action": "MODIFY"},
    {"path": ".agents/skills/sdd-proposal/SKILL.md", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_command_twin_parity.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

## Implementation Blueprint

### Steps (in order)
1. Regenerate each workflow twin: keep the twin's frontmatter, append the command body (frontmatter stripped), apply the substitution — because parity is asserted byte-for-byte.
2. Edit SKILL.md (3 spots).
3. Extend the parity test and run it.

### `tests/sdd_scripts/test_command_twin_parity.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^_TWINNED = ' tests/sdd_scripts/test_command_twin_parity.py)
_TWINNED = ("sdd-brainstorm", "sdd-next", "sdd-proposal", "sdd-spec", "sdd-status", "sdd-task")

# add inside _SUBSTITUTIONS:
    "sdd-brainstorm": (
        '- Worktree policy: `CLAUDE.md` (section "Worktree Policy")',
        "- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`",
    ),
    "sdd-proposal": (
        '- Worktree policy:          `CLAUDE.md` (section "Worktree Policy")',
        "- Worktree policy:          `AGENTS.md` and `sdd/WORKFLOW.md`",
    ),
```

### `.agents/skills/sdd-proposal/SKILL.md` (MODIFY)
```markdown
<!-- :20 → append ` [--no-parallel]` before the closing backtick -->
<!-- AFTER the `| loose | ...` row under :59: -->
`default`/`loose` may split Phase 2 into codebase/git/wiki lanes on hosts with
forks (Claude Code). Codex has no forks: research always runs sequentially and
`--no-parallel` is accepted as a no-op.
<!-- under `5. Execute research:` (:88), new first bullet: -->
   - Sequential here (no forks). Findings are `FNNN`; no lane merge step.
```

### FILL IN checklist
- [ ] Copy the substitution strings byte-exactly from the files (the sdd-proposal one has aligned spaces)
- [ ] Mention the citation probe? — Codex runs citation checks inline; add one bullet under `6. Synthesize:` only if the command's §4d is referenced by name

## Acceptance Criteria

- [ ] `test_command_twin_parity.py` passes for all 6 commands
- [ ] SKILL.md documents `--no-parallel` and the sequential Codex behavior
- [ ] No command file edited by this task

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

**Completed by**: sdd-worker (orchestrator) — coder seat gemini-3.5-flash (google-compat), attempt 1
**Date**: 2026-10-20
**Notes**: synced twins/SKILL.md/parity test; delivery missed required substitution entries (attempt 'salvaged'), orchestrator fixed in 9343439a7; feedback coder-feedback:199c878b4abb2bca05063cd4. Orchestrator read the full diff (1b06831ea); merge-tier validation green. Seat: gemini-3.5-flash · Backend: google-compat · Attempts: 1 · Duration: 134.0s. Closed via close_task.sh (finalize_task unavailable: no review EvidenceRef resolvable from the engine store).

**Deviations from spec**: none
