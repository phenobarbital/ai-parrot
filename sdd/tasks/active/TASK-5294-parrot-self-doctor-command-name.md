# TASK-5294: Correct `parrot doctor` → `parrot self doctor` in all live FEAT-802 text

**Feature**: FEAT-835 — Correct the `parrot doctor` Command Name in FEAT-802 Text
**Spec**: `sdd/specs/fixgroup-a76673a5632a.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:f90b8c2c3472`

---

## Context

Implements the whole of `sdd/specs/fixgroup-a76673a5632a.spec.md` (§3 Modules
M1, M2 and M3).

FEAT-802 shipped a legacy-worktree migration instruction that tells users to run
"the recipe `parrot doctor` prints". That command is not registered:

```
$ parrot doctor --help
Error: No such command 'doctor'.
```

The real command is `parrot self doctor` (`parrot/self_/cli.py:61`). The wrong
name sits in the packaged installer asset (inherited by every repository
`parrot sdd install` touches), in the two installed host twins, in the
`ensure_worktree` runtime error message, and in two user-facing install docs —
seven live call sites in all.

The three modules are one atomic deliverable: the acceptance criterion is a
repo-wide grep that only goes green when every site is corrected, and the
`ensure_worktree.py` message and its assertion in
`tests/sdd_scripts/test_ensure_worktree.py` must change in the same commit or
the suite goes red. Splitting them would create three trivial tasks with a
shared pass/fail gate.

---

## Scope

- Replace the token `parrot doctor` with `parrot self doctor` at the seven
  verified call sites listed in "Files to Create / Modify".
- Update the assertion in `tests/sdd_scripts/test_ensure_worktree.py` to the new
  literal, so the corrected error message stays regression-guarded.
- Keep every edited line otherwise byte-identical — same wording, same physical
  line, no rewrapping.

**NOT in scope**:
- Registering a top-level `parrot doctor` alias. The project decided against
  top-level `env`/`doctor` commands (TASK-4080, TASK-4091, TASK-4095) and
  `parrot status` is already taken by the agentd daemon. The command name is
  correct; only the prose is wrong.
- Any behavioural change to `parrot self doctor`, `parrot sdd install`, or
  `_find_reusable_worktree`'s legacy-root refusal logic. The
  `ensure_worktree.py` diff touches the f-string literal and nothing else.
- Historical SDD artifacts under `sdd/specs/`, `sdd/proposals/` and
  `sdd/tasks/completed/`. They record what was decided at the time and are never
  retro-edited. In particular `sdd/specs/parrot-installer.spec.md:1586` names
  `parrot doctor` inside a struck-through "does not exist" list — correcting it
  there would invert its meaning.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` | MODIFY | Packaged installer asset — the source of the shipped instruction |
| `.claude/rules/worktree-management.md` | MODIFY | Installed twin of the asset in this repo; must stay byte-identical to it |
| `.agent/skills/worktree-management/SKILL.md` | MODIFY | Agent-side twin of the same instruction (different wording) |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | MODIFY | Runtime `EnsureWorktreeError` message |
| `tests/sdd_scripts/test_ensure_worktree.py` | MODIFY | Assertion pinning that message |
| `docs/getting-started.md` | MODIFY | Install doc stating the refusal behaviour |
| `wiki/operations/install/global-runtime.md` | MODIFY | Install doc stating the refusal behaviour |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against `origin/dev` @ `3143259f6d` (2026-11-07).
> Every occurrence count below was re-run with `grep -c` at task-authoring time.

### Verified Imports

```python
# tests/sdd_scripts/test_ensure_worktree.py — already present, do not add imports
from parrot.sdd.scripts.ensure_worktree import EnsureWorktreeError, ensure
```

No new imports are introduced by this task.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py:193
def _find_reusable_worktree(plan: WorktreePlan, target_path: Path, *, repo_root: Path) -> Path | None:
    ...
    # line 210: raise EnsureWorktreeError(
    # line 211:     f"Branch {plan.name!r} is already checked out at {worktree_path}, not at the expected "
    # line 212:     f"{target_path}; move it (see `parrot doctor` for the migration recipe) or remove it first."
    # line 213: )
```

