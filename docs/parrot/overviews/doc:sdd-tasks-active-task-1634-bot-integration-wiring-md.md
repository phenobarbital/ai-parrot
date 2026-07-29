---
type: Wiki Overview
title: 'TASK-1634: Bot Integration Wiring'
id: doc:sdd-tasks-active-task-1634-bot-integration-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wires LLMWikiToolkit into the bot framework following the established
---

# TASK-1634: Bot Integration Wiring

**Feature**: FEAT-260 — LLM Wiki: Persistent Knowledge Base with PageIndex + GraphIndex
**Spec**: `sdd/specs/llmwiki-pageindex-graphindex.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1633
**Assigned-to**: unassigned

---

## Context

Wires LLMWikiToolkit into the bot framework following the established
`_capture_knowledge_toolkit()` pattern. Adds attribute initialization,
property accessor, capability flag, and toolkit detection. Implements Spec
§3 Module 8.

---

## Scope

- Add `self._llmwiki_toolkit: Optional[Any] = None` to `AbstractBot.__init__`
- Add `"LLMWikiToolkit"` case to `_capture_knowledge_toolkit()` in
  `interfaces/tools.py`
- Add `llmwiki_toolkit` property to `ToolInterface`
- Add `has_llmwiki_tools` property to `ToolInterface`
- Write tests verifying detection and property access

**NOT in scope**: Agent-specific toolkit instantiation (each agent decides
whether to include wiki tools in its `agent_tools()` override)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add `_llmwiki_toolkit` attr (line ~354) |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | Add LLMWikiToolkit case + property + flag |
| `tests/knowledge/wiki/test_bot_integration.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# No new imports needed in the modified files — they already import Optional, Any
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py:353-354
self._pageindex_toolkit: Optional[Any] = None  # line 353
self._graphindex_toolkit: Optional[Any] = None  # line 354
# ← ADD: self._llmwiki_toolkit: Optional[Any] = None  # after line 354

# packages/ai-parrot/src/parrot/interfaces/tools.py:147-163
def _capture_knowledge_toolkit(self, toolkit: Any) -> None:  # line 147
    cls_name = type(toolkit).__name__
    if cls_name == "PageIndexToolkit" and self._pageindex_toolkit is None:
        self._pageindex_toolkit = toolkit
    elif cls_name == "GraphIndexToolkit" and self._graphindex_toolkit is None:
        self._graphindex_toolkit = toolkit
    # ← ADD: elif cls_name == "LLMWikiToolkit" and self._llmwiki_toolkit is None:
    #             self._llmwiki_toolkit = toolkit

# packages/ai-parrot/src/parrot/interfaces/tools.py:98-133
@property
def pageindex_toolkit(self) -> Any:  # line 98
    return self._pageindex_toolkit

@property
def has_pageindex_tools(self) -> bool:  # line 118
    if self._pageindex_toolkit is not None:
        return True
    # ... also checks tool_manager name prefix scan

# ← ADD matching llmwiki_toolkit property and has_llmwiki_tools flag
```

### Does NOT Exist

- ~~`self._llmwiki_toolkit`~~ — does not exist in AbstractBot yet; this task adds it
- ~~`ToolInterface.llmwiki_toolkit`~~ — does not exist yet
- ~~`ToolInterface.has_llmwiki_tools`~~ — does not exist yet
- ~~`"LLMWikiToolkit"` case in `_capture_knowledge_toolkit`~~ — does not exist yet

---

## Implementation Notes

### Key Constraints

- Use class name string detection (`"LLMWikiToolkit"`) to avoid circular imports
- Follow the exact same pattern as pageindex_toolkit/graphindex_toolkit
- `has_llmwiki_tools` should check both `_llmwiki_toolkit is not None` AND
  tool_manager prefix scan for "wiki_" tools
- Do NOT import LLMWikiToolkit in these files — detection is by class name string

### References in Codebase

- `packages/ai-parrot/src/parrot/interfaces/tools.py:147-163` — existing capture hook
- `packages/ai-parrot/src/parrot/bots/abstract.py:353-354` — existing attr init
- `agents/oddie.py:223-265` — example of agent_tools() override that instantiates toolkits

---

## Acceptance Criteria

- [ ] `_llmwiki_toolkit` initialized to None in AbstractBot.__init__
- [ ] `_capture_knowledge_toolkit` detects "LLMWikiToolkit" by class name
- [ ] `llmwiki_toolkit` property returns the stashed instance
- [ ] `has_llmwiki_tools` returns True when toolkit is registered
- [ ] No circular imports introduced
- [ ] Existing PageIndex/GraphIndex detection still works
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_bot_integration.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import MagicMock

class TestBotIntegration:
    def test_capture_wiki_toolkit(self):
        # Create a mock bot with the ToolInterface mixin
        # Create a mock toolkit with __class__.__name__ == "LLMWikiToolkit"
        mock_toolkit = MagicMock()
        mock_toolkit.__class__.__name__ = "LLMWikiToolkit"
        # bot._capture_knowledge_toolkit(mock_toolkit)
        # assert bot._llmwiki_toolkit is mock_toolkit

    def test_has_llmwiki_tools_false_by_default(self):
        # assert bot.has_llmwiki_tools is False

    def test_llmwiki_toolkit_property(self):
        # After capture, property returns the toolkit
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/llmwiki-pageindex-graphindex.spec.md` §3 Module 8
2. **Check dependencies** — TASK-1633 must be completed
3. **Read** `interfaces/tools.py:98-163` and `bots/abstract.py:353-354` to verify current state
4. **Add** the wiki toolkit following the exact same pattern as pageindex/graphindex
5. **Verify** existing toolkit detection still works (no regressions)

---

## Completion Note

*(Agent fills this in when done)*
