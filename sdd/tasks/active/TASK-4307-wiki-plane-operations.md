# TASK-4307: Structural, decisions and schema plane operations modules

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4306
**Assigned-to**: unassigned

---

## Context

Spec §3 M3. The three planes' tool classes hold their business logic in `execute()`; extract `structural/operations.py`, `decisions/operations.py`, `schema/operations.py` returning `OperationResult`.

---

## Scope

- Create the three operations modules with one op per tool (symbol lookup/outline/blast; decisions for-symbol/why/generate; schema lookup/search/neighbors/sources) and their input models.
- Make each plane `tools.py` delegate and import helpers from `wiki.operations`.
- Tests: parity per op on fixtures already used by the plane tests.

**NOT in scope**: Moving wrappers to parrot_tools (TASK-4310).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/operations.py` | CREATE | structural ops |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py` | CREATE | decision ops |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/operations.py` | CREATE | schema ops |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | MODIFY | delegate |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` | MODIFY | delegate |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` | MODIFY | delegate |
| `packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py` | CREATE | parity tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.wiki.operations import OperationResult, _scoped_store, _unknown_namespace_error  # TASK-4306
from parrot.knowledge.wiki.structural.service import StructuralService  # structural/toolkit.py:21
```

### Existing Signatures to Use
```python
# structural/tools.py: inputs :51/:62/:71; WikiSymbolLookupTool :106; WikiCodeOutlineTool :146; WikiBlastRadiusTool :181; create_structural_tools :226
# decisions/tools.py: inputs :40/:50/:60; _dossier_result :66; _error_result :95; tools :100/:140/:178; create_decision_tools :210
# schema/tools.py: inputs :17/:26/:33/:40; _SchemaTool :44; tools :68/:92/:104/:116; create_schema_tools :128
```

### Does NOT Exist
- ~~the three `operations.py` modules (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/operations.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/operations.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py#WikiSymbolLookupTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py#WikiDecisionWhyTool",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py#WikiSchemaLookupTool"
  ]
}
```

---

## Implementation Notes

Keep structural `read_repair` behaviour and decision budgets identical. Input models move with the ops (schemas must stay byte-identical for golden manifests).

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Lift each execute body into an op — *why*: G4.
2. Delegate in the tool classes — *why*: no behaviour change yet.
3. Parity tests — *why*: prove it.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/operations.py` (CREATE)
```python
"""Framework-free structural plane operations (FEAT-540 M3)."""
from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.operations import OperationResult, _scoped_store, _unknown_namespace_error

# FILL IN: move SymbolLookupInput/CodeOutlineInput/BlastRadiusInput, _hit_line, _render_text from structural/tools.py


async def op_symbol_lookup(store: Any, params: "SymbolLookupInput", **context: Any) -> OperationResult:
    """wiki_symbol_lookup — lifted from WikiSymbolLookupTool.execute."""
    raise NotImplementedError  # FILL IN
# FILL IN: op_code_outline, op_blast_radius
```
**Why**: Same pattern as TASK-4306.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/operations.py` (CREATE)
```python
"""Framework-free decision-plane operations (FEAT-540 M3)."""
from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.operations import OperationResult

# FILL IN: inputs + op_decisions_for_symbol, op_decision_why, op_decision_generate; _dossier_result/_error_result return OperationResult
```
**Why**: Keep DecisionError → error-result conversion identical.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/operations.py` (CREATE)
```python
"""Framework-free schema-plane operations (FEAT-540 M3)."""
from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.operations import OperationResult

# FILL IN: inputs + op_schema_lookup, op_schema_search, op_schema_neighbors, op_schema_sources (_lookup_text moves too)
```
**Why**: Schema ops wrap SchemaPlaneService calls.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error' parrot/knowledge/wiki/structural/tools.py)
# AFTER/AT — anchor `from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error` (verified: tools.py:30)
# REPLACE with:
from parrot.knowledge.wiki.operations import _scoped_store, _unknown_namespace_error
from parrot.knowledge.wiki.structural.operations import op_blast_radius, op_code_outline, op_symbol_lookup
# FILL IN: tools' execute() delegate to the ops
```
**Why**: Helpers now come from the framework-free module.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/decisions/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:28)
# KEEP; FILL IN: import ops from decisions.operations and delegate in the three tools
```
**Why**: Thin adapters.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/schema/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:14)
# KEEP; FILL IN: import ops from schema.operations and delegate in _SchemaTool subclasses
```
**Why**: Thin adapters.

### `packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py` (CREATE)
```python
"""Plane operations parity (FEAT-540 M3)."""
import pytest


@pytest.mark.parametrize("module", ["parrot.knowledge.wiki.structural.operations", "parrot.knowledge.wiki.decisions.operations", "parrot.knowledge.wiki.schema.operations"])
def test_operations_framework_free(module: str) -> None:
    # FILL IN: probe; assert 'parrot.tools.abstract' not loaded
    ...

# FILL IN: one parity test per op family reusing existing plane fixtures
```
**Why**: Absence + parity.

### FILL IN checklist
- [ ] three ops modules
- [ ] delegation in the three tools.py
- [ ] parity tests

---

## Acceptance Criteria

- [ ] three ops modules import no `parrot.tools`
- [ ] plane tool outputs unchanged (existing structural/decisions/schema tests pass)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_plane_operations.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_structural_read_repair.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_tool_surface_golden.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4307 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
