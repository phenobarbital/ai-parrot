---
feature_id: FEAT-642
type: feature
base_branch: dev
status: approved
created: 2026-10-08
source: ledger (issue:da0151296f53) via /sdd-fix
---

# FEAT-642 — Order-dependent test collection collisions

## 1. Problem
`pytest --collect-only packages/ai-parrot/tests` reports two errors whose files collect fine alone
(pytest `prepend` import mode, rootdir-relative basenames):

1. `tests/outputs/a2ui/graph/test_models.py` — its directory has no `__init__.py`, so it imports as bare
   `test_models`, colliding with `tests/knowledge/wiki/inbox/test_models.py` (also bare) → "import file mismatch".
2. `tests/unit/scripts/test_recompute_contextual_embeddings.py` — `unit/scripts/` has an `__init__.py` but
   `unit/` does not, so the module resolves as `scripts.test_recompute_contextual_embeddings`; top-level
   `scripts` is already the repo's SDD tooling package in `sys.modules` → ModuleNotFoundError.

## 2. Scope
- Add `tests/outputs/a2ui/graph/__init__.py` (parents are packages → fully-qualified module name).
- Delete the empty `tests/unit/scripts/__init__.py` (basename is unique repo-wide, so bare import is safe).
- NOT in scope: adding `tests/unit/__init__.py` (would rename every module under `unit/`), and the two
  BotManager collection errors fixed by FEAT-641 (PR #1608).

## 3. Acceptance Criteria
- AC1: full collection of `packages/ai-parrot/tests` reports neither file as an error.
- AC2: the three affected files pass when run together.
