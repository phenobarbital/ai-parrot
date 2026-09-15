# TASK-3262: Move wiki AbstractTools to `parrot_tools.wiki`

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3261
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, design brief D6. After TASK-3260/3261 every wiki, ledger, vault and structural
tool is a thin `AbstractTool` delegate over framework-free handlers in
`parrot.knowledge.wiki.operations` / `parrot.knowledge.wiki.structural.operations`. This task
physically moves those delegates out of the graph tree into a NEW package
`packages/ai-parrot-tools/src/parrot_tools/wiki/` (precedent: `parrot_tools/graphindex/`), deletes
`wiki/tools.py` and `wiki/structural/tools.py`, and repoints every consumer — including
`wiki/mcp_server.py`, minimally, so the MCP server keeps working until TASK-3265 adds the
dual transport (spec §7: "Sequence Module 3 before Module 5, or the MCP server breaks").

`LLMWikiToolkit` / `CodeStructuralToolkit` do NOT move here — TASK-3263.

---

## Scope

- Create `parrot_tools/wiki/` with `__init__.py` (PEP 562 lazy exports), `_adapter.py`,
  `tools.py` (7 wiki + 5 ledger tools + `create_wiki_tools`), `structural_tools.py`
  (3 structural tools + `create_structural_tools`).
- `git rm` `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` and
  `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py`.
- `structural/__init__.py`: stop importing `structural.tools`; keep the tool names +
  `create_structural_tools` resolvable via a lazy PEP 562 alias to `parrot_tools.wiki.structural_tools`
  (they are in `__all__` today — "No breaking change to any documented public import path").
  `CodeStructuralToolkit` re-export stays eager until TASK-3263.
- `wiki/mcp_server.py`: drop module-level `create_wiki_tools` import (:28); import
  `create_wiki_tools`, `create_structural_tools`, `VaultIngestTool` from `parrot_tools.wiki` lazily
  inside `create_wiki_mcp_server`, under the existing `redirect_stdout` discipline.
- Repoint tests (see Files table). `git mv` `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py`
  → `packages/ai-parrot-tools/tests/wiki/test_wiki_tools.py`.
- Add `packages/ai-parrot-tools/tests/wiki/test_schema_golden.py` (`test_wiki_tools_produce_same_schemas`).

**NOT in scope**:
- `LLMWikiToolkit`, `CodeStructuralToolkit`, `wiki/__init__.py` lazy map — TASK-3263.
- MCP SDK transport / `_open_mcp_stores` refactor — TASK-3265.
- Changing any tool name, description, input model, or handler logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` | CREATE | Lazy exports |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/_adapter.py` | CREATE | `to_tool_result()` |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | CREATE | 12 tools + `create_wiki_tools` (from core `wiki/tools.py`) |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/structural_tools.py` | CREATE | 3 tools + `create_structural_tools` (from core `structural/tools.py`) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | DELETE | `git rm` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | DELETE | `git rm` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py` | MODIFY | Lazy aliases for moved names |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | Lazy `parrot_tools.wiki` imports |
| `packages/ai-parrot-tools/tests/wiki/__init__.py` | CREATE | empty |
| `packages/ai-parrot-tools/tests/wiki/test_wiki_tools.py` | MOVE+MODIFY | `git mv` from `packages/ai-parrot/tests/knowledge/wiki/`; repoint imports |
| `packages/ai-parrot-tools/tests/wiki/test_schema_golden.py` | CREATE | golden compare |
| `packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py` | MODIFY | repoint `VaultIngestTool` import (stays in place — see Notes) |
| `tests/knowledge/wiki/test_ledger_tools.py` | MODIFY | repoint :6 import |
| `tests/knowledge/wiki/test_mcp_server_ledger.py` | MODIFY | repoint :8 import |
| `tests/knowledge/wiki/structural/test_tools.py` | MODIFY | repoint :13-17 imports |
| `tests/knowledge/wiki/test_structural_e2e.py` | MODIFY | repoint :322 lazy import |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `63cc2198e` on 2026-09-15, **before** TASK-3260/3261. Re-verify: those
> tasks rewrote `wiki/tools.py` and `structural/tools.py` into delegates — use the post-3261 file
> content as the source you move.

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, ToolResult                     # tools/abstract.py:281, :250
from parrot.knowledge.wiki import operations as ops                            # TASK-3260
from parrot.knowledge.wiki.operations import OperationResult                   # TASK-3260
from parrot.knowledge.wiki.operations import (WikiQueryInput, WikiPageInput, WikiRelatedInput, WikiRememberInput,
    WikiNoteInput, WikiStatusInput, VaultIngestInput, LedgerOpenInput, LedgerReadyInput, LedgerClaimInput,
    LedgerCloseInput, LedgerContextInput)                                      # TASK-3260
