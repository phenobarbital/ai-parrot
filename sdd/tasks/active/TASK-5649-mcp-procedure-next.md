# TASK-5649: MCP tool `wiki_procedure_next` on both transports

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5640, TASK-5641
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10, goal G6 and spec rev 0.3 decision 1. The wiki MCP server has two transports
that must expose the same tools: the SDK transport builds them from `transport.py` (core), the
framework transport from wrappers in `parrot_tools.wiki`. `transport.py` imports every operation
from a **core** module, so the input model and the operation live in core and `parrot_tools`
holds only the wrapper.

---

## Scope

- Create `parrot/knowledge/wiki/procedure/operations.py`: `ProcedureNextInput`,
  `PROCEDURE_NEXT_DESCRIPTION`, `procedure_plane_available`, `op_procedure_next`.
- Create `parrot_tools/wiki/procedure.py`: `WikiProcedureNextTool`, `create_procedure_tools`; add
  the export/registry lines next to the schema ones.
- Wire both transports: `transport.py` (`_SPECS`, dispatch, mount gate) and `mcp_server.py`.
- Create `test_mcp_tool.py`.

**NOT in scope**: remote probes in the tool (local only), any change to the resolver, the CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py` | CREATE | Input model, gate, operation |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/procedure.py` | CREATE | Framework tool and factory |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` | MODIFY | Lazy export of the factory and tool |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Tool registry entry |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `_Spec`, dispatch branch, mount gate |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | Add the framework tools |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py` | CREATE | Both-transport tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). `ProcedurePlane` (TASK-5640), `resolve`, `SddProbeRunner`,
> `scope_for` (TASK-5641), `is_stale` / `read_index` (TASK-5639), `checkout_root` (TASK-5637) are
> dependency-provided — re-check them after they land.

### Verified Imports
```python
from parrot.knowledge.wiki.operations import OperationResult                 # wiki/operations.py:35
from parrot.knowledge.wiki import project                                    # use project.find_shared_root(...) via the MODULE attribute
from parrot.knowledge.wiki.project import WikiProjectConfig                  # wiki/project.py:589
from parrot.knowledge.wiki.store import BaseWikiStore                        # wiki/store.py:870
from parrot.tools.abstract import AbstractTool, ToolResult                   # tools/abstract.py:283, :252
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/operations.py
class OperationResult(BaseModel): text: str = ""; data: dict[str, Any] | None = None; is_error: bool = False   # :35

# packages/ai-parrot/src/parrot/knowledge/wiki/schema/operations.py  — the operation shape to copy
async def op_schema_sources(store: Any, params: SchemaSourcesInput, **context: Any) -> OperationResult:   # :77

# packages/ai-parrot/src/parrot/knowledge/wiki/transport.py
from parrot.knowledge.wiki.schema.operations import (                        # :68
from parrot.knowledge.wiki.usage_operations import USAGE_REPORT_DESCRIPTION, UsageReportInput, op_usage_report   # :86 — a shared description constant
@dataclass(frozen=True)
class _Spec: mount: str; input_model: type[BaseModel]; description: str     # :102
_SPECS: dict[str, _Spec] = { ...                                             # :114
    "vault_ingest": _Spec(                                                   # :234
def _operation_invoke(name: str, ctx: WikiOperationContext) -> Callable[...]:   # :291
    elif name == "wiki_schema_lookup":                                       # :391
        async def invoke(params: BaseModel) -> OperationResult:
            return await op_schema_lookup(None, params, service=schema, annotation_store=store)
    elif name == "ledger_open":                                              # :411
def mounted_operation_names(ctx: WikiOperationContext) -> list[str]:        # :476
    if ctx.schema_service is not None and ctx.config.schema_plane.enabled:  # :496
        names += [name for name, spec in _SPECS.items() if spec.mount == "schema"]
    if ctx.vault_dir is not None:                                            # :498
class WikiOperationContext: root: Path; config: Any; ...                     # :243

# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py   (inside build_framework_tools)
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.schema.tools import create_schema_tools
        tools = tools + create_schema_tools(read_store, root, config, context.schema_service)   # :387

# packages/ai-parrot-tools/src/parrot_tools/wiki/schema.py  — the wrapper shape to copy
class WikiSchemaSourcesTool(_SchemaTool):                                    # :95
    name = "wiki_schema_sources"; description = __doc__; args_schema = SchemaSourcesInput
    async def _execute(self) -> ToolResult: ...
def create_schema_tools(store, root, config, service=None) -> list[AbstractTool]: ...   # :111
# packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py:32      "create_schema_tools": "parrot_tools.wiki.schema",
# packages/ai-parrot-tools/src/parrot_tools/__init__.py:141           "wiki_schema_sources": "parrot_tools.wiki.schema.WikiSchemaSourcesTool",

# packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py
#   :97-:105 — framework tools must have the SAME description and args schema as the descriptor of the same name
#   :121     — the goldens monkeypatch `project.find_shared_root`; no golden configuration has a procedure plane
```

