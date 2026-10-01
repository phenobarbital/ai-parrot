# TASK-3918: Document the unknown health state and the non-SDD discriminator in the command twins

**Feature**: FEAT-619 — worktree_status Tech-Debt Drain (FEAT-582 follow-up)
**Spec**: `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module 4. This is the documentation half of the group's major
finding, `issue:07b75dc7dfae`.

That issue is a **documentation/implementation divergence**, and the issue text
offered two mutually exclusive fixes: (a) make the code emit non-SDD worktrees,
or (b) delete the worked example from the docs. This feature chose **(a)** —
because FEAT-582's own spec §8 had already resolved the question as *"Yes, in
the Worktrees panel only"*. So the existing worked example in the docs is kept
exactly as it is; it stops being aspirational the moment TASK-3915 lands.

What the docs are genuinely missing is everything the code now reports that
they never described: the `flow_type: "non-sdd"` discriminator a reader needs
to recognise such a row in `WT_REPORTS`, and the `unknown` health state
TASK-3916 introduces. Without the latter, an agent rendering the panel from the
documented flag list has no symbol for an unreadable worktree and will fall back
to printing `clean` — re-creating `issue:6b0b91e1f5b2` at the presentation
layer after the library has been fixed.

This task has **no dependency** on the three code tasks: it edits a disjoint set
of files and describes a contract the spec already fixes. It is the one task in
this feature that can run in parallel with the code chain.

---

## Scope

- `.claude/commands/sdd-status.md` §5: add the `unknown` entries to the "Health
  flags" list and state that non-SDD rows are the `WT_REPORTS` entries with
  `flow_type: "non-sdd"`.
- `.agent/workflows/sdd-status.md`: apply the **byte-identical** body edit —
  the two files' bodies differ only by their frontmatter today.
- `.agents/skills/sdd-status/SKILL.md` step 6: one line for each of the same two
  facts, in the skill's condensed style.
- `.claude/commands/sdd-next.md` and `.agents/skills/sdd-next/SKILL.md`: note
  that `flow_type: "non-sdd"` entries carry no tasks and are not suggestion
  candidates, so the `feature_slug` → `WorktreeReport` lookup must skip them.

**NOT in scope**:
- Any code change. This task touches no `.py` file.
- Removing or rewriting the existing `chore-ruff-config` worked example — it is
  correct under fix (a) and must stay.
- Restructuring the panels, adding new panels, or changing the Summary line
  format beyond what these two facts require.
- `.agent/workflows/sdd-next.md` beyond the same note, if it carries the twin
  body of `.claude/commands/sdd-next.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-status.md` | MODIFY | Health flags list + non-SDD discriminator |
| `.agent/workflows/sdd-status.md` | MODIFY | Byte-identical twin of the above |
| `.agents/skills/sdd-status/SKILL.md` | MODIFY | Step 6, condensed form |
| `.claude/commands/sdd-next.md` | MODIFY | Skip non-SDD entries in the lookup |
| `.agent/workflows/sdd-next.md` | MODIFY | Byte-identical twin of the above |
| `.agents/skills/sdd-next/SKILL.md` | MODIFY | Step 2, condensed form |

---

## Codebase Contract (Anti-Hallucination)

### Verified file layout

Each of `sdd-status` and `sdd-next` has **three** copies, verified present:

```
.claude/commands/sdd-status.md          # frontmatter: model: haiku
.agent/workflows/sdd-status.md          # frontmatter: description: ...
.agents/skills/sdd-status/SKILL.md      # condensed numbered-step format
.claude/commands/sdd-next.md
.agent/workflows/sdd-next.md
.agents/skills/sdd-next/SKILL.md
```

None is git-ignored (verified: `git check-ignore -v` returns nothing for all
six), so a plain `git add` works — no `-f` needed.

### Verified anchors

```markdown
<!-- .claude/commands/sdd-status.md:178-181 and .agent/workflows/sdd-status.md (same lines) -->
Health flags:
- `clean` = dirty_count == 0 AND unpushed_count == 0
- `N dirty` = dirty_count > 0
- `N unpushed` = unpushed_count > 0
- `N live processes` = live_process_count > 0
```

```markdown
<!-- .claude/commands/sdd-status.md:192 (same in the twin) -->
Non-SDD worktrees (those with no parsed feature_id) show health only, no task
counts.
```

```markdown
<!-- .agents/skills/sdd-status/SKILL.md:53 -->
   - Non-SDD worktrees show health only, no task counts.
