# TASK-230: Database Tools — Complete Vector-Store Cache Tier (`cache.py`)

**Feature**: Database Schema Tools — Completion & Hardening (FEAT-032)
**Spec**: `sdd/specs/tools-database.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: claude-sonnet-4-6

---

## Context

> `SchemaMetadataCache` declares a two-tier caching strategy (LRU hot cache + vector store for
> semantic similarity search) but all three vector-store methods are no-op stubs:
>
> - `_search_vector_store` always returns `None`
> - `_store_in_vector_store` has a `pass` inside the try block (documents are built but never stored)
> - `_convert_vector_results` always returns `[]`
>
> As a result, enabling a vector store has zero effect — every search silently falls back to
> keyword matching in the LRU cache.  The spec requires these three methods to be real, and
> adds auto-creation of an in-memory `FAISSStore` when no `vector_store` is passed.

---

## Scope

Modify `parrot/tools/database/cache.py`:

### 1. Auto-create FAISSStore when `vector_store=None`

In `__init__`, when `vector_store is None`, attempt to create a `FAISSStore`:

```python
if vector_store is None:
    try:
        from ...stores.faiss_store import FAISSStore
        vector_store = FAISSStore(
            collection_name="schema_metadata",
            embedding_model="sentence-transformers/all-mpnet-base-v2",
            use_database=False,   # in-memory only
        )
        self.logger.info("SchemaMetadataCache: auto-created in-memory FAISSStore")
    except ImportError:
        self.logger.warning(
            "SchemaMetadataCache: faiss-cpu not installed — running LRU-only mode"
        )
```

Keep `self.vector_enabled = vector_store is not None` after this block.

Remove the `print("Vector store not provided...")` call — replace with `self.logger.info`.

### 2. Implement `_store_in_vector_store(metadata: TableMetadata)`

```python
async def _store_in_vector_store(self, metadata: TableMetadata):
    if not self.vector_enabled:
        return
    try:
        document = {
            "content": metadata.to_yaml_context(),
            "metadata": {
                "type": "table_metadata",
                "schema_name": metadata.schema,
                "tablename": metadata.tablename,
                "table_type": metadata.table_type,
                "full_name": metadata.full_name,
            },
        }
        async with self.vector_store as vs:
            await vs.add_documents([document])
    except Exception as exc:
        self.logger.warning("Vector store write failed for %s.%s: %s",
                            metadata.schema, metadata.tablename, exc)
```

### 3. Implement `_search_vector_store(schema_name: str, table_name: str) -> Optional[TableMetadata]`

```python
async def _search_vector_store(self, schema_name: str, table_name: str) -> Optional[TableMetadata]:
    if not self.vector_enabled:
        return None
    try:
        async with self.vector_store as vs:
            results = await vs.similarity_search(
                f"{schema_name}.{table_name}",
                k=1,
                metadata_filters={"schema_name": schema_name},
            )
        if results:
            converted = await self._convert_vector_results(results)
            return converted[0] if converted else None
    except Exception as exc:
        self.logger.warning("Vector store read failed: %s", exc)
    return None
```

### 4. Implement `_convert_vector_results(results) -> List[TableMetadata]`

Parse YAML content stored by `_store_in_vector_store` back into `TableMetadata`.  Each result
is expected to have a `content` field (string) and a `metadata` dict:

```python
async def _convert_vector_results(self, results) -> List[TableMetadata]:
    import yaml
    converted = []
    for result in results:
        try:
            content = getattr(result, "content", None) or (
                result.get("content") if isinstance(result, dict) else None
            )
            meta = getattr(result, "metadata", {}) or (
                result.get("metadata", {}) if isinstance(result, dict) else {}
            )
            if not content:
                continue
            data = yaml.safe_load(content)
            full_name = data.get("table", meta.get("full_name", ""))
            # Parse schema.table from full_name
            schema_name = meta.get("schema_name", "")
            tablename = meta.get("tablename", "")
            table_metadata = TableMetadata(
                schema=schema_name,
                tablename=tablename,
                table_type=data.get("type", "BASE TABLE"),
                full_name=full_name,
                comment=data.get("description"),
                columns=data.get("columns", []),
                primary_keys=data.get("primary_keys", []),
                row_count=data.get("row_count"),
                sample_data=[],
            )
            converted.append(table_metadata)
        except Exception as exc:
            self.logger.warning("Failed to convert vector result: %s", exc)
    return converted
