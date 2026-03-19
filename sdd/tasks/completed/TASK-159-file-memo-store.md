# TASK-159: FileMemoStore Implementation

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (3h)
**Depends-on**: TASK-158
**Assigned-to**: claude-session

---

## Context

> Filesystem-based implementation of AbstractMemoStore.
> Stores memos as JSON files organized by date (YYYY/MM/DD/{id}.json).
> Follows the FileResearchMemory pattern from FEAT-010.

---

## Scope

- Create `parrot/finance/memo_store/file_store.py`
- Implement `FileMemoStore` class with all interface methods
- Implement `_memo_path()` for date-based path generation
- Implement `_serialize_memo()` and `_deserialize_memo()`
- Use `aiofiles` for async file I/O
- Create directories automatically on store

**NOT in scope**: LRU cache (TASK-160), event logging (TASK-161).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/memo_store/file_store.py` | CREATE | FileMemoStore implementation |
| `parrot/finance/memo_store/__init__.py` | MODIFY | Export FileMemoStore |

---

## Acceptance Criteria

- [x] `FileMemoStore` stores memos at `{base_path}/YYYY/MM/DD/{id}.json`
- [x] Directories created automatically if missing
- [x] `store()` returns memo ID
- [x] `get()` returns None if memo not found
- [x] `get_by_date()` returns memos in chronological order
- [x] `query()` filters by ticker and consensus_level
- [x] InvestmentMemo serializes/deserializes correctly (all fields preserved)
- [x] Uses `aiofiles` for async I/O
- [x] Lock protects shared state (cache, index)

---

## Completion Note

**Completed**: 2026-03-04

### Implementation Summary

Created `parrot/finance/memo_store/file_store.py` (~620 lines):

1. **`FileMemoStore(AbstractMemoStore)`**:
   - `__init__(base_path, cache_size=100)` - configures storage path and cache limit
   - `_cache: dict[str, InvestmentMemo]` - in-memory memo cache (LRU-evict when full)
   - `_index: dict[str, MemoMetadata]` - lightweight index for fast queries
   - `_events: list[MemoEvent]` - in-memory event list
   - `_lock: asyncio.Lock` - protects shared state

2. **Core methods**:
   - `store()` - updates cache+index immediately, fire-and-forget disk write
   - `get()` - cache → index → disk scan fallback
   - `get_by_date()` - scans date directories, returns chronological order
   - `query()` - filters index by ticker/consensus_level, newest first
   - `log_event()` - in-memory + fire-and-forget JSONL append
   - `get_events()` - filters from memory + disk JSONL

3. **Helpers**:
   - `_memo_path()` - generates `{base}/{Y}/{M}/{D}/{id}.json`
   - `_serialize_memo()` - `dataclasses.asdict()` + custom datetime encoder
   - `_deserialize_memo()` - reconstructs full InvestmentMemo + nested dataclasses
   - `_write_to_disk()` / `_load_from_disk()` / `_find_on_disk()` - async I/O
   - `_append_event()` - appends to `{base}/events/memo_events.jsonl`

4. **Disk structure created**:
   ```
   {base_path}/
     2026/03/04/{memo_id}.json
     events/memo_events.jsonl
   ```

### Test Results
All functional tests pass:
- store/get roundtrip from cache ✓
- disk persistence + deserialization (cache cleared) ✓
- get_by_date() ✓
- query(ticker) + query(consensus_level) ✓
- log_event() + get_events() ✓
- get() returns None for missing memo ✓
- All linting checks pass ✓
