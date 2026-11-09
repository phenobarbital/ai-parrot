# TASK-5428: Delegate agentic retrieval and decorate pinned citations

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5427
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Implement spec M1 agentic_retrieve and _decorate_citations with the frozen signatures.
- Resolve one book and require segments/has_llm before invoking PageIndex exactly once; explain missing or unsupported tool-loop models without relabeling numeric validation failures.
- Enrich serialized citations only; preserve answer, grounded, stopped, usage, ledger and offsets. Render book labels as a semicolon-separated string.
- Use ownership/TOC only from a matching generation and revision; otherwise fall back to stored section or omit chapter. Never mutate the input bundle.
- Keep current PageIndex defaults and None forwarding; measured Bookstore-local defaults belong to the host task.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.bookstore.models import BookCard  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:152
from pathlib import Path  # verified: stdlib; existing library.py:26
import pytest  # verified: existing Bookstore test_toolkit.py:5
from unittest.mock import AsyncMock, MagicMock  # verified: stdlib; Bookstore conftest.py:13
from parrot.knowledge.bookstore.config import LibraryLocation  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:33
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:112,179
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179
class Bookstore:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:404
async def _document_of(self, card: Any, toolkit: PageIndexToolkit) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:1240
async def agentic_retrieve(
        self,
        tree_name: str,
        query: str,
        top_k: int = 5,
        draft_answer: bool = True,
        budget_chars: Optional[int] = None,
        max_reads: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py:72
class EvidenceBundle(BaseModel):
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/models.py:152
class BookCard(BaseModel):
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py:47
class Citation(BaseModel):
```


### Dependency-produced contracts

- TASK-5427: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- Bookstore.agentic_retrieve and _decorate_citations do not exist at the base; PageIndex has no stopped=stale.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/library.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._document_of",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.agentic_retrieve",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/agentic.py#EvidenceBundle",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/models.py#BookCard",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/citations.py#Citation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#LibraryLocation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError"
  ]
}
```

## Implementation Notes

TASK-5427: serializes overlapping writes to packages/ai-parrot/src/parrot/knowledge/bookstore/library.py

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Implement spec M1 agentic_retrieve and _decorate_citations with the frozen signatures. **Why**: Delegation forwards every public argument once and adds no extra LLM invocation.
2. Resolve one book and require segments/has_llm before invoking PageIndex exactly once; explain missing or unsupported tool-loop models without relabeling numeric validation failures. **Why**: Only matching generation/revision ownership supplies chapter; ambiguous/mismatched snapshots safely fall back.
3. Enrich serialized citations only; preserve answer, grounded, stopped, usage, ledger and offsets. Render book labels as a semicolon-separated string. **Why**: No-LLM, legacy segments and unsupported tool-loop cases fail explanatorily; actual upstream stop values pass through.
4. Use ownership/TOC only from a matching generation and revision; otherwise fall back to stored section or omit chapter. Never mutate the input bundle. **Why**: Citations retain exact text/offsets and original bundle fields; metadata and rendered labels match spec §2.
5. Keep current PageIndex defaults and None forwarding; measured Bookstore-local defaults belong to the host task. **Why**: Delegation forwards every public argument once and adds no extra LLM invocation.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class Bookstore:' packages/ai-parrot/src/parrot/knowledge/bookstore/library.py)
# Container/attachment anchor: class Bookstore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179; merge scoped edits, never replace the whole container.
from parrot.knowledge.bookstore.models import BookCard

async def agentic_retrieve(self, book_id: str, query: str, top_k: int = 5,
                           draft_answer: bool = True, budget_chars: Optional[int] = None,
                           max_reads: Optional[int] = None,
                           timeout_s: Optional[float] = None) -> dict[str, Any]:
    """Return per-book PageIndex evidence with generation-safe book citation labels."""
    # FILL IN: validate library prerequisites, delegate once, decorate without changing evidence;
    # bounded by AC-1, AC-3, AC-4 and spec §2 evidence contracts.
    raise NotImplementedError

async def _decorate_citations(self, card: BookCard, scope: str,
                              bundle: dict[str, Any]) -> dict[str, Any]:
    """Copy and enrich citations, using ownership only from the matching snapshot."""
    # FILL IN: snapshot comparison and ordered fallbacks; never choose an ambiguous owner;
    # bounded by AC-2 and AC-4. Keep this helper private to tool discovery.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py` (CREATE)

```python
"""Deterministic regression coverage for this FEAT-858 task."""
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

@pytest.mark.asyncio
async def test_delegate_once(tmp_path: Path) -> None:
    """Bookstore delegates one request and preserves evidence."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_generation_safe_labels(tmp_path: Path) -> None:
    """Old citations are never decorated from current ownership."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_visible_error_contract(tmp_path: Path) -> None:
    """Missing model and segments have clear errors without provider calls."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Delegation forwards every public argument once and adds no extra LLM invocation.
- [ ] AC-2: Only matching generation/revision ownership supplies chapter; ambiguous/mismatched snapshots safely fall back.
- [ ] AC-3: No-LLM, legacy segments and unsupported tool-loop cases fail explanatorily; actual upstream stop values pass through.
- [ ] AC-4: Citations retain exact text/offsets and original bundle fields; metadata and rendered labels match spec §2.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_agentic_retrieval.py -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_agentic_retrieval.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5428` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 380s, 0 retries. Orchestrator reviewed diff vs AC-1..4, no fixes. Validation: merge-tier 104 passed. Review: coder-review recorded. Closed via 'parrot sdd task close'.
