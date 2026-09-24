# TASK-3689: Four `wiki_schema_*` AbstractTools, `create_schema_tools`, and `SchemaPlaneToolkit`

**Feature**: FEAT-600 — SQL Schema Plane
**Spec**: `sdd/specs/sql-schema-plane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3684
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (tools half). Mirrors `structural/tools.py` (one `AbstractTool` per action, Pydantic `args_schema`, `ToolResult` payload with a `text` rendering). `SchemaPlaneToolkit(AbstractToolkit)` exposes the same four for any ai-parrot agent. Writes stay CLI-only (the MCP has no credentials).

---

## Scope

- Create `schema/tools.py` — `SchemaLookupInput`, `SchemaSearchInput`, `SchemaNeighborsInput`, `SchemaSourcesInput`; `WikiSchemaLookupTool`, `WikiSchemaSearchTool`, `WikiSchemaNeighborsTool`, `WikiSchemaSourcesTool`; `create_schema_tools(store, root, config, service=None) -> list[AbstractTool]` returning `[]` when no plane is available.
- Create `schema/toolkit.py` — `SchemaPlaneToolkit(AbstractToolkit)` with `tool_prefix = "schema"` wrapping the four operations as bound methods.
- Write `test_tools.py`.

**NOT in scope**: MCP mount (TASK-3690), write tools (none in v1), namespace-scoped `service_factory` routing (v1 has one plane; keep the `namespace` arg out).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` | CREATE | 4 tools + factory |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py` | CREATE | AbstractToolkit wrapper |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_tools.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (HEAD `0384596cf`, 2026-09-24). Use them VERBATIM. Anything not listed
> here must be verified with `grep`/`read` before use.

### Verified Imports
```python
from pydantic import BaseModel, Field
from parrot.tools.abstract import AbstractTool, ToolResult            # verified: packages/ai-parrot/src/parrot/tools/abstract.py (ToolResult :250 — success, status, result, error, metadata); import as in structural/tools.py:30
from parrot.tools.toolkit import AbstractToolkit                       # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:203 (tool_prefix attr :254; get_tools :494)
from parrot.knowledge.wiki.store import BaseWikiStore                  # verified: store.py:525
from parrot.knowledge.wiki.project import WikiProjectConfig            # verified: project.py:381
from parrot.knowledge.wiki.schema.service import SchemaPlaneService   # TASK-3684
from parrot.knowledge.wiki.schema.models import LookupResult          # TASK-3680
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py:105-143 (pattern)
class WikiSymbolLookupTool(AbstractTool):
    name = "wiki_symbol_lookup"; description = "..."; args_schema = SymbolLookupInput
    def __init__(self, service_factory): super().__init__(name=self.name, description=self.description); self._service_factory = service_factory
    async def _execute(self, query: str, ..., namespace: str | None = None) -> ToolResult:
        ... return ToolResult(result=payload)   |  ToolResult(success=False, status="error", result=None, error=str(exc))
def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]   # :225
# packages/ai-parrot/src/parrot/tools/toolkit.py:203 class AbstractToolkit(ABC): tool_prefix: str | None = None (:254); __init__(self, **kwargs) (:329); get_tools(...) (:494) — public async methods become tools
# TASK-3684 SchemaPlaneService: lookup(ref) -> LookupResult | list[str]; search(query, limit=) -> list[dict]; neighbors(ref, depth=, rel=) -> list[dict]; sources() -> list[SchemaSourceConfig]
```

### Does NOT Exist
- ~~`wiki_schema_*` tools~~ — new; names fixed by spec M5 and the TASK-3688 permission list
- ~~a `ServiceFactory` for schema~~ — v1 has ONE plane; tools hold the service directly (no `namespace` arg)
- ~~write tools over MCP~~ — none in v1

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/schema/test_tools.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#ToolResult",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py#create_structural_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py#WikiSymbolLookupTool"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
`structural/tools.py:50-225` (inputs, tool classes, factory) and `structural/toolkit.py` (`CodeStructuralToolkit`) for the AbstractToolkit wrapper.

### Key Constraints
- Tool docstring == LLM-facing description (project rule).
- Every `_execute` catches `KeyError`/`ValueError` → `ToolResult(success=False, status="error", ...)`; ambiguous lookup returns candidates in `result`.
- `create_schema_tools` returns `[]` when `service is None` and `config.schema.enabled` is False or no plane dir exists (AC11).

### References in Codebase
- packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
- packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py
- sdd/specs/sql-schema-plane.spec.md §3 Module 5

---

## Implementation Blueprint

> Executor-ready starting point derived from spec §3 Interface Skeletons; anchors re-verified at HEAD
> `0384596cf`. Complete every `# FILL IN:` marker; never change a signature, class name or path fixed here.