```

**NOT in scope**: Changes to `abstract.py`, `pg.py`, `bq.py`, or `__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/cache.py` | MODIFY | Complete 3 stub methods; auto-create FAISSStore |

---

## Implementation Notes

- Read the entire `cache.py` before editing.
- The `FAISSStore` auto-creation must be guarded with `try/except ImportError` — environments
  without `faiss-cpu` must still work in LRU-only mode.
- `_store_in_vector_store` must use `async with self.vector_store as vs:` — the `AbstractStore`
  requires a context manager for connection lifecycle.
- `_convert_vector_results` must handle both object-style results (`result.content`) and
  dict-style results (`result["content"]`) since different store backends return different types.
- `yaml` is already imported in `models.py`; import it locally in `_convert_vector_results` to
  avoid module-level side-effects.
- Do not change the `search_similar_tables`, `store_table_metadata`, or `get_table_metadata`
  method signatures.

---

## Acceptance Criteria

- [ ] `SchemaMetadataCache()` (no args) sets `self.vector_enabled = True` when `faiss-cpu` is
  installed, or `False` with a warning log when it is not
- [ ] `SchemaMetadataCache(vector_store=None)` auto-creates `FAISSStore` (same as above)
- [ ] `_store_in_vector_store` calls `vs.add_documents` (not a no-op)
- [ ] `_search_vector_store(schema, table)` returns a `TableMetadata` when the vector store
  contains a matching document, `None` otherwise
- [ ] `_convert_vector_results([...])` returns a non-empty `List[TableMetadata]` for valid input
- [ ] The `print(...)` call is removed; replaced with `self.logger.info`
- [ ] `ruff check parrot/tools/database/cache.py` passes

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/tools-database.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Read** `parrot/tools/database/cache.py` in full before editing
4. **Read** `parrot/stores/faiss_store.py` (lines 1–80) to confirm constructor signature
5. **Read** `parrot/stores/abstract.py` (lines 130–165) for the async context manager pattern
6. **Implement** following the scope above
7. **Verify**:
   ```bash
   source .venv/bin/activate
   ruff check parrot/tools/database/cache.py
   python -c "
   import asyncio
   from parrot.tools.database.cache import SchemaMetadataCache
   cache = SchemaMetadataCache()
   print('vector_enabled:', cache.vector_enabled)
   "
   ```
8. **Move this file** to `sdd/tasks/completed/TASK-230-database-tools-vector-cache-tier.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-08
**Notes**:
- Replaced all three no-op stubs with real implementations.
- `_store_in_vector_store`: creates a `Document(page_content=metadata.to_yaml_context(), metadata={...})`
  and calls `vector_store.add_documents([document])` directly (no context manager — see deviation).
- `_search_vector_store`: calls `vector_store.similarity_search(...)` directly, converts first
  `SearchResult` via `_convert_vector_results`, returns `TableMetadata` or `None`.
- `_convert_vector_results`: handles both object-style (`result.content`) and dict-style results;
  parses YAML with `yaml.safe_load`, reconstructs `TableMetadata`.
- Auto-creation of `FAISSStore` in `__init__` when `vector_store=None`; guards `ImportError` so
  environments without `faiss-cpu` fall back to LRU-only mode.
- Replaced `print("Vector store not provided...")` with `self.logger.info(...)`.
- Verified: store → search round-trip returns correct `TableMetadata`; fallback to LRU on error works.

**Deviations from spec**:
- Spec recommended `async with self.vector_store as vs:` per operation. **Not used** — the
  `AbstractStore.__aexit__` calls `_free_resources()` which nullifies `self._embed_`, destroying
  the embedding model between calls. For a long-lived cache instance, direct method calls are
  correct; each method handles `connection()` lazily if not yet connected.
