# TASK-161: MemoEventLog Implementation

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (2h)
**Depends-on**: TASK-158
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Append-only JSONL file for tracking memo lifecycle events.
> Provides audit trail for compliance and debugging.

---

## Scope

- Implement `log_event()` method in `FileMemoStore`
- Implement `get_events()` method for querying events
- Write events to `{base_path}/events/memo_events.jsonl`
- Each line is a JSON object (JSONL format)
- Events are append-only (never modify existing lines)

**NOT in scope**: Event rotation, compression.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/memo_store/file_store.py` | MODIFY | Add event logging methods |

---

## Implementation Notes

### JSONL Format

Each line in `memo_events.jsonl`:
```json
{"event_id": "uuid", "memo_id": "uuid", "event_type": "created", "timestamp": "2026-03-04T10:30:00Z", "details": {}}
```

### Implementation

```python
async def log_event(
    self,
    memo_id: str,
    event_type: MemoEventType,
    details: Optional[dict] = None,
) -> None:
    """Append event to JSONL file."""
    event = MemoEvent(
        memo_id=memo_id,
        event_type=event_type,
        details=details or {},
    )
    event_path = self.base_path / "events" / "memo_events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(event_path, "a") as f:
        await f.write(json.dumps(asdict(event), default=str) + "\n")

async def get_events(
    self,
    memo_id: Optional[str] = None,
    event_type: Optional[MemoEventType] = None,
    limit: int = 100,
) -> list[MemoEvent]:
    """Query events, newest first."""
    event_path = self.base_path / "events" / "memo_events.jsonl"
    if not event_path.exists():
        return []

    events = []
    async with aiofiles.open(event_path, "r") as f:
        async for line in f:
            event = MemoEvent(**json.loads(line))
            if memo_id and event.memo_id != memo_id:
                continue
            if event_type and event.event_type != event_type:
                continue
            events.append(event)

    return sorted(events, key=lambda e: e.timestamp, reverse=True)[:limit]
```

---

## Acceptance Criteria

- [x] Events written to `{base_path}/events/memo_events.jsonl`
- [x] JSONL format (one JSON object per line)
- [x] `log_event()` appends to file (never modifies)
- [x] `get_events()` returns events newest first
- [x] `get_events()` filters by memo_id and event_type
- [x] `get_events()` respects limit parameter
- [x] Events directory created automatically
- [x] All MemoEventType values supported

---

## Completion Note

**Completed**: 2026-03-04
**Implemented by**: claude-session

### Summary

Updated `FileMemoStore` in `parrot/finance/memo_store/file_store.py` to implement the event logging spec:

1. **`log_event()`** (lines 259-285):
   - Creates `MemoEvent` with UUID, timestamp, and details
   - Appends to in-memory `_events` list
   - Fire-and-forget writes to JSONL via `asyncio.create_task()`

2. **`get_events()`** (lines 287-352):
   - Reads from both in-memory cache AND JSONL file on disk
   - Supports filtering by `memo_id` and `event_type`
   - Returns events newest first (sorted by timestamp descending)
   - Respects `limit` parameter
   - Deduplicates by `event_id` to avoid duplicates between cache and disk

3. **`_append_event()`** (lines 625-656):
   - Writes to `{base_path}/events/memo_events.jsonl`
   - Creates directory automatically
   - JSONL format: one JSON object per line
   - Append-only (never modifies existing lines)

### Changes Made

- Fixed event directory path from `_events/` to `events/` (per spec)
- Updated `get_events()` to read from JSONL file (not just in-memory)
- Added `_parse_dt()` usage for timestamp parsing from JSONL

### Verification

Tested with:
- 3 events logged across 2 memos
- Filter by memo_id: 2 events for memo-001
- Filter by event_type: 2 CREATED events
- Limit: correctly returns 1 event
- Newest first: timestamps in descending order
- Event file created at correct path