```python
# tests/sdd_scripts/test_ensure_worktree.py:133
def test_ensure_rejects_legacy_registration(tmp_git_repo: Path) -> None:
    ...
    # line 150:        assert "parrot doctor" in message
```

```python
# tests/sdd_scripts/test_command_contracts.py:107
def test_no_legacy_worktree_root_remains() -> None:
    """Scans .md/.toml/.sh under .claude/, .agent/, .agents/,
    packages/ai-parrot/src/parrot/sdd/_assets/ plus CLAUDE.md. A line containing
    `.claude/worktrees` is an offender UNLESS it also contains `git worktree repair`."""
```

The real command this task points text at:

```
packages/ai-parrot/src/parrot/self_/cli.py:61  →  `parrot self doctor`
```

### Does NOT Exist

- ~~`parrot doctor`~~ — **not a registered top-level command.**
  `parrot doctor --help` exits non-zero with `Error: No such command 'doctor'.`
  This is the entire defect. Verified by running both `--help` forms.
- ~~`parrot env`~~ — also not top-level; it is `parrot self env`.
- ~~`docs/install/global-runtime.md`~~ — that path no longer exists
  (`ls docs/install/` is empty). The page lives at
  `wiki/operations/install/global-runtime.md`. Older task files
  (TASK-5182) cite the dead path — do not follow them.
- ~~`.agents/` twin of the worktree-management rule~~ — there is none.
  `grep -rn 'parrot doctor' .agents` returns nothing. Only the `.claude/rules/`
  and `.agent/skills/` twins exist.
- ~~`packages/ai-parrot/src/parrot/sdd/_assets/agent/skills/worktree-management/SKILL.md`~~
  — does not exist. The `_assets` tree ships only
  `agent/workflows/remove-worktree.md`, `claude/commands/remove-worktree.md`
  and `claude/rules/worktree-management.md`.
