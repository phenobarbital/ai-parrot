# TASK-5509: DocumentDB → Redis copy CLI (`python -m parrot.userstore.copy`)

**Feature**: FEAT-878 — Redis user stores (MongoDB-free local installs)
**Spec**: `sdd/specs/redis-user-stores.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5496
**Assigned-to**: unassigned

---

## Context

Spec §2 "Copy CLI", §3 Module 12, AC11. Operators moving an installation from MongoDB to Redis (the fix
named in the startup guard error) copy existing documents with this command. Documents are copied
verbatim (the Redis document shape mirrors DocumentDB), so sealed values need no keyring.

---

## Scope

- Implement `copy_to_redis(collections=None, *, dry_run=False, overwrite=False) -> CopyReport` and `main(argv)`.
- Read each selected DocumentDB collection with `DocumentDb().read(name, {})`; drop `_id`; convert BSON
  datetimes to ISO strings (the store's JSON default does this); write with `RedisDocumentStore(spec)`.
- Insert-only by default (existing Redis key → `skipped`); `--overwrite` replaces only when the source
  `updated_at` is strictly newer; `--dry-run` writes nothing but counts.
- Collapse duplicate DocumentDB documents for one key to the newest by `updated_at` (rest → `duplicates`).
- Print counts per collection; exit 1 when any document failed. Log identities and exception classes only.

**NOT in scope**: Redis → DocumentDB, Postgres targets (Studio `secrets_copy` already does DocumentDB → Postgres), quarantine collections.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/userstore/copy.py` | CREATE | copy logic + CLI |
| `packages/ai-parrot/tests/userstore/test_copy.py` | CREATE | tests (fake DocumentDb + Redis db 15) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.documentdb import DocumentDb                       # verified: interfaces/documentdb.py:65
from parrot.userstore import RedisDocumentStore, USER_STORE_COLLECTIONS   # TASK-5496
from parrot.userstore.collections import CollectionSpec                   # TASK-5496
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/documentdb.py
class DocumentDb:                                                          # line 65 — async context manager (connects on __aenter__)
    async def read(...)                                                    # line 370 — read(collection_name, query, ...) -> list[dict]

