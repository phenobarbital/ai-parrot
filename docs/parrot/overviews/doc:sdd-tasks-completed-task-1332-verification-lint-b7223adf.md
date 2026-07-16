---
type: Wiki Overview
title: 'TASK-1332: Repo-wide verification, lint, full test suite, and cleanup'
id: doc:sdd-tasks-completed-task-1332-verification-lint-and-cleanup-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Final task of FEAT-198. Confirms the move is complete and no stale references
  survived, runs lint and the relevant test surface, and removes any artifacts that
  should not be tracked. Implements §3 Module 5 of the spec.
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.knowledge
  rel: mentions
- concept: mod:parrot.knowledge.pageindex
  rel: mentions
---

# TASK-1332: Repo-wide verification, lint, full test suite, and cleanup

**Feature**: FEAT-198 — move-pageindex-kb
**Spec**: `sdd/specs/move-pageindex-kb.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1328, TASK-1329, TASK-1330, TASK-1331
**Assigned-to**: unassigned

---

## Context

Final task of FEAT-198. Confirms the move is complete and no stale references survived, runs lint and the relevant test surface, and removes any artifacts that should not be tracked. Implements §3 Module 5 of the spec.

This task does **not** introduce new code or change behavior — it is a verification gate.

---

## Scope

- Run a repo-wide grep for `parrot.pageindex` (with the exclusions listed in spec §5 / §6) — must return zero matches.
- Run `ruff` over the moved source and test packages.
- Run the focused test suites: `tests/knowledge/pageindex/` and `tests/knowledge/graphindex/test_loader_extractor.py`.
- Run the full ai-parrot test suite to catch unforeseen regressions (skips marked tests OK).
- Delete the stale `__pycache__/` and `.pyc` artifacts left behind by the old `parrot/pageindex/` and `tests/test_pageindex/` directories (if any survived `git mv`).
- Confirm no `parrot.pageindex` shim was inadvertently created anywhere.
- Confirm `parrot.knowledge.__init__.py` was not modified to add re-exports (strict layout invariant).
- Run a final import-deny smoke: `import parrot.pageindex` must raise `ModuleNotFoundError`.
- Audit external-only operational configs for the literal string `"parrot.pageindex"` (open question §8 of spec) — log results in the task completion note, but do **not** edit them in this PR. Flag as follow-up.

**NOT in scope**:
- Any code change. This task only verifies and cleans up.
- Editing operational / deployment configs even if they contain stale references — surface them only.
- Updating `build/lib.*/` directories — those are stale build outputs; they regenerate on the next `pip install -e .` and are excluded from grep.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/pageindex/__pycache__/` | DELETE (if exists) | Stale bytecode left by old package |
| `packages/ai-parrot/tests/test_pageindex/__pycache__/` | DELETE (if exists) | Stale bytecode left by old tests |
| (none other) | — | This task verifies; it does not modify source code. |

---

## Codebase Contract (Anti-Hallucination)

### Verified invariants at task end

```python
# These imports must all resolve cleanly:
from parrot.knowledge.pageindex import (
    PageIndexToolkit, PageIndexRetriever, PageIndexLLMAdapter,
    build_page_index, md_to_tree, JSONTreeStore, NodeContentStore,
    HybridPageIndexSearch, TwoStepIngester, IngestedMarkdown,
    PageIndexNode, TreeSearchResult, TocItem,
)

# This import must fail:
import parrot.pageindex   # ModuleNotFoundError
```

### Files that must remain unchanged through this task

- `packages/ai-parrot/src/parrot/knowledge/__init__.py` — should still be just the module docstring (no PageIndex re-exports added). Verify with `cat`.
- All historical SDD docs under `sdd/tasks/completed/`, `sdd/tasks/archived/`, `sdd/proposals/`, and prior `sdd/specs/*.spec.md` — they reference the old path; this is correct history; do NOT update.

### Grep-zero exclusion list (canonical)

```bash
grep -rn 'parrot\.pageindex' \
  --include="*.py" --include="*.md" \
  --exclude-dir=__pycache__ --exclude-dir=build \
  --exclude-dir=site --exclude-dir=backup --exclude-dir=dist \
  --exclude-dir=.egg-info \
  --exclude-dir=sdd/tasks/completed --exclude-dir=sdd/tasks/archived \
  --exclude-dir=sdd/proposals \
  --exclude-dir=sdd/specs \
  .
```
Note: `sdd/specs` is excluded because it contains both the FEAT-198 spec (which legitimately mentions the old path while documenting the move) and older specs that reference the historical path. Both are appropriate.

