# TASK-4591: Collection identity — `pytest.ini`: importlib mode + namespace-package identities

**Feature**: FEAT-720 — One Importable Identity per Package Test Tree
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt-2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 30 min)
**Depends-on**: TASK-4590
**Assigned-to**: unassigned
**Discovered-from**: `issue:45cf6a054e06`

---

## Context

Implements spec **Module 2**, as redefined by **Amendment B** (spec §2a, `sdd/state/FEAT-720/spike-namespace-packages.md`, verdict
`STRATEGY (a″) CONFIRMED`). The original plan (delete 25 `__init__.py`, edit `pyproject.toml`) was refuted twice: it leaves 129
collection errors, and `pyproject.toml`'s pytest table is dead config because the tracked root `pytest.ini` takes precedence.

## Scope

- Edit **`pytest.ini`** only: under `[pytest]`, add `addopts = --import-mode=importlib` and `consider_namespace_packages = true`.
- Change nothing else: **no `__init__.py` is deleted or added** (all 267 stay), `pyproject.toml` is not edited.

**NOT in scope**: any import-site repair (TASK-4592–4594); the regression test (TASK-4595); `ruff.toml`; `.github/workflows/*`;
any `parrot-formdesigner` failure (FEAT-618).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pytest.ini` | MODIFY | Add `addopts = --import-mode=importlib` and `consider_namespace_packages = true` under `[pytest]` |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```ini
# pytest.ini (tracked, repo root) — the LIVE pytest config
[pytest]
asyncio_mode = auto
markers =
    integration: ...
```
### Verified facts
- `git ls-files pytest.ini` → `pytest.ini`; pytest prefers it over `pyproject.toml`'s `[tool.pytest.ini_options]`.
- `find packages/*/tests -name '__init__.py' | wc -l` → **267**, before and after this task.
- Both settings are required: importlib mode alone still raises `ImportPathMismatchError: tests.conftest`.

### Does NOT Exist
- ~~an effective pytest table in `pyproject.toml`~~ — it is ignored while `pytest.ini` exists. Do not edit it.
- ~~`addopts` in `pytest.ini` today~~ — this task introduces it (a single line, no `--strict-*` flags: they were never active).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "pytest.ini", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes
- Insert directly under `asyncio_mode = auto`. Keep `markers` and `filterwarnings` untouched.
- Verify: `python -m pytest packages/ai-parrot-embeddings/tests packages/parrot-formdesigner/tests --collect-only -q -p no:randomly`
  prints no `ImportPathMismatchError` / `Plugin already registered` (the 5 formdesigner `tests.*`/`scripts.*` errors are TASK-4594's).

---

## Acceptance Criteria

- [ ] `pytest.ini` contains `addopts = --import-mode=importlib` and `consider_namespace_packages = true`; nothing else changed in it.
- [ ] `find packages/*/tests -name '__init__.py' | wc -l` → **267**; `pyproject.toml` unmodified.
- [ ] The pair collect above shows none of `ImportPathMismatchError`, `Plugin already registered`, `import file mismatch`.

## Validation Commands

- `pytest packages/ai-parrot-embeddings/tests/test_wheel_layout.py -q`

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
2. **Read the spec** §2 *Landing* — this task leaves the branch red on purpose
3. **Check dependencies** — TASK-4590 must be `"done"` in
   `sdd/tasks/index/tests-test-wheel-layout-tech-debt-2.json`, and its evidence
   file must carry `STRATEGY (a) CONFIRMED`
4. **Verify the Codebase Contract** — re-run the three counts and re-check
   `pyproject.toml:250`; correct the task file first if anything moved
5. **Update status** in the per-spec index → `"in-progress"`, commit only that file
6. **Implement** from the blueprint; there are no `FILL IN` markers
7. **Verify** every acceptance criterion, especially the 267 count
8. **Commit the code** — stage the 26 paths explicitly, never `git add .` / `-A`
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4591 tests-test-wheel-layout-tech-debt-2 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
