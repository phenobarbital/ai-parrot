# TASK-5323: Agentic core — models, `clone_for_tools`, clipping, call controller, answer parsing

**Feature**: FEAT-843 — PageIndex Agentic Retrieval and Citations
**Spec**: `sdd/specs/pageindex-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5320, TASK-5322
**Assigned-to**: unassigned

---

## Context

Spec §2 "Dedicated client (M3)", "Exact character budget (M1/M3)", "Prompting (M3)", §3 Module 3.
This task creates `agentic.py` with every piece of the retriever that is NOT the supervised
run loop: the result models, the prompt constants, `clone_for_tools`, `clip_read_result`,
the private `ToolCallController`, and `AgenticRetriever.parse_answer`. TASK-5324 adds
`AgenticRetriever.__init__/run/_wrap` on top.

---

## Scope

- Create `knowledge/pageindex/agentic.py` with: `SYSTEM_PROMPT`, `BUDGET_MESSAGE`, `StopReason`,
  `AgenticAnswer`, `EvidenceBundle`, `clone_for_tools`, `clip_read_result`, `_ToolCallController`
  (spec calls it `ToolCallController`; private, not exported), and `AgenticRetriever` with ONLY the
  static `parse_answer` (class body otherwise empty for TASK-5324).
- `clip_read_result(result, allowance) -> ReadResult`: keep stored-text chars up to `allowance`;
  drop later segments; shorten the last kept segment's `text`/`end` (keep `start`) and set its
  `truncated`; when anything was omitted set `truncated=True` and `next_cursor` = `format_cursor`
  of the first omitted char (a dropped segment's original `start`); otherwise keep the original
  cursor; regenerate `framed` with `frame_segments`.
- Tests (first part of `test_agentic_retrieval.py`).

**NOT in scope**: `run`, `_wrap`, deadline/supervisor, repair call (TASK-5324); toolkit (TASK-5325).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py` | CREATE | Core types and helpers |
| `packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py` | CREATE | Core unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.base import AbstractClient                  # clients/base.py (class); ask :1944
from parrot.tools.manager import ToolManager                    # tools/manager.py:292; __init__(logger=None, debug=False, ...) :302
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text   # framing.py:10, :33, :42
from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead, format_cursor                # segments.py:110, :97, :282
from parrot.knowledge.pageindex.read_ledger import LedgerEntry                                        # TASK-5320
from parrot.knowledge.pageindex.citations import Citation, ProposedCitation, RejectedCitation         # TASK-5322
```

### Existing Signatures to Use
```python
# clients/base.py
class AbstractClient:
    self._tool_manager = tool_manager or ToolManager(logger=self.logger, debug=self._debug)   # :531-534
    self.tools: Dict[str, ...] = {}          # :535  (legacy registry)
    self.enable_tools: bool = use_tools      # :536
    self._debug                               # :527
    tool_manager (property + setter)          # :1002-1009
    register_tools(tools) -> None             # :1483 (sets enable_tools=True)

# framing.py
def frame_segments(reads: Sequence[SegmentRead], *, source: str) -> str      # :33
def frame_text(text: str, *, source: str, flagged: bool = False) -> str      # :42
# toolkit._read builds framed with source=f"{revision.doc_id}@{revision.revision}" (toolkit.py ~:838) — reuse that source string

# segments.py
def format_cursor(doc_id, revision, seq, offset) -> str                      # :282
```

### Does NOT Exist
- ~~`AbstractClient.clone()` / `copy_with()` / `with_tools()`~~ — use `copy.copy` in `clone_for_tools`.
- ~~`max_tool_rounds` / `max_tool_iterations` parameter on `ask()`~~.
- ~~`supports_tool_loop` capability flag~~ on any client.
- ~~`parrot.bots` usage~~ — forbidden in this module (spec Non-Goals).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/framing.py#frame_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#format_cursor"
  ]
}
```

---

## Implementation Notes

- `clone_for_tools`: `copy.copy(client)`, then `clone._tool_manager = ToolManager(logger=client.logger, debug=getattr(client, "_debug", False))`,
  `clone.tools = {}`, `clone.enable_tools = True`. Never touch `client` — AC-8.
- `_ToolCallController`: `admit() -> bool` under an `asyncio.Lock` (count < cap → count+=1, True;
  else False); `done()` decrements in-flight and sets `stop` event when count == cap and in-flight == 0;
  a terminal flag rejects every later admission. Refusals are admitted calls (they count).
