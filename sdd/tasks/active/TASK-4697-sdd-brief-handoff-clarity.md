# TASK-4697: `/sdd-brief` hand-off states that `/sdd-done` opens the PR and removes the worktree

**Feature**: FEAT-740 — Fast lane runs in its own worktree (never the main checkout)
**Spec**: `sdd/specs/sdd-fix-brief-change.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3**. `/sdd-brief` correctly keeps its worktree after
it finishes — implementation happens inside it — and leaves the PR and the
cleanup to `/sdd-done <KEY>`. But its Step 12 hand-off only says "run
`/sdd-done <KEY>` after implementation", so it reads as if the brief lane never
opens a PR and leaves worktrees behind. This task makes the hand-off explicit.
No behaviour changes (spec §1 Non-Goals).

---

## Scope

- Replace the last line of Step 12 in `.claude/commands/sdd-brief.md` (line 179)
  with the spec's three-line sentence.
- Apply the identical replacement in `.agent/workflows/sdd-brief.md` (line 183).

**NOT in scope**:
- `.agents/skills/sdd-brief/SKILL.md` — condensed Codex twin, has no Step 12; it is
  only token-checked and already carries `$sdd-done <KEY>`. Do not edit it.
- Any other line of either file; any behaviour change to `/sdd-brief`; any test edit.
- The three `/sdd-fix` twins (TASK-4695); policy docs (TASK-4696).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-brief.md` | MODIFY | Step 12 final line → explicit `/sdd-done` hand-off |
| `.agent/workflows/sdd-brief.md` | MODIFY | Identical replacement (agy twin) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
None — Markdown only.

### Existing Signatures to Use
```text
# .claude/commands/sdd-done.md — the behaviour the new sentence describes
lines 116-126: a non-FEAT input is treated as a brief KEY/slug; reads base_branch and
               ledger_issue from sdd/briefs/<slug>.brief.md; verifies every per-brief task is done
line 870:      git worktree remove "$WORKTREES_DIR/feat-<FEAT-ID>-<slug>"   (Step 11 cleanup)
```

### Test contract (`tests/sdd_scripts/test_sdd_brief_twin_contract.py:38-52`)
```text
test_agy_preserves_full_procedure_with_native_handoff:
  expected = claude_text
      .replace("```bash\ncd <wt> && claude --agent sdd-worker --model sonnet --verbose\n```",
               "```text\nOpen <wt> in agy and ask: Use the sdd-worker subagent to implement <KEY>.\n```")
      .replace("`cd <wt> && claude --agent sdd-worker --model sonnet --verbose`,",
               "open `<wt>` in agy and ask the `sdd-worker` subagent to implement `<KEY>`,")
  assert agy body (after its frontmatter) == expected
  assert "claude --agent" not in agy
tests/sdd_scripts/test_sdd_brief_command_contract.py: .claude/commands/sdd-brief.md must keep
  "python -m scripts.sdd.ensure_worktree", "--brief-key <KEY>", the ledger-base refusal message,
  "path:line", "refuse to create the worktree", and must not contain "git worktree add"
```

### Does NOT Exist
- ~~`### 12. Hand Off` in `.agents/skills/sdd-brief/SKILL.md`~~ — the Codex twin is condensed and has no such section.
- ~~a `/sdd-brief --pr` or `--cleanup` flag~~ — `/sdd-brief` opens no PR and removes nothing; do not invent one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": ".claude/commands/sdd-brief.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-brief.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Apply the **same** replacement to both files — because the agy twin must equal the
  Claude file with only the two launch-command replacements, and the replaced line
  contains neither launch string, so identical text in both keeps the equality.
- The new text must never contain `claude --agent` (forbidden in the agy twin) or
  `git worktree add` (forbidden in the Claude command).

---

## Implementation Blueprint

### Steps (in order)
1. Re-run both anchor counts below; each must be `1` — *why*: drift check since 87341f43c.
2. Replace the anchor line in both files with the block below — *why*: spec §3 M3 skeleton.
3. Run the Validation Commands — *why*: the agy-equality test is the real proof both edits match.

### `.claude/commands/sdd-brief.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -cF 'Finish by directing the owner to run `/sdd-done <KEY>` after implementation.' .claude/commands/sdd-brief.md)
# REPLACE line 179 (verified: .claude/commands/sdd-brief.md:179) WITH:
Finish by directing the owner to run `/sdd-done <KEY>` after implementation: it verifies the
brief's tasks, opens the PR against `base_branch`, and removes this worktree. `/sdd-brief`
itself opens no PR and removes nothing — the worktree must survive for implementation.
```
**Why**: names the PR+cleanup owner explicitly (AC-9) without changing behaviour.

### `.agent/workflows/sdd-brief.md` (MODIFY)
```text
# occurrences: 1 (verified: grep -cF 'Finish by directing the owner to run `/sdd-done <KEY>` after implementation.' .agent/workflows/sdd-brief.md)
# REPLACE line 183 (verified: .agent/workflows/sdd-brief.md:183) WITH the identical three lines above.
```
**Why**: keeps `test_agy_preserves_full_procedure_with_native_handoff` green.

### FILL IN checklist
- [ ] none — the replacement is fixed by the spec.

---

## Acceptance Criteria

- [ ] AC-9: both files contain `opens the PR against \`base_branch\`, and removes this worktree`.
- [ ] AC-9: `grep -c 'claude --agent' .agent/workflows/sdd-brief.md` is `0`.
- [ ] `test_agy_preserves_full_procedure_with_native_handoff` passes.
- [ ] Only the two files above are modified.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_sdd_brief_twin_contract.py -q`
- `pytest tests/sdd_scripts/test_sdd_brief_command_contract.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

No new tests (spec §8 Q2 — "prose only"). Baseline: green on `dev` at `02d113e88`
(part of a 93-passed baseline run).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-fix-brief-change --feature-id FEAT-740`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none for this task
4. **Verify the Codebase Contract** — re-run the `grep -cF` anchor counts before editing
5. **Update status** in `sdd/tasks/index/sdd-fix-brief-change.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — apply the replacement to both files
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the two files (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4697 sdd-fix-brief-change verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
