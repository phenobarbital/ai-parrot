# TASK-5462: Wheel-only foreign-repo test maps the `task review record` placeholders

**Feature**: FEAT-870 — Wheel-Only Foreign-Repo Test Maps the `task review record` Placeholders
**Spec**: `sdd/specs/commands-sdd-start-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:4e0a0d2635aa`

---

## Context

`test_install_then_every_documented_helper_invocation` runs every documented `parrot sdd <noun> <verb>` line from the
installed assets after substituting placeholders, and fails on any token still holding `<`, `$` or `...`. PR #2070
added `parrot sdd task review record --feature <slug> --task <id> --worktree <path> --summary "<review>"` to the four
`sdd-start` copies; the test maps `<slug>` and `--worktree <path>` but not `<id>` or `<review>`, so it fails 1 of 110
invocations on `dev` and blocks the release smoke job. Implements spec §2, Module 1.

---

## Scope

- Add `placeholders={"<id>": "TASK-001", "<review>": "demo review"}` to `SCENARIOS["review_checkpoint"]`, keeping its
  `prepare=_seed_worktree` and `expect_exit=(0, 1, 2, 3)`.

**NOT in scope**: the four `sdd-start` doc copies; `COMMON`; `review_checkpoint`'s accepted exit codes; any source
file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | scenario-scoped `<id>` / `<review>` placeholders |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

Verified against `origin/dev` @ `027554a40d`.

### Verified Imports
None added.

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
pytestmark = pytest.mark.integration  # :26
def _seed_worktree(clone: Path) -> None  # :153 — _seed_feature + `git worktree add .parrot/worktrees/feat-<FEAT>-<SLUG>`
COMMON: dict[str, str]  # :292 — "<TASK-ID>": "TASK-001" :298; "--worktree <path>": ... :333
@dataclass class Scenario  # :342 — placeholders: dict[str, str] = field(default_factory=dict); prepare; expect_exit
SCENARIOS: dict[str, Scenario]  # :364
#   "review_checkpoint": Scenario(prepare=_seed_worktree, expect_exit=(0, 1, 2, 3)),  # :405
def _argv_for(name, argv, scenario, clone) -> list[str]  # :572 — values = {**COMMON, **scenario.placeholders}, longest key first; unresolved assert :585-586
def test_install_then_every_documented_helper_invocation(managed_home, tools_dir, foreign_repo, tmp_path) -> None  # :598
```

### Does NOT Exist
- No `<id>` or `<review>` key in `COMMON` or in any scenario's `placeholders`.
- No `placeholders` argument on the `review_checkpoint` scenario.
- No shipped-asset line other than the `sdd-start` `record` line uses `<id>` or `<review>`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#test_install_then_every_documented_helper_invocation",
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#_argv_for"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Scenario-scoped only: a bare `<id>` in `COMMON` would apply to every helper.
- The test builds wheels and takes minutes: run it in the background from the worktree with an absolute
  `PYTHONPATH=<wt>/packages/ai-parrot/src`.

### References in Codebase
- `SCENARIOS["run_closeout_hooks"]` (`:407`), `SCENARIOS["sdd_meta"]` (`:419`) and `SCENARIOS["worktree_root"]` (`:439`) — existing scenario-scoped `placeholders`.

---

## Implementation Blueprint

### Steps (in order)
1. Run the test on the unchanged tree; confirm the `review_checkpoint: unresolved placeholder(s) ['<id>', '<review>']`
   failure.
2. Edit the scenario.
3. Re-run the test; confirm it passes.

### `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` (MODIFY)
```python
# REPLACE :405 (`    "review_checkpoint": Scenario(prepare=_seed_worktree, expect_exit=(0, 1, 2, 3)),`) with:
    "review_checkpoint": Scenario(
        prepare=_seed_worktree,
        expect_exit=(0, 1, 2, 3),
        placeholders={"<id>": "TASK-001", "<review>": "demo review"},  # sdd-start's `task review record` line
    ),
```

---

## Acceptance Criteria

- [ ] AC-1: `SCENARIOS["review_checkpoint"]` maps `<id>` → `TASK-001` and `<review>` → `demo review`; `prepare` and
      `expect_exit` are unchanged.
- [ ] AC-2: `COMMON` and the four `sdd-start` copies are unchanged.
- [ ] AC-3: `test_install_then_every_documented_helper_invocation` fails without the edit and passes with it.
- [ ] AC-4: the Validation Command passes; `ruff check` is clean on the file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py -q`

---

## Test Specification

See spec §4: `test_install_then_every_documented_helper_invocation` (existing) goes from failing to passing; the rest
of the file is unchanged and must keep passing.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug commands-sdd-start-fixes --feature-id FEAT-870`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing ANY code
5. **Update status** in `sdd/tasks/index/commands-sdd-start-fixes.json` → `"in-progress"` (set `started_at`) and
   commit only that index file
6. **Implement** — follow the Implementation Blueprint
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5462 commands-sdd-start-fixes verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
