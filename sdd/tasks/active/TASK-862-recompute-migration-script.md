# TASK-862: Migration script `recompute_contextual_embeddings.py`

**Feature**: FEAT-127 — Metadata-Driven Contextual Embedding Headers
**Spec**: `sdd/specs/contextual-embedding-headers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-857
**Assigned-to**: unassigned

---

## Context

Spec §8 Open Question 5 — answered "create the migration tooling" by
Jesus Lara. This task ships a one-shot CLI script that, given a
PgVector table, re-embeds existing rows in place using the contextual
header derived from each row's `document_meta` (already stored in the
`cmetadata` JSONB column).

The script is for ops use against existing collections that pre-date the
flag flip. It is NOT auto-invoked anywhere in the framework; users opt
in by running `python scripts/recompute_contextual_embeddings.py ...`.

Spec sections: §1 Goals (4) note about backfilling, §7 Risk #3, §8 Q5.

---

## Scope

- Create `packages/ai-parrot/scripts/recompute_contextual_embeddings.py`.
- CLI args (use `argparse`):
  - `--dsn` (required) — Postgres DSN.
  - `--table` (required) — table name.
  - `--schema` (default `public`).
  - `--embedding-model` (default reads from `parrot.conf.EMBEDDING_DEFAULT_MODEL`).
  - `--template` (optional) — template string; default uses
    `parrot.stores.utils.contextual.DEFAULT_TEMPLATE`.
  - `--max-header-tokens` (default 100).
  - `--batch-size` (default 200).
  - `--dry-run` (flag) — log what would change without writing.
  - `--limit` (optional int) — process at most N rows (for testing).
  - `--where` (optional SQL fragment) — extra filter, e.g. to skip rows
    that already carry `contextual_header`.
- Behaviour:
  1. Open `PgVectorStore(dsn=..., contextual_embedding=False, ...)` (the
     flag stays OFF on the store; we drive augmentation manually).
  2. Stream rows in batches of `batch_size`. For each row:
     - Build a `Document(page_content=row['document'], metadata=row['cmetadata'])`.
     - Call `build_contextual_text(doc, template, max_header_tokens)`.
     - If header is empty (no usable `document_meta`), skip the row
       (log at INFO with row id).
     - Else compute `new_embedding = await store._embed_.embed_documents([text])[0]`.
     - Update row: `embedding = new_embedding`, `cmetadata = cmetadata + {'contextual_header': header}`.
  3. Use a single transaction per batch.
  4. Print a final summary: `processed=X updated=Y skipped=Z duration=...`.
- `--dry-run` short-circuits the UPDATE; everything else (read, render,
  embed) still runs so users can validate.

**NOT in scope**:

- Migration for Milvus / Faiss / Arango. Postgres only for v1.
- Schema migrations — `cmetadata` is already JSONB.
- Auto-invocation from any framework path.
- Re-running `LateChunkingProcessor`. The script operates on already-chunked
  rows.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/scripts/recompute_contextual_embeddings.py` | CREATE | The CLI script. |
| `packages/ai-parrot/tests/unit/scripts/test_recompute_contextual_embeddings.py` | CREATE | Unit test against the rendering+UPDATE construction logic, mocking the DB. |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-04-27.

### Verified Imports

```python
from parrot.stores.models import Document                            # parrot/stores/models.py:21
from parrot.stores.postgres import PgVectorStore                     # parrot/stores/postgres.py
from parrot.stores.utils.contextual import (                         # CREATED by TASK-855
    build_contextual_text,
    DEFAULT_TEMPLATE,
    DEFAULT_MAX_HEADER_TOKENS,
)
from parrot.conf import EMBEDDING_DEFAULT_MODEL                      # parrot/conf
```

### Existing Public Surface to Use

```python
# PgVectorStore — existing helpers the script can re-use
store = PgVectorStore(
    dsn=...,
    table=...,
    schema=...,
    embedding_model=...,
    contextual_embedding=False,   # script drives augmentation manually
)
await store.connection()
async with store.session() as session: ...                           # context manager exists
store._embed_.embed_documents(texts) -> list[np.ndarray]             # async, used at postgres.py:622
store._sanitize_metadata(metadata: dict) -> dict                     # postgres.py:653
```

### Does NOT Exist

- ~~`PgVectorStore.iter_rows(...)`~~ — there is no batched-row iterator
  helper. The script must issue a `SELECT id, document, cmetadata, embedding FROM <table>`
  with a server-side cursor or `OFFSET / LIMIT` paging.
- ~~`PgVectorStore.update_row(id, ...)`~~ — no public update helper. Use
  raw SQLAlchemy `update(table).where(...).values(...)` inside
  `store.session()`.
- ~~A `parrot.scripts` module~~ — `scripts/` is a top-level directory
  with executable Python files; no `__init__.py` required.

---

## Implementation Notes

### Skeleton

