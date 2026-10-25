---
id: F003
query_id: Q003
type: read
intent: "Read the FEAT-704 per-spec index on dev and the two engine tasks (TASK-4467 sidemantic, TASK-4468 native)"
executed_at: 2026-10-25T10:15:00Z
duration_ms: 3000
parent_id: null
depth: 0
---

# F003 — On `dev` all 20 FEAT-704 tasks are `pending`; TASK-4467 is the sidemantic spike + engine

## Summary

`sdd/tasks/index/semantic-layer.json` on `dev` lists TASK-4463…TASK-4482, every one `pending`, `completed_at: null`. TASK-4467 ("sidemantic spike, model loader and sidemantic engine (M4)") creates `loader.py`, `engines/__init__.py`, `engines/sidemantic_engine.py` and the shared fixtures; TASK-4468 creates `engines/native.py`. The task's Codebase Contract marks every sidemantic name "(unverified — check before use)" and relies on `SQLGLOT_DIALECT_MAP` (`knowledge/common/sql_dialects.py:6`) and `driver_to_dialect` (`dataset_manager/sources/dialects.py:41`).

## Citations

- path: `sdd/tasks/index/semantic-layer.json`
  lines: 1-20
  symbol: `feature_id`, `tasks[].status`
  excerpt: |
    {'feature': 'semantic-layer', 'feature_id': 'FEAT-704', 'spec': 'sdd/specs/semantic-layer.spec.md', 'type': 'feature', 'base_branch': 'dev', 'created_at': '2026-10-19T00:00:00+00:00', 'completed_at': None, ...}
    [('TASK-4463','pending'), ..., ('TASK-4467','pending'), ('TASK-4468','pending'), ..., ('TASK-4482','pending')]

- path: `sdd/tasks/active/TASK-4467-semantic-loader-sidemantic-engine.md`
  lines: 1-30
  symbol: `TASK-4467`
  excerpt: |
    # TASK-4467: sidemantic spike, model loader and sidemantic engine (M4)
    **Depends-on**: TASK-4465, TASK-4466
    - Implement `packages/ai-parrot-semantic/src/parrot/semantic/engines/sidemantic_engine.py`: `filter_tree_to_sidemantic`, `compile_sidemantic`.
    **NOT in scope**: the native compiler (TASK-4468 creates `engines/native.py`)

- path: `sdd/tasks/active/TASK-4467-semantic-loader-sidemantic-engine.md`
  lines: 62-72
  symbol: `Existing Signatures to Use`
  excerpt: |
    # packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py
    SQLGLOT_DIALECT_MAP: Dict[str, str]   # line 6
    # packages/ai-parrot/src/parrot/tools/dataset_manager/sources/dialects.py
    def driver_to_dialect(driver)          # line 41

- path: `sdd/tasks/active/TASK-4468-semantic-native-compiler.md`
  lines: 1-5
  symbol: `TASK-4468`
  excerpt: |
    TASK-4468 … Native fallback compiler (M5)

## Notes

The `dev` index contradicts the feature branch (F004): this is the known "dev index hides feature-branch progress" effect — the branch was never merged, so its `done` stamps never reached `dev`.
