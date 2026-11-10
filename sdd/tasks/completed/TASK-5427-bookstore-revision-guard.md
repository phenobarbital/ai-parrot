# TASK-5427: Guard Bookstore segment reads by returned revision

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Extend only the library read_segments signature with keyword-only expected_revision=None (spec M1, AC-3).
- Compare the actual returned revision before returning any text; retain normal return shape when omitted.
- Propagate RevisionMismatchError unchanged, including cursor mismatch; keep existing BookstoreError mapping for other read errors.
- Cover a re-import between _document_of and toolkit.read_segments; a preflight-only check is insufficient.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.pageindex.segments import RevisionMismatchError  # verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:123
from pathlib import Path  # verified: stdlib; existing library.py:26
import pytest  # verified: existing Bookstore test_toolkit.py:5
from unittest.mock import AsyncMock, MagicMock  # verified: stdlib; Bookstore conftest.py:13
from parrot.knowledge.bookstore.config import LibraryLocation  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/config.py:33
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError  # verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:112,179
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:434
async def read_segments(
        self,
        book_id: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node_id: Optional[str] = None,
        max_chars: int = 12000,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:404
async def _document_of(self, card: Any, toolkit: PageIndexToolkit) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py:1117
async def read_segments(
        self,
        tree_name: str,
        doc_id: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node_id: Optional[str] = None,
        max_chars: int = 12000,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py:123
class RevisionMismatchError(ValueError):
```


### Does NOT Exist

- Bookstore.read_segments has no expected_revision argument at the verified base.

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
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore.read_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._document_of",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit.read_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/segments.py#RevisionMismatchError",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/config.py#LibraryLocation",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#BookstoreError"
  ]
}
```

## Implementation Notes

Independent guarded-read contract; no prerequisite symbols are created by another task.

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Extend only the library read_segments signature with keyword-only expected_revision=None (spec M1, AC-3). **Why**: Matching or omitted expected_revision preserves the existing return contract and positional calls.
2. Compare the actual returned revision before returning any text; retain normal return shape when omitted. **Why**: A mismatching returned revision raises RevisionMismatchError without releasing the result text.
3. Propagate RevisionMismatchError unchanged, including cursor mismatch; keep existing BookstoreError mapping for other read errors. **Why**: Cursor mismatch remains RevisionMismatchError; other legacy errors keep existing messages.
4. Cover a re-import between _document_of and toolkit.read_segments; a preflight-only check is insufficient. **Why**: A controlled lookup/read race proves the guard checks the returned result, not just live preflight.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class Bookstore:' packages/ai-parrot/src/parrot/knowledge/bookstore/library.py)
# Container/attachment anchor: class Bookstore:
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/library.py:179; merge scoped edits, never replace the whole container.
from parrot.knowledge.pageindex.segments import RevisionMismatchError

# Merge this member into Bookstore; preserve the rest of the class.
async def read_segments(self, book_id: str, start: Optional[int] = None,
                        end: Optional[int] = None, node_id: Optional[str] = None,
                        max_chars: int = 12000, cursor: Optional[str] = None, *,
                        expected_revision: Optional[str] = None) -> dict[str, Any]:
    """Read paragraphs; reject a returned snapshot that differs from expected_revision."""
    # FILL IN: preserve current read flow, propagate mismatch before broad ValueError handling,
    # compare returned revision before _book_result; bounded by AC-1..AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py` (CREATE)

```python
"""Deterministic regression coverage for this FEAT-858 task."""
from pathlib import Path
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

@pytest.mark.asyncio
async def test_returned_revision_guard(tmp_path: Path) -> None:
    """Matching and mismatching result revisions are distinguished."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_lookup_read_race(tmp_path: Path) -> None:
    """Re-import after document lookup cannot expose mismatched text."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_cursor_mismatch(tmp_path: Path) -> None:
    """Cursor mismatch retains its typed exception."""
    # FILL IN: arrange synthetic state and assert the documented observable result; AC-1..AC-4.
    raise NotImplementedError

```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Matching or omitted expected_revision preserves the existing return contract and positional calls.
- [ ] AC-2: A mismatching returned revision raises RevisionMismatchError without releasing the result text.
- [ ] AC-3: Cursor mismatch remains RevisionMismatchError; other legacy errors keep existing messages.
- [ ] AC-4: A controlled lookup/read race proves the guard checks the returned result, not just live preflight.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_revision_guard.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_segment_reads.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5427` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Implemented by seat gpt-5.6-terra (codex), 1 attempt, 206s, 0 retries. Merged on feature branch; orchestrator reviewed diff against AC-1..4, no fixes. Validation: test_revision_guard.py + test_segment_reads.py = 7 passed. Review recorded: coder-review:412ddd53a37ee9643e7457e1. Note: finalized via 'parrot sdd task close' (no EvidenceRef store available for 'task finalize').
