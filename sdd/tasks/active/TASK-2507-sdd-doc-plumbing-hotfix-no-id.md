# TASK-2507: SDD doc plumbing — flow-type flags and "a hotfix reserves no id"

**Feature**: FEAT-466 — Dev-Loop Run Fidelity
**Spec**: `sdd/specs/dev-loop-run-fidelity.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2502
**Assigned-to**: unassigned

---

## Context

Implements the **markdown half of spec Module 2** plus all of **Module 3**.
These are merged into one task because they edit the same three files;
splitting them would guarantee conflicts.

Two of the three links in the FEAT-466 failure chain live in markdown, not
Python:

**Link 1 — `/sdd-spec` silently defaults, and cannot be told otherwise.**
`.claude/commands/sdd-spec.md:131` says:

> "Read the brainstorm/proposal frontmatter (**or default to `feature`/`dev`
> when no exploration doc exists**)"

and the usage line (`:6`) is `/sdd-spec <feature-name> [-- notes]` — no way to
pass a type or base branch. The dev-loop bug path *never* has an exploration
doc (`ResearchNode` dispatches `sdd-research`, which calls `/sdd-spec` straight
from the `BugBrief`), so the default always wins. §2d then runs
`git checkout "$BASE_BRANCH"` → `dev`.

**Link 2 — the agent's own correct rule is overridden by the command it calls.**
`.claude/agents/sdd-research.md:61-69` already says the right thing: `kind` of
`bug` → `type: hotfix` / `base_branch: main`, worktree from `origin/main`. But
`/sdd-spec` §5.1 is what actually *writes* the frontmatter, from §2d's values.
And `CLAUDE.md`'s worktree section says to create worktrees from `HEAD`, which
contradicts branching a hotfix from `origin/main`.

On top of that, this task carries FEAT-466's central simplification:
**a bugfix is not a feature and reserves no `FEAT`/`TASK` id.** Ledger ids exist
for features and the brainstorm → spec → task flow. A hotfix is identified by
its Jira issue key. This removes an entire knot: `reserve_ids.py` refuses unless
the current branch equals `--base-branch` (`reserve_ids.py:140`) and the tree is
clean (`:134`), and a branch cannot be checked out in two worktrees — so a
hotfix that had to reserve on `main` would need `main` checked out somewhere it
could push from. Skipping reservation entirely makes the problem vanish rather
than solving it.

---

## Scope

### A. `.claude/commands/sdd-spec.md`

- Extend the usage line to
  `/sdd-spec <feature-name> [--type feature|hotfix] [--base-branch <branch>] [-- notes]`.
- Rewrite §2d to resolve `(TYPE, BASE_BRANCH)` via `resolve_flow()`
  (TASK-2502) rather than calling `parse()` on a possibly-absent path — the
  current snippet crashes with `FileNotFoundError` when no exploration doc
  exists, which is the documented default case. New shape:
  ```bash
  META=$(python -c "
  from pathlib import Path
  from scripts.sdd.sdd_meta import resolve_flow
  m = resolve_flow(
      doc_path=Path('<brainstorm-or-proposal-path>') if '<...>' else None,
      type_override='<--type or empty>',
      base_branch_override='<--base-branch or empty>',
  )
  print(m.type, m.base_branch)")
  ```
- Keep both existing validation aborts (`:141-152`) verbatim — `resolve_flow`
  raises `ValueError` for the hotfix/non-main case, so the command should
  surface that message rather than re-deriving the check.
- Add to §5 (Scaffold the Spec): **when `TYPE == "hotfix"`, skip the
  `reserve_ids.py --kind feature` call entirely.** Write no `FEAT-<NNN>`; the
  spec's identity line carries the Jira issue key instead
  (`**Jira**: <KEY>`). State plainly *why*: a bugfix is not a feature.
- Note that the `reuse_feature_id` escape hatch is unrelated and unchanged.

### B. `.claude/commands/sdd-task.md`

- In §4, skip `reserve_ids.py --kind task` when the spec's `type` is `hotfix`.
  Tasks for a hotfix are numbered locally within the feature
  (`HOTFIX-<JIRA-KEY>-1`, `-2`, …) or the hotfix produces no task artifacts at
  all — **pick one and state it explicitly**; do not leave it ambiguous for the
  implementing agent.
- Keep §1's `type: hotfix` ⇒ `BASE` must be `main` validation.
- Note in §1 that a hotfix's index header carries `feature_id: null` and the
  Jira key.

### C. `.claude/agents/sdd-research.md`

- Step 4: pass the resolved flow explicitly —
  `/sdd-spec <slug> --type <type> --base-branch <base>` — derived from
  `brief.kind` instead of relying on `/sdd-spec` to infer it. Keep the existing
  `kind == "bug"` → `hotfix`/`main` rule; it becomes an instruction to pass
  flags rather than a hope.
- Step 4: for `kind == "bug"`, state that **no `FEAT`/`TASK` id is reserved**.
- Step 5: rename the hotfix branch/worktree from `feat-<id>-<slug>` to
  **`hotfix-<JIRA-KEY>-<slug>`** (there is no id to put in it), keeping
  `origin/main` as the base ref:
  ```
  hotfix:  git worktree add -b hotfix-<JIRA-KEY>-<slug> \
             .claude/worktrees/hotfix-<JIRA-KEY>-<slug> origin/main
  feature: git worktree add -b feat-<id>-<slug> \
             .claude/worktrees/feat-<id>-<slug> origin/dev
  ```
- Update the ResearchOutput example (`:93-95`) so `feat_id` is `""` and
  `branch_name` uses the hotfix shape for a bug brief.
- Update the "branch name MUST match `feat-<id>-<slug>`" constraint (`:81`) to
  cover both shapes.
- Keep the mirrored copy in sync — there is a second copy of this agent
  definition at
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md`
  (see `:93`). **Both must be updated** or the dispatched subagent will read
  stale instructions.

### D. `CLAUDE.md`

- In the "Worktree Creation" section, add a carve-out so the blanket
  "create worktrees manually from the current branch … `HEAD`" no longer
  contradicts the hotfix rule. State: feature worktrees branch from
  `origin/<base_branch>` (usually `dev`); **hotfix worktrees branch from
  `origin/main`**; `HEAD` is the shorthand only when `HEAD` already *is* the
  intended base.
- In the "SDD Auto-Commit Rule" table, note that the `/sdd-spec` and
  `/sdd-task` reservation commits do not occur for `type: hotfix`.

**NOT in scope**:
- Any change to `scripts/sdd/reserve_ids.py`. Spec §1 Non-Goals, with an
  acceptance criterion asserting the file is untouched.
- `resolve_flow()` itself — TASK-2502.
- Python-side consumption of `feat_id == ""` — TASK-2503.
- `ResearchOutput.base_branch` — TASK-2504.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/sdd-spec.md` | MODIFY | `--type`/`--base-branch` flags; §2d via `resolve_flow`; skip FEAT reservation for hotfix |
| `.claude/commands/sdd-task.md` | MODIFY | Skip TASK reservation for hotfix; hotfix index header |
| `.claude/agents/sdd-research.md` | MODIFY | Pass flags; `hotfix-<JIRA-KEY>-<slug>`; no id reserved |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | Keep the mirrored copy in sync |
| `CLAUDE.md` | MODIFY | Worktree carve-out; auto-commit table note |

---

## Codebase Contract (Anti-Hallucination)

### Verified Anchors

```
.claude/commands/sdd-spec.md
  :6     usage line — "/sdd-spec <feature-name> [-- free-form description and notes]"
  :131   "or default to feature/dev when no exploration doc exists"
  :136   the META=$(python -c "... parse(Path('<...>')) ...") snippet
  :141   abort: type='hotfix' requires base_branch='main'
  :147   abort: type='feature' cannot base on 'main'
  :154   note: staging is valid for type: feature during a freeze
  :229   §5 "Frontmatter at the very top: set type and base_branch to the
          values resolved in §2d"
  :234-235  the frontmatter shape block

.claude/commands/sdd-task.md
  :16    "TASK-<NNN> numbers are reserved via scripts/sdd/reserve_ids.py"
  :107   TASK_IDS=$(python -m scripts.sdd.reserve_ids --kind task --count <N> ...)
  :118   "reserve_ids.py commits and pushes its own ledger-only update"

.claude/agents/sdd-research.md
  :8     ".claude/worktrees/feat-<id>-<slug>/"
  :61-64 kind=="bug" -> type: hotfix / base_branch: main
  :66-69 worktree base ref per flow type
  :81    "branch name MUST match feat-<id>-<slug>"
  :93-95 the ResearchOutput JSON example (feat_id / branch_name / worktree_path)

packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md
  :93    mirrored "feat_id": "FEAT-130" example  <-- second copy, keep in sync

CLAUDE.md
  "Worktree Creation" section — 'Do NOT use claude --worktree' +
    'git worktree add -b <branch-name> .claude/worktrees/<name> HEAD'
  "SDD Auto-Commit Rule" table — /sdd-spec and /sdd-task rows
```

```python
# scripts/sdd/reserve_ids.py — READ-ONLY for this feature
def _assert_safe_to_reserve(root: Path, base_branch: str) -> None:   # line 106
    #  refuses on a dirty tree besides the ledger                    # line 134
    #  refuses when current_branch != base_branch                    # line 140
# CLI accepts only: --kind --count --base-branch --label --max-retries  # 305-310
```

```python
# scripts/sdd/sdd_meta.py
def resolve_flow(*, kind=None, doc_path=None, type_override=None,
                 base_branch_override=None) -> FlowMeta   # created by TASK-2502
KNOWN_BRANCHES = frozenset({"main", "staging", "dev"})               # line 26
```

### Does NOT Exist

- ~~`/sdd-spec --type` / `--base-branch`~~ — you are adding them. The current
  usage line accepts only a feature name and `--` notes.
- ~~`reserve_ids.py --ledger-branch`~~ — the CLI has no such flag, and adding
  one is out of scope.
- ~~`hotfix-<JIRA-KEY>-<slug>` naming anywhere~~ — every current path hardcodes
  `feat-<id>-<slug>`.
- ~~a single canonical copy of `sdd-research.md`~~ — there are **two**
  (`.claude/agents/` and `_subagent_data/`). Verify with:
  `find . -name "sdd-research.md" -not -path "*/worktrees/*"`
- ~~`sdd_meta.parse()` tolerating a missing file~~ — it raises
  `FileNotFoundError` (`sdd_meta.py:66`), which is exactly why §2d must move to
  `resolve_flow()`.

---

## Implementation Notes

### Key Constraints

- **These are instruction files for LLM agents, not code.** Optimise for an
  agent reading them cold: state the rule, then the exact command, then the
  reason. Avoid conditional prose an agent can misread — prefer an explicit
  two-branch structure ("if TYPE == hotfix: … / if TYPE == feature: …").
- **Keep the existing abort messages verbatim.** They are quoted in the spec
  and other commands reference them.
- **The two `sdd-research.md` copies must not diverge.** Diff them after
  editing:
  ```bash
  diff .claude/agents/sdd-research.md \
       packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md
  ```
  Understand *why* there are two before editing (one is the Claude Code agent
  registry entry, one ships with the package for dispatched sessions) and
  preserve any intentional differences.
- **Resolve the "hotfix task numbering" question explicitly.** The scope above
  offers two options; pick one, write it down in the command, and record the
  choice in the Completion Note. An ambiguous instruction here will produce
  inconsistent runs.
- `.gitignore` has a global `templates/` rule (CLAUDE.md notes this at line
  245) — irrelevant unless you add a new template, but do not add one.
- Do **not** touch `sdd/templates/spec.md`'s frontmatter block. It already
  documents both `type` values correctly.

### Verification is harder here than for Python tasks

There is no unit test for a markdown instruction file. Verify by **executing
the documented commands by hand** and confirming they behave as written:

```bash
# The old snippet crashes; prove it, then prove the new one does not.
python -c "from pathlib import Path; from scripts.sdd.sdd_meta import parse; parse(Path('nope.md'))"
python -c "from scripts.sdd.sdd_meta import resolve_flow; print(resolve_flow(kind='bug'))"

# Confirm reserve_ids is genuinely untouched.
git diff --stat scripts/sdd/reserve_ids.py     # must be empty
```

### References in Codebase

- `.claude/agents/sdd-research.md:61-69` — the prose rule this task turns into
  passed flags.
- `.claude/commands/sdd-spec.md:229-236` — §5's frontmatter write, the place the
  resolved values land.
- `sdd/specs/dev-loop-run-fidelity.spec.md` §3 Module 2 — the full rationale for
  no-id hotfixes, including the consumer-fallback list.
- `sdd/specs/dev-loop-run-fidelity.spec.md` §8 — the resolved question
  explaining why the allocator is *not* being changed.

---

## Acceptance Criteria

- [ ] `/sdd-spec` documents `--type` and `--base-branch`, and §2d resolves via
      `resolve_flow()` with no possibility of `FileNotFoundError`
- [ ] Both existing `/sdd-spec` validation abort messages are preserved verbatim
- [ ] `/sdd-spec` explicitly instructs: `TYPE == "hotfix"` ⇒ do **not** call
      `reserve_ids.py --kind feature`; no `FEAT-<NNN>` is written; Jira key
      carries identity
- [ ] `/sdd-task` explicitly instructs: hotfix ⇒ do **not** call
      `reserve_ids.py --kind task`, with an unambiguous statement of what
      replaces TASK ids
- [ ] `sdd-research.md` passes `--type`/`--base-branch` derived from
      `brief.kind`, and states that a bug reserves no id
- [ ] `sdd-research.md` documents `hotfix-<JIRA-KEY>-<slug>` branch/worktree
      naming from `origin/main`, and its `ResearchOutput` example shows
      `feat_id: ""` for a bug
- [ ] Both copies of `sdd-research.md` are updated and `diff` shows only
      intentional differences
- [ ] `CLAUDE.md`'s worktree section no longer contradicts the hotfix base ref
- [ ] `scripts/sdd/reserve_ids.py` is unmodified (`git diff --stat` empty)
- [ ] The documented `resolve_flow` snippet runs successfully when pasted into a
      shell from the repo root
- [ ] A dry read-through by a fresh agent: hand `sdd-research.md` to a
      subagent with a `kind="bug"` brief and confirm it describes the correct
      commands without reserving an id

---

## Test Specification

No automated tests — these are instruction documents. Instead, produce
evidence in the Completion Note:

1. Paste-and-run output of the new §2d snippet for all four cases
   (`kind=bug`, `kind=enhancement`, explicit overrides, missing doc path).
2. `git diff --stat` proving `reserve_ids.py` is untouched.
3. The `diff` of the two `sdd-research.md` copies.
4. The fresh-agent read-through result from the last acceptance criterion.

If the repo grows a docs-lint or command-schema check later, wire these files
into it — but do not invent one here.

---

## Agent Instructions

1. **Check your dependency**: TASK-2502 completed and `resolve_flow` importable.
2. **Read the spec** — §1 links 1 and 2, §3 Modules 2 and 3, and §8's resolved
   question on why the allocator is untouched. That reasoning must survive into
   the docs you write.
3. **Read all five target files end to end before editing.** These are
   instruction files; a local edit that contradicts a paragraph three sections
   away is the exact failure mode this task is fixing.
4. **Decide the hotfix task-numbering question early** and write it down.
5. **Verify by execution**, per the section above, and paste the evidence into
   the Completion Note.
6. Move this file to `sdd/tasks/completed/` and set the index entry to `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Hotfix task-numbering decision**:

**Deviations from spec**: none | describe if any
