# TASK-3094: `/sdd-task` command — Implementation Blueprint rules (+ `.agent/workflows` twin)

**Feature**: FEAT-545 — Collaborative Adversarial Spec Design
**Spec**: `sdd/specs/collaborative-adversarial-spec-design.spec.md` (§3 Module 2, §2 Overview A)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3093
**Assigned-to**: unassigned

---

## Context

TASK-3093 gives the task template an `## Implementation Blueprint` section. This task makes `/sdd-task` *fill* it: it rewords the "tasks are plans, not code" guardrail, adds the blueprint rules to §3, requires the section in §4, and reports blueprint coverage in §7. The command has a twin at `.agent/workflows/sdd-task.md` that must receive the same body edits (spec G5; parity test lands in TASK-3098).

---

## Scope

- Edit `.claude/commands/sdd-task.md`: guardrail line, §3 new CRITICAL block, §4 step 4 sentence, §7 output line.
- Mirror the body into `.agent/workflows/sdd-task.md`, preserving ONLY its 4-line YAML frontmatter and its `- Worktree policy:` line.

**NOT in scope**: template text (TASK-3093); `/sdd-spec` (TASK-3097); parity test (TASK-3098); any Python.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-task.md` | MODIFY | 4 edits listed in the blueprint |
| `.agent/workflows/sdd-task.md` | MODIFY | Same 4 edits (body parity) |

---

## Codebase Contract (Anti-Hallucination)

### Anchors in `.claude/commands/sdd-task.md` (292 lines, verified 2026-09-10)
```text
:10-15   ## Guardrails
:14      - Do NOT write implementation code — tasks are plans, not code.        ← REPLACE
:84      ### 3. Plan Task Decomposition
:96      **CRITICAL — Codebase Contract per Task (Anti-Hallucination):**         ← new block goes AFTER this block's "Quality bar" paragraph (:110-112)
:110-112 **Quality bar**: A task without a populated Codebase Contract section is incomplete. ... WILL hallucinate ...
:114     ### 4. Generate Tasks
:154-159 4. For each task, create `sdd/tasks/active/<id>-<slug>.md` using the template ... never invent, recompute, or reuse a `TASK-<NNN>` number
:271     ### 7. Output   (:273 "✅ Generated and committed <N> tasks for FEAT-<ID> — <feature-name>", :276 "Tasks created:")
```
### Twin `.agent/workflows/sdd-task.md` (296 lines)
```text
:1-4     ---\ndescription: ...\n---\n(blank)          ← keep verbatim (twin-only)
:47      (sub-features extend a parent feature branch — see `AGENTS.md`).   ← keep; original (.claude/commands/sdd-task.md:46) says `CLAUDE.md`
```
**Contract correction (verified 2026-09-10, re-grepped against actual files — the
original text above describing a "`- Worktree policy:`" line was stale/not
present in either file)**: the ONLY twin-only delta today is (a) the 4-line
YAML frontmatter block and (b) this single `AGENTS.md`/`CLAUDE.md` substitution
on the "sub-features extend a parent feature branch" line. All other lines must
equal the `.claude/commands` original (`diff .agent/workflows/sdd-task.md
.claude/commands/sdd-task.md` → exactly 6 changed lines: 4 added frontmatter +
1 changed substitution line, i.e. `grep -c '^[<>]'` → 6).

### Does NOT Exist
- ~~`### 3b.`~~ in sdd-task.md — that step belongs to `/sdd-spec` (TASK-3097), not here
- ~~a Python "blueprint linter"~~ — the ~80-line cap is a written rule (spec §8 open question defaults to "written rule only")
- ~~`Blueprints:` line~~ in §7 output — added by this task

---

## Implementation Notes

### Pattern to Follow
The new §3 block mirrors the existing "**CRITICAL — Codebase Contract per Task (Anti-Hallucination):**" block (`sdd-task.md:96-112`): bold title, numbered rules, closing **Quality bar** paragraph.

### Key Constraints
- Edit `.claude/commands/sdd-task.md` first; then produce the twin with `tail -n +5 .claude/commands/sdd-task.md` appended to the twin's first 4 lines, then restore the twin's `- Worktree policy:` line. Verify with `diff` that only those lines differ.
- Explain-for-executor rule must be stated as a rule (it is what makes blueprints usable by Haiku).

---

## Implementation Blueprint

### Steps (in order)
1. Replace the guardrail line — *why*: the old text forbids exactly what the section requires.
2. Insert the CRITICAL block after the Codebase Contract "Quality bar" paragraph in §3 — *why*: blueprint is the second per-task quality gate, same rank as the contract.
3. Add one sentence to §4 step 4 — *why*: the generation step must name the section it fills.
4. Add the `Blueprints:` line to §7 — *why*: coverage is visible in the command output.
5. Regenerate the twin and `diff` it — *why*: G5 / parity test.

### `.claude/commands/sdd-task.md` (MODIFY — line 14)
```markdown
# BEFORE (verified :14)
- Do NOT write implementation code — tasks are plans, not code.
# AFTER
- Do NOT write the full implementation — but every task MUST carry an
  **Implementation Blueprint** (executor-ready per-file code blocks + why +
  `FILL IN` checklist, see §3). Blueprints stop at the mechanical parts;
  branches, edge cases and test bodies stay as `FILL IN` stubs.
```