from parrot.knowledge.wiki.structural import operations as sops                # TASK-3261
from parrot.knowledge.wiki.structural.operations import (SymbolLookupInput, CodeOutlineInput, BlastRadiusInput,
    ServiceFactory, make_service_factory)                                     # TASK-3261
from parrot.knowledge.wiki.project import WikiProjectConfig                    # project.py:379
from parrot.knowledge.wiki.store import BaseWikiStore                          # store.py:525
from parrot.knowledge.wiki.symbols import SymbolKind                           # symbols.py:31
from parrot.knowledge.wiki.ledger.service import LedgerService                 # ledger/service.py:96 (TYPE_CHECKING)
from parrot.mcp.adapter import MCPToolAdapter                                  # mcp/adapter.py:8 (golden test only)
```

### Existing Signatures to Use
```python
# Public tool classes to reproduce (class name / `name` / __init__), from core wiki/tools.py:
WikiQueryTool(store)                          # "wiki_query"      _execute(question, budget_tokens=DEFAULT_BUDGET_TOKENS, namespace=None, include_symbols=False) -> str
WikiPageTool(store)                           # "wiki_page"       _execute(page_id, namespace=None)
WikiRelatedTool(store)                        # "wiki_related"    _execute(page_id, namespace=None)
WikiRememberTool(store, storage_dir=None)     # "wiki_remember"   _execute(fact, category="note", title=None, link_page_id=None, rel="references", derived_from=None, about=None)
WikiNoteTool(store, storage_dir=None)         # "wiki_note"       _execute(page_id, text)
WikiStatusTool(store)                         # "wiki_status"     _execute()
VaultIngestTool(store, root, config)          # "vault_ingest"    _execute(vault_path=None, force=False, **kwargs)
LedgerOpenTool(ledger_service)                # "ledger_open"     _execute(title, body, kind="bug", severity="minor", discovered_from="", about=None)
LedgerReadyTool(ledger_service)               # "ledger_ready"    _execute(kind=None)
LedgerClaimTool(ledger_service)               # "ledger_claim"    _execute(issue_id)
LedgerCloseTool(ledger_service)               # "ledger_close"    _execute(issue_id, reason)
LedgerContextTool(ledger_service)             # "ledger_context"  _execute(file_paths, max_tokens=3000)
def create_wiki_tools(store, root=None, config=None, ledger_service=None) -> list[AbstractTool]   # core wiki/tools.py:741
# from core structural/tools.py:
WikiSymbolLookupTool(service_factory)  # "wiki_symbol_lookup"  :105
WikiCodeOutlineTool(service_factory)   # "wiki_code_outline"   :145
WikiBlastRadiusTool(service_factory)   # "wiki_blast_radius"   :180
def create_structural_tools(store: BaseWikiStore, root: Path, config: WikiProjectConfig) -> list[AbstractTool]  # :225

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit   # line 19 — keep (TASK-3263)
# lines 20-28 (post-3261): import from structural.operations + structural.tools; __all__ lines ~30-45

# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py (293 lines)
"""...Wires the six wiki `AbstractTool` wrappers (`parrot.knowledge.wiki.tools`)..."""        # docstring lines 1-8
from parrot.knowledge.wiki.tools import create_wiki_tools                                     # line 28
def create_wiki_mcp_server(root: Path) -> StdioMCPServer:                                     # line 91
    with contextlib.redirect_stdout(sys.stderr):                                              # line 106
        from parrot.mcp.local_server import StdioMCPServer                                    # line 107
    tools = create_wiki_tools(read_store, root=root, config=config, ledger_service=ledger_service)  # line 202
    from parrot.knowledge.wiki.structural import create_structural_tools                      # line 207
    tools = tools + create_structural_tools(read_store, root, config)                         # line 209
            from parrot.knowledge.wiki.tools import VaultIngestTool                           # line 233
            from parrot.tools.obsidian import ObsidianToolkit                                 # line 234