- `parse_answer`: first ```json fenced block, else first balanced `{...}`; `AgenticAnswer.model_validate_json`; `None` on any failure.

---

## Implementation Blueprint

### Steps (in order)
1. Create `agentic.py` from the block.
2. Fill `clip_read_result`, controller and `parse_answer`.
3. Tests; run.

### `agentic.py` (CREATE)
```python
"""PageIndex stage-2 agentic retrieval (FEAT-843): bounded read loop with validated citations."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.knowledge.pageindex.citations import Citation, ProposedCitation, RejectedCitation
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text
from parrot.knowledge.pageindex.read_ledger import LedgerEntry
from parrot.knowledge.pageindex.segments import ReadResult, SegmentRead, format_cursor
from parrot.tools.manager import ToolManager

__all__ = ["AgenticAnswer", "EvidenceBundle", "AgenticRetriever", "clone_for_tools", "clip_read_result",
           "SYSTEM_PROMPT", "BUDGET_MESSAGE"]

logger = logging.getLogger(__name__)

BUDGET_MESSAGE = "read budget exhausted — answer from what you have read"
StopReason = Literal["answered", "budget", "max_tool_calls", "timeout", "no_tool_calls", "parse_error"]

SYSTEM_PROMPT = DATA_FRAMING_INSTRUCTION + "\n\n" + (
    # FILL IN: citing contract — read before answering; cite by the exact `address` attribute of a
    #          <segment address=…> tag (doc@rev#seq); excerpt copied verbatim, no paraphrase; final message is ONE
    #          ```json block {"answer": str|null, "citations": [{"address": ..., "excerpt": ...}]} — spec §2 Prompting
    ""
)


class AgenticAnswer(BaseModel):
    answer: Optional[str] = None
    citations: list[ProposedCitation] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    tree_name: str
    query: str
    generation: Optional[int] = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    reads: list[LedgerEntry] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    rejected: list[RejectedCitation] = Field(default_factory=list)
    answer: Optional[str] = None
    grounded: bool = False
    tool_calls: int = 0
    chars_read: int = 0
    stopped: StopReason = "answered"
    usage: dict[str, int] = Field(default_factory=dict)
    rendered_citations: str = ""


def clone_for_tools(client: AbstractClient) -> AbstractClient:
    """Shallow copy of ``client`` with a fresh ``ToolManager``, empty legacy ``tools`` and ``enable_tools=True``.

    Shares credentials, the per-loop SDK client cache and the session; isolates the tool registry."""
    clone = copy.copy(client)
    clone._tool_manager = ToolManager(logger=client.logger, debug=getattr(client, "_debug", False))
    clone.tools = {}
    clone.enable_tools = True
    return clone


def clip_read_result(result: ReadResult, allowance: int) -> ReadResult:
    """Return ``result`` cut to at most ``allowance`` stored-text characters (see spec §2 Exact character budget)."""
    # FILL IN: walk segments accumulating len(text); keep whole ones, shorten the boundary one, drop the rest;
    #          next_cursor/truncated/framed per Scope; return result.model_copy(update=...) — AC-18
    raise NotImplementedError


class _ToolCallController:
    """Admits at most ``cap`` tool invocations per request; sets ``stop`` after the last one finishes."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.admitted = 0
        self.in_flight = 0
        self.stop = asyncio.Event()
        self._lock = asyncio.Lock()

    async def admit(self) -> bool:
        # FILL IN: under lock: reject when admitted >= cap; else admitted += 1, in_flight += 1 — AC-17
        raise NotImplementedError

    async def done(self) -> None:
        # FILL IN: under lock: in_flight -= 1; if admitted >= cap and in_flight == 0: stop.set() — AC-17
        raise NotImplementedError


class AgenticRetriever:
    """Runs the bounded stage-2 loop on a dedicated client (run/_wrap added by TASK-5324)."""

    @staticmethod
    def parse_answer(text: str) -> Optional[AgenticAnswer]:
        """First fenced or bare JSON object in ``text`` as ``AgenticAnswer``; ``None`` when absent/invalid."""
        # FILL IN: ```json fence regex first, then first balanced {...}; validate; None on failure
        raise NotImplementedError
```
**Why**: import `frame_text` only if this task uses it; if ruff reports it unused (F401), remove it here — TASK-5324 adds it with the prompt code. `_ToolCallController` stays private because the spec says it is not a public export.

### `test_agentic_retrieval.py` (CREATE)
```python
"""FEAT-843 M3/M4 — agentic retrieval."""
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.pageindex.agentic import AgenticRetriever, clip_read_result, clone_for_tools
# FILL IN: test_clone_for_tools_isolated — real minimal AbstractClient subclass (implement abstract methods as stubs);
#          AC-8: tool_manager differs, tools == {}, enable_tools True, same class/model; registering on clone leaves original list_tools() unchanged
# FILL IN: clip tests — allowance 100 on a 1,200-char read; clip exactly at a segment boundary (cursor = next seg start);
#          allowance >= total keeps original cursor; framed regenerated — AC-18
# FILL IN: controller admits exactly cap under asyncio.gather of cap+5 admits; stop set after last done — AC-17
# FILL IN: parse_answer fenced / bare / invalid -> None
```

### FILL IN checklist
- [ ] `SYSTEM_PROMPT` text
- [ ] `clip_read_result`
- [ ] controller `admit`/`done`
- [ ] `parse_answer`
- [ ] tests

---

## Acceptance Criteria

- [ ] AC-8 clone isolation.
- [ ] AC-18 (clipping part): clipped text, offsets, truncation flags, framing and cursor agree, including a clip between segments.
- [ ] AC-17 (controller part): parallel admission never exceeds the cap.

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`

---

## Test Specification

Spec §4 rows for `test_agentic_retrieval.py` (clone isolation, clipping fixtures).

---

## Agent Instructions

1. `ruff check --fix`; run validation with `PYTHONPATH=packages/ai-parrot/src`.
2. Commit: `feat(pageindex-agentic-retrieval): TASK-5323 — agentic core`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 288s. Merged (lint 56301b4a72).

Validation: direct run of test_agentic_retrieval/test_citations/test_read_ledger/test_read_tools → 32 passed at HEAD a91c800be1.
