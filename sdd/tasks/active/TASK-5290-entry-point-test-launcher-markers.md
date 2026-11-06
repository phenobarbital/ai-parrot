# TASK-5290: Export launcher markers in the native-mode hook entry-point test

**Feature**: FEAT-832 — native-mode hook entry-point test sets launcher markers
**Spec**: `sdd/specs/scripts-worktree-environment-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:ca2e26e666cd`

---

## Context

Spec §1. Since a7cec86e23, `worktree_environment.main` trusts `PARROT_SDD_SANDBOX_BACKEND=claude-native` only
beside both `LAUNCHER_MARKERS`; otherwise it selects `auto`, whose file-tool guard does not deny
`.claude/settings.local.json`. `test_packaged_hook_entry_point_denies_in_native_mode_without_import_error` sets
only the backend, so it gets no decision and fails with `KeyError: 'permissionDecision'`.

---

## Scope

- In that test, build `env` from `os.environ` without any `PARROT_SDD_*` key, then set the backend plus
  `PARROT_SDD_SANDBOX_ROOTS` (`feature`, `main/.git`, `main` joined by `os.pathsep`) and
  `PARROT_SDD_CACHE_DIR` (`tmp_path / "cache"`).

**NOT in scope**: any file under `packages/ai-parrot/src/`; other tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py` | MODIFY | export launcher markers in the entry-point test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import worktree_environment as policy  # verified: test_worktree_environment.py:18
```

### Existing Signatures to Use
```python
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")  # worktree_environment.py:572
def _native_hook_worktrees(tmp_path: Path) -> tuple[Path, Path, Path]:  # test_worktree_environment.py:710 — (feature, task, main)
def test_packaged_hook_entry_point_denies_in_native_mode_without_import_error(tmp_path: Path) -> None:  # test_worktree_environment.py:1439
```

### Does NOT Exist
- No helper in the test module that builds a launcher-marker env; inline the dict (precedent at line 919).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py#test_packaged_hook_entry_point_denies_in_native_mode_without_import_error"
  ]
}
```

---

## Implementation Notes

The native module reads `PARROT_SDD_SANDBOX_ROOTS` as frozen roots, so the value must be the real
`feature`, `main/.git`, `main` paths from `_native_hook_worktrees` (not a placeholder).

---

## Implementation Blueprint

```python
    feature, _task, main = _native_hook_worktrees(tmp_path)
    ...
    env = {k: v for k, v in os.environ.items() if not k.startswith("PARROT_SDD_")}
    env.update(
        {
            "PARROT_SDD_SANDBOX_BACKEND": "claude-native",
            "PARROT_SDD_SANDBOX_ROOTS": os.pathsep.join((str(feature), str(main / ".git"), str(main))),
            "PARROT_SDD_CACHE_DIR": str(tmp_path / "cache"),
        }
    )
```

---

## Acceptance Criteria

- [ ] AC-1 The entry-point test passes and its denial comes from the native policy.
- [ ] AC-2 `test_worktree_environment.py` passes in full.
- [ ] `ruff check` clean on the changed file.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q`

---

## Test Specification

The modified test is the specification.

---

## Agent Instructions

1. Work in `feat-FEAT-832-scripts-worktree-environment-fixes`; run tests with `PYTHONPATH=packages/ai-parrot/src`.
2. Implement from the Blueprint, run the Validation Commands.
3. Commit only the listed file; close with `parrot sdd task close TASK-5290 scripts-worktree-environment-fixes verified`.

---

## Completion Note

*(Agent fills this in when done)*
