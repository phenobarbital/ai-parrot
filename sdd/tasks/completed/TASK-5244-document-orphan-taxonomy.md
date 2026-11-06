# TASK-5244: Document the orphan taxonomy and regenerate the shipped assets

**Feature**: FEAT-823 — Close the `--stale` work-loss holes in `remove_worktree`
**Spec**: `sdd/specs/scripts-remove-worktree-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5242
**Assigned-to**: unassigned
**Discovered-from**: `issue:751782605094`

---

## Context

The `/remove-worktree` documentation states, of an orphan directory:

```
- `ORPHAN-DIR` — no git record; removal is a plain directory delete.
```

That sentence is the false promise at the centre of `issue:751782605094`. A
coder pool directory carries `ORPHAN-DIR` while holding registered git
worktrees, so "no git record" is wrong and "a plain directory delete" is a
recursive `rmtree` of other people's checkouts. The doc's gate description also
implies `--force` is required before uncommitted work is discarded, which was
not true for any orphan.

TASK-5242 fixes the behaviour. This task implements spec Module 5: make the
documentation describe the behaviour that now exists, in the three hand-edited
sources, then regenerate the copies `parrot sdd install` ships.

---

## Scope

- Update the three repo-root documentation sources with the orphan taxonomy from
  spec §2 and the new nested-registration refusal.
- Regenerate the shipped `_assets/` tree with
  `python scripts/sdd/check_asset_sync.py --write`.

**NOT in scope**:
- Hand-editing anything under
  `packages/ai-parrot/src/parrot/sdd/_assets/` — those files are **generated**.
  Edit the sources and run `--write`.
- Adding rows to `ASSET_SOURCES` in `scripts/sdd/check_asset_sync.py` — all
  three sources are already registered there (L34, L40, L43).
- Changing `remove_worktree.py` (TASK-5242) or the tests (TASK-5243).
- `wiki/` pages. This spec sets no `docs.policy`, so there is no FEAT-801
  documentation task.
- Rewording the `LIVE(n)`, `dirty:n` or `unpushed:n` flag descriptions beyond
  what the new taxonomy requires — they are accurate today.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.claude/commands/remove-worktree.md` | MODIFY | Source for all hosts; orphan taxonomy + refusal |