### `.claude/commands/sdd-task.md` (MODIFY — insert after the "Quality bar" paragraph that ends "...explicit, verified code anchors." at :110-112)
````markdown

**CRITICAL — Implementation Blueprint per Task (Executor Readiness, FEAT-545):**
For EACH task, you MUST populate its `## Implementation Blueprint` section so a
non-thinking executor (Haiku) can write the declared code to disk and complete
only the marked gaps:

1. **One block per file** listed in "Files to Create / Modify" — CREATE blocks
   are whole-file starting points; MODIFY blocks quote the verified anchor line
   they attach to (`# AFTER — insert below \`<anchor>\` (verified: path:NN)`).
2. **Mechanical code is complete**: imports, class/function signatures,
   docstrings, `self.logger` calls, registration/wiring, return types.
3. **Judgement calls are `FILL IN` stubs**: `# FILL IN: <decision> — bounded by
   <constraint | AC-N>`. Never leave a gap without the constraint that bounds it.
4. **Every import comes from the task's Verified Imports** — the blueprint may
   not introduce a symbol the Codebase Contract does not list.
5. **Derive from the spec's Interface Skeletons** (spec §3) and re-verify the
   anchors now; signatures fixed by the skeleton are not renegotiable.
6. **Size cap**: no block over ~80 lines. If a file needs more, split the task.
7. **Explain-for-executor rule**: every non-trivial decision is written as an
   imperative instruction *plus its reason* ("do X — because Y"), in the
   Steps list and in the **Why** paragraph under each block. Do not rely on
   the executor to infer intent.
8. **Steps (in order)** and the **FILL IN checklist** are mandatory even when
   a task has a single file.

**Quality bar**: A task without a populated Implementation Blueprint section is
incomplete — same bar as the Codebase Contract. If the blueprint would be the
full implementation, the task is too small; if it needs more than ~80 lines per
file, the task is too big.
````

### `.claude/commands/sdd-task.md` (MODIFY — §4 step 4, after "...one per task." :157)
```markdown
# AFTER — append to the end of step 4
   Fill the template's `## Implementation Blueprint` section for every task
   per §3's rules; a task without one is incomplete.
```

### `.claude/commands/sdd-task.md` (MODIFY — §7 Output, after the "Tasks created:" list)
```markdown
Blueprints: <N>/<N> tasks carry an Implementation Blueprint
```

### `.agent/workflows/sdd-task.md` (MODIFY — regenerate body)
```bash
# run from repo root
head -n 4 .agent/workflows/sdd-task.md > /tmp/twin.md          # keep frontmatter
tail -n +5 .claude/commands/sdd-task.md | \
  sed 's|^- Worktree policy: `CLAUDE.md` (section "Worktree Policy")$|- Worktree policy: `AGENTS.md` and `sdd/WORKFLOW.md`|' >> /tmp/twin.md
mv /tmp/twin.md .agent/workflows/sdd-task.md
diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'   # expect 6
```
**Why**: the only tolerated deltas are the twin's frontmatter and the policy line; anything else is drift (TASK-3098 will assert this).

### FILL IN checklist
- [ ] Confirm the exact `- Worktree policy:` wording in the twin before running the sed (verified today as `\`AGENTS.md\` and \`sdd/WORKFLOW.md\``); adjust the sed if it differs.

---

## Acceptance Criteria

- [ ] `grep -n "tasks are plans, not code" .claude/commands/sdd-task.md` → no match (spec AC-4)
- [ ] `grep -n "Implementation Blueprint per Task" .claude/commands/sdd-task.md` → one match inside §3
- [ ] `grep -n "Blueprints: <N>/<N>" .claude/commands/sdd-task.md` → one match inside §7
- [ ] `diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'` → `6`
- [ ] No other file changed

---

## Test Specification

Manual until TASK-3098 adds `test_command_twin_parity[sdd-task]`:
```bash
diff <(tail -n +5 .agent/workflows/sdd-task.md | grep -v '^- Worktree policy:') \
     <(grep -v '^- Worktree policy:' .claude/commands/sdd-task.md) && echo PARITY-OK
```

---

## Agent Instructions

1. Read spec §3 Module 2 and §2 Overview (A).
2. Dependency: TASK-3093 must be in `sdd/tasks/completed/`.
3. Re-grep every anchor above.
4. Index → `"in-progress"`; implement; verify; commit both files together.
5. Move to completed; index → `"done"`; Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Applied all 4 edits to `.claude/commands/sdd-task.md` (guardrail reword, §3 blueprint
CRITICAL block, §4 step 4 sentence, §7 `Blueprints:` line). Regenerated the twin
`.agent/workflows/sdd-task.md`. Corrected a stale Codebase Contract entry: the task's original
contract described a "`- Worktree policy:`" twin-only line that does not exist in either file;
the actual (and only) twin-only delta besides the 4-line frontmatter is the single
`AGENTS.md`/`CLAUDE.md` substitution on the "sub-features extend a parent feature branch" line.
Updated the contract in this file before regenerating, per the anti-hallucination rule. Verified
`diff .agent/workflows/sdd-task.md .claude/commands/sdd-task.md | grep -c '^[<>]'` → 6, matching
the acceptance criterion.

**Deviations from spec**: Codebase Contract correction (twin-delta anchor was stale — see Notes);
no behavioral deviation from the spec's Module 2 responsibility.
