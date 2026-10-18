# HOTFIX-PR-1727-1: QANode mirror helpers go file-level; rewrite the dir-level QANode tests

**Feature**: PR-1727 — FEAT-699 red tests
**Spec**: `sdd/briefs/feat-699-red-tests.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:1e684c2b1d72`

---

## Context

FEAT-699 made tier planning file-level (`plan_tests` → `pytest_file_targets`), so
`QANode._default_criteria` — which calls `plan_tests` — no longer derives a criterion
for fixtures that only create test *directories*. Five tests in
`test_qa_default_criteria.py` / `test_qanode_feature_tier.py` are red for that reason,
and `QANode._pytest_targets` still delegates to the dir-level walk-up, contradicting
the spec ("Mirror resolution becomes file-level everywhere", spec line 110). Brief
decision 2: switch the QANode helpers to the file-level mirror and rewrite every
dir-level assertion.

---

## Scope

- In `nodes/qa.py`: make `QANode._pytest_targets` delegate to
  `_scope_mirror.pytest_file_targets` and `QANode._pytest_target_for` to
  `_scope_mirror.pytest_file_target_for`; delete the orphan `_deepest_existing_dir`
  static delegate (verified: no caller outside `qa.py`); keep `_prune_nested`.
  Update the two docstrings and the `_default_criteria` docstring sentence that
  mentions "narrowest existing test directory".
- Rewrite `test_qa_default_criteria.py` so every fixture that must yield a target
  contains a real `test_<name>.py` file, and every expectation names a file, never a
  directory (details in Implementation Notes).
- Rewrite `test_qanode_feature_tier.py::test_feature_tier_equals_mirror_selection` to
  create `packages/ai-parrot/tests/flows/dev_loop/test_qa.py` and assert the derived
  targets are non-empty and equal to `QANode._pytest_targets(...)`.
- Rewrite `test_mirror.py::test_mirror_parity_with_qanode_fixtures` to compare
  `pytest_file_targets` with `QANode._pytest_targets` over a fixture that contains
  real test files (so parity is non-trivial).

**NOT in scope**: `mirror.pytest_targets` / `pytest_target_for` /
`deepest_existing_dir` (still exported; legacy API), `plan_tests`, `select_tests.py`,
`test_supervisor_ledger.py` (HOTFIX-PR-1727-2), root `test_select_tests.py`
(HOTFIX-PR-1727-3), the baseline-red `test_pr_enrichment.py` / `test_recovery_lifecycle.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` | MODIFY | `_pytest_targets` / `_pytest_target_for` delegate to the file-level mirror; drop `_deepest_existing_dir` |
| `packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py` | MODIFY | fixtures gain test files; dir-level expectations become file-level |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py` | MODIFY | fixture gains `test_qa.py`; non-empty parity assertion |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py` | MODIFY | parity test compares against `pytest_file_targets` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope import mirror as _scope_mirror  # verified: nodes/qa.py:61
from parrot.flows.dev_loop.test_scope import plan_tests  # verified: nodes/qa.py:60
from parrot.flows.dev_loop.test_scope.mirror import pytest_file_target_for, pytest_file_targets  # verified: test_scope/test_mirror.py:7
from parrot.flows.dev_loop.nodes.qa import QANode  # verified: test_qa_default_criteria.py:22
from parrot.flows.dev_loop import DevelopmentOutput, QAReport, ResearchOutput  # verified: test_qanode_feature_tier.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py:84
def pytest_file_targets(files: Sequence[str], worktree_path: str) -> list[str]: ...
# mirror.py:88 — a changed test module maps to itself; a source module maps to the first
# existing test_<name>.py walking from the mirrored depth up to packages/<dist>/tests;
# returns None for non-.py, __init__.py, deleted files, `packages/<d>/src/<file>.py`
# (len(rest) < 3), or when no test file exists. Root `tests/...py` maps to itself if it exists.
def pytest_file_target_for(path: str, worktree_path: str) -> str | None: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:642-664 (current, dir-level)
@classmethod
def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:  # :643 → pytest_targets
@classmethod
def _pytest_target_for(cls, path: str, worktree_path: str) -> Optional[str]:  # :648 → pytest_target_for
@staticmethod
def _deepest_existing_dir(tests_root: str, subdirs: Tuple[str, ...], worktree_path: str) -> str:  # :653 — DELETE
@staticmethod
def _prune_nested(targets: set) -> List[str]:  # :662 — keep

