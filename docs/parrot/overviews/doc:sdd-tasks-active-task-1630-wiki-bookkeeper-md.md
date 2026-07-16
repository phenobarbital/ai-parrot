---
type: Wiki Overview
title: 'TASK-1630: Wiki Bookkeeper'
id: doc:sdd-tasks-active-task-1630-wiki-bookkeeper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements index.md and log.md bookkeeping for the wiki. Extends OKF's
relates_to:
- concept: mod:parrot.knowledge.pageindex.okf.projection
  rel: mentions
- concept: mod:parrot.knowledge.wiki.bookkeeper
  rel: mentions
---

# TASK-1630: Wiki Bookkeeper

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1627
**Assigned-to**: unassigned

---

## Context

Implements index.md and log.md bookkeeping for the wiki. Extends OKF's
`generate_index_md()` with wiki-specific metadata (source counts, category
breakdown). Manages the append-only operation log. Implements Spec §3 Module 4.

---

## Scope

- Implement `WikiBookkeeper` class with:
  - `generate_index(tree, tree_name, sources, categories) -> str` — extends
    OKF's `generate_index_md()` with source count, category breakdown,
    last-updated timestamp
  - `write_index(wiki_dir)` — write index.md to wiki directory
  - `log_operation(wiki_dir, operation, details)` — append to log.md with
    ISO timestamp and parseable prefix
  - `read_log(wiki_dir, last_n) -> str` — read last N log entries
  - `rebuild_index(wiki_dir, tree, tree_name, sources) -> str` — full
    regeneration of index.md from current state
- Log format: `[YYYY-MM-DDTHH:MM:SSZ] [OPERATION] details`
- Write unit tests

**NOT in scope**: Lint operations (via OKFToolkit), toolkit integration (TASK-1633)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py` | CREATE | WikiBookkeeper |
| `tests/knowledge/wiki/test_bookkeeper.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.okf.projection import generate_index_md  # line 158
# Signature: def generate_index_md(tree: dict, tree_name: str) -> str
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py
def generate_index_md(tree: dict, tree_name: str) -> str:  # line 158
```

### Does NOT Exist

- ~~`parrot.knowledge.wiki.bookkeeper`~~ — does not exist yet; this task creates it
- ~~`WikiBookkeeper`~~ — does not exist yet
- ~~`generate_wiki_index_md`~~ — no such function; extend `generate_index_md` output

---

## Implementation Notes

### Key Constraints

- Log must be append-only (never truncate or overwrite)
- Log entries must have parseable ISO-8601 timestamps
- Index.md should be regeneratable from current state at any time
- Use `self.logger` for internal logging

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/pageindex/okf/projection.py:158` — `generate_index_md()`

---

## Acceptance Criteria

- [ ] `generate_index` extends OKF's output with source counts and categories
- [ ] `log_operation` appends with parseable timestamp prefix
- [ ] `read_log` returns last N entries
- [ ] `rebuild_index` regenerates from current state
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_bookkeeper.py -v`

---

## Test Specification

```python
import pytest
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper

class TestWikiBookkeeper:
    def test_log_operation(self, tmp_path):
        bk = WikiBookkeeper()
        bk.log_operation(tmp_path, "INGEST", "source: article.md, pages: 3")
        log = bk.read_log(tmp_path)
        assert "[INGEST]" in log
        assert "article.md" in log

    def test_log_append_only(self, tmp_path):
        bk = WikiBookkeeper()
        bk.log_operation(tmp_path, "INGEST", "first")
        bk.log_operation(tmp_path, "QUERY", "second")
        log = bk.read_log(tmp_path)
        assert log.count("\n") >= 2

    def test_read_log_last_n(self, tmp_path):
        bk = WikiBookkeeper()
        for i in range(10):
            bk.log_operation(tmp_path, "OP", f"entry {i}")
        last3 = bk.read_log(tmp_path, last_n=3)
        assert "entry 9" in last3
        assert "entry 0" not in last3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §3 Module 4
2. **Check dependencies** — TASK-1627 must be completed
3. **Read** `okf/projection.py:158` to understand `generate_index_md()` output format
4. **Implement** WikiBookkeeper extending that output
5. **Verify** all acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
