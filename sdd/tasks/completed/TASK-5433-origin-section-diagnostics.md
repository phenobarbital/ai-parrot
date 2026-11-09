# TASK-5433: Add request-local successful origin section diagnostics

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

- Add default SearchOrigin.search_section(query,k)->OriginSection while preserving search()->list[OriginHit].
- Dispatch non-FTS origins through the optional hook when available, preserving duck-typed search-only origins.
- Accept returned OriginSection in _section_from_result and overwrite identity/kind/description with configured values.
- Keep existing timeout/error/FTS behavior and cancel timed-out work; no mutable last_note state.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py` | CREATE | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models import OriginHit, OriginSection, SearchOriginKind  # verified: packages/ai-parrot/src/parrot/models/__init__.py:109-117; definitions models/stores.py:31,79,106
import asyncio  # verified: stdlib; existing library.py:19
import pytest  # verified: existing Bookstore test_toolkit.py:5
from parrot_tools.multistoresearch.origins.base import SearchOrigin  # verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18
class SearchOrigin(ABC):
```

```python
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:268
async def _run_origins(
        self, query: str, k: int, fts: bool
    ) -> List[OriginSection]:
```

```python
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:304
def _section_from_result(self, origin: SearchOrigin, result: Any) -> OriginSection:
```

```python
# verified: packages/ai-parrot/src/parrot/models/stores.py:106
class OriginSection(BaseModel):
```


### Does NOT Exist

- SearchOrigin.search_section is new; current successful sections always have note=None.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py#SearchOrigin",
    "sym:packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py#MultiStoreSearchToolkit._run_origins",
    "sym:packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py#MultiStoreSearchToolkit._section_from_result",
    "sym:packages/ai-parrot/src/parrot/models/stores.py#OriginSection",
    "sym:packages/ai-parrot/src/parrot/models/stores.py#OriginHit",
    "sym:packages/ai-parrot/src/parrot/models/stores.py#SearchOriginKind"
  ]
}
```

## Implementation Notes

Independent origin protocol task; modifies only base/toolkit and its own tests.

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Add default SearchOrigin.search_section(query,k)->OriginSection while preserving search()->list[OriginHit]. **Why**: Existing subclass and duck-typed origins retain the same successful hit behavior.
2. Dispatch non-FTS origins through the optional hook when available, preserving duck-typed search-only origins. **Why**: Section hooks can supply request-local partial/all-skipped notes without changing shared models.
3. Accept returned OriginSection in _section_from_result and overwrite identity/kind/description with configured values. **Why**: Configured identity always wins over a returned section; concurrent notes cannot cross-contaminate.
4. Keep existing timeout/error/FTS behavior and cancel timed-out work; no mutable last_note state. **Why**: FTS, backend error and per-origin timeout isolation remain unchanged.

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class SearchOrigin(ABC):' packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py)
# Container/attachment anchor: class SearchOrigin(ABC):
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py:18; merge scoped edits, never replace the whole container.
from parrot.models import OriginHit, OriginSection, SearchOriginKind

async def search_section(self, query: str, k: int) -> OriginSection:
    """Wrap search hits in a successful section; leave exceptions to the toolkit."""
    return OriginSection(origin=self.name, origin_kind=self.kind,
                         description=self.description, status="ok", note=None,
                         hits=await self.search(query, k))
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class MultiStoreSearchToolkit(AbstractToolkit):' packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py)
# Container/attachment anchor: class MultiStoreSearchToolkit(AbstractToolkit):
# verified: packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:39; merge scoped edits, never replace the whole container.
# Within _run_origins, preserve the existing timeout/gather boundaries.
# FILL IN: for non-FTS choose getattr(origin, "search_section", origin.search), retaining
# origin.fts_search for FTS. Do not move work outside asyncio.wait_for; AC-1, AC-4.

def _section_from_result(self, origin: SearchOrigin, result: Any) -> OriginSection:
    """Normalize hits/sections/errors while keeping configured origin identity authoritative."""
    # FILL IN: preserve existing exception branches; accept OriginSection with identity stamped
    # from origin, and keep list-return fallback; AC-1..AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py` (CREATE)

```python
"""Request-local multi-origin section diagnostics regressions."""
import asyncio
import pytest
from parrot.models import OriginHit, OriginSection, SearchOriginKind
from parrot_tools.multistoresearch.origins.base import SearchOrigin

@pytest.mark.asyncio
async def test_concurrent_section_notes_are_isolated() -> None:
    """Two queries preserve their own notes and configured origin identity."""
    # FILL IN: controlled overlapping calls and assertions; AC-2, AC-3.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_legacy_fts_and_timeout_compatibility() -> None:
    """Legacy origins, FTS and cancellation retain the existing contracts."""
    # FILL IN: fake subclass/duck origin plus timeout and error fixtures; AC-1, AC-4.
    raise NotImplementedError
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: Existing subclass and duck-typed origins retain the same successful hit behavior.
- [ ] AC-2: Section hooks can supply request-local partial/all-skipped notes without changing shared models.
- [ ] AC-3: Configured identity always wins over a returned section; concurrent notes cannot cross-contaminate.
- [ ] AC-4: FTS, backend error and per-origin timeout isolation remain unchanged.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/multistoresearch/test_origin_sections.py -q`
- `pytest packages/ai-parrot-tools/tests/multistoresearch/test_toolkit.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5433` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Implemented by seat gpt-5.6-sol (codex), 1 attempt, 217s, 0 retries. Merged; orchestrator reviewed diff against AC-1..4, no fixes. Validation: merge-tier (multistoresearch) 35 passed. Review recorded: coder-review:509b72cac5a716090cedb638. Engine lint residual_count=1 left for /sdd-done. Finalized via 'parrot sdd task close'.