# packages/ai-parrot-tools/src/parrot_tools/graphindex/__init__.py — package precedent (eager, 9 lines)
# packages/ai-parrot-tools/pyproject.toml:120-122 — [tool.setuptools.packages.find] include = ["parrot_tools*"] (auto-includes wiki/)
# packages/ai-parrot-tools/tests/__init__.py exists; subpackages have __init__.py (business_automation/, graphindex/)

# Tests importing moved symbols (verified grep):
# packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py:4-11, :317 (from parrot.knowledge.wiki.tools import ...),
#   patch strings :113, :150 (post-3260: "parrot.knowledge.wiki.operations.WikiBookkeeper.log_operation" — unchanged)
# packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py:10 (VaultIngestTool), :11 imports
#   `from tests.interfaces.obsidian.conftest import fixture_vault` (packages/ai-parrot/tests/interfaces/obsidian/conftest.py)
# tests/knowledge/wiki/test_ledger_tools.py:6-14 (WikiRememberTool + 5 Ledger*Tool)
# tests/knowledge/wiki/test_mcp_server_ledger.py:8 (create_wiki_tools)
# tests/knowledge/wiki/structural/test_tools.py:13-17 (CodeStructuralToolkit, create_structural_tools from
#   parrot.knowledge.wiki.structural; WikiQueryTool from parrot.knowledge.wiki.tools)
# tests/knowledge/wiki/test_structural_e2e.py:322 (from parrot.knowledge.wiki.structural.tools import create_structural_tools)
```

### Does NOT Exist
- ~~`parrot_tools.wiki`~~ — created here (`ls packages/ai-parrot-tools/src/parrot_tools | grep wiki` → nothing today).
- ~~`packages/ai-parrot-tools/tests/wiki/`~~ — created here.
- ~~`packages/ai-parrot-tools/tests/conftest.py`~~ — no conftest at that root.
- ~~`parrot_tools/obsidian`~~ — `ObsidianToolkit` is imported as `parrot.tools.obsidian` (mcp_server.py:234); leave as is.
- ~~A `sys.meta_path` redirect for `parrot.knowledge.wiki.tools`~~ — FEAT-541; this task just deletes the module.
- ~~`tests/tools/`-style ignore for ai-parrot-tools~~ — CI "core tests" run root `tests/` with `--ignore=tests/tools` (ci.yml:138); ai-parrot-tools tests are a separate tree.

---

## Implementation Notes

### Key Constraints
- The moved classes keep class name, class docstring, `name`, `description`, `args_schema`,
  `__init__` signature and `_execute` signature — only their module changes.
- `parrot_tools/wiki/__init__.py` must be lazy (PEP 562), so `import parrot_tools.wiki` does not
  import `parrot.tools.abstract` until a tool is accessed (mirrors `parrot/knowledge/wiki/__init__.py:44-110`).
- `mcp_server.py` stays importable without `parrot_tools` (imports only inside the function).
- `test_vault_ingest_tool.py` stays in `packages/ai-parrot/tests/knowledge/wiki/` (design brief D6
  said to move it): it imports `tests.interfaces.obsidian.conftest`, a fixture module that only
  exists in the `packages/ai-parrot/tests` tree — moving it would break collection. Only its import
  is repointed; record this in the Completion Note.
- Structural alias: the graph tree may reference `parrot_tools` only as a **string** in a PEP 562
  map — never an `import` statement (TASK-3268's AST scan).

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/graphindex/` — package placement precedent.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py:117-143` — `_LAZY_ATTRS` + `__getattr__` precedent.

---

## Implementation Blueprint

### Steps (in order)
1. `git mv` core `wiki/tools.py` → `parrot_tools/wiki/tools.py` and core `structural/tools.py` → `parrot_tools/wiki/structural_tools.py` — *why*: preserves history of the delegates.
2. Rewrite imports in the moved files (blocks B, C); remove their local `_to_tool_result` in favour of `_adapter.to_tool_result` — *why*: one conversion helper.
3. Create `__init__.py` and `_adapter.py` (blocks A, D) — *why*: lazy public surface.
4. Edit `structural/__init__.py` (block E) and `mcp_server.py` (block F) — *why*: nothing in core may import the deleted modules.
5. Repoint tests; `git mv` `test_wiki_tools.py`; add golden test — *why*: CI trees must collect.
6. `grep -rn "knowledge.wiki.tools\b\|structural.tools" packages/*/src tests packages/*/tests --include=*.py` returns nothing — *why*: no dangling import.
7. Run the ACs.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` (CREATE) — block A
```python
"""Agent-facing wiki tools (FEAT-540 Module 3).

``AbstractTool`` wrappers over the framework-free handlers in
``parrot.knowledge.wiki.operations`` and ``parrot.knowledge.wiki.structural.operations``.
Exports resolve lazily so importing the package stays cheap.
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORT_MODULES: dict[str, str] = {
    "WikiQueryTool": "parrot_tools.wiki.tools",
    "WikiPageTool": "parrot_tools.wiki.tools",
    "WikiRelatedTool": "parrot_tools.wiki.tools",
    "WikiRememberTool": "parrot_tools.wiki.tools",
    "WikiNoteTool": "parrot_tools.wiki.tools",
    "WikiStatusTool": "parrot_tools.wiki.tools",
    "VaultIngestTool": "parrot_tools.wiki.tools",
    "LedgerOpenTool": "parrot_tools.wiki.tools",
    "LedgerReadyTool": "parrot_tools.wiki.tools",
    "LedgerClaimTool": "parrot_tools.wiki.tools",
    "LedgerCloseTool": "parrot_tools.wiki.tools",
    "LedgerContextTool": "parrot_tools.wiki.tools",
    "create_wiki_tools": "parrot_tools.wiki.tools",
    "WikiSymbolLookupTool": "parrot_tools.wiki.structural_tools",
    "WikiCodeOutlineTool": "parrot_tools.wiki.structural_tools",
    "WikiBlastRadiusTool": "parrot_tools.wiki.structural_tools",
    "create_structural_tools": "parrot_tools.wiki.structural_tools",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    """Resolve a public export on first access (PEP 562).

    Raises:
        AttributeError: If ``name`` is not a public export.
    """
    module_path = _EXPORT_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List public exports for dir()/completion."""
    return sorted(__all__)
```
**Why**: TASK-3263 appends `LLMWikiToolkit` / `CodeStructuralToolkit` to this map.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/_adapter.py` (CREATE) — block D
```python
"""OperationResult → ToolResult conversion shared by the wiki tool wrappers."""
from __future__ import annotations

