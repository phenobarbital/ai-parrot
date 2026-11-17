---
id: F014
query_id: Q014
type: git_log
intent: "Recent commits on the SDD docs and on the core files the branch also edits; open ledger issues from the FEAT-704 review"
executed_at: 2026-10-25T11:10:00Z
duration_ms: 4000
parent_id: null
depth: 0
---

# F014 — FEAT-738 (merged 2026-10-24) already shipped the request-scoped RLS fix that FEAT-704's M12 also implements; two ledger issues from the FEAT-704 review are still open

## Summary

`git log --since=2026-10-10` on the relevant paths: 2026-10-24 `5b88bce7a` (TASK-4679, per-user dataset clones) and `55619c5ce` (TASK-4678, request-scoped RLS injection) landed on `dev` via PR #1801 (FEAT-738 `handlers-datasets-fixes`), touching `dataset_manager/sources/authorizing.py` and `handlers/datasets.py` — the same files FEAT-704's TASK-4482 (M12, `issue:90cf04ce8edd`) edits on the branch, which explains the merge conflicts in F004. SDD history: FEAT-704 brainstorm/spec/tasks all on 2026-10-19; FEAT-713 brainstorm accepted + spec on 2026-10-21. The work ledger still has two open `minor` issues discovered by the FEAT-704 review: `issue:3c4d154c0172` (semantic toolkit catalog hardening) and `issue:46e8f6219bf5` (contains-filter does not escape LIKE wildcards).

## Citations

| Commit | When | Author | Message | Touched files |
|---|---|---|---|---|
| `5b88bce7a` | 2026-10-24 | Jesus Lara | fix(handlers): TASK-4679 — per-user dataset clones no longer share a DataSource | `packages/ai-parrot-server/src/parrot/handlers/datasets.py` |
| `55619c5ce` | 2026-10-24 | Jesus Lara | fix(dataset-manager): TASK-4678 — request-scoped RLS injection | `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` |
| `15d77efe4` | 2026-10-21 | Jesus Lara | sdd: add spec for FEAT-713 — accounting-metrics-layer | `sdd/specs/accounting-metrics-layer.spec.md` |
| `43cd6bcb3` | 2026-10-21 | Jesus Lara | sdd: accept brainstorm for accounting-metrics-layer | `sdd/proposals/accounting-metrics-layer.brainstorm.md` |
| `dd97dec23` | 2026-10-19 | Jesus | sdd: resolve §8 open questions for semantic-layer (FEAT-704, spec rev 0.2) | `sdd/specs/semantic-layer.spec.md` |
| `0324bb1d4` | 2026-10-19 | Jesus Lara | sdd: add spec for FEAT-704 — semantic-layer | `sdd/specs/semantic-layer.spec.md` |

- path: `sdd/specs/handlers-datasets-fixes.spec.md`
  lines: 1-12
  symbol: `FEAT-738`
  excerpt: |
    **Feature ID**: FEAT-738   **Date**: 2026-10-24   (PR #1801 merged → dev)

- path: `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`
  lines: 1-75
  symbol: `AuthorizingDataSource._apply_rls`
  excerpt: |
    wiki: AuthorizingDataSource._apply_rls — Return a request-scoped copy of the inner source with RLS applied. (score=0.84)

- path: `sdd/ledger/issues.jsonl`
  lines: 1
  symbol: `issue:3c4d154c0172`, `issue:46e8f6219bf5`
  excerpt: |
    issue:3c4d154c0172 [minor] open semantic toolkit: catalog/minor hardening follow-ups from FEAT-704 review (tech_debt)
    issue:46e8f6219bf5 [minor] open semantic contains-filter does not escape LIKE wildcards (bug)

## Notes

Rev2 must drop FEAT-704's M12/TASK-4482 (already delivered by FEAT-738) and fold the two open ledger issues into the salvaged `toolkit.py`/`catalog.py` work.