# qa.py:597 — the plan QANode derives criteria from (file-level mirror, tier="feature")
plan = await asyncio.to_thread(plan_tests, worktree=Path(worktree), changed_files=files, tier="feature")
# qa.py:606-614 — one ShellCriterion per invocation, name f"pytest[{inv.distribution}]"
```

### Does NOT Exist
- ~~`QANode._pytest_file_targets`~~ — do not add a new name; change the existing delegates.
- ~~`mirror.pytest_file_targets(..., worktree: Path)`~~ — the second argument is a `str`.
- ~~a `pytest_file_target_for` result for `packages/ai-parrot/src/b.py`~~ — files directly
  under `src/` map to nothing (`len(rest) < 3`); use `src/parrot/b.py`-shaped paths in tests.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._pytest_targets",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._pytest_target_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py#QANode._default_criteria",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py#pytest_file_targets",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/mirror.py#pytest_file_target_for"
  ]
}
```

---

## Implementation Notes

### `nodes/qa.py`
```python
    @classmethod
    def _pytest_targets(cls, files: List[str], worktree_path: str) -> List[str]:
        """Delegates to test_scope.mirror.pytest_file_targets (FEAT-699 file-level mirror)."""
        return _scope_mirror.pytest_file_targets(files, worktree_path)

    @classmethod
    def _pytest_target_for(cls, path: str, worktree_path: str) -> Optional[str]:
        """Delegates to test_scope.mirror.pytest_file_target_for (FEAT-699 file-level mirror)."""
        return _scope_mirror.pytest_file_target_for(path, worktree_path)
```
Remove the `_deepest_existing_dir` staticmethod (qa.py:652-659). Keep `_prune_nested`.
`Tuple` may become an unused import — check `ruff` and drop it only if nothing else uses it.
In the `_default_criteria` docstring replace "scoped to the narrowest existing test
directory that mirrors each changed file" with "scoped to the existing test files that
mirror each changed file (file-level, FEAT-699)".

### `test_qa_default_criteria.py` — fixture and expectation changes
`worktree` fixture (lines 25-31) must create, in addition to the directories:
- `packages/ai-parrot/tests/loaders/test_base.py` (mirror of `src/parrot/loaders/base.py`)
- `packages/ai-parrot/tests/test_x.py` (mirror of `src/parrot/x.py`, used at line 138)
- `packages/ai-parrot-tools/tests/test_http.py` (mirror of `src/parrot_tools/http.py`)
(empty files are fine: the mirror checks `os.path.isfile`; the source files themselves
need NOT exist for `plan_tests`? — they DO: `pytest_file_target_for` returns `None`
when the *changed* path is not a file (`mirror.py:107-109`), so the fixture must also
create the changed source files it names: `packages/ai-parrot/src/parrot/loaders/base.py`,
`packages/ai-parrot/src/parrot/x.py`, `packages/ai-parrot-tools/src/parrot_tools/http.py`,
and (in `mirrored`) `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`.)

Per test:
- `test_derives_pytest_scoped_to_changed_packages` (:75-84): keep the criterion names;
  assert `"packages/ai-parrot/tests/loaders/test_base.py" in criteria[0].command` and
  `"packages/ai-parrot-tools/tests/test_http.py" in criteria[1].command`.
- `test_derived_criterion_gates_the_run` (:88): unchanged — passes once the fixture yields a target.
- `test_falls_back_to_git_diff_when_development_published_nothing` (:133-144): assert
  `"packages/ai-parrot/tests/test_x.py" in ...command`.
- `test_pytest_targets_are_deduped_and_sorted` (:185-195): input
  `["packages/ai-parrot-tools/src/parrot_tools/a.py", "packages/ai-parrot/src/parrot/b.py",
  "packages/ai-parrot/src/parrot/c.py", "scripts/sdd/reserve_ids.py"]`; create the three
  sources plus `packages/ai-parrot-tools/tests/test_a.py` and `packages/ai-parrot/tests/test_b.py`
  (no `test_c.py`); expect
  `["packages/ai-parrot-tools/tests/test_a.py", "packages/ai-parrot/tests/test_b.py"]`.
- `mirrored` fixture (:203-208): also create `packages/ai-parrot/tests/flows/dev_loop/test_qa.py`,
  `packages/ai-parrot/tests/flows/test_ideation.py`, and the sources
  `src/parrot/flows/dev_loop/nodes/qa.py`, `src/parrot/flows/dev_flow/nodes/ideation.py`.
