# TASK-4023: Transactional SQLite page attrs and unsupported backend contract

---

**Feature**: FEAT-627 — wikitoolkit standup: entity attributes and daily/period briefs
**Spec**: `sdd/specs/wikitoolkit-standup.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implement M1 for store.py only (AC1, AC2, AC18). Add the page_attrs table/index after idx_pages_node and WikiPageRecord.attrs. Add non-abstract BaseWikiStore defaults. Implement SQLite get_attrs/list_by_attrs/upsert_attrs, get_page attrs and stats attrs_pages. Keep SCHEMA_VERSION="3". Probe table presence before the current-version migration early return, and on read-only opens without DDL. Put attrs replacement in _upsert_pages_conn so normal upserts, source replacement and compare-and-swap share the transaction. Delete attrs explicitly with removed pages even if foreign keys are disabled. Empty record.attrs must clear previous attrs. Avoid nested _write contexts. Use bound SQL parameters including filter keys; AND across keys, IN within sequence, inclusive ISO-date bounds. upsert_attrs only targets existing pages, rejects read-only writes, merges only with replace=False.

---

## Scope

Implement M1 for store.py only (AC1, AC2, AC18). Add the page_attrs table/index after idx_pages_node and WikiPageRecord.attrs. Add non-abstract BaseWikiStore defaults. Implement SQLite get_attrs/list_by_attrs/upsert_attrs, get_page attrs and stats attrs_pages. Keep SCHEMA_VERSION="3". Probe table presence before the current-version migration early return, and on read-only opens without DDL. Put attrs replacement in _upsert_pages_conn so normal upserts, source replacement and compare-and-swap share the transaction. Delete attrs explicitly with removed pages even if foreign keys are disabled. Empty record.attrs must clear previous attrs. Avoid nested _write contexts. Use bound SQL parameters including filter keys; AND across keys, IN within sequence, inclusive ISO-date bounds. upsert_attrs only targets existing pages, rejects read-only writes, merges only with replace=False.

**NOT in scope**: changes outside the declared file table; new runtime dependencies; unrelated cleanup. Follow the approved v1 non-goals for backend parity and pre-existing ledger import cost.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | Putting attrs in the existing connection-scoped write helper covers all page write entry points atomically. |
| `packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py` | CREATE | Use real temporary SQLite files and an injected failure, not mocked transaction assertions. |

---

## Codebase Contract (Anti-Hallucination)

Verified at `75fe680a0`. Dependency-created imports below are planned contracts, not claims of current existence.

### Verified Imports

```python
from collections.abc import Mapping, Sequence  # stdlib or existing pyproject dependency/test environment
from typing import Any  # stdlib or existing pyproject dependency/test environment
from pydantic import Field  # stdlib or existing pyproject dependency/test environment
from pathlib import Path  # stdlib or existing pyproject dependency/test environment
import pytest  # stdlib or existing pyproject dependency/test environment
import parrot.knowledge.wiki.store as subject  # verified source packages/ai-parrot/src/parrot/knowledge/wiki/store.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409
class WikiPageRecord(BaseModel):

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525
class BaseWikiStore(ABC):

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1370
    async def _migrate(self, conn: aiosqlite.Connection) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1339
    async def _migration_needed(
        self,
        conn: aiosqlite.Connection,
    ) -> tuple[list[tuple[str, str, str]], bool]:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1533
    async def _upsert_pages_conn(
        self,
        conn: aiosqlite.Connection,
        pages: list[WikiPageRecord],
    ) -> None:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1664
    async def replace_source_slice(
        self,
        source_id: str,
        pages: list[WikiPageRecord],
        edges: Optional[list[tuple[str, str, str]]] = None,
    ) -> dict[str, Any]:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1751
    async def delete_page(self, concept_id: str) -> bool:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2005
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]:

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:2228
    async def stats(self) -> dict[str, Any]:
```

### Does NOT Exist

- `packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py` is created by this task; do not assume it already exists.
- `list_pages(offset=...)`, `DecisionRecord.updated_at`, and a JiraPerson email field are not existing APIs. Do not invent them.
- Category names remain open strings; no new WikiPageCategory enum members are required.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#WikiPageRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._migrate",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._migration_needed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._upsert_pages_conn",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.replace_source_slice",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.delete_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.get_page",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore.stats"
  ]
}
```

---

## Implementation Notes

Independent sqlite-page-attrs deliverable; uses existing verified code only and owns its declared files.

Use async I/O paths, existing lifecycle/context managers, module logging, strict types and Google-style docstrings. Black uses 120 columns; ruff is the lint gate. Keep tests isolated and file-scoped. Fresh dependency code may shift anchors: reverify before edits, and retain the semantic attachment site.

---

## Implementation Blueprint

### Steps (in order)

1. Verify the existing references and completed dependency interfaces — because the blueprint must match the executing worktree.
2. Apply the per-file blocks below in declared order and complete only bounded FILL IN work — because each task owns a limited surface.
3. Implement the listed adversarial cases and run Validation Commands — because the acceptance criteria cover observable behavior, not only imports.

---

### `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` (MODIFY)

