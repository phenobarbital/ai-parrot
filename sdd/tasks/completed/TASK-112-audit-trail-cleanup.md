# TASK-112: Audit Trail & Cleanup Implementation

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-111
**Assigned-to**: claude-session

---

## Context

This task adds audit trail logging and cleanup/archival functionality to `FileResearchMemory`. The audit trail logs all store/access events to an append-only JSONL file, and cleanup archives old documents to `_historical/` folder.

Reference: Spec Section 2 "Directory Structure" and "Lifecycle Management"

---

## Scope

- Implement audit trail logging to `_audit_log/research_events.jsonl`
- Log events: `stored`, `accessed`, `expired`, `cleaned`
- Implement `cleanup()` method to archive documents older than retention_days
- Implement `get_audit_events()` method to query audit trail
- Rotate audit log by size (10MB)
- Run cleanup at startup BEFORE cache warming

**NOT in scope**:
- Research tools (TASK-113)
- Service integration (TASK-114)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/research/memory/file.py` | MODIFY | Add audit trail and cleanup methods |

---

## Implementation Notes

### Audit Trail Log Structure

```
research_memory/
├── _audit_log/
│   ├── research_events.jsonl      # Current log
│   └── research_events.jsonl.1    # Rotated logs
```

### Audit Event Logging

```python
async def _log_audit_event(
    self,
    event_type: str,
    crew_id: str,
    period_key: str,
    domain: str,
    actor: str | None = None,
    details: dict | None = None,
) -> None:
    """Append an audit event to the log file (fire-and-forget)."""
    event = AuditEvent(
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        crew_id=crew_id,
        period_key=period_key,
        domain=domain,
        actor=actor,
        details=details or {},
    )

    log_path = self.base_path / "_audit_log" / "research_events.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Rotate if needed
    await self._rotate_log_if_needed(log_path)

    async with aiofiles.open(log_path, 'a', encoding='utf-8') as f:
        await f.write(event.model_dump_json() + "\n")
```

### Log Rotation by Size

```python
MAX_LOG_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

async def _rotate_log_if_needed(self, log_path: Path) -> None:
    """Rotate log file if it exceeds MAX_LOG_SIZE_BYTES."""
    if not log_path.exists():
        return

    size = log_path.stat().st_size
    if size < self.MAX_LOG_SIZE_BYTES:
        return

    # Find next rotation number
    rotated = 1
    while (log_path.parent / f"{log_path.name}.{rotated}").exists():
        rotated += 1

    # Rename current to rotated
    log_path.rename(log_path.parent / f"{log_path.name}.{rotated}")
    self.logger.info(f"Rotated audit log to {log_path.name}.{rotated}")
