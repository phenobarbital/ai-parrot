# TASK-4310: parrot_tools.wiki — structural, decisions, schema wrappers; lazy old paths

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4307, TASK-4309
**Assigned-to**: unassigned

---

## Context

Spec §3 M3. Structural, decision and schema tools/toolkits still subclass framework bases inside `parrot/knowledge/wiki/`.

---

## Scope

- Create `parrot_tools/wiki/{structural,decisions,schema}.py` with the tool + toolkit classes and `create_*_tools` factories moved verbatim.
- Turn the six core modules (`structural/{tools,toolkit}.py`, `decisions/{tools,toolkit}.py`, `schema/{tools,toolkit}.py`) into lazy shims.
- Check `structural/__init__.py` and `decisions/__init__.py` lazy maps still resolve (they already use PEP 562).
- Tests: new/old paths.

**NOT in scope**: MCP transport (TASK-4315).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/wiki/structural.py` | CREATE | structural tools + toolkit |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py` | CREATE | decision tools + toolkit |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/schema.py` | CREATE | schema tools + toolkit |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | MODIFY | shim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py` | MODIFY | shim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` | MODIFY | shim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` | MODIFY | shim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` | MODIFY | shim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py` | MODIFY | shim |
| `packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki_planes.py` | CREATE | import tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
```

### Existing Signatures to Use
```python
# structural/toolkit.py: class CodeStructuralToolkit(AbstractToolkit) :26; decisions/toolkit.py: class DecisionToolkit :24; schema/toolkit.py: class SchemaPlaneToolkit :11
# structural/__init__.py:57 __getattr__, :68 __dir__; decisions/__init__.py:91 __getattr__, :104 __dir__
```

### Does NOT Exist
- ~~`parrot_tools.wiki.structural|decisions|schema` (created here)~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/structural.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/wiki/schema.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki_planes.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py#CodeStructuralToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py#DecisionToolkit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py#SchemaPlaneToolkit"
  ]
}
```

---

## Implementation Notes

If the plane package `__init__` maps point at `.tools`/`.toolkit` they keep working through the shims.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Move classes verbatim — *why*: G2.
2. Shim six modules — *why*: old paths.
3. Tests.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/structural.py` (CREATE)
```python
"""Structural plane AbstractTools/Toolkit."""
from __future__ import annotations

from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit

# FILL IN: move Wiki*Tool classes, create_structural_tools, CodeStructuralToolkit verbatim
```
**Why**: Verbatim move.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/decisions.py` (CREATE)
```python
"""Decision plane AbstractTools/Toolkit."""
from __future__ import annotations

from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit

# FILL IN: move decision tools, create_decision_tools, DecisionToolkit
```
**Why**: Verbatim move.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/schema.py` (CREATE)
```python
"""Schema plane AbstractTools/Toolkit."""
from __future__ import annotations

from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit

# FILL IN: move _SchemaTool + 4 tools, create_schema_tools, SchemaPlaneToolkit
```
**Why**: Verbatim move.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/structural/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:31)
# REPLACE module body with a PEP 562 shim to parrot_tools.wiki.structural (keep plain re-exports of ops/inputs)
```
**Why**: Old path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.toolkit import AbstractToolkit' parrot/knowledge/wiki/structural/toolkit.py)
# AFTER/AT — anchor `from parrot.tools.toolkit import AbstractToolkit` (verified: toolkit.py:23)
# REPLACE module body with a PEP 562 shim: CodeStructuralToolkit -> parrot_tools.wiki.structural
```
**Why**: Old path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/decisions/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:28)
# REPLACE module body with a PEP 562 shim to parrot_tools.wiki.decisions
```
**Why**: Old path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.toolkit import AbstractToolkit' parrot/knowledge/wiki/decisions/toolkit.py)
# AFTER/AT — anchor `from parrot.tools.toolkit import AbstractToolkit` (verified: toolkit.py:21)
# REPLACE module body with a PEP 562 shim: DecisionToolkit
```
**Why**: Old path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.abstract import AbstractTool, ToolResult' parrot/knowledge/wiki/schema/tools.py)
# AFTER/AT — anchor `from parrot.tools.abstract import AbstractTool, ToolResult` (verified: tools.py:14)
# REPLACE module body with a PEP 562 shim to parrot_tools.wiki.schema
```
**Why**: Old path.

### `packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.tools.toolkit import AbstractToolkit' parrot/knowledge/wiki/schema/toolkit.py)
# AFTER/AT — anchor `from parrot.tools.toolkit import AbstractToolkit` (verified: toolkit.py:8)
# REPLACE module body with a PEP 562 shim: SchemaPlaneToolkit
```
**Why**: Old path.

### `packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki_planes.py` (CREATE)
```python
"""Plane wrappers moved to parrot_tools.wiki (FEAT-540 M3)."""
import pytest

@pytest.mark.parametrize("name", ["CodeStructuralToolkit", "DecisionToolkit", "SchemaPlaneToolkit", "create_structural_tools", "create_decision_tools", "create_schema_tools"])
def test_exported(name: str) -> None:
    import parrot_tools.wiki as w

    assert getattr(w, name)

# FILL IN: old-path identity checks + laziness probes for the six shimmed modules
```
**Why**: Compatibility + laziness.

### FILL IN checklist
- [ ] three verbatim moves
- [ ] six shims
- [ ] identity + laziness tests

---

## Acceptance Criteria

- [ ] plane classes importable from `parrot_tools.wiki`
- [ ] old paths resolve lazily to the same objects
- [ ] existing plane tests pass

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/wiki/test_parrot_tools_wiki_planes.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_structural_read_repair.py -q`

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
9. **Close** with `scripts/sdd/close_task.sh TASK-4310 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: native sonnet, consolidated by sdd-worker
**Date**: 2026-10-15
**Notes**: Moved the structural, decisions and schema plane tools/toolkits into parrot_tools.wiki.{structural,decisions,schema}; the six core modules are PEP 562 lazy shims. The coder audited the old modules' exports with ast and grepped importers before shimming (the lesson from TASK-4309), and added test_parrot_tools_wiki_planes.py (22 passed with the existing file). No review corrections. Verification is `partial`: the engine merge-tier sandbox cannot reach Postgres and has pre-existing reds. With GRAPHINDEX_PG_DSN on local docker-postgres-1, tests/knowledge + tests/embeddings (4294 passed in the chunk run) showed no failure absent from the clean origin/dev baseline other than TASK-4313's own two test failures, fixed in 8640f08f5 (test-only, 3 consecutive green runs); ai-parrot-tools wiki tests 22 passed.

**Deviations from spec**: none