- ~~a `tests/sdd_scripts/test_asset_guards.py`~~ — does not exist. The guard
  test lives in `tests/sdd_scripts/test_command_contracts.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".claude/rules/worktree-management.md",
      "action": "MODIFY"
    },
    {
      "path": ".agent/skills/worktree-management/SKILL.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/sdd_scripts/test_ensure_worktree.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/getting-started.md",
      "action": "MODIFY"
    },
    {
      "path": "wiki/operations/install/global-runtime.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py#_find_reusable_worktree",
    "sym:tests/sdd_scripts/test_ensure_worktree.py#test_ensure_rejects_legacy_registration",
    "sym:tests/sdd_scripts/test_command_contracts.py#test_no_legacy_worktree_root_remains"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **The guard test is the trap.**
  `tests/sdd_scripts/test_command_contracts.py::test_no_legacy_worktree_root_remains`
  fails on any line under `.claude/`, `.agent/`, `.agents/` or
  `packages/ai-parrot/src/parrot/sdd/_assets/` that contains `.claude/worktrees`
  without also containing `git worktree repair` **on the same physical line**.
  Two of the edited lines rely on that. Edit in place; never rewrap or split a
  line.
- **Asset / twin parity.** The `_assets/claude/rules/worktree-management.md:79`
  line and `.claude/rules/worktree-management.md:79` are byte-identical today.
  Apply the identical edit to both so the installer reports no drift.
- **`"parrot doctor" in "parrot self doctor"` is `False`.** The existing
  assertion at `test_ensure_worktree.py:150` therefore *fails* unless it is
  updated in the same change. This is not optional cleanup.
- `.claude/` paths may be gitignored — check `git status` after editing and use
  `git add -f` for that file if it does not appear.
- `wiki/` is source, not generated: `sdd/config.json` sets
  `techwiki.source_dir: "wiki"`, so edit the file directly.

### References in Codebase

- `packages/ai-parrot/src/parrot/self_/cli.py:61` — the `parrot self doctor`
  command definition (the correct name).
- `tests/sdd_scripts/test_command_contracts.py:102-137` — the guard test logic.

---

## Implementation Blueprint

> Seven single-token substitutions. Every block below is a MODIFY with a
> verified anchor and an occurrence count of exactly 1 — each anchor is unique
> in its file, so no disambiguation is required.

### Steps (in order)

1. Apply the identical substitution to the packaged asset and its `.claude`
   twin — *why*: they must stay byte-identical or `parrot sdd install` reports
   drift between the shipped asset and the installed copy.
2. Apply the substitution to the `.agent` twin — *why*: its wording differs, so
   it cannot be copied from the other two; only the backticked token changes.
3. Apply the substitution to `ensure_worktree.py:212` **and**
   `test_ensure_worktree.py:150` together — *why*: the assertion pins the exact
   literal, so changing one without the other turns the suite red.
4. Apply the substitution to the two install docs — *why*: they state the
   refusal behaviour to users who have not yet hit the error, and they are the
   same FEAT-802 text.
5. Run both validation commands — *why*: one proves the new message, the other
   proves the `.claude/worktrees` guard still accepts the edited lines.

### `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'parrot doctor' packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md)
# REPLACE line 79 in place (verified: .../worktree-management.md:79)
# BEFORE:
Users with worktrees under the legacy `.claude/worktrees/` must run the recipe `parrot doctor` prints to migrate. Any line that names `.claude/worktrees` must also contain `git worktree repair` (the TASK-5183 guard test allows exactly those lines).
# AFTER:
Users with worktrees under the legacy `.claude/worktrees/` must run the recipe `parrot self doctor` prints to migrate. Any line that names `.claude/worktrees` must also contain `git worktree repair` (the TASK-5183 guard test allows exactly those lines).
```

**Why this shape**: this is the packaged source every `parrot sdd install`
copies, so correcting it here is what actually reaches other repositories. The
line keeps both `.claude/worktrees` and `git worktree repair` so the TASK-5183
guard still accepts it; only the backticked command token changes.

### `.claude/rules/worktree-management.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'parrot doctor' .claude/rules/worktree-management.md)
# REPLACE line 79 in place — byte-identical edit to the asset block above (verified: .claude/rules/worktree-management.md:79)
Users with worktrees under the legacy `.claude/worktrees/` must run the recipe `parrot self doctor` prints to migrate. Any line that names `.claude/worktrees` must also contain `git worktree repair` (the TASK-5183 guard test allows exactly those lines).
```

**Why**: this is the installed twin of the asset in this repo. It must match the
asset byte for byte, so the edit is literally the same substitution.

### `.agent/skills/worktree-management/SKILL.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'parrot doctor' .agent/skills/worktree-management/SKILL.md)
# REPLACE line 77 in place (verified: .agent/skills/worktree-management/SKILL.md:77)
# BEFORE:
`parrot doctor` prints (it moves them to the new worktree root and ends with
# AFTER:
`parrot self doctor` prints (it moves them to the new worktree root and ends with
```

**Why**: the agent twin carries the same instruction with different wording
(it spans lines 76–78). Only the backticked token on line 77 changes — do not
reflow the surrounding sentence.

### `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'parrot doctor' packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py)
# REPLACE line 212 in place, inside _find_reusable_worktree (verified: ensure_worktree.py:212)
# BEFORE:
                f"{target_path}; move it (see `parrot doctor` for the migration recipe) or remove it first."
# AFTER:
                f"{target_path}; move it (see `parrot self doctor` for the migration recipe) or remove it first."
```

**Why**: this is the message a user actually hits when a branch sits at a legacy
worktree path. Only the literal changes — the `raise`, the f-string structure,
the surrounding control flow and the function signature all stay exactly as they
are.

### `tests/sdd_scripts/test_ensure_worktree.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'parrot doctor' tests/sdd_scripts/test_ensure_worktree.py)
# REPLACE line 150 in place, inside test_ensure_rejects_legacy_registration (verified: test_ensure_worktree.py:150)
# BEFORE:
        assert "parrot doctor" in message
# AFTER:
        assert "parrot self doctor" in message