### Does NOT Exist
- ~~`ProcedureNextInput` / `op_procedure_next` in `parrot_tools`~~ — they are core (rev 0.3 decision 1).
- ~~An import of `parrot_tools` in `transport.py`~~ — core never imports it there.
- ~~A golden file to regenerate~~ — the tool mounts only when a plane exists, and no golden
  configuration has one; `test_mcp_manifest_golden.py` must pass unchanged.
- ~~Remote probes in this tool~~ — `allow_remote=False` always.
- ~~`from parrot.knowledge.wiki.project import find_shared_root` in `operations.py`~~ — call it as
  `project.find_shared_root(...)` so the tests' monkeypatch of the module attribute applies.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/wiki/procedure.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/transport.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/operations.py#OperationResult",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#_Spec",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#_operation_invoke",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/transport.py#mounted_operation_names",
    "sym:packages/ai-parrot-tools/src/parrot_tools/wiki/schema.py#create_schema_tools",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#ToolResult"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.
- **One gate**: `procedure_plane_available(root)` is true when `root` is not `None`,
  `project.find_shared_root(root)` returns a directory, and
  `<shared>/.parrot/procedure/procedures.json` is a file. Both transports call it.
- **One description**: `PROCEDURE_NEXT_DESCRIPTION` is used by the `_Spec` and by the tool class,
  so the manifest test's equality check cannot drift.
- **Operation**: no plane → `OperationResult(text="No procedure plane. Run: parrot sdd procedure
  build")` (not an error). Otherwise read the specs with `ProcedurePlane(...).specs()`, compute
  `stale`, then run `scope_for` + `resolve(..., allow_remote=False, stale=stale)` inside
  `asyncio.to_thread` (the probes read files synchronously). Any `ValueError` / `OSError` becomes
  `OperationResult(text=str(exc), is_error=True)`.
- **Payload** (`data`): `{"scope", "stale", "next": [{"id", "title", "mode", "command", "advice",
  "unmet": [<check text>…]}], "mandatory": [{"id", "command", "use_instead"}]}` — never the full
  spec bodies. `text` is a three-to-ten line plain rendering of the same content.
- The framework tool is constructed with the project `root`; it ignores `store` and `config`.

---

## Implementation Blueprint

### Steps (in order)
1. Write `operations.py` — *why*: both transports depend on it.
2. Wire `transport.py` — *why*: the SDK transport is generated from `_SPECS`.
3. Write the wrapper and wire `mcp_server.py` — *why*: the framework transport must list the same
   tool under the same condition.
4. Write the tests; run the manifest golden test unchanged.