| `.agent/workflows/remove-worktree.md` | MODIFY | Google workflow twin; same edit |
| `.agents/skills/remove-worktree/SKILL.md` | MODIFY | Codex/Google skill twin; one-line caveat |
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/remove-worktree.md` | MODIFY | **Generated** by `check_asset_sync.py --write` |
| `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/remove-worktree.md` | MODIFY | **Generated** by `check_asset_sync.py --write` |
| `packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/remove-worktree/SKILL.md` | MODIFY | **Generated** by `check_asset_sync.py --write` |
| `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` | MODIFY | **Generated** by `check_asset_sync.py --write` |

---

## Codebase Contract (Anti-Hallucination)

Verified against `237cff8aaa` (dev, 2026-11-06).

### Verified Imports

None — this task writes Markdown and runs one script. No Python is imported.

### Existing Signatures to Use

```python
# scripts/sdd/check_asset_sync.py
ASSET_SOURCES = [
    ...
    (".claude/commands/remove-worktree.md", HOST_ORDER),        # line 34
    (".agents/skills/remove-worktree/SKILL.md", ("codex", "google")),  # line 40
    (".agent/workflows/remove-worktree.md", ("google",)),       # line 43
]
```

Invocations (both verified to exist and `--check` exits 0 on the base commit):

```bash
python scripts/sdd/check_asset_sync.py --check   # verify; exit 0 = in sync
python scripts/sdd/check_asset_sync.py --write   # regenerate the _assets/ tree
```

Verbatim anchors in the two long docs:

```
.claude/commands/remove-worktree.md:45   - `ORPHAN-DIR` — no git record; removal is a plain directory delete.
.agent/workflows/remove-worktree.md:43   - `ORPHAN-DIR` — no git record; removal is a plain directory delete.
.claude/commands/remove-worktree.md:20   | **Orphan directory** | on disk, *not* in `git worktree list` | ...
.agent/workflows/remove-worktree.md:18   | **Orphan directory** | on disk, *not* in `git worktree list` | ...
.agents/skills/remove-worktree/SKILL.md:22  3. Remove only after the user agrees: ... (`--stale` for orphan directories).
```

### Does NOT Exist

- ~~a hand-maintained `_assets/` copy~~ — the three `_assets/` files and
  `manifest.json` are **generated**. Editing them by hand makes
  `check_asset_sync.py --check` fail and will be reverted by the next `--write`.
- ~~`scripts/sdd/check_asset_sync.py --fix`~~ — the flag is `--write`.
- ~~`parrot sdd assets sync`~~ — no such verb; call the script by path.
- ~~a `.agents/workflows/` directory~~ — it is `.agent/workflows/` (singular
  `agent`) for the Google workflow twin and `.agents/skills/` (plural) for the
  Codex/Google skill twin. The two prefixes are different and both real.
- ~~`wiki/sdd-tooling/remove-worktree.md`~~ — does not exist and is not created
  here; this spec declares no `docs.policy`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": ".claude/commands/remove-worktree.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/workflows/remove-worktree.md",
      "action": "MODIFY"
    },
    {
      "path": ".agents/skills/remove-worktree/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/remove-worktree.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/remove-worktree.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/agents/skills/remove-worktree/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/manifest.json",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints

- **Edit sources, then generate.** The seven files are three inputs and four
  outputs. Never the other way round.
- The two long docs are near-identical twins; apply the same edit to both so
  they do not drift. The `SKILL.md` is a 36-line terse skill — it gets one
  caveat sentence, not the whole table.
- Describe what TASK-5242 actually implemented. Read its Completion Note and the
  final code before writing, not the blueprint — the `FILL IN` decisions
  (notably the fail-closed `git status` behaviour) are settled there, and the
  refusal wording must match the real output.
- Keep the existing tone: short flag bullets, imperative steps, no new sections
  unless the taxonomy genuinely needs one.

### References in Codebase

- Spec §2's "Orphan taxonomy" table is the content to adapt — four rows: plain
  container, pool dir holding registrations, deregistered checkout, symlink.
- `TASK-5134-ship-remove-worktree-assets.md` is the task that first shipped
  these three sources and wired them into `ASSET_SOURCES`; its validation
  commands are reused here.

---

## Implementation Blueprint

### Steps (in order)

1. Read TASK-5242's final diff and Completion Note — *why*: the doc must match
   the implemented refusal text and the settled `FILL IN` decisions, not the
   blueprint's intent.
2. Replace the `ORPHAN-DIR` flag bullet in both long docs — *why*: this single
   sentence is the false promise the ledger issue names.
3. Add the orphan taxonomy to the "Two kinds of leftovers" section in both long
   docs — *why*: "two kinds" is now wrong; an orphan has four shapes with
   different gates.
4. Add the one-line caveat to `SKILL.md` — *why*: the terse skill tells an agent
   `--stale` is for orphan directories with no mention that it can refuse.
5. Run `python scripts/sdd/check_asset_sync.py --write` — *why*: regenerates the
   four shipped files; skipping it leaves installed repos promising the old
   semantics.
6. Run `python scripts/sdd/check_asset_sync.py --check` and the two pytest
   commands — *why*: `--check` exiting 0 is AC9's evidence.

### `.claude/commands/remove-worktree.md` and `.agent/workflows/remove-worktree.md` (MODIFY — flag bullet)

```markdown
# occurrences: 1 per file (verified: grep -cF -- '- `ORPHAN-DIR` — no git record; removal is a plain directory delete.' <each file>)
# REPLACE the line `- `ORPHAN-DIR` — no git record; removal is a plain directory delete.`
#   (verified: .claude/commands/remove-worktree.md:45, .agent/workflows/remove-worktree.md:43)
- `ORPHAN-DIR` — on disk but not in `git worktree list`. Removal is a recursive
  directory delete, so it is only "plain" when the directory holds nothing of
  value — see the orphan table above. A `holds:n` flag means it contains `n`
  **registered** worktrees and `--stale` will refuse it.
- `holds:n` — this orphan directory contains n registered worktrees (a coder
  pool dir is the normal case). Remove those individually first — they get
  their own dirty/unpushed gates — then sweep the empty parent.