```

**Why**: `"parrot doctor" in "parrot self doctor"` evaluates to `False`, so this
assertion fails the moment the message is corrected. Updating it in the same
commit keeps the corrected message regression-guarded rather than merely
unbroken.

### `docs/getting-started.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'parrot doctor' docs/getting-started.md)
# REPLACE the `parrot doctor` token on line 436 in place (verified: docs/getting-started.md:436)
# BEFORE: ... commit it. `parrot sdd install` and `parrot doctor` refuse while worktrees remain ...
# AFTER:  ... commit it. `parrot sdd install` and `parrot self doctor` refuse while worktrees remain ...
```

**Why**: the sentence describes the refusal to users before they ever trigger
it. The rest of the line, including the trailing `/sdd-insight` note, is
unchanged.

### `wiki/operations/install/global-runtime.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -c 'parrot doctor' wiki/operations/install/global-runtime.md)
# REPLACE the `parrot doctor` token on line 257 in place (verified: wiki/operations/install/global-runtime.md:257)
# BEFORE: ... `parrot self doctor --sdd` checks both. `parrot sdd install` and `parrot doctor` refuse while ...
# AFTER:  ... `parrot self doctor --sdd` checks both. `parrot sdd install` and `parrot self doctor` refuse while ...
```

**Why**: this line already names `parrot self doctor --sdd` correctly earlier in
the same sentence, which makes the stale second reference actively confusing.
Note the line contains the string `parrot self doctor` twice after the edit —
replace only the `` `parrot doctor` `` occurrence, not the `--sdd` one.

### FILL IN checklist

*(none — every edit above is fully determined; there is no judgement left to the
executor. If any anchor's `grep -c` returns a count other than 1, stop and
report the drift rather than guessing a new attachment point.)*

---

## Acceptance Criteria

- [ ] `grep -rn "parrot doctor" packages/ .claude/ .agent/ .agents/ docs/ wiki/ tests/ CLAUDE.md`
      returns no hits (historical artifacts under `sdd/` are excluded by scope
      and deliberately untouched).
- [ ] `pytest tests/sdd_scripts/test_ensure_worktree.py::test_ensure_rejects_legacy_registration -q` passes.
- [ ] `pytest tests/sdd_scripts/test_command_contracts.py::test_no_legacy_worktree_root_remains -q` passes.
- [ ] `packages/ai-parrot/src/parrot/sdd/_assets/claude/rules/worktree-management.md:79`
      and `.claude/rules/worktree-management.md:79` are byte-identical
      (`diff <(sed -n 79p <asset>) <(sed -n 79p <twin>)` is empty).
- [ ] `ruff check` clean on the two changed Python files.
- [ ] `git diff --stat` shows exactly the seven files listed above, one changed
      line each (`7 files changed, 7 insertions(+), 7 deletions(-)`).

---

## Validation Commands

- `pytest tests/sdd_scripts/test_ensure_worktree.py::test_ensure_rejects_legacy_registration -q`
- `pytest tests/sdd_scripts/test_command_contracts.py::test_no_legacy_worktree_root_remains -q`
- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`

---

## Test Specification

No new tests. The existing assertion is retargeted to the corrected literal:

```python
# tests/sdd_scripts/test_ensure_worktree.py:133 — test_ensure_rejects_legacy_registration
    for dry_run in (True, False):
        with pytest.raises(EnsureWorktreeError) as exc_info:
            ensure(plan, repo_root=tmp_git_repo, dry_run=dry_run)
        message = str(exc_info.value)
        assert str(legacy_path.resolve()) in message
        assert str(target_path) in message
        assert "parrot self doctor" in message      # <- the one changed line
    assert not target_path.exists()
```

`test_no_legacy_worktree_root_remains` needs no edit — it must simply keep
passing, which it does as long as the two long Markdown lines are edited in
place and keep `git worktree repair`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug fixgroup-a76673a5632a --feature-id FEAT-835`)
2. **Read the spec** at `sdd/specs/fixgroup-a76673a5632a.spec.md`
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-run `grep -c 'parrot doctor' <path>` for
   all seven files. Every count must be exactly 1. A count of 0 means the site
   was already fixed; a count > 1 means the file drifted. Either way, stop and
   report rather than guessing.
5. **Update status** in `sdd/tasks/index/fixgroup-a76673a5632a.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** the seven substitutions from the blueprint. Change nothing else
   on any edited line.
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed
   against the main checkout, so a bare `pytest` inside a worktree imports the
   wrong branch).
8. **Commit the code** — stage only the seven files (never `git add .` / `-A`).
   `.claude/rules/worktree-management.md` may need `git add -f`.
9. **Close the task** with
   `parrot sdd task close TASK-5294 fixgroup-a76673a5632a verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
