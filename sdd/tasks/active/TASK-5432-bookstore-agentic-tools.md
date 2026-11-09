# TASK-5432: Expose agentic retrieval and revision guard through toolkit and MCP

**Feature**: FEAT-858 — Bookstore Agentic Retrieval
**Spec**: `sdd/specs/bookstore-agentic-retrieval.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h; host wall time depends on provider when applicable)
**Depends-on**: TASK-5428
**Assigned-to**: unassigned

## Context

Implement this bounded deliverable of the approved FEAT-858 spec. Its behavioral authority
is the spec's §2 and owning §3 module, with §4 validation and §5 acceptance criteria.
Verified source base: `8387cd3e1b604955928064ff51a2fa207deceb36`. No implementation has been performed by this planning task.

## Scope

- Add the exact BookstoreToolkit.agentic_retrieve wrapper and append expected_revision to toolkit.read_segments.
- Keep the new tool visible with no LLM; do not introduce llm_dependent_tools or expose private helpers.
- Update MCP description/degradation documentation and exact tool-discovery assertions from 13 to 14.
- Test parameter forwarding, revision schema and stdout purity. Keep ingest/doctor out of MCP.

**NOT in scope**: files outside the table, provider SDK calls, PageIndex loop/validator changes,
unrelated refactoring, new dependencies, and other tasks' deliverables.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` | MODIFY | Scoped deliverable described above |
| `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` | MODIFY | Task regression coverage |
| `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` | MODIFY | Task regression coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Optional  # verified: stdlib; existing library.py:27
```

### Existing Signatures to Use

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:29
class BookstoreToolkit(AbstractToolkit):
```

```python
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:140
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
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py:61
def create_bookstore_mcp_server(
    locations: list[LibraryLocation],
    adapter: Optional[object] = None,
    lightweight_model: Optional[str] = None,
) -> StdioMCPServer:
```


### Dependency-produced contracts

- TASK-5428: consumes Bookstore.agentic_retrieve and inherited read revision guard

Those newly created symbols/files are planned contracts, not claims that they exist at this base. Read prerequisite commits before implementation.

### Does NOT Exist

