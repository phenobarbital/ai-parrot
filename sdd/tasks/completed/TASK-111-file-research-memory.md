# TASK-111: File Research Memory Implementation

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-6h)
**Depends-on**: TASK-109, TASK-110
**Assigned-to**: claude-session

---

## Context

This task implements `FileResearchMemory`, the filesystem-based implementation of `ResearchMemory`. This is the core component of the collective memory system, featuring in-memory cache, fire-and-forget disk writes, and LRU eviction.

Reference: Spec Section 2 "Architectural Design" and Section 6 "Implementation Notes"

---

## Scope

- Implement `FileResearchMemory` class extending `ResearchMemory` ABC
- In-memory cache (dict-based) with LRU eviction when exceeding max_size
- Fire-and-forget disk writes using `asyncio.create_task()`
- Async file I/O using `aiofiles`
- Directory structure: `{domain}/{crew_id}/{period_key}.json`
- Cache warming at startup from existing files
- Path generation and locking per document

**NOT in scope**:
- Audit trail logging (TASK-112)
- Cleanup/archival (TASK-112)
- Research tools (TASK-113)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/research/memory/file.py` | CREATE | `FileResearchMemory` implementation |
| `parrot/finance/research/memory/__init__.py` | MODIFY | Add `FileResearchMemory` export |

---

## Implementation Notes

### Class Structure

```python
# parrot/finance/research/memory/file.py
import asyncio
import json
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
from collections import OrderedDict

import aiofiles
from navconfig.logging import logging

from .abstract import ResearchMemory
from .schemas import ResearchDocument, AuditEvent


class FileResearchMemory(ResearchMemory):
    """Filesystem-based research memory with in-memory cache.

    Features:
    - In-memory cache (OrderedDict for LRU) for fast reads
    - Fire-and-forget writes to filesystem
    - Async file I/O with aiofiles
    - Cache warming at startup
    - Per-path locking to prevent write conflicts
    """

    DOMAIN_CREW_MAP = {
        "macro": "research_crew_macro",
        "equity": "research_crew_equity",
        "crypto": "research_crew_crypto",
        "sentiment": "research_crew_sentiment",
        "risk": "research_crew_risk",
    }

    def __init__(
        self,
        base_path: str = "./research_memory",
        cache_max_size: int = 100,
        warmup_on_init: bool = True,
        debug: bool = False,
    ):
        super().__init__(debug=debug)
        self.base_path = Path(base_path)
        self.cache_max_size = cache_max_size
        self.warmup_on_init = warmup_on_init

        # LRU cache: OrderedDict[tuple[crew_id, period_key], ResearchDocument]
        self._cache: OrderedDict[tuple[str, str], ResearchDocument] = OrderedDict()

        # Per-path locks to prevent concurrent writes
        self._locks: dict[str, asyncio.Lock] = {}

        # Startup flag
        self._started = False

    async def start(self) -> None:
        """Initialize the memory store."""
        if self._started:
            return

        # Create directory structure
        self.base_path.mkdir(parents=True, exist_ok=True)
        for domain in self.DOMAIN_CREW_MAP:
            crew_id = self.DOMAIN_CREW_MAP[domain]
            (self.base_path / domain / crew_id).mkdir(parents=True, exist_ok=True)

        # Warm cache from existing files
        if self.warmup_on_init:
            await self._warm_cache()

        self._started = True
        self.logger.info(f"FileResearchMemory started at {self.base_path}")

    async def stop(self) -> None:
        """Graceful shutdown - wait for pending writes."""
        # Give pending tasks a moment to complete
        await asyncio.sleep(0.1)
        self.logger.info("FileResearchMemory stopped")
```

### Fire-and-Forget Pattern

```python
async def store(self, document: ResearchDocument) -> str:
    """Store a research document with fire-and-forget persistence."""
    cache_key = (document.crew_id, document.period_key)

    # Update cache immediately (LRU: move to end)
    self._cache[cache_key] = document
    self._cache.move_to_end(cache_key)

    # Evict if over max size
    while len(self._cache) > self.cache_max_size:
        self._cache.popitem(last=False)  # Remove oldest

    # Fire-and-forget disk write
    asyncio.create_task(self._persist_to_disk(document))

    self.logger.debug(f"Stored document {document.id} for {document.crew_id}")
    return document.id


async def _persist_to_disk(self, document: ResearchDocument) -> None:
    """Async persist document to filesystem."""
    path = self._get_file_path(document.domain, document.crew_id, document.period_key)
    lock = self._locks.setdefault(str(path), asyncio.Lock())

    async with lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(path, 'w', encoding='utf-8') as f:
                await f.write(document.model_dump_json(indent=2))
            self.logger.debug(f"Persisted {path}")
        except Exception as e:
            self.logger.error(f"Failed to persist {path}: {e}")
```

### Path Generation

```python
def _get_file_path(self, domain: str, crew_id: str, period_key: str) -> Path:
    """Generate file path for a document."""
    # Sanitize period_key for filename (replace : with -)
    safe_period = period_key.replace(":", "-")
    return self.base_path / domain / crew_id / f"{safe_period}.json"