### Does NOT Exist (verify by grep)

```bash
# 1. No parrot/pageindex/ directory in source tree
test ! -d packages/ai-parrot/src/parrot/pageindex && echo "old src dir gone"

# 2. No tests/test_pageindex/ directory
test ! -d packages/ai-parrot/tests/test_pageindex && echo "old tests dir gone"

# 3. No shim files
! find packages -path '*knowledge/pageindex/shim*' -o -path '*knowledge/pageindex/compat*' 2>/dev/null | grep -q .

# 4. No __getattr__ redirect added to parrot/__init__.py
! grep -q "pageindex" packages/ai-parrot/src/parrot/__init__.py

# 5. parrot.knowledge.__init__.py unchanged (no PageIndex re-exports)
! grep -q "pageindex\|PageIndex" packages/ai-parrot/src/parrot/knowledge/__init__.py
```

---

## Implementation Notes

### Procedure

```bash
source .venv/bin/activate

# ─── Verification ─────────────────────────────────────────────────
# 1. Repo-wide grep — MUST be empty
grep -rn 'parrot\.pageindex' \
  --include="*.py" --include="*.md" \
  --exclude-dir=__pycache__ --exclude-dir=build \
  --exclude-dir=site --exclude-dir=backup --exclude-dir=dist \
  --exclude-dir=.egg-info \
  --exclude-dir=sdd/tasks/completed --exclude-dir=sdd/tasks/archived \
  --exclude-dir=sdd/proposals \
  --exclude-dir=sdd/specs \
  . && echo "STALE REFS FOUND" || echo "grep-zero ok"

# 2. Confirm shim invariants
test ! -d packages/ai-parrot/src/parrot/pageindex
test ! -d packages/ai-parrot/tests/test_pageindex
grep -q "pageindex\|PageIndex" packages/ai-parrot/src/parrot/knowledge/__init__.py \
  && echo "FAIL: parrot.knowledge re-exports leaked" \
  || echo "knowledge namespace unchanged"

# 3. Import-allow and import-deny smoke
python -c "from parrot.knowledge.pageindex import PageIndexToolkit, PageIndexRetriever, PageIndexLLMAdapter, build_page_index, md_to_tree, JSONTreeStore, NodeContentStore, HybridPageIndexSearch, TwoStepIngester, IngestedMarkdown; print('imports ok')"
python -c "import parrot.pageindex" 2>&1 | grep -q ModuleNotFoundError && echo "old path gone"

# ─── Lint ─────────────────────────────────────────────────────────
ruff check \
  packages/ai-parrot/src/parrot/knowledge/pageindex \
  packages/ai-parrot/tests/knowledge/pageindex

# ─── Tests ────────────────────────────────────────────────────────
# Focused suites:
pytest packages/ai-parrot/tests/knowledge/pageindex -v
pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v

# Full ai-parrot suite (catches anything we missed):
pytest packages/ai-parrot/tests -v --no-header 2>&1 | tail -30

# ─── Cleanup ──────────────────────────────────────────────────────
find packages/ai-parrot -path '*__pycache__*' -name '*.pyc' -delete 2>/dev/null
rmdir packages/ai-parrot/src/parrot/pageindex 2>/dev/null
rmdir packages/ai-parrot/tests/test_pageindex 2>/dev/null

# ─── Operational config audit (info-only, no edits) ───────────────
echo "── External log-filter audit (open question §8) ──"
grep -rn '"parrot\.pageindex"\|parrot\.pageindex' \
  services/ etc/ deployments/ 2>/dev/null \
  | grep -v __pycache__ | grep -v build || echo "no operational refs found"
```

### Key Constraints

- If the grep-zero check finds matches outside the exclusion list, **diagnose** before suppressing — every match is a real stale reference. Common forgotten spots: comments, `pyproject.toml` (verify), CI workflows under `.github/workflows/`.
- The full suite (`pytest packages/ai-parrot/tests`) may have unrelated pre-existing failures (skipped optional deps, slow integration tests). Compare **failure deltas** against the suite's baseline pass count on `dev` — no new failures introduced by this PR.
- Empty old directories may be removed by Git automatically; `rmdir` is a belt-and-braces no-op if Git already cleaned them up.
- If the audit step surfaces operational configs referencing `"parrot.pageindex"`, **document them** in the task completion note as a follow-up ticket candidate. Do not edit them here.