```

**Why**: the replaced sentence is what `issue:751782605094` is about. The new
`holds:n` bullet documents the flag TASK-5242 adds to `parrot sdd worktree list`,
and points at the workaround that was needed before the fix existed.

### `.claude/commands/remove-worktree.md` and `.agent/workflows/remove-worktree.md` (MODIFY — taxonomy)

```markdown
# occurrences: 1 per file (verified: grep -cF '| **Orphan directory** |' <each file>)
# AFTER — insert below the `| **Orphan directory** | ... |` row
#   (verified: .claude/commands/remove-worktree.md:20, .agent/workflows/remove-worktree.md:18)

Not every orphan is a plain leftover, and `--stale` treats them differently:

| Orphan shape | How you spot it | What `--stale` does |
|---|---|---|
| Plain container — an emptied coder pool dir | `ORPHAN-DIR`, nothing else | removes it; no `--force` needed |
| Pool dir still holding registered worktrees | `ORPHAN-DIR holds:n` | **refuses**, naming each child and its dirty/unpushed counts; `--force` overrides but still prints them |
| Deregistered checkout (its `.git` survives) | `ORPHAN-DIR` plus `dirty:n` / `unpushed:n` | refuses when it has work to lose; `--force` discards it |
| Symlink | not listed at all | skipped, with a warning on stderr |
```

**Why**: spec §2's taxonomy, adapted. The section is titled "Two kinds of
leftovers" and that framing is what let a pool dir read as a plain leftover.
Keep the original two-row table — registered vs orphan is still the first
distinction — and add this table under it rather than rewriting the section.
FILL IN below covers the heading.

```markdown
# FILL IN: the section heading still reads "## Two kinds of leftovers" while the
# section now describes two kinds AND four orphan shapes. Either retitle it or
# leave it — decide once and apply the same choice to BOTH long docs, so
# check_asset_sync.py does not surface a diff between the twins. Bounded by AC9
# (the twins stay in sync) and by the Key Constraint against new sections.
```

### `.agents/skills/remove-worktree/SKILL.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -cF '`--stale` for orphan directories' .agents/skills/remove-worktree/SKILL.md)
# AFTER — insert below line 22 (`3. Remove only after the user agrees: ... (`--stale` for orphan directories).`)
   `--stale` refuses an orphan directory that still holds registered worktrees
   (a coder `--pool` dir is the usual case) and one that is itself a checkout
   with uncommitted or unpushed work. Remove those individually first, then
   sweep the empty parent. Never reach for `--force` to get past the refusal
   without reading what it names.
```

**Why**: this skill is 36 lines and is what Codex and Google hosts read. It tells
an agent `--stale` handles orphan directories and nothing about refusals, so an
agent hitting the new exit code would likely retry with `--force` — which is the
one thing this feature exists to make deliberate. Match the file's existing
indentation under its numbered list.

### Regeneration (no hand edits)

```bash
# Run from the repo root inside the feature worktree, AFTER the three sources are final.
python scripts/sdd/check_asset_sync.py --write
python scripts/sdd/check_asset_sync.py --check   # must exit 0
git status --porcelain packages/ai-parrot/src/parrot/sdd/_assets/
# expect exactly the 3 remove-worktree copies + manifest.json as modified
```

**Why**: `--write` is the only correct way to touch the `_assets/` tree. The
`git status` check is there to catch a regeneration that swept in unrelated
drift — if more than those four files change, stop and report it rather than
committing the extras.

### FILL IN checklist

- [ ] "Two kinds of leftovers" heading — retitle or keep; same choice in both
  long docs; bounded by AC9 and the no-new-sections constraint.

---

## Acceptance Criteria

- [ ] The `ORPHAN-DIR` flag bullet no longer claims "no git record; removal is a
  plain directory delete" in either long doc.
- [ ] Both long docs document all four orphan shapes and what `--stale` does
  with each, and document the `holds:n` flag.
- [ ] `.agents/skills/remove-worktree/SKILL.md` warns that `--stale` can refuse
  and that `--force` should not be reached for blindly.
- [ ] The documented refusal wording matches TASK-5242's actual output.
- [ ] No file under `packages/ai-parrot/src/parrot/sdd/_assets/` was edited by
  hand; all four changed only via `check_asset_sync.py --write`.
- [ ] `python scripts/sdd/check_asset_sync.py --check` exits 0 (spec AC9).
- [ ] `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q` passes.
- [ ] `pytest packages/ai-parrot/tests/sdd/test_installer.py -q` passes.
- [ ] The two long docs remain twins — no wording drift introduced between them.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`