### Steps (in order)
1. Write `tools.py` from the block — why: one action per tool is the design invariant; names are fixed by the permission list.
2. Write `toolkit.py` — why: non-Claude agents get the same four operations via `AbstractToolkit`.
3. Tests over an in-memory plane (`SchemaPlaneService.from_dir(tmp, read_only=False)` + `put_table(sales_metadata)`).

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` (CREATE)
```python
"""Schema-plane MCP tools — read-only, one action per tool (FEAT-600 M5; mirrors structural/tools.py)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.project import WikiProjectConfig  # verified: project.py:381
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.store import BaseWikiStore  # verified: store.py:525
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: structural/tools.py:30 import


class SchemaLookupInput(BaseModel):
    ref: str = Field(..., description="table:<origin>/<schema>.<table>, bare <origin>:<schema>.<table>, or <schema>.<table>")


class SchemaSearchInput(BaseModel):
    query: str = Field(..., description="Words to match in table names, column names and comments")
    limit: int = Field(default=20, ge=1, le=100)


class SchemaNeighborsInput(BaseModel):
    ref: str = Field(..., description="Table reference (same forms as lookup)")
    depth: int = Field(default=1, ge=1, le=4)


class SchemaSourcesInput(BaseModel):
    pass


class _SchemaTool(AbstractTool):
    """Shared plumbing: hold the service, turn KeyError/ValueError into an error ToolResult."""

    def __init__(self, service: SchemaPlaneService) -> None:
        super().__init__(name=self.name, description=self.description)
        self._service = service

    async def _guard(self, coro: Any) -> ToolResult:
        try:
            return ToolResult(result=await coro)
        except (KeyError, ValueError) as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


class WikiSchemaLookupTool(_SchemaTool):
    """Look up one table in the schema plane: DDL, columns, relations, annotations, age and staleness. Never introspects a database."""

    name = "wiki_schema_lookup"
    description = __doc__
    args_schema = SchemaLookupInput

    async def _execute(self, ref: str) -> ToolResult:
        result = await self._guard(self._service.lookup(ref))
        # FILL IN: when result.result is a list (ambiguous), set status="ambiguous" and result={"candidates": [...]}; when a LookupResult,
        #   result=model_dump(mode="json") + "text" rendering (DDL + columns table) — bounded by AC3 and DEFAULT token budget
        return result


class WikiSchemaSearchTool(_SchemaTool):
    """Full-text search over table names, column names and comments in the schema plane."""

    name = "wiki_schema_search"
    description = __doc__
    args_schema = SchemaSearchInput

    async def _execute(self, query: str, limit: int = 20) -> ToolResult:
        return await self._guard(self._service.search(query, limit=limit))


class WikiSchemaNeighborsTool(_SchemaTool):
    """Foreign-key join paths from a table, up to `depth` hops, each with the (src_column -> dst_column) pair."""

    name = "wiki_schema_neighbors"
    description = __doc__
    args_schema = SchemaNeighborsInput

    async def _execute(self, ref: str, depth: int = 1) -> ToolResult:
        return await self._guard(self._service.neighbors(ref, depth=depth))


class WikiSchemaSourcesTool(_SchemaTool):
    """List the declared SQL sources (alias, dialect, schemas). DSNs are never exposed — only env-var names."""

    name = "wiki_schema_sources"
    description = __doc__
    args_schema = SchemaSourcesInput

    async def _execute(self) -> ToolResult:
        return await self._guard(self._service.sources())


def create_schema_tools(store: BaseWikiStore, root: Optional[Path], config: WikiProjectConfig,
                        service: Optional[SchemaPlaneService] = None) -> list[AbstractTool]:
    """Return the four read tools bound to ``service``; ``[]`` when no plane is available (AC11)."""
    if service is None or not config.schema.enabled:
        return []
    return [WikiSchemaLookupTool(service), WikiSchemaSearchTool(service), WikiSchemaNeighborsTool(service), WikiSchemaSourcesTool(service)]
```
**Why**: Same class shape as the structural tools so `mcp_server` can append them the same way; the empty-list contract lets TASK-3690 keep the tool count unchanged when no plane exists (AC11).

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py` (CREATE)
```python
"""SchemaPlaneToolkit — the four schema-plane reads for any ai-parrot agent (FEAT-600 M5)."""
from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.tools.toolkit import AbstractToolkit  # verified: tools/toolkit.py:203


class SchemaPlaneToolkit(AbstractToolkit):
    """Read-only access to the SQL schema plane: lookup, search, neighbors (join paths), sources."""

    tool_prefix = "schema"  # verified: toolkit.py:254

    def __init__(self, service: SchemaPlaneService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._service = service

    async def lookup(self, ref: str) -> dict[str, Any]:
        """Look up one table (DDL, columns, relations, annotations, age, stale). REF: table:<o>/<s>.<t>, <o>:<s>.<t> or <s>.<t>."""
        result = await self._service.lookup(ref)
        return {"candidates": result} if isinstance(result, list) else result.model_dump(mode="json")

    async def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search over table names, column names and comments."""
        return await self._service.search(query, limit=limit)

    async def neighbors(self, ref: str, depth: int = 1) -> list[dict[str, Any]]:
        """Foreign-key join paths from a table up to `depth` hops."""
        return await self._service.neighbors(ref, depth=depth)

    async def sources(self) -> list[dict[str, Any]]:
        """Declared SQL sources (alias, dialect, schemas, dsn_env NAME)."""
        return [s.model_dump(mode="json") for s in await self._service.sources()]