- BookstoreToolkit has no agentic_retrieve or llm_dependent_tools declaration at the base.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py#BookstoreToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py#BookstoreToolkit.read_segments",
    "sym:packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py#create_bookstore_mcp_server"
  ]
}
```

## Implementation Notes

TASK-5428: consumes Bookstore.agentic_retrieve and inherited read revision guard

Use the activated project environment, async I/O, strict types, Google-style docstrings,
self.logger and existing dependency patterns. Do not alter shared conftest.py. This task
has no Delegation Contract: its behavioral branches/tests or host evidence still require
normal implementation reasoning; blueprint placeholders are planning instructions only.

## Implementation Blueprint

### Steps (in order)

1. Add the exact BookstoreToolkit.agentic_retrieve wrapper and append expected_revision to toolkit.read_segments. **Why**: All 14 expected read tools are listed with and without an LLM.
2. Keep the new tool visible with no LLM; do not introduce llm_dependent_tools or expose private helpers. **Why**: Wrapper forwards every retrieval and revision argument unchanged to the facade.
3. Update MCP description/degradation documentation and exact tool-discovery assertions from 13 to 14. **Why**: No-model invocation returns explanatory failure while discovery succeeds.
4. Test parameter forwarding, revision schema and stdout purity. Keep ingest/doctor out of MCP. **Why**: MCP construction/tool listing does not contaminate stdout or import wiki unnecessarily.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'class BookstoreToolkit(AbstractToolkit):' packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py)
# Container/attachment anchor: class BookstoreToolkit(AbstractToolkit):
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py:29; merge scoped edits, never replace the whole container.
async def agentic_retrieve(self, book_id: str, query: str, top_k: int = 5,
                           draft_answer: bool = True, budget_chars: Optional[int] = None,
                           max_reads: Optional[int] = None,
                           timeout_s: Optional[float] = None) -> dict[str, Any]:
    """Research one book with validated citations; requires PARROT_BOOKSTORE_LLM."""
    return await self._bookstore.agentic_retrieve(
        book_id, query, top_k=top_k, draft_answer=draft_answer,
        budget_chars=budget_chars, max_reads=max_reads, timeout_s=timeout_s,
    )

async def read_segments(self, book_id: str, start: Optional[int] = None,
                        end: Optional[int] = None, node_id: Optional[str] = None,
                        max_chars: int = 12000, cursor: Optional[str] = None,
                        expected_revision: Optional[str] = None) -> dict[str, Any]:
    """Read exact paragraphs, rejecting a supplied revision differing from the result."""
    return await self._bookstore.read_segments(
        book_id, start=start, end=end, node_id=node_id, max_chars=max_chars,
        cursor=cursor, expected_revision=expected_revision,
    )
# FILL IN: expand Google-style Args/Returns/Raises docstrings for the LLM-facing schema; AC-2, AC-3.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'def create_bookstore_mcp_server(' packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py)
# Container/attachment anchor: def create_bookstore_mcp_server(
# verified: packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py:61; merge scoped edits, never replace the whole container.
# Keep create_bookstore_mcp_server signature/registration and stderr redirection unchanged.
# FILL IN: change module description to fourteen read-only tools and describe visible-but-erroring
# agentic retrieval without an LLM; include the research handoff in server description; AC-1, AC-4.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'EXPECTED_TOOLS = {' packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py)
# Container/attachment anchor: EXPECTED_TOOLS = {
# verified: packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py:13; merge scoped edits, never replace the whole container.
# Add "bookstore_agentic_retrieve" to EXPECTED_TOOLS.
# FILL IN: AsyncMock the facade and assert every forwarded argument including expected_revision;
# inspect discovered input schema and absent llm_dependent_tools; AC-1..AC-3.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -cF -- 'def test_mcp_tools_list_has_thirteen_tools(seeded_locations):' packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py)
# Container/attachment anchor: def test_mcp_tools_list_has_thirteen_tools(seeded_locations):
# verified: packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py:48; merge scoped edits, never replace the whole container.
# Rename test_mcp_tools_list_has_thirteen_tools to test_mcp_tools_list_has_fourteen_tools.
# Change its exact count assertion to 14; EXPECTED_TOOLS is imported from test_toolkit.
# FILL IN: model/no-model discovery and error paths, retaining stdout/wiki-import guards; AC-1, AC-3, AC-4.
```

**Why**: this file owns the scoped behavior and regression evidence above; keep all unrelated content intact. Complete each FILL IN against AC-1..AC-4.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/src/parrot/knowledge/bookstore/mcp_server.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.
- [ ] `packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py` — complete its bounded blueprint and verify relevant AC-1..AC-4.

## Acceptance Criteria

- [ ] AC-1: All 14 expected read tools are listed with and without an LLM.
- [ ] AC-2: Wrapper forwards every retrieval and revision argument unchanged to the facade.
- [ ] AC-3: No-model invocation returns explanatory failure while discovery succeeds.
- [ ] AC-4: MCP construction/tool listing does not contaminate stdout or import wiki unnecessarily.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_toolkit.py -q`
- `pytest packages/ai-parrot/tests/knowledge/bookstore/test_mcp_server.py -q`

## Test Specification

Exercise the observable cases in the blueprint and AC-1..AC-4 with synthetic temporary
state and bounded synchronization. Existing operands listed above are regression gates,
not authorization to edit them unless they appear in the file table. No live provider
calls in pytest. Save execution logs under artifacts/logs/.


## Agent Instructions

1. Run `$sdd-start TASK-5432` to provision the feature worktree; do not implement on dev.
2. Read the approved spec and dependency evidence before editing.
3. Reverify every MODIFY anchor; dependency-created files must be inspected after their creators land.
4. Implement only the declared files; final code must contain no blueprint placeholders.
5. Run the Validation Commands and appropriate formatting/lint checks; retain real logs.
6. Commit scoped work and finalize with `parrot sdd task finalize` using actual completion evidence.

## Completion Note

Populated by the task finalizer after implementation, validation and the exact implementation commit.