from parrot.knowledge.wiki.operations import OperationResult
from parrot.tools.abstract import ToolResult


def to_tool_result(outcome: OperationResult | str) -> ToolResult | str:
    """Convert a handler outcome for ``AbstractTool._execute``.

    Args:
        outcome: A handler's return value; ``wiki_query`` returns plain text.

    Returns:
        The text unchanged, or a ``ToolResult`` carrying the same fields.
    """
    if isinstance(outcome, str):
        return outcome
    return ToolResult(**outcome.model_dump())
```

### `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` (MOVED, MODIFY) — block B: import header
```python
# After `git mv`, REPLACE the module docstring + import block (everything above the first class) with:
"""Wiki + ledger + vault AbstractTool wrappers (moved from parrot.knowledge.wiki.tools, FEAT-540).

Thin delegates over ``parrot.knowledge.wiki.operations``; names, descriptions and
input schemas are byte-identical to the pre-move tools (golden-tested).
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union

from parrot.knowledge.wiki import operations as ops
from parrot.knowledge.wiki.operations import (
    LedgerClaimInput, LedgerCloseInput, LedgerContextInput, LedgerOpenInput, LedgerReadyInput,
    VaultIngestInput, WikiNoteInput, WikiPageInput, WikiQueryInput, WikiRelatedInput,
    WikiRememberInput, WikiStatusInput,
)
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot_tools.wiki._adapter import to_tool_result

if TYPE_CHECKING:
    from parrot.knowledge.wiki.ledger.service import LedgerService

# In every `_execute`, replace `_to_tool_result(` with `to_tool_result(`; delete the local
# `_to_tool_result` helper and the helper/`_NAMESPACE_DESC` re-export lines added by TASK-3260.
# Class bodies and create_wiki_tools stay as TASK-3260 left them.
# FILL IN: drop any now-unused import flagged by `ruff check` — bounded by ruff clean.
```

### `packages/ai-parrot-tools/src/parrot_tools/wiki/structural_tools.py` (MOVED, MODIFY) — block C
```python
# After `git mv`, REPLACE the module docstring + import block with:
"""Structural symbol-plane AbstractTool wrappers (moved from parrot.knowledge.wiki.structural.tools, FEAT-540)."""
from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.knowledge.wiki.structural import operations as sops
from parrot.knowledge.wiki.structural.operations import (
    BlastRadiusInput,
    CodeOutlineInput,
    ServiceFactory,
    SymbolLookupInput,
)
from parrot.knowledge.wiki.symbols import SymbolKind
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot_tools.wiki._adapter import to_tool_result

# Replace `_to_tool_result(` → `to_tool_result(` and delete the local helper. Keep the three
# classes and create_structural_tools(store, root, config) exactly as TASK-3261 left them.
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py` (MODIFY) — block E
```python
# occurrences: 1 (verified post-3261: grep -c '^from parrot.knowledge.wiki.structural.tools import ($' packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py)
# DELETE that `from parrot.knowledge.wiki.structural.tools import (...)` block; APPEND after __all__:

#: Names that moved to ``parrot_tools.wiki.structural_tools`` (FEAT-540). Kept resolvable
#: lazily — a string reference, so the graph tree gains no import of parrot_tools.
_MOVED_TO_PARROT_TOOLS: dict[str, str] = {
    "WikiSymbolLookupTool": "parrot_tools.wiki.structural_tools",
    "WikiCodeOutlineTool": "parrot_tools.wiki.structural_tools",
    "WikiBlastRadiusTool": "parrot_tools.wiki.structural_tools",
    "create_structural_tools": "parrot_tools.wiki.structural_tools",
}


def __getattr__(name: str):
    """Resolve names relocated to ``parrot_tools.wiki`` on first access (PEP 562).

    Raises:
        AttributeError: For unknown names, or when ai-parrot-tools is not installed.
    """
    module_path = _MOVED_TO_PARROT_TOOLS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise AttributeError(f"{name} requires ai-parrot-tools ({module_path}): {exc}") from exc
    return getattr(module, name)
# Keep all four names in __all__ (documented surface).
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY) — block F
```python
# occurrences: 1 (verified: grep -c '^from parrot.knowledge.wiki.tools import create_wiki_tools$' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# DELETE line 28. Then:

# occurrences: 1 (verified: grep -c '        from parrot.mcp.local_server import StdioMCPServer' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# AFTER — insert below `        from parrot.mcp.server_base import LocalServerConfig` (inside the redirect_stdout block, line 108):
        from parrot_tools.wiki.structural_tools import create_structural_tools
        from parrot_tools.wiki.tools import create_wiki_tools

# occurrences: 1 (verified: grep -c '    from parrot.knowledge.wiki.structural import create_structural_tools' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# DELETE line 207 (now imported above).

# occurrences: 1 (verified: grep -c '            from parrot.knowledge.wiki.tools import VaultIngestTool' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# REPLACE line 233 with:
            from parrot_tools.wiki.tools import VaultIngestTool

# Docstring line 3: `(parrot.knowledge.wiki.tools)` → `(parrot_tools.wiki)`.
```
**Why**: minimal repoint — TASK-3265 restructures this function; here it only must keep working.

### Test repoints
```python
# tests/knowledge/wiki/test_ledger_tools.py:6         from parrot.knowledge.wiki.tools import (  →  from parrot_tools.wiki.tools import (
# tests/knowledge/wiki/test_mcp_server_ledger.py:8    from parrot.knowledge.wiki.tools import create_wiki_tools  →  from parrot_tools.wiki.tools import create_wiki_tools
# tests/knowledge/wiki/structural/test_tools.py:13-17 → from parrot.knowledge.wiki.structural import CodeStructuralToolkit
#                                                      from parrot_tools.wiki.structural_tools import create_structural_tools
#                                                      from parrot_tools.wiki.tools import WikiQueryTool
# tests/knowledge/wiki/test_structural_e2e.py:322     → from parrot_tools.wiki.structural_tools import create_structural_tools
# packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py:10 → from parrot_tools.wiki.tools import VaultIngestTool
# packages/ai-parrot-tools/tests/wiki/test_wiki_tools.py (after git mv): :4 and :317 → parrot_tools.wiki.tools;
#   input-model import at :317-321 → parrot.knowledge.wiki.operations (models are not re-exported by parrot_tools)
# FILL IN: any further hit from Step 6's grep — bounded by "no dangling import".
```

### FILL IN checklist
- [ ] Unused imports in the two moved modules removed (ruff).
- [ ] All test references repointed; Step 6 grep empty.
- [ ] Golden test body compares all 15 tools.

---

## Acceptance Criteria

- [ ] `from parrot_tools.wiki import create_wiki_tools, create_structural_tools, VaultIngestTool, LedgerOpenTool` resolves.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` and `.../structural/tools.py` no longer exist.
- [ ] No `import`/`from` statement under `packages/ai-parrot/src/parrot/knowledge/wiki/` references `parrot.tools` except `toolkit.py`, `structural/toolkit.py` (TASK-3263) and the lazy ones inside `mcp_server.py`/`claude_code/cli.py` (out of scope).
- [ ] `from parrot.knowledge.wiki.structural import create_structural_tools` still resolves (lazy alias).
- [ ] Golden: names, descriptions, MCP input schemas of the 15 relocated tools equal `packages/ai-parrot/tests/knowledge/wiki/fixtures/wiki_tool_schemas.golden.json`.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot-tools/tests/wiki/ -v` passes.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest tests/knowledge/wiki/test_ledger_tools.py tests/knowledge/wiki/test_mcp_server_ledger.py tests/knowledge/wiki/structural/ tests/knowledge/wiki/test_structural_e2e.py tests/knowledge/wiki/test_mcp_server_structural.py tests/knowledge/wiki/test_cli_symbols.py -v` passes.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot/tests/knowledge/wiki/test_vault_ingest_tool.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py -v` passes.
- [ ] `ruff check` clean on all created/modified source files.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/wiki/test_schema_golden.py
import contextlib
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.wiki.project import WikiProjectConfig

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "ai-parrot" / "tests" / "knowledge" / "wiki" / "fixtures" / "wiki_tool_schemas.golden.json"
)


def _definitions(tmp_path):
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.mcp.adapter import MCPToolAdapter
    from parrot_tools.wiki import VaultIngestTool, create_structural_tools, create_wiki_tools

    store = AsyncMock()
    tools = create_wiki_tools(store, ledger_service=MagicMock())
    tools.append(VaultIngestTool(store, root=tmp_path, config=WikiProjectConfig()))
    tools += create_structural_tools(store, tmp_path, WikiProjectConfig())
    return sorted((MCPToolAdapter(t).to_mcp_tool_definition() for t in tools), key=lambda d: d["name"])


def test_wiki_tools_produce_same_schemas(tmp_path):
    golden = json.loads(GOLDEN.read_text())
    assert len(golden) == 15
    # FILL IN: assert json.dumps(_definitions(tmp_path), sort_keys=True) == json.dumps(golden, sort_keys=True) — bounded by spec AC "byte-identical names and input schemas"


def test_package_import_is_lazy():
    import subprocess

    code = "import sys, parrot_tools.wiki; print('parrot.tools.abstract' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "False"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 3, §7 "Both old and new tool import paths", "mcp_server.py:27 depends on what Module 3 moves") and design brief D6.
2. **Check dependencies** — TASK-3260 and TASK-3261 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** against the post-3261 files; update line numbers first if drifted.
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`.
6. Test with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (shared venv is editable against the main checkout). CI runs repo-root `tests/` — the root-tree ACs are mandatory.
7. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note (record that `test_vault_ingest_tool.py` stayed in place and why).

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