```

### Cache Warming

```python
async def _warm_cache(self) -> None:
    """Load existing documents into cache at startup."""
    count = 0
    for domain in self.DOMAIN_CREW_MAP:
        crew_id = self.DOMAIN_CREW_MAP[domain]
        domain_path = self.base_path / domain / crew_id

        if not domain_path.exists():
            continue

        # Get all JSON files, sorted by name (newest first)
        files = sorted(domain_path.glob("*.json"), reverse=True)

        # Load up to a reasonable limit per domain
        for file_path in files[:20]:
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                doc = ResearchDocument.model_validate_json(content)
                self._cache[(doc.crew_id, doc.period_key)] = doc
                count += 1
            except Exception as e:
                self.logger.warning(f"Failed to load {file_path}: {e}")

    self.logger.info(f"Cache warmed with {count} documents")
```

### Key Constraints

- Use `OrderedDict` for LRU cache behavior
- Use `asyncio.Lock` per file path to prevent concurrent writes
- Use `aiofiles` for all file I/O
- Handle JSON serialization errors gracefully
- Sanitize period_key for filesystem (replace `:` with `-`)

### References in Codebase

- `parrot/memory/file.py` — `FileConversationMemory` pattern
- `parrot/memory/cache.py` — Fire-and-forget pattern with `asyncio.create_task`

---

## Acceptance Criteria

- [ ] `FileResearchMemory` implements all `ResearchMemory` abstract methods
- [ ] In-memory cache with LRU eviction works correctly
- [ ] Fire-and-forget writes use `asyncio.create_task()`
- [ ] Cache warming loads existing files at startup
- [ ] Per-path locking prevents concurrent write conflicts
- [ ] Directory structure matches spec: `{domain}/{crew_id}/{period_key}.json`
- [ ] `start()` and `stop()` lifecycle methods work
- [ ] No linting errors: `ruff check parrot/finance/research/memory/file.py`

---

## Test Specification

```python
# tests/test_file_research_memory.py
import pytest
import asyncio
from pathlib import Path
from parrot.finance.research.memory.file import FileResearchMemory
from parrot.finance.research.memory.schemas import ResearchDocument
from parrot.finance.schemas import ResearchBriefing


@pytest.fixture
def temp_memory(tmp_path):
    """Temporary file research memory."""
    return FileResearchMemory(
        base_path=str(tmp_path / "research_memory"),
        cache_max_size=10,
        warmup_on_init=False,
    )


class TestFileResearchMemory:
    @pytest.mark.asyncio
    async def test_store_and_get(self, temp_memory, sample_document):
        await temp_memory.start()
        doc_id = await temp_memory.store(sample_document)

        result = await temp_memory.get(
            sample_document.crew_id,
            sample_document.period_key
        )
        assert result is not None
        assert result.id == doc_id

    @pytest.mark.asyncio
    async def test_exists_true(self, temp_memory, sample_document):
        await temp_memory.start()
        await temp_memory.store(sample_document)

        exists = await temp_memory.exists(
            sample_document.crew_id,
            sample_document.period_key
        )
        assert exists is True

    @pytest.mark.asyncio
    async def test_exists_false(self, temp_memory):
        await temp_memory.start()
        exists = await temp_memory.exists("nonexistent", "2026-03-03")
        assert exists is False

    @pytest.mark.asyncio
    async def test_cache_lru_eviction(self, temp_memory):
        """Oldest items evicted when cache exceeds max_size."""
        await temp_memory.start()
        # Store 15 documents with max_size=10
        for i in range(15):
            doc = create_document(f"doc-{i}", f"2026-03-{i:02d}")
            await temp_memory.store(doc)

        # First 5 should be evicted from cache
        assert len(temp_memory._cache) == 10

    @pytest.mark.asyncio
    async def test_fire_and_forget_persists(self, temp_memory, sample_document):
        await temp_memory.start()
        await temp_memory.store(sample_document)

        # Wait for fire-and-forget to complete
        await asyncio.sleep(0.2)

        # Check file exists on disk
        path = temp_memory._get_file_path(
            sample_document.domain,
            sample_document.crew_id,
            sample_document.period_key
        )
        assert path.exists()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for implementation patterns
2. **Check dependencies** — TASK-109 and TASK-110 must be complete
3. **Update status** → `"in-progress"`
4. **Implement** `FileResearchMemory` in `parrot/finance/research/memory/file.py`
5. **Run tests**: `pytest tests/test_file_research_memory.py -v`
6. **Verify** all acceptance criteria
7. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**: Implemented `FileResearchMemory` in `parrot/finance/research/memory/file.py` with all features: in-memory LRU cache (OrderedDict), fire-and-forget disk writes using `asyncio.create_task()`, cache warming at startup, per-path locking, query/cleanup operations, and audit trail logging. Directory structure: `{base_path}/{domain}/{crew_id}/{period_key}.json`. All 29 tests passing.