Also run (not a test runner; record the exit code in the Completion Note):
`python scripts/sdd/check_asset_sync.py --check`.

Run from the worktree with `PYTHONPATH=packages/ai-parrot/src` — the shared
`.venv` is editable-installed against the main checkout, so a bare `pytest`
inside a worktree imports the wrong branch.

---

## Test Specification

This task adds no tests. It is gated by two existing suites:

```python
# packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py
#   _SHIPPED_GLOBS already covers the three remove-worktree asset paths
#   (wired by TASK-5134) — it fails if a shipped copy references a repo-only
#   script path.
# packages/ai-parrot/tests/sdd/test_installer.py
#   test_rewrite_preserves_asset_names reads the pinned set in
#   tests/sdd/fixtures/asset_targets.json, which already lists these targets.
```

If either suite fails after `--write`, the regeneration changed more than this
task's four files — investigate before committing.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug scripts-remove-worktree-fixes --feature-id FEAT-823`)
2. **Read the spec** at `sdd/specs/scripts-remove-worktree-fixes.spec.md` (§2 for
   the orphan taxonomy, §3 Module 5 for the source/generated split)
3. **Check dependencies** — TASK-5242 must be `"done"` in
   `sdd/tasks/index/scripts-remove-worktree-fixes.json`; read its final diff so
   the documented wording matches the implemented refusal
4. **Verify the Codebase Contract** — confirm the three `ASSET_SOURCES` rows and
   re-run the anchor greps above before editing
5. **Update status** in `sdd/tasks/index/scripts-remove-worktree-fixes.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — edit the three sources, complete the `FILL IN`, then
   regenerate with `--write`
7. **Verify** every acceptance criterion; run the Validation Commands
8. **Commit** — stage only the three sources and the four generated files
   (never `git add .` / `-A`)
9. **Close the task** with
   `parrot sdd task close TASK-5244 scripts-remove-worktree-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5.5 (/sdd-fix, actor agent:sdd-fix:118971f4)
**Date**: 2026-11-06
**Notes**: Three sources hand-edited, three shipped copies regenerated
(+82/-8 across 6 files).

`python scripts/sdd/check_asset_sync.py --check` → **exit 0** (measured
directly, not through a pipe: `tail` was masking the real status). Before
`--write` it reported all three copies `diverged`, which confirms the
regeneration was actually needed and actually ran.

The `FILL IN` (the section heading) resolved as a retitle: **"Two kinds of
leftovers" → "Kinds of leftovers"**, applied identically to both long twins and
verified with a `diff` of the changed region — the section still opens with the
two-row registered/orphan table, so the original distinction is intact, but it
no longer claims to describe only two things when four orphan shapes follow.

Content written from the **implemented** strings, not the blueprint's intent —
`grep`-ed out of the final `remove_worktree.py` after TASK-5242 closed. That is
why the deregistered-checkout row documents the unknown-state refusal: TASK-5242's
fail-closed decision means a checkout whose `git status` cannot run is refused
rather than read as clean, and an operator needs to know that is deliberate.

**Deviation from this task's own file table**: it listed
`packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` as MODIFY, and it was
**not** modified. `--write` regenerates all 88 assets plus the manifest, but the
manifest records asset names and paths, and this change adds and removes none —
so it came out byte-identical. Six files changed, not seven. The Complexity
Contract's `targets` still matches the table as authored; the over-declaration
is recorded here rather than silently dropped.

**Verification evidence**

- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py
  packages/ai-parrot/tests/sdd/test_installer.py -q` → **78 passed**.
- `git status --porcelain` after `--write` showed exactly the 3 sources and
  their 3 generated copies — no unrelated asset drift swept in, which was the
  blueprint's stated stop condition.
- No file under `_assets/` was opened for editing; all three changed solely via
  `--write`.

**Deviations from spec**: none. Spec §3 Module 5's source/generated split was
followed exactly.
