# TASK-045: CrawlStrategy Protocol & Built-in Strategies

**Feature**: FEAT-013 — CrawlEngine
**Spec**: `sdd/specs/scrapingplan-crawlengine.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-044
**Assigned-to**: claude-session

---

## Context

The `CrawlStrategy` protocol decouples traversal order from the crawl engine,
enabling BFS, DFS, and future strategies (priority-based, LLM-guided) without
modifying the engine. BFS is the default strategy.

Implements spec Module 3 and proposal Section 4.

---

## Scope

- Define `CrawlStrategy` protocol with `next(graph)` and `enqueue(graph, nodes)` methods
- Implement `BFSStrategy` — visits all nodes at depth N before depth N+1 (uses `deque.popleft()`)
- Implement `DFSStrategy` — follows links deep before backtracking (uses `deque.pop()`)
- Write unit tests verifying traversal order

**NOT in scope**: Priority-based or LLM-guided strategies (future work).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/crawl_strategy.py` | CREATE | Protocol + BFS/DFS implementations |
| `tests/tools/scraping/test_crawl_strategy.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
from typing import Protocol, List, Optional

class CrawlStrategy(Protocol):
    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]: ...
    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None: ...

class BFSStrategy:
    def next(self, graph: CrawlGraph) -> Optional[CrawlNode]:
        return graph._frontier.popleft() if graph._frontier else None

    def enqueue(self, graph: CrawlGraph, nodes: List[CrawlNode]) -> None:
        graph._frontier.extend(nodes)
```

### Key Constraints
- Use `Protocol` (structural subtyping) — no inheritance required for custom strategies
- Strategies operate on `CrawlGraph._frontier` directly
- BFS uses `popleft()`, DFS uses `pop()` — both use `extend()` for enqueue

### References in Codebase
- `parrot/tools/scraping/crawl_graph.py` (TASK-044) — `CrawlGraph` and `CrawlNode`

---

## Acceptance Criteria

- [ ] `CrawlStrategy` protocol defined with `next()` and `enqueue()` methods
- [ ] `BFSStrategy` visits breadth-first (all depth-N before depth-N+1)
- [ ] `DFSStrategy` visits depth-first (deepest branch before siblings)
- [ ] Both strategies handle empty frontier gracefully (return None)
- [ ] All tests pass: `pytest tests/tools/scraping/test_crawl_strategy.py -v`
- [ ] Import works: `from parrot.tools.scraping.crawl_strategy import CrawlStrategy, BFSStrategy, DFSStrategy`

---

## Test Specification

```python
# tests/tools/scraping/test_crawl_strategy.py
import pytest
from parrot.tools.scraping.crawl_graph import CrawlNode, CrawlGraph
from parrot.tools.scraping.crawl_strategy import BFSStrategy, DFSStrategy


def _make_nodes(urls, depth=1):
    return [CrawlNode(url=u, normalized_url=u, depth=depth) for u in urls]


class TestBFSStrategy:
    def test_breadth_first_order(self):
        graph = CrawlGraph()
        strategy = BFSStrategy()
        root = graph.add_root("https://example.com")
        # Simulate depth-1 children
        children = _make_nodes(["https://example.com/a", "https://example.com/b"], depth=1)
        strategy.enqueue(graph, children)
        # Simulate depth-2 grandchild added after first child
        grandchild = _make_nodes(["https://example.com/a/1"], depth=2)
        strategy.enqueue(graph, grandchild)
        # BFS: should get /a, /b before /a/1
        assert strategy.next(graph).url == "https://example.com/a"
        assert strategy.next(graph).url == "https://example.com/b"
        assert strategy.next(graph).url == "https://example.com/a/1"

    def test_empty_frontier(self):
        graph = CrawlGraph()
        strategy = BFSStrategy()
        assert strategy.next(graph) is None


class TestDFSStrategy:
    def test_depth_first_order(self):
        graph = CrawlGraph()
        strategy = DFSStrategy()
        children = _make_nodes(["https://example.com/a", "https://example.com/b"], depth=1)
        strategy.enqueue(graph, children)
        # DFS: pop from end, so /b first
        assert strategy.next(graph).url == "https://example.com/b"
        assert strategy.next(graph).url == "https://example.com/a"

    def test_empty_frontier(self):
        graph = CrawlGraph()
        strategy = DFSStrategy()
        assert strategy.next(graph) is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scrapingplan-crawlengine.spec.md` for full context
2. **Check dependencies** — verify TASK-044 is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-045-crawl-strategies.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Implemented `CrawlStrategy` runtime-checkable Protocol, `BFSStrategy` (popleft/FIFO), and `DFSStrategy` (pop/LIFO). 10 unit tests passing covering protocol conformance, traversal order, deep-dive behavior, empty frontier, and empty enqueue batches.

**Deviations from spec**: none