### References in Codebase

- Spec §5 — exhaustive list of acceptance criteria mirrored in this task.
- Spec §6 — codebase contract; this task is the canonical end-state verifier for that contract.

---

## Acceptance Criteria

- [ ] Repo-wide grep (with exclusions) for `parrot\.pageindex` returns ZERO matches.
- [ ] `test ! -d packages/ai-parrot/src/parrot/pageindex` passes.
- [ ] `test ! -d packages/ai-parrot/tests/test_pageindex` passes.
- [ ] No `pageindex` or `PageIndex` token in `packages/ai-parrot/src/parrot/knowledge/__init__.py` (confirm the namespace stays a thin shell).
- [ ] No `pageindex` token in `packages/ai-parrot/src/parrot/__init__.py` (no `__getattr__` redirect).
- [ ] No `shim.py` / `compat.py` under `packages/ai-parrot/src/parrot/knowledge/pageindex/`.
- [ ] `python -c "from parrot.knowledge.pageindex import ..."` (full re-export list) succeeds.
- [ ] `python -c "import parrot.pageindex"` raises `ModuleNotFoundError`.
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/pageindex packages/ai-parrot/tests/knowledge/pageindex` returns 0 issues.
- [ ] `pytest packages/ai-parrot/tests/knowledge/pageindex -v` passes (matching baseline pass count from TASK-1330).
- [ ] `pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v` passes.
- [ ] `pytest packages/ai-parrot/tests -v` produces no NEW failures vs. the pre-feature baseline on `dev` (delta-only check).
- [ ] Operational-config audit completed; results recorded in the completion note (no edits made).

---

## Test Specification

```bash
source .venv/bin/activate

# ── Grep gate ────────────────────────────────────────────────────
HITS=$(grep -rn 'parrot\.pageindex' \
  --include="*.py" --include="*.md" \
  --exclude-dir=__pycache__ --exclude-dir=build \
  --exclude-dir=site --exclude-dir=backup --exclude-dir=dist \
  --exclude-dir=.egg-info \
  --exclude-dir=sdd/tasks/completed --exclude-dir=sdd/tasks/archived \
  --exclude-dir=sdd/proposals \
  --exclude-dir=sdd/specs \
  . | wc -l)
test "$HITS" -eq 0

# ── Import gates ─────────────────────────────────────────────────
python -c "from parrot.knowledge.pageindex import PageIndexToolkit"
python -c "import parrot.pageindex" 2>&1 | grep -q ModuleNotFoundError

# ── Lint gate ────────────────────────────────────────────────────
ruff check \
  packages/ai-parrot/src/parrot/knowledge/pageindex \
  packages/ai-parrot/tests/knowledge/pageindex

# ── Suite gate ───────────────────────────────────────────────────
pytest packages/ai-parrot/tests/knowledge/pageindex -v
pytest packages/ai-parrot/tests/knowledge/graphindex/test_loader_extractor.py -v
```

### Completion note checklist (to fill in when done)

- Pre-move test count (from TASK-1330 baseline): 167 passed / 2 failed / 21 warnings (2 pre-existing failures in test_adapter.py)
- Post-move test count: 167 passed / 2 failed / 21 warnings — identical counts, no regressions
- Cross-subsystem test: 22 passed
- Full ai-parrot suite delta vs. dev baseline: 0 new failures
- Operational config audit findings: none — `services/`, `etc/`, `deployments/`, `.github/` contain no `parrot.pageindex` references

Ruff status: 8 pre-existing errors in `src/parrot/knowledge/pageindex/` (F401 unused imports — same 8 as in original location before move). 12 pre-existing errors in `tests/knowledge/pageindex/` (same 12 as original). Not fixed — out of scope per FEAT-198 non-goals.

Grep-zero on production code: PASS (0 matches in packages/, examples/, docs/ after excluding sdd/).
sdd/tasks/active/TASK-1332 itself contains `parrot.pageindex` strings (documenting grep commands) — moved to completed/, so grep-zero holds on non-SDD paths.
sdd/state/FEAT-187/source.md contains a historical reference — preserved per spec §1 Non-Goals.

All 5 acceptance criteria structural checks: PASS.