```
**Why**: Bound methods become tools via `AbstractToolkit`; `tool_prefix` yields `schema_lookup` etc. for agents outside Claude Code.

### FILL IN checklist
- [ ] `WikiSchemaLookupTool._execute` ambiguous/text rendering — AC3
- [ ] tests: 4 tool names; lookup bare form; ambiguous → status ambiguous; `create_schema_tools(service=None) == []`; toolkit `get_tools()` yields 4 with `schema_` prefix

---

## Acceptance Criteria

- [ ] each tool works over an in-memory plane; `wiki_schema_lookup` accepts bare `o:s.t` (AC3)
- [ ] `create_schema_tools(..., service=None)` returns `[]` (AC11)
- [ ] `SchemaPlaneToolkit.get_tools()` exposes four tools
- [ ] no DSN in any payload
- [ ] ruff/black clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/schema/test_tools.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/schema/test_tools.py
import pytest
from parrot.knowledge.wiki.schema.models import SchemaPlaneConfig
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.schema.tools import create_schema_tools
from parrot.knowledge.wiki.project import WikiProjectConfig

@pytest.fixture
async def svc(plane_dir, sales_metadata):
    s = SchemaPlaneService.from_dir(plane_dir, config=SchemaPlaneConfig(), read_only=False)
    await s.put_table("bigquery", "bigquery", sales_metadata); return s

async def test_lookup_tool_bare_form(svc):
    tools = {t.name: t for t in create_schema_tools(svc.store, None, WikiProjectConfig(), service=svc)}
    assert set(tools) == {"wiki_schema_lookup", "wiki_schema_search", "wiki_schema_neighbors", "wiki_schema_sources"}
    res = await tools["wiki_schema_lookup"]._execute(ref="bigquery:epson.sales")
    assert res.success and res.result["page_id"] == "table:bigquery/epson.sales"

def test_no_plane_no_tools():
    assert create_schema_tools(None, None, WikiProjectConfig(), service=None) == []
```

---

## Agent Instructions

1. Read the spec (`sdd/specs/sql-schema-plane.spec.md`) §2, §3 module for this task, §6 Codebase Contract, §7.
2. Check dependencies — `TASK-3684` must be in `sdd/tasks/completed/`.
3. Verify the Codebase Contract above (`grep`/`read`) before writing code; re-run `grep -c` on every MODIFY anchor.
4. Implement from the Blueprint; complete every `# FILL IN:`; run the Validation Commands
   (inside a worktree: `PYTHONPATH=packages/ai-parrot/src pytest …`), then `ruff check` + `black --check` on touched files.
5. Commit ONLY the files listed above. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
