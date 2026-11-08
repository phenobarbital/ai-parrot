# TASK-5366: LLM passes: live gate, heading proposals and key_items

**Feature**: FEAT-846 — PageIndex Tree Optimizer
**Spec**: `sdd/specs/pageindex-tree-optimizer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5365
**Assigned-to**: unassigned

---

## Context

First half of spec Module 2 (§2 "LLM passes": *heading proposals*, *concept key_items*; §3 M2 skeleton). Every prompt
is framed (G11). LLM calls happen only with a *live* adapter — Bookstore hands the toolkit a `_NullAdapter`.

## Scope

- Create `optimizer_llm.py` with `HeadingProposals`, `KeyItemProposal`, `KeyItemProposals`, `SummaryOut`,
  `adapter_is_live`, `execution_digest`, `reads_for`, `heading_like`, `literal_in_anchor`, `propose_headings`,
  `propose_key_items`.
- Tests: `test_heading_like_and_proposals`, `test_key_items_literal_check`, `test_adapter_is_live`, `test_prompts_are_framed`
  (for the two proposal prompts).

**NOT in scope**: summaries, `describe_document`, `run_llm_passes` (TASK-5367).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` | CREATE | live gate, execution digest, reads_for, heading_like, proposals |
| `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` | CREATE | M2 unit tests (first half) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # verified: framing.py:10,33,39
from parrot.knowledge.pageindex.builder import _LLM_SEMAPHORE, _limited_gather  # verified: builder.py:75,80
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead  # verified: segments.py:33,59,71,97
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS  # verified: layout_structure.py:23
from parrot.knowledge.pageindex.utils import create_clean_structure_for_description  # verified: utils.py:713
from parrot.knowledge.pageindex.optimizer import (  # TASK-5364/5365
    KeyItem, OptimizePlan, OptimizerSettings, Revisions, is_stamped, owned_tokens, pass_cache_key, pass_input, split_at,
)
```

### Existing Signatures to Use
```python
# framing.py
DATA_FRAMING_INSTRUCTION: str                                  # :10 — use verbatim as the system prompt
def frame_segments(reads, *, source=...) -> str                # :33 — check exact kwargs before use
def frame_text(text, *, source=...) -> str                     # :39 — neutralizes embedded closing tags
# builder.py
_LLM_SEMAPHORE: ContextVar[Optional[asyncio.Semaphore]]       # :75
async def _limited_gather(coros, *, return_exceptions=False) -> list  # :80 (plain gather when the var is unset)
# llm_adapter.py
class PageIndexLLMAdapter:                                     # :42
    async def ask(...)                                         # :61
    async def ask_structured(..., output_type=<pydantic model>) # :99 — check the exact parameter names
# bookstore/library.py
class _NullAdapter: model = None; client = None; ask() -> ""; ask_structured raises RuntimeError  # :150-176
# segments.py
class SegmentRead(BaseModel): address, seq, kind, text, start, end, truncated, flags   # :97
class SegmentAddress(BaseModel): doc_id, revision, seq, page, ordinal, section          # :71
```

### Does NOT Exist
- ~~`toolkit.has_llm` as the live gate~~ — True for Bookstore's `_NullAdapter` (`toolkit.py:377`); use `adapter_is_live`
- ~~framing in `generate_node_summary` / `generate_prefix_summaries` / `generate_doc_description`~~ — all unframed legacy; never call them here
- ~~a word cap in any existing summary prompt~~ — none exists; `summary_max_words` is new
- ~~proposals keyed by echoed text~~ — proposals are keyed by `seq` only (spec §7)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/framing.py#frame_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py#_limited_gather"
  ]
}
```

---

## Implementation Notes

- `heading_like`: single line, `<= MAX_HEADING_WORDS` words, no terminal period, `kind not in {"table","code","caption"}`.
  No median-paragraph check (rejected in spec §8).
- A proposal outside the node's owned ranges, or failing `heading_like`, is counted (caller adds to
  `report.rejected_proposals`) and never applied. Return accepted seqs plus the rejected count, or expose a helper —
  FILL IN the shape but keep the spec signature `-> list[int]` (e.g. count via an optional `report` kwarg).
- `literal_in_anchor`: casefold + collapse whitespace on both sides, substring test.
- `execution_digest` never includes credentials or object ids: mode, prompt version, provider/client class name, model.

---

## Implementation Blueprint

**Steps (in order)**
1. Create `optimizer_llm.py` from the block. 2. Fill the bodies. 3. Create the tests with a fake live adapter
   (MagicMock with `.client` set) and a `_NullAdapter`-shaped object (`client=None`).

