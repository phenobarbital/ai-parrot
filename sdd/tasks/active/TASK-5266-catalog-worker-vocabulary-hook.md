# TASK-5266: `ConceptCatalogSyncWorker` republishes tenants to the vocabulary store

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5265
**Assigned-to**: unassigned

---

## Context

Spec Module 10 (worker half). The existing outbox worker gains an **optional**
`vocabulary_publisher`. After a batch transaction commits, it calls `publish_tenant` once per
distinct `payload["tenant_id"]` seen in the batch. Publication is a full-state projection and an
unchanged ontology creates no version, so the call is idempotent. A failure is logged and never
raised. Behaviour without the argument — including the ArangoDB materialisation — is unchanged
(spec AC; D-P7: ArangoDB stays until Phase 7).

---

## Scope

- `concept_catalog/worker.py`: add keyword-only `vocabulary_publisher: CatalogVocabularyPublisher | None = None`
  to `__init__` (store as `self._vocabulary_publisher`); at the end of `run_once`, before
  `return len(rows)`, when a publisher is set, collect distinct non-empty tenant ids from
  `dict(row["payload"]).get("tenant_id")` over `rows` and await `publish_tenant` for each, catching
  and logging any exception per tenant.
- Import `CatalogVocabularyPublisher` under `TYPE_CHECKING` only (no runtime import of the
  vocabulary package from the worker).
- `test_worker_vocabulary.py` — new file; do **not** edit the existing `test_worker.py`.

**NOT in scope**: any change to `_op_publish` / `_op_deprecate` / `_op_invalidate` or to the
ArangoDB calls; changing `run_once`'s return value.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py` | MODIFY | optional publisher + republish |
| `packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker_vocabulary.py` | CREATE | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import TYPE_CHECKING
# under TYPE_CHECKING only:
from parrot.knowledge.ontology.vocabulary.catalog_bridge import CatalogVocabularyPublisher   # TASK-5265
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py (verified at 8b73aa8c88)
from typing import Any                                                     # :11
class ConceptCatalogSyncWorker:                                            # :18
    def __init__(self, pg_pool: Any, graph_store: ArangoOntologyGraphStore, redis_client: Any) -> None:  # :44-49
        self._pool = pg_pool; self._graph_store = graph_store; self._redis = redis_client      # :50-52
        self.logger = logging.getLogger("Parrot.Ontology.ConceptCatalog.Worker")             # :53
    async def run_once(self, batch_size: int = 50) -> int:                # :57
        # rows = await conn.fetch("SELECT * FROM ontology_concept_outbox ... FOR UPDATE SKIP LOCKED")  # :75-82
        return len(rows)                                                   # :131  (outside the async with blocks)
    # payload read pattern: payload = dict(row["payload"]) if row["payload"] else {}; payload.get("tenant_id")  # :146-148
# test pattern — packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker.py:18-40 (_make_pool, _make_conn with transaction())
```

### Does NOT Exist
- ~~`ontology_concept_outbox.tenant_id`~~ — the tenant is in the payload JSON only.
- ~~a runtime import of `parrot.knowledge.ontology.vocabulary` in `worker.py`~~ — TYPE_CHECKING only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker_vocabulary.py", "action": "CREATE"}
  ],
  "contract_symbols": ["sym:packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py#ConceptCatalogSyncWorker"]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the TYPE_CHECKING import — *why*: annotation without a runtime dependency.
2. Extend `__init__` — *why*: optional argument keeps every existing caller working.
3. Insert the republish block before `return len(rows)` — *why*: runs after the batch transaction committed.
4. Tests.

### `.../concept_catalog/worker.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c '^from typing import Any$' worker.py)
# REPLACE `from typing import Any` (verified: worker.py:11) with:
from typing import TYPE_CHECKING, Any
```
and add, below `from parrot.knowledge.ontology.schema import TenantContext` (worker.py:15, occurrences: 1):
```python

if TYPE_CHECKING:
    from parrot.knowledge.ontology.vocabulary.catalog_bridge import CatalogVocabularyPublisher
```

### `.../concept_catalog/worker.py` (MODIFY) — `__init__`
```python
# occurrences: 1 (verified: grep -c '        redis_client: Any,' worker.py)
# AFTER — insert below `        redis_client: Any,` (verified: worker.py:48)
        *,
        vocabulary_publisher: "CatalogVocabularyPublisher | None" = None,
```
and, below `        self._redis = redis_client` (worker.py:52, occurrences: 1):
```python
        self._vocabulary_publisher = vocabulary_publisher
```

### `.../concept_catalog/worker.py` (MODIFY) — republish
```python
# occurrences: 1 (verified: grep -c '        return len(rows)' worker.py)
# BEFORE — insert above `        return len(rows)` (verified: worker.py:131)
        if self._vocabulary_publisher is not None:
            await self._republish_tenants(rows)
```
and add the private method right after `run_once` (before the `# ── Operation handlers` comment):
```python
    async def _republish_tenants(self, rows: Any) -> None:
        """Publish each distinct tenant of the batch to the vocabulary store; never raises."""
        # FILL IN: distinct non-empty payload tenant ids (sorted); await publish_tenant each;
        #          self.logger.exception per failing tenant and continue.
```

### `.../concept_catalog/test_worker_vocabulary.py` (CREATE) — required cases
```python
async def test_worker_republishes_tenants(): ...          # rows with tenants a, a, b → publish_tenant called for a and b once each
async def test_publisher_error_does_not_fail_run_once(): ...  # publish_tenant raises → run_once still returns len(rows)
async def test_worker_without_publisher_unchanged(): ...  # no argument → no publish attempt; graph_store calls as before
```

### FILL IN checklist
- [ ] `_republish_tenants` body.
- [ ] three tests (mock pool/conn as in `test_worker.py:18-40`).

---

## Acceptance Criteria

- [ ] Without `vocabulary_publisher` the worker behaves exactly as before; existing `test_worker.py` passes unchanged.
- [ ] With it, each distinct tenant of a batch is published once; a publisher failure never fails `run_once`.
- [ ] ArangoDB materialisation untouched.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker_vocabulary.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/concept_catalog/test_worker.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5265 is `done`.
2. Re-run each `grep -c` anchor check; a count other than 1 means the file moved — re-locate and note it.
3. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit only the listed files; close with `parrot sdd task close TASK-5266 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