### `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py` (CREATE)
```python
"""Transport-neutral procedure operations (FEAT-891)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki import project
from parrot.knowledge.wiki.operations import OperationResult
from parrot.knowledge.wiki.procedure.models import INDEX_FILE, PLANE_DIR

PROCEDURE_NEXT_DESCRIPTION = (
    "Deterministic next step in this repository's procedure graph: the procedures that apply to a feature or "
    "task, which step is valid next, which preconditions are unmet, and the mandatory rules ahead. "
    "Local checks only; no LLM call."
)


class ProcedureNextInput(BaseModel):
    """Arguments for ``wiki_procedure_next``."""

    feature: str | None = Field(default=None, description="Feature slug or FEAT id; default: from the current branch.")
    task: str | None = Field(default=None, description="Task id, e.g. TASK-123.")


def procedure_plane_available(root: Path | None) -> bool:
    """True when ``<shared-root>/.parrot/procedure/procedures.json`` exists for ``root``."""
    if root is None:
        return False
    shared = project.find_shared_root(Path(root))
    return shared is not None and (shared / PLANE_DIR / INDEX_FILE).is_file()


async def op_procedure_next(store: Any, params: ProcedureNextInput, **context: Any) -> OperationResult:
    """Resolve the next valid procedure step(s) for ``context['root']`` with local probes only."""
    root = context.get("root")
    if not procedure_plane_available(root):
        return OperationResult(text="No procedure plane. Run: parrot sdd procedure build")
    # FILL IN: lazy imports (ProcedurePlane, read_index, is_stale, resolve, checkout_root, SddProbeRunner,
    # scope_for); specs + stale; asyncio.to_thread for scope_for + resolve; build `data` and `text` per the
    # Implementation Notes; map ValueError / OSError to is_error=True.
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.schema.operations import (' packages/ai-parrot/src/parrot/knowledge/wiki/transport.py)
# BEFORE — insert above `from parrot.knowledge.wiki.schema.operations import (` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/transport.py:68)
from parrot.knowledge.wiki.procedure.operations import (
    PROCEDURE_NEXT_DESCRIPTION,
    ProcedureNextInput,
    op_procedure_next,
    procedure_plane_available,
)

# occurrences: 1 (verified: grep -c '    "vault_ingest": _Spec(' packages/ai-parrot/src/parrot/knowledge/wiki/transport.py)
# BEFORE — insert above `    "vault_ingest": _Spec(` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/transport.py:234), inside _SPECS
    "wiki_procedure_next": _Spec("procedure", ProcedureNextInput, PROCEDURE_NEXT_DESCRIPTION),

# occurrences: 1 (verified: grep -c '    elif name == "ledger_open":' packages/ai-parrot/src/parrot/knowledge/wiki/transport.py)
# BEFORE — insert above `    elif name == "ledger_open":` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/transport.py:411), inside _operation_invoke
    elif name == "wiki_procedure_next":

        async def invoke(params: BaseModel) -> OperationResult:
            return await op_procedure_next(None, params, root=ctx.root)

# occurrences: 1 (verified: grep -c '    if ctx.vault_dir is not None:' packages/ai-parrot/src/parrot/knowledge/wiki/transport.py)
# BEFORE — insert above `    if ctx.vault_dir is not None:` (verified: packages/ai-parrot/src/parrot/knowledge/wiki/transport.py:498), inside mounted_operation_names
    if procedure_plane_available(ctx.root):
        names += [name for name, spec in _SPECS.items() if spec.mount == "procedure"]
```
**Why**: same three touch points every other operation has. The mount gate sits right after the
schema gate, so the framework transport (below) appends its tool in the same relative position.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/procedure.py` (CREATE)
```python
"""Procedure plane tool (FEAT-891): the framework wrapper of ``wiki_procedure_next``."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from parrot.knowledge.wiki.procedure.operations import (
    PROCEDURE_NEXT_DESCRIPTION,
    ProcedureNextInput,
    op_procedure_next,
    procedure_plane_available,
)
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import AbstractTool, ToolResult


class WikiProcedureNextTool(AbstractTool):
    """Deterministic next step in the repository's procedure graph."""

    name = "wiki_procedure_next"
    description = PROCEDURE_NEXT_DESCRIPTION
    args_schema = ProcedureNextInput

    def __init__(self, root: Path) -> None:
        super().__init__(name=self.name, description=self.description)
        self._root = root

    async def _execute(self, feature: Optional[str] = None, task: Optional[str] = None) -> ToolResult:
        """Resolve the next valid step(s) with local probes only."""
        result = await op_procedure_next(None, ProcedureNextInput(feature=feature, task=task), root=self._root)
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        return ToolResult(result=result.data if result.data is not None else result.text)


def create_procedure_tools(store: BaseWikiStore, root: Optional[Path], config: WikiProjectConfig) -> list[AbstractTool]:
    """[WikiProcedureNextTool] when <shared-root>/.parrot/procedure/procedures.json exists, else []."""
    if root is None or not procedure_plane_available(root):
        return []
    return [WikiProcedureNextTool(root)]
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        tools = tools + create_schema_tools(read_store, root, config, context.schema_service)' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:387), at function-body indentation
    # FEAT-891: procedure-plane tool; [] when no plane has been built.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot_tools.wiki.procedure import create_procedure_tools

        tools = tools + create_procedure_tools(read_store, root, config)
```

### `parrot_tools` exports (MODIFY)
```python
# packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py
# occurrences: 1 (verified: grep -c '"create_schema_tools": "parrot_tools.wiki.schema",' packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py — line 32)
# AFTER — insert below it, same indentation:
    "WikiProcedureNextTool": "parrot_tools.wiki.procedure",
    "create_procedure_tools": "parrot_tools.wiki.procedure",

# packages/ai-parrot-tools/src/parrot_tools/__init__.py
# occurrences: 1 (verified: grep -c '"wiki_schema_sources": "parrot_tools.wiki.schema.WikiSchemaSourcesTool",' packages/ai-parrot-tools/src/parrot_tools/__init__.py — line 141)
# AFTER — insert below it, same indentation:
    "wiki_procedure_next": "parrot_tools.wiki.procedure.WikiProcedureNextTool",
```
**Why**: the schema tools are listed in both tables; a tool missing from them is invisible to the
lazy registries. If either table is sorted or has a test pinning its keys, follow that order.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py` (CREATE)
```python
"""Tests for the `wiki_procedure_next` MCP tool on both transports (FEAT-891)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.procedure.operations import (
    PROCEDURE_NEXT_DESCRIPTION,
    ProcedureNextInput,
    op_procedure_next,
    procedure_plane_available,
)
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.transport import build_operation_descriptors


def _project(root: Path, *, with_plane: bool) -> None:
    """A git-backed wiki project; with_plane also writes sdd/procedures/x.yaml and builds the plane.
    Copy the project/store setup of tests/knowledge/wiki/schema/test_mcp_mount.py (:28-:41)."""
    # FILL IN


def test_no_plane_no_tool(tmp_path: Path) -> None:
    """Without a built plane neither transport lists the tool."""
    # FILL IN: procedure_plane_available(tmp_path) is False; "wiki_procedure_next" not in server.tools;
    # not in {d.name for d in build_operation_descriptors(server.wiki_bundle)}.


def test_mcp_tool_both_transports(tmp_path: Path) -> None:
    """With a plane, both transports list the tool with the same description and schema, and it answers."""
    # FILL IN: framework: server.tools["wiki_procedure_next"] (description == PROCEDURE_NEXT_DESCRIPTION,
    # args_schema is ProcedureNextInput); SDK: the descriptor of the same name, mount == "procedure";
    # await descriptor.invoke(ProcedureNextInput()) -> not is_error, data has "next" and "mandatory".


async def test_operation_without_plane_is_not_an_error(tmp_path: Path) -> None:
    """op_procedure_next answers with a one-line message when no plane exists."""
    result = await op_procedure_next(None, ProcedureNextInput(), root=tmp_path)
    assert not result.is_error and "parrot sdd procedure build" in result.text
```

### FILL IN checklist
- [ ] `operations.py::op_procedure_next` — bounded by "Operation" and "Payload"
- [ ] `test_mcp_tool.py` — `_project` and two test bodies
- [ ] Run `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_manifest_golden.py -q` (acceptance): it must pass with **no** golden regenerated

---

## Acceptance Criteria

- [ ] `wiki_procedure_next` is listed by the framework and the SDK transports when a plane exists, with identical description and input schema.
- [ ] Neither transport lists it when no plane exists; the MCP manifest goldens are unchanged.
- [ ] The operation uses local probes only and returns a trimmed payload (no spec bodies).
- [ ] `transport.py` imports nothing from `parrot_tools`.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5640 and TASK-5641 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5649 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
