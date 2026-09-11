# TASK-3158: `sdd-planner`, `sdd-research`, `sdd-autopilot` use the shared rule

**Feature**: FEAT-552 — Worktree Creation Ownership
**Spec**: `sdd/specs/worktree-creation-ownership.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3154
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. These three agents keep creating the worktree — deliberately.
They plan *and* dispatch in the same run on the same machine, so their intention
to implement is contemporaneous and legitimate; that is the documented exception
in spec §2 point 3.

What they must stop doing is hand-building the name. `sdd-planner` and
`sdd-research` use `feat-<id>-<slug>` while everything else uses
`feat-<FEAT-ID>-<slug>`. That single disagreement is why this clone holds both
`feat-538-workingmemory-toolkit` and `feat-FEAT-538-workingmemory-toolkit` for
one feature, and why `/sdd-done`'s `grep "feat-<FEAT-ID>"` can miss a worktree
the dev-loop created.

---

## Scope

- Replace the inline `git worktree add` in `sdd-planner` step 4,
  `sdd-research` step 5, and `sdd-autopilot` §6 with
  `python -m scripts.sdd.ensure_worktree --json`.
- Restate each agent's "cardinal rule" about branch naming so it points at
  `plan_worktree` instead of quoting a template.
- Mirror all three edits byte-identically into `_subagent_data/`.

**NOT in scope**: `sdd-worker` (TASK-3157); changing *whether* these agents
create the worktree — they still do.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/agents/sdd-planner.md` | MODIFY | step 4 + cardinal rule |
| `.claude/agents/sdd-research.md` | MODIFY | step 5 + cardinal rule |
| `.claude/agents/sdd-autopilot.md` | MODIFY | §6 Create Worktree |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-planner.md` | MODIFY | Byte-identical twin |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | Byte-identical twin |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-autopilot.md` | MODIFY | Byte-identical twin |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```
.claude/agents/sdd-planner.md
  line 54-58  4. **Create the worktree** at ``.claude/worktrees/feat-<id>-<slug>/``
              using ``git worktree add -b feat-<id>-<slug> … HEAD``
              from the base branch (``dev``, unless the spec's frontmatter says otherwise).
  line 68     - The worktree branch name MUST match ``feat-<id>-<slug>`` so the …

.claude/agents/sdd-research.md
  line 95-98  5. **Create the worktree**. The base ref and branch/worktree naming depend
              on the spec's ``type`` (FEAT-466 …):
              - ``hotfix``: ``git worktree add -b hotfix-<JIRA-KEY>-<slug> … origin/main``
              - ``feature``: ``git worktree add -b feat-<id>-<slug> … origin/dev``
  line 110    - The worktree branch name MUST match ``feat-<id>-<slug>`` (features) or …

.claude/agents/sdd-autopilot.md
  line 251    #### 6. Create Worktree
  line 253-254  git worktree add -b feat-<FEAT-ID>-<slug> \
                  .claude/worktrees/feat-<FEAT-ID>-<slug> HEAD
```
Each anchor occurs exactly once (verified with `grep -cF`, 2026-09-11).

`sdd-autopilot` already emits the canonical name; it still moves to the CLI so
there is one creator implementation, not four.

### The twins — byte parity is ENFORCED
`packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py` asserts every
`_subagent_data/<name>.md` is byte-identical to `.claude/agents/<name>.md`. All
three pairs are identical today (verified with `cmp -s`). `load_subagent_definition()`
reads ONLY the packaged copy, so an un-mirrored edit means dev-loop keeps
dispatching the old prompt *and* the suite goes red.

### Contracts these agents must keep satisfying
```python
# sdd-planner emits PlannerOutput, sdd-research emits ResearchOutput — both carry
# a worktree path field. That is why ensure_worktree has --json (spec §8):
#   {"name": ..., "path": ..., "base_ref": ..., "created": true}
```
Verify the exact field name in the Pydantic model before writing the agent text:
`grep -rn "worktree" packages/ai-parrot/src/parrot/flows/dev_loop/models.py`

### Does NOT Exist
- ~~a fourth naming template~~ — there are exactly two today, and after this task
  exactly one, owned by `plan_worktree`
- ~~`sdd-autopilot` in `.agent/workflows/`~~ — it is an agent; its twin is under
  `_subagent_data/`
- ~~a reason to keep `HEAD` as the base ref~~ — `plan_worktree` returns
  `origin/<base_branch>`; `HEAD` is what let a hotfix inherit `dev` (FEAT-466)

---

## Implementation Notes

### Key Constraints
- Keep each agent's step number and surrounding prose; swap the mechanism only.
- A cardinal rule must not quote a name template any more. Replace with:
  *"The worktree name is whatever `scripts.sdd.sdd_meta.plan_worktree` returns —
  never hand-built."*
- Use `--json` in these three (not the bare-path form): each agent has to put
  the path into a structured output contract.
- `sdd-research` handles hotfixes; keep that branch, expressed as `--jira-key`.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm the output-model field name with the `grep` in the Codebase Contract
   — *why*: the agent text tells the model which JSON key feeds which field; a
   wrong name here is silent until a dev-loop run fails.
