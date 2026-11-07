---
type: feature
base_branch: dev
feature_id: FEAT-836
projects: [ai-parrot]
tags: [sdd, worktree, ledger-fix]
discovered_from: issue:d713bb1cf575
docs:
  policy: none
---

# Feature Specification: `sdd_meta.parse()` accepts brief frontmatter

**Feature ID**: FEAT-836
**Date**: 2026-11-07
**Author**: Jesus Lara (spec drafted with Claude via /sdd-fix)
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger issue `issue:d713bb1cf575` (bug, minor, found during FEAT-698).

`parrot sdd launch worker <BRIEF-KEY>` prints:

```
Cannot parse selected brief .../sdd/briefs/<slug>.brief.md: 1 validation error for FlowMeta
type
  Field required [type=missing, input_value={'kind': 'brief', 'slug': ..., 'hotfix_base': 'main'}, input_type=dict]
stale-base check skipped: cannot resolve the base branch of this hotfix/fix worktree; pass --base explicitly
```

`worktree_sync.resolve_base_branch` reads a brief worktree's base branch with
`parse(brief).base_branch`. `parse()` passes the frontmatter to `FlowMeta`, whose `type` field is required.
`/sdd-brief` writes `kind: brief`, `slug`, `key`, `base_branch` and no `type`, so validation fails. The
resolver logs the error and then raises `SyncError` for `hotfix-*` / `fix-*` branches, so the host-side
stale-base advisory (`stale_base_summary`) is skipped for every brief worktree. That advisory is the only
warning that a hotfix/fix branch is behind its base.

### Goals

- `parse()` returns a valid `FlowMeta` for the frontmatter `/sdd-brief` emits.
- `worktree_sync.resolve_base_branch` resolves a brief worktree's base branch from its brief frontmatter, so
  the stale-base advisory runs again.

### Non-Goals (explicitly out of scope)

- No change to the brief frontmatter format or to `/sdd-brief`.
- No change to `FlowMeta`'s fields or its hotfix validator.
- No change to how `worktree_sync` looks up per-spec indexes.

---

## 2. Architectural Design

### `parse()` brief branch

In `parrot.knowledge.wiki.ledger.sdd_meta.parse`, after reading the frontmatter block and dropping
`hotfix_base`:

- When `block.get("kind") == "brief"` and `type` is absent, derive it from `base_branch`:
  `"hotfix"` when `base_branch == cfg.hotfix_base`, otherwise `"feature"`.
- An explicit `type` in a brief is kept as written (and still validated).
- A brief without `base_branch` still fails validation: a brief always declares its base, and `parse()`
  must not invent one.

`FlowMeta` ignores the other brief keys (`slug`, `key`, `source`, ...) as it already does for unknown keys.

`worktree_sync.resolve_base_branch` needs no code change: `parse(brief).base_branch` now succeeds.

---

## 3. Module Breakdown

### Module 1: brief-aware `parse()`
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py`
- **Responsibility**: derive `type` for `kind: brief` frontmatter; docstring documents the rule.

### Module 2: tests
- **Path**: `packages/ai-parrot/tests/sdd/test_brief_flow_meta.py` (new)
- **Responsibility**: `parse()` on brief frontmatter and `resolve_base_branch` on a brief worktree.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_parse_brief_on_hotfix_base_is_hotfix` | M1 | `kind: brief`, `base_branch: main`, `hotfix_base: main` (the shape from the issue) → `FlowMeta(type="hotfix", base_branch="main")` |
| `test_parse_brief_on_dev_is_feature` | M1 | `kind: brief`, `base_branch: dev` plus `slug`/`key`/`source` keys → `type="feature"`, `base_branch="dev"` |
| `test_parse_brief_explicit_type_kept` | M1 | `kind: brief`, `type: hotfix`, `base_branch: dev` → `ValidationError` (explicit type is not overridden) |
| `test_parse_brief_without_base_branch_fails` | M1 | `kind: brief` with no `base_branch` → `ValidationError` |
| `test_resolve_base_branch_reads_brief_frontmatter` | M2 | worktree dir with `sdd/briefs/<slug>.brief.md`, `_branch` patched to `fix-<KEY>-<slug>` → returns the brief's `base_branch` |
| existing `tests/sdd_scripts/test_sdd_meta.py` | M1 | unchanged and passing |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_brief_flow_meta.py
- tests/sdd_scripts/test_sdd_meta.py
- tests/sdd_scripts/test_sdd_meta_resolve_flow.py
markers: none

### Test Data / Fixtures

Tests write brief files under `tmp_path` and pass an explicit `SddConfig` (or patch `_branch`) so no real
repository is needed.

---

## 5. Acceptance Criteria

- [ ] AC-1 `parse()` on `/sdd-brief` frontmatter without `type` returns `FlowMeta` with `type="hotfix"` when
  `base_branch` is the configured hotfix base, otherwise `type="feature"`.
- [ ] AC-2 An explicit `type` in a brief is not overridden; a brief without `base_branch` still raises
  `ValidationError`.
- [ ] AC-3 `worktree_sync.resolve_base_branch` returns the brief's `base_branch` for a `fix-*` / `hotfix-*`
  brief worktree instead of raising `SyncError`.
- [ ] AC-4 Validation Contract tests pass; `ruff check` clean on the changed files.

---

## 6. Codebase Contract

- `class FlowMeta(BaseModel)` with `type: Literal["feature", "hotfix"]`, `base_branch: str`,
  `hotfix_base` (excluded) and the `_hotfix_implies_main` validator — `knowledge/wiki/ledger/sdd_meta.py:108-122`.
- `_config_for(doc_path, config) -> SddConfig` — `sdd_meta.py:125`.
- `_read_frontmatter(doc_path) -> dict | None` — `sdd_meta.py:132`.
- `parse(doc_path, *, config=None) -> FlowMeta` — `sdd_meta.py:169`; builds `FlowMeta(**block, hotfix_base=cfg.hotfix_base)`.
- `resolve_flow(...)` calls `parse(doc_path, config=cfg)` — `sdd_meta.py:359` (benefits, unchanged).
- `parrot.sdd.scripts.sdd_meta` re-exports `parse` — `sdd/scripts/sdd_meta.py:15-30`.
- `worktree_sync.resolve_base_branch(wt, override)` — `sdd/scripts/worktree_sync.py:189`; brief read at
  `worktree_sync.py:202-209`; `_branch(wt)` — `worktree_sync.py:101`; `_slug_candidates(wt)` — `worktree_sync.py:172`.

---

## 7. Implementation Notes & Constraints

- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`.

---

## 8. Open Questions

None.

---

## Revision History

| Rev | Date | Change |
|---|---|---|
| 0.1 | 2026-11-07 | Initial spec from ledger issue `issue:d713bb1cf575` |