```

```markdown
<!-- .claude/commands/sdd-next.md:55-56 (same in .agent/workflows/sdd-next.md) -->
Build a lookup from `feature_slug` → `WorktreeReport`. This provides task progress
counts and `ready_for_done` flags that the bare `git worktree list` cannot give.
```

```markdown
<!-- .agents/skills/sdd-next/SKILL.md:37 -->
   - Additionally run `python -m scripts.sdd.worktree_status --json` for task-level progress and `ready_for_done` flags.
```

### Verified twin invariant

```bash
diff <(sed '1,/^---$/d;1,/^---$/d' .claude/commands/sdd-status.md) \
     <(sed '1,/^---$/d;1,/^---$/d' .agent/workflows/sdd-status.md)
# → empty today. It MUST still be empty after this task.
```

### Does NOT Exist

- ~~`tests/sdd_scripts/test_command_twin_parity.py` covering `sdd-status`~~ —
  its `_TWINNED` tuple is `("sdd-spec", "sdd-task")` only (verified:
  `tests/sdd_scripts/test_command_twin_parity.py:22`). Nothing automatically
  catches drift between the `sdd-status` / `sdd-next` twins, so the `diff`
  above is a manual acceptance criterion, not something a test will enforce.
- ~~A `.agent/skills/` directory~~ — the skills live under `.agents/skills/`
  (plural `agents`), while the workflows live under `.agent/workflows/`
  (singular `agent`). These are two different trees; do not conflate them.
- ~~A generator that produces the twins from one source~~ — they are
  hand-maintained copies.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/sdd-status.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-status.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-status/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/commands/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/sdd-next.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/sdd-next/SKILL.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key constraint — the twins

`.claude/commands/<name>.md` and `.agent/workflows/<name>.md` have
byte-identical bodies and differ only in frontmatter. Make the **same** edit in
both, in the same commit. No test enforces this for `sdd-status`/`sdd-next`
(see "Does NOT Exist"), so verify it yourself with the `diff` in the Codebase
Contract before committing.

### Naming must match the code exactly

The strings an agent will key on are `"non-sdd"` (the `flow_type` value) and
the attribute names `dirty_unknown` / `unpushed_unknown`. Quote them verbatim —
a near-miss like `non_sdd` or `"nonsdd"` makes the documentation actively
wrong.

### The `.agents/skills/` files are condensed

Do not paste the command's prose into the SKILL files. Match the surrounding
one-line numbered-step style.

---

## Implementation Blueprint

### Steps (in order)

1. Edit `.claude/commands/sdd-status.md` — *why*: it is the canonical copy; the
   workflow twin is derived from it by hand.
2. Apply the identical body edit to `.agent/workflows/sdd-status.md` and run the
   `diff` — *why*: silent twin drift is the failure mode this repo keeps hitting.
3. Edit `.agents/skills/sdd-status/SKILL.md` step 6 in condensed style.
4. Repeat 1–3 for the `sdd-next` trio.
5. Run the doc-contract tests — *why*: `test_command_contracts.py` and
   `test_command_twin_parity.py` both read this tree and must stay green.

### `.claude/commands/sdd-status.md` (MODIFY) — health flags

```markdown
# occurrences: 1 (verified: grep -c '^- `N live processes` = live_process_count > 0' .claude/commands/sdd-status.md)
# AFTER — insert below `- ``N live processes`` = live_process_count > 0` (verified: .claude/commands/sdd-status.md:181)
- `dirty:unknown` = `dirty_unknown: true` — `git status` failed; the worktree is
  NOT known to be clean
- `unpushed:unknown` = `unpushed_unknown: true` — `git log origin/<base>..HEAD`
  failed, usually a missing remote-tracking ref

