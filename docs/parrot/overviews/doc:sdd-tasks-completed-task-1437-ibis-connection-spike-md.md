---
type: Wiki Overview
title: 'TASK-1437: Ibis ⇄ navconfig connection spike (decision gate)'
id: doc:sdd-tasks-completed-task-1437-ibis-connection-spike-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The single biggest unknown in this feature (spec §3 Module 2, §8 open question
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: mentions
---

# TASK-1437: Ibis ⇄ navconfig connection spike (decision gate)

**Feature**: FEAT-219 — Spatial Filtering for DatasetManager
**Spec**: `sdd/specs/spatial-dataset-filter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1436
**Assigned-to**: unassigned

---

## Context

The single biggest unknown in this feature (spec §3 Module 2, §8 open question
"Ibis ⇄ navconfig connection mapping"). The engine push-down compiler (TASK-1438) can use
Ibis to compile ONE expression to both PostGIS and BigQuery `ST_DWITHIN` — **but only if**
`_get_connection_args()`'s `(credentials_dict, dsn)` maps cleanly onto Ibis's connect
signatures. This is a **time-boxed spike** whose only deliverable is a GO/NO-GO decision.

---

## Scope

- Investigate whether `TableSource._get_connection_args()` output maps onto:
  - `ibis.postgres.connect(host, port, user, password, database)`
  - `ibis.bigquery.connect(project_id, credentials)`
- Determine if a translation shim is required, and if so how thin/ugly it is.
- Produce a written **GO / NO-GO** recommendation:
  - **GO** → TASK-1438 uses Ibis; add `ibis-framework` to `pyproject.toml` (conditional extra).
  - **NO-GO** → TASK-1438 uses ~2 hand-written SQL dialect templates (pg + bigquery),
    `syrupy`-snapshotable. (Brainstorm Option C — already pre-approved as the fallback.)
- Record the decision in this task's Completion Note AND update spec §8 the open question
  to `[x]` with the outcome.

**NOT in scope**: building the actual compiler (TASK-1438), the fallback path (TASK-1439),
or merging `ibis-framework` into `pyproject.toml` unless the outcome is GO.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/spatial/_ibis_probe.py` | CREATE (throwaway) | minimal probe exercising both connect paths |
| `sdd/specs/spatial-dataset-filter.spec.md` | MODIFY | flip §8 Ibis OQ to `[x]` with the outcome |

> The throwaway probe may be deleted before TASK-1438 — it exists only to produce the decision.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-03. Paths under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.

### Verified Imports
```python
from parrot.tools.dataset_manager.table import TableSource  # table.py:113
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/table.py
def _resolve_credentials(driver: str) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.55  (module-level)
class TableSource(DataSource):                          # l.113
    self.driver = _normalize_driver(driver)             # l.157  (normalized: "pg","bigquery","mysql",…)
    def _get_connection_args(self) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.311  → (credentials_dict, dsn)
    def _build_schema_query(self) -> Tuple[str, bool]: ...  # l.325  (confirms pg/bigquery/mysql are live drivers)
```

### Does NOT Exist
- ~~`ibis` / `ibis-framework`~~ — NOT yet installed. This spike decides whether it gets added.
- ~~any existing Ibis usage in the repo~~ — none. No prior art to copy.
- ~~`DataSource.driver`~~ — `driver` is on `TableSource` only (table.py:157), not the base. Use `getattr(source, "driver", None)`.

---

## Implementation Notes

### Key Constraints
- Time-box it. The deliverable is a DECISION, not production code.
- If GO: the conditional dependency is `ibis-framework` (version TBD, target `>=9`).
- If NO-GO: explicitly note that TASK-1438 builds ~2 hand-written dialect templates instead
  (no Ibis import anywhere in the feature).
- Map the navconfig credentials dict keys explicitly — document exact key → Ibis-param
  mapping (or the gap) in the Completion Note so TASK-1438 inherits a precise answer.

### References in Codebase
- `parrot/tools/dataset_manager/table.py:311` — `_get_connection_args`.
- `parrot/tools/dataset_manager/table.py:55` — `_resolve_credentials`.

---

## Acceptance Criteria

- [ ] A documented GO/NO-GO decision with the explicit credentials → Ibis-param mapping (or gap).
- [ ] Spec §8 Ibis open question flipped to `[x]` with the outcome.
- [ ] If GO: a one-line note on which `pyproject.toml` extra TASK-1438 should add.
- [ ] If NO-GO: a one-line note confirming TASK-1438 uses hand-written dialect templates.
- [ ] No linting errors in any non-throwaway file touched: `ruff check`.

---

## Test Specification

> A spike — no permanent unit tests required. If the probe is kept, it must be excluded
> from the default test run (e.g. underscore-prefixed module / marked manual).

```python
# parrot/tools/dataset_manager/spatial/_ibis_probe.py  (throwaway)
# Exercises ibis.postgres.connect(...) and ibis.bigquery.connect(...) from
# TableSource._get_connection_args() output; prints the mapping result.
```

---

## Agent Instructions

Standard SDD lifecycle. This task's primary output is the **Completion Note decision** and
the spec §8 update — make both explicit and unambiguous, because TASK-1438 branches on them.

---

## Completion Note

**Completed by**: Claude Sonnet (sdd-worker)
**Date**: 2026-06-03
**Decision**: NO-GO — TASK-1438 uses hand-written SQL dialect templates; `ibis-framework` is NOT added to `pyproject.toml`.
**Credentials → Ibis mapping**:
  - pg: host/port/database/user/password → direct match (no shim needed for dict form)
  - pg DSN: asyncpg DSN format (asyncpg://...) ≠ psycopg/libpq format — non-trivial translation gap
  - bigquery: project_id → direct match; credentials (navconfig Path) → ibis expects google.oauth2.Credentials object — requires from_service_account_file() shim
**Notes**: ibis-framework is not installed in the project. pg dict credentials map cleanly, but the DSN path has a format mismatch and bigquery requires a google-auth shim. The brainstorm pre-approved hand-written dialect templates (Option C) as the fallback. Two short SQL template strings are far simpler than adding a new heavy dependency with credential translation complexity.
**Deviations from spec**: none
