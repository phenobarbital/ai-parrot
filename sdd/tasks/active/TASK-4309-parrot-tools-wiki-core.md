# TASK-4309: parrot_tools.wiki — core, ledger, bulk tools + LLMWikiToolkit; lazy old paths

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4308
**Assigned-to**: unassigned

---

## Context

Spec §3 M3. Every `AbstractTool`/`AbstractToolkit` wiki wrapper moves to `ai-parrot-tools`; old modules become lazy compatibility exports so importing them no longer loads `AbstractTool`.

---

## Scope

- Create `parrot_tools/wiki/{__init__,tools,ledger,bulk,toolkit}.py`: move core tools, ledger tools, bulk/sync tools, `VaultIngestTool`, `create_wiki_tools`, `create_bulk_tools`, `LLMWikiToolkit` verbatim.
- `parrot_tools/wiki/__init__.py`: lazy export map covering these AND the plane modules TASK-4310 creates (structural/decisions/schema).
- Turn `wiki/tools.py` and `wiki/toolkit.py` into PEP 562 lazy shims (operation names stay plain imports from `wiki.operations`).
- Repoint `parrot_tools/business_automation/memory.py:31,110` to `parrot_tools.wiki`.
- Tests: new imports work; importing the old modules does not load `parrot.tools.abstract`; requesting a class does.

**NOT in scope**: Plane wrappers (TASK-4310); transport selection (TASK-4315); source backend selection inside LLMWikiToolkit (TASK-4326).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` | CREATE | lazy export map |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` | CREATE | core tools + create_wiki_tools |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/ledger.py` | CREATE | ledger tools |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/bulk.py` | CREATE | bulk/sync tools + create_bulk_tools |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` | CREATE | LLMWikiToolkit |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | lazy shim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | lazy shim |
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` | MODIFY | repoint import |
| `packages/ai-parrot-tools/tests/wiki/__init__.py` | CREATE | test package |
| `packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki.py` | CREATE | import tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, ToolResult  # wiki/tools.py:29
from parrot.tools.toolkit import AbstractToolkit  # wiki/toolkit.py:33
from parrot.tools.server_params import ServerParam  # wiki/toolkit.py:32
from parrot.knowledge.wiki.operations import OperationResult  # TASK-4306
```

### Existing Signatures to Use
```python
# wiki/toolkit.py: _is_federated :36; class LLMWikiToolkit(AbstractToolkit) :43
# wiki/tools.py: create_bulk_tools :1211; create_wiki_tools :1221; tool classes listed in TASK-4306/4308
# business_automation/memory.py: TYPE_CHECKING import :31; runtime import :110
# precedent: parrot_tools/graphindex/toolkit.py:110 class GraphIndexToolkit(AbstractToolkit)
```

### Does NOT Exist
- ~~`parrot_tools.wiki` (no such package today)~~
- ~~importing `parrot_tools` from anything under `parrot/knowledge/wiki` at module level — shims import it lazily inside `__getattr__`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/ledger.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/bulk.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/wiki/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py#LLMWikiToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/tools.py#create_wiki_tools",
    "sym:packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py#GraphIndexToolkit"
  ]
}
```

---

## Implementation Notes

Internal plain consumers must never use the shims. `mcp_server.py:29` imports `create_wiki_tools` from the shim until TASK-4315 rewires it — that keeps working because the shim resolves lazily.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Move classes verbatim into parrot_tools.wiki — *why*: framework imports are the norm there (precedent GraphIndexToolkit).
2. Write the lazy export map incl. future plane modules — *why*: one public import surface.
3. Shim the old modules — *why*: old paths keep resolving without eager AbstractTool.
4. Repoint memory.py and add tests.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` (CREATE)
```python
"""Agent-facing wiki tools and toolkits (moved from parrot.knowledge.wiki — FEAT-540 M3)."""
from typing import Any

_EXPORTS: dict[str, str] = {
    "LLMWikiToolkit": "parrot_tools.wiki.toolkit",
    "create_wiki_tools": "parrot_tools.wiki.tools",
    "create_bulk_tools": "parrot_tools.wiki.bulk",
    "CodeStructuralToolkit": "parrot_tools.wiki.structural",
    "create_structural_tools": "parrot_tools.wiki.structural",
    "DecisionToolkit": "parrot_tools.wiki.decisions",
    "create_decision_tools": "parrot_tools.wiki.decisions",
    "SchemaPlaneToolkit": "parrot_tools.wiki.schema",
    "create_schema_tools": "parrot_tools.wiki.schema",
    # FILL IN: every moved tool class name -> its module
}
__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
```
**Why**: Plane entries point at modules TASK-4310 creates; lazy resolution means they are only imported on access.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py` (CREATE)
```python
"""Core wiki AbstractTools (moved from parrot.knowledge.wiki.tools)."""
from __future__ import annotations

from parrot.tools.abstract import AbstractTool, ToolResult

# FILL IN: move WikiQueryTool..WikiStandupTool, VaultIngestTool, _to_tool_result and create_wiki_tools verbatim
```
**Why**: Verbatim move; tools already delegate to ops.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/ledger.py` (CREATE)
```python
"""Ledger AbstractTools."""
from __future__ import annotations