- `test_source_file_maps_to_mirrored_test_subtree` → rename
  `test_source_file_maps_to_mirrored_test_file`; expect `["packages/ai-parrot/tests/flows/dev_loop/test_qa.py"]`.
- `test_mapping_walks_up_to_the_deepest_directory_that_exists` → rename
  `test_mapping_walks_up_to_the_first_existing_test_file`; expect `["packages/ai-parrot/tests/flows/test_ideation.py"]`.
- `test_changed_test_module_is_its_own_target` (:230): unchanged.
- `test_target_covered_by_an_ancestor_is_pruned` → rename
  `test_source_and_its_own_test_map_to_one_file`; expect `["packages/ai-parrot/tests/loaders/test_base.py"]`.
- `test_deleted_test_module_falls_back_to_the_package_root` → rename
  `test_deleted_test_module_maps_to_nothing`; expect `[]`.
- `test_tests_created_by_development_are_unioned_with_the_diff` (:262-281): assert
  `"packages/ai-parrot/tests/flows/dev_loop/test_qa.py" in command` and
  `"packages/ai-parrot/tests/loaders/test_new.py" in command`.
- `test_root_level_test_module_is_its_own_target` (:284): unchanged.
- `test_deleted_root_test_module_falls_back_to_the_root_tree` → rename
  `test_deleted_root_test_module_maps_to_nothing`; expect `[]`.
- `test_root_test_without_a_root_tree_maps_to_nothing`, `test_package_without_tests_is_not_a_target`,
  `test_docs_only_change_derives_nothing`, `test_declared_criteria_are_never_overridden`,
  `test_manual_only_brief_is_left_alone`: unchanged.
Update the module docstring / section comment "Narrow (mirrored-subtree) scoping" to
"File-level mirror scoping (FEAT-699)".

### `test_qanode_feature_tier.py::test_feature_tier_equals_mirror_selection` (:27-38)
Create `packages/ai-parrot/tests/flows/dev_loop/test_qa.py` and the changed source
`packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py` under `tmp_path`; after the
existing parity assertion add `assert got_targets == {"packages/ai-parrot/tests/flows/dev_loop/test_qa.py"}`.

### `test_mirror.py::test_mirror_parity_with_qanode_fixtures` (:10-33)
Import `pytest_file_targets` only (drop `pytest_targets` from the import if it becomes
unused); extend `mirrored` to write `packages/ai-parrot/tests/flows/dev_loop/test_qa.py`,
`packages/ai-parrot/tests/test_b.py`, `packages/ai-parrot-tools/tests/test_a.py` and the
matching sources; assert `pytest_file_targets(files, str(mirrored)) == QANode._pytest_targets(files, str(mirrored))`
and, for the `nodes/qa.py` parameter, that the result is non-empty.

### Key Constraints
- Do not change `mirror.py`, `select.py`, or `planner.py`.
- `plan_tests` on a non-git `tmp_path` appends the note "worktree is not a git
  repository; skipping the import index" — harmless, the mirror still resolves.

---

## Acceptance Criteria

- [ ] `QANode._pytest_targets` / `_pytest_target_for` return only files (never directories).
- [ ] `QANode._deepest_existing_dir` no longer exists; `_prune_nested` still does.
- [ ] All three validation files pass; no test asserts a directory target.
- [ ] `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_default_criteria.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_qanode_feature_tier.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in this worktree** — `.claude/worktrees/fix-PR-1727-feat-699-red-tests`
   (branch `fix-PR-1727-feat-699-red-tests`, based on the tip of
   `origin/feat-FEAT-699-tests-optimization-sdd-flow`).
2. **Run tests with the worktree's source**:
   `PYTHONPATH=packages/ai-parrot/src pytest <file> -q`. The compiled Cython modules
   (`parrot/utils/*.so`, `parrot/utils/parsers/*.so`) exist only in the main checkout;
   copy them once:
   `(cd /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/src && find parrot -name '*.so' -exec cp --parents {} <wt>/packages/ai-parrot/src/ \;)`
   (they are git-ignored).
3. **Verify the Codebase Contract** before writing code.
4. **Implement**, run `ruff check --fix` on the four files, run the Validation Commands.
5. **Commit the code** — stage only the four files: `fix(dev_loop): HOTFIX-PR-1727-1 — QANode mirror helpers go file-level`.
6. **Update** `sdd/briefs/feat-699-red-tests.index.json` (`status: "done"`, `completed_at`), fill in the
   Completion Note below, commit `sdd: complete HOTFIX-PR-1727-1`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