### `packages/ai-parrot/src/parrot/knowledge/pageindex/optimizer_llm.py` (CREATE)
```python
"""LLM passes of the PageIndex tree optimizer (FEAT-846, Module 2). Every prompt is framed."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel

from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text  # verified: framing.py:10,33,39
from parrot.knowledge.pageindex.builder import _LLM_SEMAPHORE, _limited_gather  # verified: builder.py:75,80
from parrot.knowledge.pageindex.segments import DocumentRevision, Segment, SegmentAddress, SegmentRead  # verified: segments.py:33,59,71,97
from parrot.knowledge.pageindex.layout_structure import MAX_HEADING_WORDS  # verified: layout_structure.py:23
from parrot.knowledge.pageindex.utils import create_clean_structure_for_description  # verified: utils.py:713
from parrot.knowledge.pageindex.optimizer import (  # TASK-5364/5365
    KeyItem, OptimizePlan, OptimizerSettings, Revisions, is_stamped, owned_tokens, pass_cache_key, pass_input, split_at,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v1"
_NON_HEADING_KINDS = frozenset({"table", "code", "caption"})


class HeadingProposals(BaseModel):
    """Structured output: ``seqs`` of segments the model takes for printed sub-headings."""
    seqs: list[int]


class KeyItemProposal(BaseModel):
    label: str
    kind: Literal["literal", "abstractive"]
    seq: int


class KeyItemProposals(BaseModel):
    items: list[KeyItemProposal]


class SummaryOut(BaseModel):
    summary: str


def adapter_is_live(adapter: Any) -> bool:
    """True only for an adapter with a client (Bookstore's ``_NullAdapter`` has ``client = None``)."""
    return adapter is not None and getattr(adapter, "client", None) is not None


def execution_digest(adapter: Optional[Any], *, mode: str, prompt_version: str = PROMPT_VERSION) -> str:
    """Digest mode + prompt version; live adds provider/client type and effective model, never credentials."""
    # FILL IN: payload = [mode, prompt_version] (+ type(adapter.client).__name__, getattr(adapter, "model", None) when live)


def reads_for(node: dict, revision: DocumentRevision) -> list[SegmentRead]:
    """One full ``SegmentRead`` per owned segment, so ``frame_segments`` labels each with its address."""
    # FILL IN: build SegmentAddress + SegmentRead per seq in owned ranges (check required fields at segments.py:71,97)


def heading_like(segment: Segment) -> bool:
    """Single line, <= MAX_HEADING_WORDS words, no terminal period, kind not table/code/caption."""
    text = (segment.text or "").strip()
    if not text or "\n" in text or segment.kind in _NON_HEADING_KINDS:
        return False
    return len(text.split()) <= MAX_HEADING_WORDS and not text.endswith(".")


def literal_in_anchor(label: str, text: str) -> bool:
    """Casefolded, whitespace-collapsed substring test."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip().casefold()  # noqa: E731
    return bool(norm(label)) and norm(label) in norm(text)


async def propose_headings(node: dict, revision: DocumentRevision, adapter: Any,
                           settings: OptimizerSettings) -> list[int]:
    """Framed prompt -> ``HeadingProposals``; keep seqs inside owned ranges that pass ``heading_like``."""
    # FILL IN: user prompt = instructions + frame_segments(reads_for(...), source=<fixed label>);
    #          system prompt = DATA_FRAMING_INSTRUCTION; adapter.ask_structured(output_type=HeadingProposals)


async def propose_key_items(node: dict, revision: DocumentRevision, adapter: Any,
                            settings: OptimizerSettings) -> list[KeyItem]:
    """Framed prompt -> ``KeyItemProposals``; validate anchors and literal labels; cap at ``max_key_items``."""
    # FILL IN
```
**Why**: the gate and acceptance predicates are spec-exact, so they are complete; prompt wording is judgement.

### `packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py` (CREATE)
```python
"""Unit tests for optimizer_llm (FEAT-846 M2)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION
from parrot.knowledge.pageindex.optimizer_llm import adapter_is_live, heading_like, literal_in_anchor


def test_heading_like_and_proposals(): ...   # FILL IN
def test_key_items_literal_check(): ...      # FILL IN
def test_adapter_is_live(): ...              # FILL IN
def test_prompts_are_framed(): ...           # FILL IN: '<document_text' in prompt; system prompt == DATA_FRAMING_INSTRUCTION
```

**FILL IN checklist**
- [ ] `execution_digest`, `reads_for`, both proposal functions
- [ ] four tests

---

## Acceptance Criteria

- [ ] AC-4: accepted headings are printed lines that pass `heading_like`; key_items carry `kind` and a valid anchor;
      a `literal` label occurs in its anchor.
- [ ] AC-12 (proposal part): both prompts are framed with `DATA_FRAMING_INSTRUCTION`; out-of-range seqs are rejected.
- [ ] `adapter_is_live` is False for `None` and for `client=None` objects.


## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_optimizer_llm.py -q`

---

## Test Specification

Spec §4 rows `test_heading_like_and_proposals`, `test_key_items_literal_check`, `test_adapter_is_live`,
`test_prompts_are_framed`.

---

## Agent Instructions

1. Read the spec sections named in Context, then this task's Codebase Contract — use only the listed imports.
2. Re-run `grep -c` on every MODIFY anchor before editing; a count that differs from the blueprint means drift — stop and report.
3. Write the blueprint blocks, then resolve every `FILL IN` within its stated bound.
4. Run `ruff check --fix` on the touched files and the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
5. Commit only the files listed above: `feat(pageindex-tree-optimizer): TASK-5366 — LLM passes: live gate, heading proposals and key_items`.

---

## Completion Note

*(Agent fills this in when done)*