Anchor `class WikiPageRecord(BaseModel):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:409`.

Anchor `CREATE INDEX IF NOT EXISTS idx_pages_node     ON pages(node_id);` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:110`.

Anchor `class BaseWikiStore(ABC):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:525`.

Anchor `class SQLiteWikiStore(BaseWikiStore):` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:878`.

Anchor `    async def _migrate(self, conn` — occurrences: 1 (verified: `grep -F -c`), `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1370`.

```python
from collections.abc import Mapping, Sequence
from typing import Any
from pydantic import Field
class AttrsUnsupportedError(RuntimeError):
    """Raised when a backend cannot persist page attributes."""
# Add attrs to the existing WikiPageRecord class, preserving all current fields.
attrs: dict[str, str] = Field(default_factory=dict)
# Add AttrsUnsupportedError(RuntimeError) and the following NON-abstract methods
# to BaseWikiStore; override them on SQLiteWikiStore with the same signatures.
supports_attrs: bool = False
async def get_attrs(self, concept_id: str) -> dict[str, str]:
    """Return persisted attrs, or an empty mapping when unsupported."""
    return {}
async def list_by_attrs(
    self, filters: Mapping[str, str | Sequence[str]], *, date_key: str | None = None,
    since: str | None = None, until: str | None = None, limit: int = 200,
) -> list[dict[str, Any]]:
    """Return matching page stubs without bodies; unsupported stores return none."""
    return []
async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int:
    """Persist attrs only on supported writable stores."""
    raise AttrsUnsupportedError("This wiki backend does not support page attrs")
# FILL IN: import Mapping/Sequence from collections.abc, retain existing Any/Field.
# DDL after the verified idx_pages_node line:
# CREATE TABLE IF NOT EXISTS page_attrs (
#   concept_id TEXT NOT NULL REFERENCES pages(concept_id) ON DELETE CASCADE,
#   key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (concept_id, key));
# CREATE INDEX IF NOT EXISTS idx_page_attrs_kv ON page_attrs(key, value);
# FILL IN: implement SQLite overrides, lifecycle/migration and stats per AC1/AC2.
# _upsert_pages_conn receives the existing connection: do not open a new writer.
# Read-only old planes must never attempt CREATE TABLE or query a missing table.
```

**Why**: Putting attrs in the existing connection-scoped write helper covers all page write entry points atomically.

---

### `packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py` (CREATE)

```python
"""Regression cases for FEAT-627."""
from pathlib import Path
import pytest
import parrot.knowledge.wiki.store as subject


def test_attrs_transaction_and_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify attrs transaction and lifecycle."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_v3_migration_and_readonly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify v3 migration and readonly."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError


def test_filters_merge_and_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify filters merge and unsupported."""
    # FILL IN: build isolated inputs and assert the corresponding AC below.
    # Use pytest.mark.asyncio / async def when exercising async APIs.
    raise NotImplementedError
```

**Why**: Use real temporary SQLite files and an injected failure, not mocked transaction assertions.

---

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py` — complete the block instructions and tests within this task’s acceptance criteria; leave no implementation placeholders.

---

## Acceptance Criteria

- [ ] Writable legacy v3 gains attrs table without schema bump; read-only legacy v3 reports unsupported and empty reads.
- [ ] Forced page/attrs failure rolls back both; replacement/deletion/CAS do not leak stale attrs or orphan rows.
- [ ] AND/IN/date filtering, empty filters, merge/replace and missing-page handling are tested; stats counts distinct attr-bearing pages.
- [ ] Base defaults preserve abstract surface; Arango/Postgres inherit unsupported behavior without live network access.
- [ ] All declared-file tests pass; no ruff errors or unfinished implementation placeholders remain.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_attrs.py -q`
- `pytest tests/knowledge/wiki/test_store_migration_v2.py -q`
- `pytest tests/knowledge/wiki/test_store_concurrency.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_store_meta_backends.py -q`

---

## Test Specification

- Writable legacy v3 gains attrs table without schema bump; read-only legacy v3 reports unsupported and empty reads.
- Forced page/attrs failure rolls back both; replacement/deletion/CAS do not leak stale attrs or orphan rows.
- AND/IN/date filtering, empty filters, merge/replace and missing-page handling are tested; stats counts distinct attr-bearing pages.
- Base defaults preserve abstract surface; Arango/Postgres inherit unsupported behavior without live network access.

Use temporary local state, deterministic clocks and fake network/model adapters. Test failures and negative cases as well as success. New tests live alongside the core distribution; legacy suites are validation references only unless explicitly declared MODIFY above.

---

## Agent Instructions

1. Run `$sdd-start TASK-4023`; implementation belongs in the feature worktree, never directly on dev.
2. Read the approved spec and verify dependency completion in `sdd/tasks/index/wikitoolkit-standup.json`.
3. Recheck imports/anchors, implement only declared files and run the validation commands.
4. Commit scoped implementation and finalize with `scripts.sdd.finalize_task` plus real `TaskCompletionEvidence` for the exact implementation HEAD. Do not manually move the task or manufacture completion evidence.

## Completion Note

Pending; owned by the evidence-based finalizer.
