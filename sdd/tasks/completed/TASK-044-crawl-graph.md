# TASK-044: CrawlGraph & CrawlNode

**Feature**: FEAT-013 — CrawlEngine
**Spec**: `sdd/specs/scrapingplan-crawlengine.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-043
**Assigned-to**: claude-session

---

## Context

`CrawlGraph` is the state container for the entire crawl session. It tracks which
URLs have been visited, maintains the frontier queue, and collects results. It is
the data structure that `CrawlEngine` and `CrawlStrategy` operate on.

Implements spec Module 2 and proposal Section 3.2.

---

## Scope

- Implement `CrawlNode` dataclass with fields: `url`, `normalized_url`, `depth`,
  `parent_url`, `status`, `result`, `discovered_links`, `started_at`, `finished_at`, `error`
- Implement `CrawlGraph` class with:
  - `add_root(url)` — create and track root node
  - `enqueue(node)` — add node to frontier and visited set
  - `next()` — pop from frontier (default FIFO for BFS compatibility)
  - `mark_done(node, result)` — transition node to done state
  - `mark_failed(node, error)` — transition node to failed state
  - `is_visited(normalized_url)` — check visited set
  - Properties: `visited_count`, `done_nodes`, `failed_nodes`
- Implement `CrawlResult` dataclass for aggregated crawl output
- Write unit tests

**NOT in scope**: Strategy implementations (TASK-043), link discovery (TASK-044), engine orchestration (TASK-045).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/crawl_graph.py` | CREATE | `CrawlNode`, `CrawlGraph`, `CrawlResult` |
| `tests/tools/scraping/test_crawl_graph.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
from dataclasses import dataclass, field
from collections import deque
from typing import Dict, List, Optional, Set
from datetime import datetime

@dataclass
class CrawlNode:
    url: str
    normalized_url: str
    depth: int
    parent_url: Optional[str] = None
    status: str = "pending"
    ...

class CrawlGraph:
    def __init__(self):
        self.nodes: Dict[str, CrawlNode] = {}
        self._frontier: deque[CrawlNode] = deque()
        self._visited: Set[str] = set()
    ...
```

### Key Constraints
- Use `dataclass` (not Pydantic) — these are lightweight internal structures
- Use `normalize_url` from TASK-043 in `add_root()` for consistency
- `_frontier` is a `deque` to support both BFS (popleft) and DFS (pop) via strategies
- `enqueue` must check `_visited` to prevent duplicates

### References in Codebase
- `parrot/tools/scraping/models.py` — `ScrapingResult` dataclass for the `result` field type

---

## Acceptance Criteria

- [ ] `CrawlNode` dataclass with all required fields
- [ ] `CrawlGraph.add_root()` creates and tracks root node
- [ ] `CrawlGraph.enqueue()` prevents duplicate normalized URLs
- [ ] `CrawlGraph.mark_done()` / `mark_failed()` update node status correctly
- [ ] `done_nodes` and `failed_nodes` properties return correct subsets
- [ ] `CrawlResult` dataclass captures aggregated crawl output
- [ ] All tests pass: `pytest tests/tools/scraping/test_crawl_graph.py -v`
- [ ] Import works: `from parrot.tools.scraping.crawl_graph import CrawlNode, CrawlGraph, CrawlResult`

---

## Test Specification

```python
# tests/tools/scraping/test_crawl_graph.py
import pytest
from parrot.tools.scraping.crawl_graph import CrawlNode, CrawlGraph, CrawlResult


class TestCrawlGraph:
    def test_add_root(self):
        graph = CrawlGraph()
        root = graph.add_root("https://example.com")
        assert root.depth == 0
        assert root.url == "https://example.com"
        assert graph.visited_count == 1

    def test_enqueue_dedup(self):
        graph = CrawlGraph()
        graph.add_root("https://example.com")
        node = CrawlNode(url="https://example.com", normalized_url="https://example.com", depth=1)
        graph.enqueue(node)
        # Should not add duplicate
        assert graph.visited_count == 1

    def test_enqueue_new_url(self):
        graph = CrawlGraph()
        graph.add_root("https://example.com")
        node = CrawlNode(url="https://example.com/page", normalized_url="https://example.com/page", depth=1)
        graph.enqueue(node)
        assert graph.visited_count == 2

    def test_mark_done(self):
        graph = CrawlGraph()
        root = graph.add_root("https://example.com")
        graph.mark_done(root, result=None)
        assert root.status == "done"
        assert len(graph.done_nodes) == 1

    def test_mark_failed(self):
        graph = CrawlGraph()
        root = graph.add_root("https://example.com")
        graph.mark_failed(root, error="Timeout")
        assert root.status == "failed"
        assert root.error == "Timeout"
        assert len(graph.failed_nodes) == 1

    def test_is_visited(self):
        graph = CrawlGraph()
        graph.add_root("https://example.com")
        assert graph.is_visited("https://example.com") is True
        assert graph.is_visited("https://other.com") is False
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-crawlengine.spec.md` for full context
2. **Check dependencies** — verify TASK-043 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-044-crawl-graph.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `CrawlNode` dataclass, `CrawlGraph` class with add_root/enqueue/next/mark_done/mark_failed/is_visited and properties, and `CrawlResult` dataclass. 18 unit tests passing covering all acceptance criteria.

**Deviations from spec**: none