`clean` means every signal was read successfully and all were zero. A worktree
with either `unknown` flag is never `clean` and never `ready_for_done`.
```

**Why**: the flag list is the contract an agent renders the panel from; without
these two rows it has no symbol for "unreadable" and will print `clean`,
re-creating `issue:6b0b91e1f5b2` one layer up.

### `.claude/commands/sdd-status.md` (MODIFY) — non-SDD discriminator

```markdown
# occurrences: 1 (verified: grep -c 'Non-SDD worktrees (those with no parsed feature_id) show health only, no task' .claude/commands/sdd-status.md)
# REPLACE the sentence `Non-SDD worktrees (those with no parsed feature_id) show health only, no task\ncounts.` (verified: .claude/commands/sdd-status.md:192-193)
Non-SDD worktrees are the `WT_REPORTS` entries with `flow_type: "non-sdd"`
(`feature_id: null`, empty `tasks[]`, `ready_for_done: false`). Show health
only, no task counts, and append ` (non-SDD)` to the name as in the example
above. They never appear on the task board — `--reconcile` excludes them.
```

**Why**: names the exact JSON discriminator, so the panel is rendered from data
instead of from a guess about which rows "look" non-SDD.

### `.agent/workflows/sdd-status.md` (MODIFY)

```markdown
# Apply BOTH blocks above verbatim to this file at the same anchors.
# occurrences: 1 each (verified: grep -c '<anchor>' .agent/workflows/sdd-status.md)
# Then verify byte-identical bodies:
#   diff <(sed '1,/^---$/d;1,/^---$/d' .claude/commands/sdd-status.md) \
#        <(sed '1,/^---$/d;1,/^---$/d' .agent/workflows/sdd-status.md)
# must print nothing.
```

### `.agents/skills/sdd-status/SKILL.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c '   - Non-SDD worktrees show health only, no task counts.' .agents/skills/sdd-status/SKILL.md)
# REPLACE the line `   - Non-SDD worktrees show health only, no task counts.` (verified: .agents/skills/sdd-status/SKILL.md:53)
   - Non-SDD worktrees (`flow_type: "non-sdd"`) show health only, no task counts; mark them ` (non-SDD)`.
   - A `dirty_unknown`/`unpushed_unknown` worktree renders `unknown`, never `clean`, and is never ready for `/sdd-done`.
```

### `.claude/commands/sdd-next.md` + `.agent/workflows/sdd-next.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'counts and `ready_for_done` flags that the bare `git worktree list` cannot give.' .claude/commands/sdd-next.md)
# AFTER — insert below the line ending `...that the bare ``git worktree list`` cannot give.`
# (verified: .claude/commands/sdd-next.md:56; same anchor in .agent/workflows/sdd-next.md)
Skip entries whose `flow_type` is `"non-sdd"` — they carry no `tasks[]` and no
feature, so they can never be the source of a next-task suggestion.
```

**Why**: `/sdd-next` builds a `feature_slug` → `WorktreeReport` lookup, and a
non-SDD entry's `feature_slug` is its **branch name**. Without this line it
would enter the lookup and could shadow a real feature whose slug happens to
match a branch name.

### `.agents/skills/sdd-next/SKILL.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'Additionally run `python -m scripts.sdd.worktree_status --json` for task-level progress and `ready_for_done` flags.' .agents/skills/sdd-next/SKILL.md)
# AFTER — insert below that line (verified: .agents/skills/sdd-next/SKILL.md:37)
   - Ignore `flow_type: "non-sdd"` entries — they have no tasks and are not suggestion candidates.
```

### FILL IN checklist

None — every block above is complete, verbatim documentation text. The only
judgement left is matching the surrounding markdown style if an anchor has
moved, in which case re-locate it and report the drift rather than inventing a
new attachment point.

---

## Acceptance Criteria

- [ ] AC10 — `.claude/commands/sdd-status.md`, `.agent/workflows/sdd-status.md`
      and `.agents/skills/sdd-status/SKILL.md` describe the `unknown` health
      state and the `"non-sdd"` discriminator; the `/sdd-next` trio notes that
      non-SDD rows are not suggestion candidates.
- [ ] The `sdd-status` twin bodies remain byte-identical (the `diff` in the
      Codebase Contract prints nothing); likewise for the `sdd-next` twins.
- [ ] The existing `chore-ruff-config  (non-SDD)` worked example is unchanged.
- [ ] No `.py` file is modified by this task.
- [ ] `pytest tests/sdd_scripts/test_command_contracts.py tests/sdd_scripts/test_command_twin_parity.py -q`
      passes.

---

## Validation Commands

- `pytest tests/sdd_scripts/test_command_twin_parity.py -q`
- `pytest tests/sdd_scripts/test_command_contracts.py -q`

---

## Test Specification

No new tests. This task is documentation-only; the two existing contract/parity
suites are the regression net, and the twin `diff` in the Acceptance Criteria is
the manual check they do not cover for these two commands.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug sdd-worktree-status-tech-debt --feature-id FEAT-619`)
2. **Read the spec** at `sdd/specs/sdd-worktree-status-tech-debt.spec.md`
3. **Check dependencies** — none. This task may run in parallel with
   TASK-3915/3916/3917; it shares no file with them.
4. **Verify the Codebase Contract** — re-`grep` each anchor and its occurrence
   count before editing.
5. **Update status** in `sdd/tasks/index/sdd-worktree-status-tech-debt.json` →
   `"in-progress"` (set `started_at`) and commit only that index file.
6. **Implement** from the Implementation Blueprint — the blocks are verbatim.
7. **Verify** all acceptance criteria, including the twin `diff`.
8. **Commit the docs** — stage only the six files this task lists.
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-3918 sdd-worktree-status-tech-debt verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