```

### Cleanup / Archival

```python
async def cleanup(self, retention_days: int = 7) -> int:
    """Archive documents older than retention_days.

    Moves old documents to _historical/{year-month}/ instead of deleting.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    archived_count = 0

    for domain in self.DOMAIN_CREW_MAP:
        crew_id = self.DOMAIN_CREW_MAP[domain]
        domain_path = self.base_path / domain / crew_id

        if not domain_path.exists():
            continue

        for file_path in domain_path.glob("*.json"):
            try:
                # Parse period_key from filename
                period_key = file_path.stem.replace("-", ":")
                doc_date = datetime.fromisoformat(period_key[:10])

                if doc_date.replace(tzinfo=timezone.utc) < cutoff:
                    # Move to historical
                    historical_path = (
                        self.base_path / "_historical"
                        / doc_date.strftime("%Y-%m")
                        / domain / crew_id / file_path.name
                    )
                    historical_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.rename(historical_path)

                    # Remove from cache if present
                    cache_key = (crew_id, file_path.stem)
                    self._cache.pop(cache_key, None)

                    # Log cleanup event
                    asyncio.create_task(
                        self._log_audit_event(
                            "cleaned",
                            crew_id,
                            period_key,
                            domain,
                            details={"archived_to": str(historical_path)},
                        )
                    )
                    archived_count += 1

            except Exception as e:
                self.logger.warning(f"Failed to process {file_path}: {e}")

    self.logger.info(f"Archived {archived_count} documents")
    return archived_count
```

### Query Audit Events

```python
async def get_audit_events(
    self,
    since: datetime | None = None,
    until: datetime | None = None,
    event_type: str | None = None,
) -> list[AuditEvent]:
    """Query audit trail events with filters."""
    log_path = self.base_path / "_audit_log" / "research_events.jsonl"

    if not log_path.exists():
        return []

    events = []
    async with aiofiles.open(log_path, 'r', encoding='utf-8') as f:
        async for line in f:
            try:
                event = AuditEvent.model_validate_json(line.strip())

                # Apply filters
                if since and event.timestamp < since:
                    continue
                if until and event.timestamp > until:
                    continue
                if event_type and event.event_type != event_type:
                    continue

                events.append(event)
            except Exception:
                continue  # Skip malformed lines

    return events
```

### Integration with start()

```python
async def start(self) -> None:
    """Initialize the memory store."""
    if self._started:
        return

    # Create directory structure
    self.base_path.mkdir(parents=True, exist_ok=True)
    (self.base_path / "_audit_log").mkdir(exist_ok=True)
    # ... domain dirs ...

    # Run cleanup BEFORE cache warming
    archived = await self.cleanup()
    self.logger.info(f"Startup cleanup archived {archived} documents")

    # Warm cache from remaining files
    if self.warmup_on_init:
        await self._warm_cache()

    self._started = True
```

### Integration with store()

```python
async def store(self, document: ResearchDocument) -> str:
    # ... existing cache logic ...

    # Fire-and-forget disk write
    asyncio.create_task(self._persist_to_disk(document))

    # Fire-and-forget audit log
    asyncio.create_task(
        self._log_audit_event(
            "stored",
            document.crew_id,
            document.period_key,
            document.domain,
        )
    )

    return document.id
```

---

## Acceptance Criteria

- [ ] Audit events logged to `_audit_log/research_events.jsonl`
- [ ] Events include: event_type, timestamp, crew_id, period_key, domain, actor, details
- [ ] `get_audit_events()` returns filtered events
- [ ] Log rotates when exceeding 10MB
- [ ] `cleanup()` moves documents >7 days to `_historical/{year-month}/`
- [ ] Cleanup runs at startup BEFORE cache warming
- [ ] Archived documents removed from cache
- [ ] No linting errors

---

## Test Specification

```python
# tests/test_research_memory_audit.py

class TestAuditTrail:
    @pytest.mark.asyncio
    async def test_store_logs_event(self, temp_memory, sample_document):
        await temp_memory.start()
        await temp_memory.store(sample_document)

        # Wait for fire-and-forget
        await asyncio.sleep(0.2)

        events = await temp_memory.get_audit_events(event_type="stored")
        assert len(events) == 1
        assert events[0].crew_id == sample_document.crew_id

    @pytest.mark.asyncio
    async def test_audit_filter_by_time(self, temp_memory):
        # ... test since/until filters ...

    @pytest.mark.asyncio
    async def test_log_rotation(self, temp_memory):
        # ... test rotation at 10MB ...


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_archives_old(self, temp_memory):
        """Documents older than retention_days are archived."""
        await temp_memory.start()

        # Create old document
        old_doc = create_document_with_date("2026-02-20")
        await temp_memory.store(old_doc)
        await asyncio.sleep(0.2)

        # Run cleanup
        archived = await temp_memory.cleanup(retention_days=7)
        assert archived == 1

        # Check moved to _historical
        historical = temp_memory.base_path / "_historical" / "2026-02"
        assert historical.exists()

    @pytest.mark.asyncio
    async def test_cleanup_removes_from_cache(self, temp_memory):
        # ... verify cache eviction ...
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-111 must be complete
2. **Update status** → `"in-progress"`
3. **Modify** `FileResearchMemory` to add audit trail and cleanup
4. **Run tests**: `pytest tests/test_research_memory_audit.py -v`
5. **Verify** all acceptance criteria
6. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**: Enhanced `FileResearchMemory` with: (1) Audit trail logging to `research_events.jsonl` with log rotation at 10MB, (2) Cleanup archives to `_historical/{year-month}/` directory structure, (3) Cleanup runs at startup BEFORE cache warming, (4) Fire-and-forget audit logging for cleanup events, (5) Thread-safe audit log writes via `_audit_log_lock`. All 42 tests passing (29 file memory + 13 audit/cleanup).