```python
#!/usr/bin/env python
"""Recompute embeddings of an existing PgVector table using metadata-derived
contextual headers (FEAT-127).

Usage:
    python scripts/recompute_contextual_embeddings.py \
        --dsn postgresql://... \
        --table my_collection --schema public \
        --batch-size 200 --dry-run
"""
import argparse, asyncio, logging
from sqlalchemy import select, update
from parrot.stores.models import Document
from parrot.stores.postgres import PgVectorStore
from parrot.stores.utils.contextual import (
    build_contextual_text, DEFAULT_TEMPLATE, DEFAULT_MAX_HEADER_TOKENS,
)


async def run(args):
    store = PgVectorStore(
        dsn=args.dsn,
        table=args.table,
        schema=args.schema,
        embedding_model=args.embedding_model,
        contextual_embedding=False,   # we augment manually
    )
    await store.connection()

    template = args.template or DEFAULT_TEMPLATE
    processed = updated = skipped = 0

    async with store.session() as session:
        # Iterate in batches using OFFSET/LIMIT.
        offset = 0
        while True:
            rows = (await session.execute(
                select(store.embedding_store).limit(args.batch_size).offset(offset)
            )).scalars().all()
            if not rows:
                break
            offset += len(rows)

            new_payloads = []
            for row in rows:
                processed += 1
                if args.limit and processed > args.limit:
                    break
                doc = Document(
                    page_content=row.document,
                    metadata=dict(row.cmetadata or {}),
                )
                text, header = build_contextual_text(
                    doc, template, args.max_header_tokens,
                )
                if not header:
                    skipped += 1
                    continue
                [emb] = await store._embed_.embed_documents([text])
                new_payloads.append((
                    row.id,
                    emb.tolist() if hasattr(emb, "tolist") else emb,
                    {**(row.cmetadata or {}), "contextual_header": header},
                ))

            if not args.dry_run and new_payloads:
                for row_id, emb, cmeta in new_payloads:
                    await session.execute(
                        update(store.embedding_store)
                        .where(store.embedding_store.id == row_id)
                        .values(embedding=emb, cmetadata=cmeta)
                    )
                updated += len(new_payloads)

            if args.limit and processed >= args.limit:
                break

    logging.info("processed=%d updated=%d skipped=%d", processed, updated, skipped)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dsn", required=True)
    p.add_argument("--table", required=True)
    p.add_argument("--schema", default="public")
    p.add_argument("--embedding-model", default=None)
    p.add_argument("--template", default=None)
    p.add_argument("--max-header-tokens", type=int, default=DEFAULT_MAX_HEADER_TOKENS)
    p.add_argument("--batch-size", type=int, default=200)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
```

### Key Constraints

- The script must be runnable WITHOUT importing this from a long-lived
  process. Wrap everything in `asyncio.run`.
- `store.contextual_embedding` MUST stay False on the script's
  `PgVectorStore` instance — otherwise the inherited
  `_apply_contextual_augmentation` would double-apply on any code path
  that uses it.
- `--dry-run` must NOT issue UPDATEs but must still issue
  `embed_documents` calls so users can validate the embedding model is
  reachable.

### References in Codebase

- `parrot/stores/postgres.py:646` — value list shape inside `add_documents`
  (mirror the embedding `tolist()` pattern).
- `parrot/stores/postgres.py:663` — `async with self.session() as session`
  pattern.

---

## Acceptance Criteria

- [ ] `scripts/recompute_contextual_embeddings.py` is executable and
      `--help` prints all arguments.
- [ ] Dry-run mode performs reads and renderings but no UPDATEs.
- [ ] Real run updates `embedding` AND `cmetadata['contextual_header']`
      per row that yields a non-empty header.
- [ ] Rows with empty/missing `document_meta` are skipped (counted, not
      errored).
- [ ] Final summary line emitted at INFO.
- [ ] Unit test passes:
      `pytest packages/ai-parrot/tests/unit/scripts/test_recompute_contextual_embeddings.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/scripts/test_recompute_contextual_embeddings.py
"""Drive the run() coroutine against a fully mocked store and session."""
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
import numpy as np
import pytest


@pytest.fixture
def args():
    return SimpleNamespace(
        dsn="postgresql://x", table="t", schema="public",
        embedding_model=None, template=None, max_header_tokens=100,
        batch_size=2, limit=None, dry_run=False,
    )


@pytest.mark.asyncio
async def test_run_updates_rows_with_meta(args):
    from parrot.stores.utils.contextual import DEFAULT_TEMPLATE  # noqa: F401
    import importlib
    mod = importlib.import_module("scripts.recompute_contextual_embeddings")

    rows = [
        SimpleNamespace(
            id="1", document="Body 1",
            cmetadata={"document_meta": {"title": "T1"}},
            embedding=[0.0] * 4,
        ),
        SimpleNamespace(
            id="2", document="Body 2", cmetadata={}, embedding=[0.0] * 4,
        ),
    ]
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    exec_mock = AsyncMock(side_effect=[
        MagicMock(scalars=lambda: MagicMock(all=lambda: rows)),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [])),
        # subsequent UPDATEs return None
        MagicMock(), MagicMock(),
    ])
    fake_session.execute = exec_mock

    fake_store = MagicMock()
    fake_store.connection = AsyncMock()
    fake_store.session = MagicMock(return_value=fake_session)
    fake_store._embed_ = MagicMock()
    fake_store._embed_.embed_documents = AsyncMock(return_value=[np.zeros(4)])
    fake_store.embedding_store = MagicMock()

    with patch.object(mod, "PgVectorStore", return_value=fake_store):
        await mod.run(args)

    # Row 1 (has document_meta) → embed_documents called once.
    # Row 2 (empty meta) → skipped.
    assert fake_store._embed_.embed_documents.await_count == 1
```

---

## Agent Instructions

1. Read the spec §8 Q5 (the "create the migration tooling" answer is the trigger).
2. Verify TASK-857 is completed (so the framework path is consistent
   with what the script writes).
3. Update status to in-progress.
4. Implement the script + its unit test.
5. Verify `python scripts/recompute_contextual_embeddings.py --help` prints help.
6. Move to completed; update index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