from parrot.tools.abstract import AbstractTool, ToolResult

# FILL IN: move Ledger*Tool classes
```
**Why**: Verbatim move.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/bulk.py` (CREATE)
```python
"""Bulk/sync AbstractTools."""
from __future__ import annotations

from parrot.tools.abstract import AbstractTool, ToolResult

# FILL IN: move WikiPageHashesTool, WikiIngestBatchTool, WikiSyncPushTool, WikiSyncPullTool, create_bulk_tools
```
**Why**: Verbatim move.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` (CREATE)
```python
"""LLMWikiToolkit (moved from parrot.knowledge.wiki.toolkit)."""
from __future__ import annotations

from parrot.tools.server_params import ServerParam
from parrot.tools.toolkit import AbstractToolkit

# FILL IN: move _is_federated and LLMWikiToolkit verbatim
```
**Why**: Verbatim move.

### `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:29)
# REPLACE the module body with: re-exports of plain names from wiki.operations (eager — they are framework-free)
# plus a PEP 562 __getattr__ mapping every moved class/factory name to parrot_tools.wiki.{tools,ledger,bulk}
```
**Why**: Old path stays valid; importing it no longer loads AbstractTool.

### `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.toolkit import AbstractToolkit' parrot/knowledge/wiki/toolkit.py)
# AFTER/AT — anchor `from parrot.tools.toolkit import AbstractToolkit` (verified: toolkit.py:33)
# REPLACE the module body with a PEP 562 shim: LLMWikiToolkit / _is_federated -> parrot_tools.wiki.toolkit
```
**Why**: Same.

### `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.toolkit import LLMWikiToolkit' parrot_tools/business_automation/memory.py)
# AFTER/AT — anchor `from parrot.knowledge.wiki.toolkit import LLMWikiToolkit` (verified: memory.py:31)
# REPLACE with:
    from parrot_tools.wiki import LLMWikiToolkit
# FILL IN: same change at the runtime import (:110)
```
**Why**: Internal consumers use the new path.

### `packages/ai-parrot-tools/tests/wiki/__init__.py` (CREATE)
```python

```
**Why**: Test package marker.

### `packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki.py` (CREATE)
```python
"""parrot_tools.wiki exports and lazy old paths (FEAT-540 M3)."""


def test_new_path_exports() -> None:
    from parrot_tools.wiki import LLMWikiToolkit, create_bulk_tools, create_wiki_tools

    assert LLMWikiToolkit and create_wiki_tools and create_bulk_tools


def test_old_path_same_object() -> None:
    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit as old
    from parrot_tools.wiki import LLMWikiToolkit as new

    assert old is new


def test_old_module_import_is_lazy() -> None:
    # FILL IN: probe 'parrot.knowledge.wiki.tools'; assert 'parrot.tools.abstract' not loaded
    ...
```
**Why**: Proves compatibility and laziness.

### FILL IN checklist
- [ ] verbatim moves into five parrot_tools.wiki modules
- [ ] two shims
- [ ] memory.py runtime import
- [ ] laziness probe

---

## Acceptance Criteria

- [ ] `from parrot_tools.wiki import LLMWikiToolkit, create_wiki_tools` works
- [ ] old paths resolve to the same objects lazily
- [ ] importing `parrot.knowledge.wiki.tools` loads no `parrot.tools.abstract`
- [ ] existing wiki tool tests pass

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/business_automation/test_memory.py -q`

---

## Test Specification

```python
# see block
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4309 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: codex gpt-5.6-terra, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: Moved the wiki AbstractTool wrappers and LLMWikiToolkit into packages/ai-parrot-tools (parrot_tools.wiki: tools/ledger/bulk/toolkit) with lazy compatibility shims at parrot.knowledge.wiki.{tools,toolkit}; new test in packages/ai-parrot-tools/tests/wiki (3 passed). Review fix 1fb7eef13: the tools shim dropped ~52 re-exports that tests and remote_cli import, so two test modules failed at collection and aborted the whole run; restored. feedback coder-feedback:921a90cad89e852b174ca715 (compat-shim-drops-existing-reexports); review recorded. NOTE for the owner: running ai-parrot/tests and ai-parrot-tools/tests in ONE pytest invocation collides on the tests/ package name; run them separately. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings (4293 passed) show no failure absent from the clean origin/dev baseline.

**Deviations from spec**: none