# RedisDocumentStore (TASK-5496): get(key), put(document), exists(key)
# Pattern reference: packages/ai-parrot-server/src/parrot/handlers/studio/storage/secrets_copy.py
#   (insert-only default, --overwrite newer-wins, --dry-run, counts + exit code 1 on failures, identity-only logs)
```

### Does NOT Exist
- ~~`parrot.userstore.copy`~~ — created by this task.
- ~~A keyring requirement~~ — ciphertexts are copied as-is; nothing is decrypted.
- ~~`DocumentDb.read_all`~~ — use `read(name, {})`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/userstore/copy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/userstore/test_copy.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/documentdb.py#DocumentDb"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `updated_at` comparison: parse to aware datetimes (`datetime.fromisoformat`, BSON `datetime` as-is, naive → UTC);
  a source without `updated_at` never overwrites.
- A document missing a key field counts as `failed` (logged with collection + exception class), never aborts the run.
- Use `asyncio.run(...)` in `main`; argparse flags `--dry-run`, `--overwrite`, `--collections a,b`
  (unknown collection name → exit 2 with a message listing valid names).

---

## Implementation Blueprint

### Steps (in order)
1. Write `CopyReport`, the per-collection copy, and `copy_to_redis` — *why*: testable without the CLI.
2. Write `main()` with argparse — *why*: the documented operator entry point.
3. Write tests with a fake `DocumentDb` (patch `parrot.userstore.copy.DocumentDb`) and Redis db 15.

### `packages/ai-parrot/src/parrot/userstore/copy.py` (CREATE)
```python
"""Copy user-store documents from DocumentDB into Redis (FEAT-878). Verbatim: sealed values are not re-sealed.

Usage::

    python -m parrot.userstore.copy --dry-run
    python -m parrot.userstore.copy
    python -m parrot.userstore.copy --collections user_credentials,user_llm_keys --overwrite
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from parrot.interfaces.documentdb import DocumentDb

from .collections import USER_STORE_COLLECTIONS, CollectionSpec
from .redis_documents import RedisDocumentStore

logger = logging.getLogger("parrot.userstore.copy")


@dataclass
class CopyReport:
    copied: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    duplicates: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)

    @property
    def any_failed(self) -> bool:
        return any(self.failed.values())


def _when(value: Any) -> datetime | None:
    """Aware datetime for an ``updated_at`` value, or None."""
    # FILL IN: datetime → aware; str → fromisoformat (tolerate trailing 'Z'); else None
    raise NotImplementedError


def _newest_per_key(spec: CollectionSpec, docs: list[dict[str, Any]], report: CopyReport) -> list[dict[str, Any]]:
    """Collapse duplicates (same key) to the newest by updated_at; count the rest as duplicates."""
    # FILL IN: group by tuple(str(doc.get(f)) for f in spec.key_fields); keep max by (_when(updated_at) or epoch)
    raise NotImplementedError


async def _copy_collection(spec: CollectionSpec, report: CopyReport, *, dry_run: bool, overwrite: bool) -> None:
    async with DocumentDb() as db:
        docs = await db.read(spec.name, {}) or []
    store = RedisDocumentStore(spec)
    for doc in _newest_per_key(spec, [{k: v for k, v in d.items() if k != "_id"} for d in docs], report):
        # FILL IN: existing = await store.get(doc) (ValueError → failed); skip unless overwrite and source strictly newer;
        #   put unless dry_run; count copied/skipped/failed; on failure log collection + key fields + exception class only.
        raise NotImplementedError


async def copy_to_redis(collections: Sequence[str] | None = None, *, dry_run: bool = False,
                        overwrite: bool = False) -> CopyReport:
    """Copy the selected collections (default: all of USER_STORE_COLLECTIONS)."""
    report = CopyReport()
    for name in collections or list(USER_STORE_COLLECTIONS):
        await _copy_collection(USER_STORE_COLLECTIONS[name], report, dry_run=dry_run, overwrite=overwrite)
    return report


def main(argv: list[str] | None = None) -> int:
    """Flags: --dry-run, --overwrite, --collections a,b. Exit 1 when any document failed, 2 on bad arguments."""
    # FILL IN: argparse; validate --collections against USER_STORE_COLLECTIONS (exit 2); asyncio.run(copy_to_redis(...));
    #   print "would copy:" (dry run) or "copied:" plus skipped/duplicates/failed dicts; return 1 if report.any_failed.
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
```
**Why**: shape and flags follow Studio `secrets_copy` so operators see one convention; verbatim copy is the
"Document shape rule" of the spec.

### FILL IN checklist
- [ ] `_when`, `_newest_per_key`
- [ ] per-document decision (skip / overwrite newer-wins / dry run)
- [ ] `main` argparse + output + exit codes

---

## Acceptance Criteria

- [ ] A sealed credential copied from (fake) DocumentDB decrypts from Redis with the same keyring (AC11)
- [ ] Second run is a no-op (all `skipped`); `--overwrite` replaces only strictly newer sources (AC11)
- [ ] `--dry-run` writes nothing; duplicates collapse to the newest
- [ ] No ciphertext or value appears in logs (caplog) (AC14)
- [ ] `ruff check` clean

---

## Validation Commands
- `pytest packages/ai-parrot/tests/userstore/test_copy.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/userstore/test_copy.py
import pytest

from parrot.userstore import copy as copy_mod
from parrot.userstore.testing import redis_test_settings


class _FakeDocumentDb:
    collections: dict[str, list[dict]] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self, name, query):
        return [dict(d) for d in self.collections.get(name, [])]


@pytest.fixture
async def env(monkeypatch):
    monkeypatch.setattr(copy_mod, "DocumentDb", _FakeDocumentDb)
    async with redis_test_settings(monkeypatch):
        yield


async def test_copy_insert_only_and_overwrite(env): ...
async def test_copy_dry_run_writes_nothing(env): ...
async def test_copy_collapses_duplicates(env): ...
async def test_copy_no_secret_in_logs(env, caplog): ...
def test_main_rejects_unknown_collection(): ...   # exit code 2
```

---

## Agent Instructions

1. **Work in the feature worktree** — `parrot sdd worktree ensure --slug redis-user-stores --feature-id FEAT-878`
2. **Read the spec** (§2 Copy CLI, §3 M12, AC11)
3. **Check dependencies** — TASK-5496 must be `done`
4. **Verify the Codebase Contract**
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement** from the blueprint, complete every `# FILL IN:`
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — only the files listed above
9. **Close the task** — `parrot sdd task close TASK-5509 redis-user-stores verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