2. Edit the three `.claude/agents/` files — *why*: they are the human-readable
   source of truth.
3. Mirror each into `_subagent_data/` with `cp`, then `cmp` — *why*: enforced.
4. Run `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q`.

### `.claude/agents/sdd-planner.md` (MODIFY)
```
# occurrences: 1 (verified: grep -cF '4. **Create the worktree** at' .claude/agents/sdd-planner.md)
# REPLACE — step 4, lines 54-58

4. **Create the worktree** through the shared rule — never hand-build the
   name or the base ref (FEAT-552)::

       python -m scripts.sdd.ensure_worktree --json \
         --slug <slug> --feature-id FEAT-<NNN> \
         --spec sdd/specs/<slug>.spec.md \
         --index sdd/tasks/index/<slug>.json

   Take ``path`` from the JSON object it prints for your output contract. The
   command is idempotent: it reuses an existing worktree rather than failing.

# occurrences: 1 (verified: grep -cF 'The worktree branch name MUST match' .claude/agents/sdd-planner.md)
# REPLACE — the cardinal rule at line 68

- The worktree name is whatever ``scripts.sdd.sdd_meta.plan_worktree``
  returns — never hand-built. Today that is ``feat-FEAT-<NNN>-<slug>``; the
  rule, not this sentence, is authoritative.
```
**Why**: the planner previously wrote `feat-<id>-<slug>`, half of the drift this
feature removes. Deferring to the function by name is what stops it recurring.

### `.claude/agents/sdd-research.md` (MODIFY)
```
# occurrences: 1 (verified: grep -cF '5. **Create the worktree**.' .claude/agents/sdd-research.md)
# REPLACE — step 5, lines 95-98

5. **Create the worktree** through the shared rule. Naming and base ref follow
   the spec's ``type`` automatically (FEAT-466: a hotfix has no reserved id, so
   it is named from its Jira key and branches from ``origin/main``)::

       # feature
       python -m scripts.sdd.ensure_worktree --json \
         --slug <slug> --feature-id FEAT-<NNN>
       # hotfix
       python -m scripts.sdd.ensure_worktree --json \
         --slug <slug> --jira-key <JIRA-KEY>

   Take ``path`` from the JSON object for your output contract.

# occurrences: 1 (verified: grep -cF 'The worktree branch name MUST match' .claude/agents/sdd-research.md)
# REPLACE — the cardinal rule at line 110, with the same sentence used in sdd-planner,
#           extended with: "…; for a hotfix that is ``hotfix-<JIRA-KEY>-<slug>``."
```
**Why**: research is the hotfix lane. Its two bullets become two flags, and the
`origin/main` guarantee moves from prose into `plan_worktree`, where it cannot
be forgotten by the next editor.

### `.claude/agents/sdd-autopilot.md` (MODIFY)
```
# occurrences: 1 (verified: grep -cF '#### 6. Create Worktree' .claude/agents/sdd-autopilot.md)
# REPLACE — the fenced block at lines 252-255 (keep the `#### 6. Create Worktree` heading)

python -m scripts.sdd.ensure_worktree --json \
  --slug <slug> --feature-id FEAT-<NNN> \
  --spec sdd/specs/<slug>.spec.md \
  --index sdd/tasks/index/<slug>.json
```
**Why**: autopilot already emits the canonical name, so this is consolidation
rather than a fix — but leaving one hand-rolled creator would re-open the drift
the moment the rule changes.

### twins (MODIFY)
```bash
for a in sdd-planner sdd-research sdd-autopilot; do
  cp ".claude/agents/$a.md" \
     "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/$a.md"
  cmp ".claude/agents/$a.md" \
      "packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/$a.md" || exit 1
done
```

### FILL IN checklist
- [ ] the exact `worktree*` field name in `PlannerOutput` / `ResearchOutput`;
      bounded by the grep in the Codebase Contract — quote the real name in the
      agent text rather than "the path field"

---

## Acceptance Criteria

- [ ] `grep -rc "git worktree add" .claude/agents/sdd-planner.md .claude/agents/sdd-research.md .claude/agents/sdd-autopilot.md` returns `0` for all three
- [ ] `grep -rn "feat-<id>-<slug>" .claude/ --exclude-dir=worktrees` returns nothing
- [ ] All three files reference `scripts.sdd.ensure_worktree` with `--json`
- [ ] `sdd-research` documents both `--feature-id` and `--jira-key`
- [ ] No cardinal rule quotes a name template as authoritative; each defers to `plan_worktree`
- [ ] `cmp` exits 0 for all three `.claude/agents/` ↔ `_subagent_data/` pairs
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_subagent_parity.py -q` passes

---

## Test Specification

Covered by the existing `test_subagent_parity.py`; the grep criteria become
permanent in TASK-3160.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 6, §2 point 3 for why
   these three keep creating the worktree)
2. **Check dependencies** — TASK-3154 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `cmp -s` all three pairs before starting
4. **Update status** in `sdd/tasks/index/worktree-creation-ownership.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3158-orchestrators-shared-rule.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
