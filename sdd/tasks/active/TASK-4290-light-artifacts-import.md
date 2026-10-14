# TASK-4290: Defer the adapters.structured import in artifacts.py

**Feature**: FEAT-668 — A2UI Lazy Imports
**Spec**: `sdd/specs/a2ui-lazy-imports.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. `outputs/a2ui/artifacts.py:29` imports `adapters.structured`
at module level. `structured.py:45` imports `builders`, and `builders.py:32,36`
import `catalog.parrot` / `catalog.viz_core` for their registration side
effects. So every importer of `artifacts` (`bots/data.py:33`,
`bots/database/agent.py:18`, `tools/infographic_recipes/runner.py:67`) registers
the whole A2UI catalog at import time. This is the chain that hits the CLI and
the MCP data agents.

---

## Scope

- Move `from parrot.outputs.a2ui.adapters.structured import SCHEMA_VERSION, root_component` from module level into `attach_structured_artifact()`, inside the `if envelope is not None:` branch where the names are used.

**NOT in scope**: `bots/data.py`, `bots/database/agent.py` (they stay unchanged and become light automatically), `builders.py` (its side-effect imports are legitimate), and the regression tests (TASK-4293).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` | MODIFY | function-local import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.adapters.structured import SCHEMA_VERSION, root_component  # verified: artifacts.py:29
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py
from __future__ import annotations                                   # line 18
def attach_structured_artifact(response: Any, output_mode: Any) -> str | None:   # line 108
    ...
        envelope = getattr(response, "a2ui_envelope", None)          # line 141
        if envelope is not None:                                     # line 142
            surface_id = envelope["createSurface"]["surfaceId"]      # line 143
            entry: dict[str, Any] = {
                ...
                "schemaVersion": SCHEMA_VERSION,                     # line 148 — only use of SCHEMA_VERSION
                "definition": root_component(envelope),              # line 149 — only use of root_component
```
`SCHEMA_VERSION` / `root_component` are used nowhere else in the module (line 113 is a docstring reference only).

### Does NOT Exist
- ~~another module-level use of `SCHEMA_VERSION` or `root_component` in `artifacts.py`~~ — grep verified: only lines 148-149.
- ~~a re-export of `SCHEMA_VERSION` from `artifacts`~~ — no caller imports it from there; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py#attach_structured_artifact"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Put the import inside `if envelope is not None:` — *because* the no-envelope fallback does not need `builders` at all.
- Tag it `# noqa: PLC0415 — lazy on purpose (FEAT-668)` (the same convention as `parrot/cli/agent_repl.py:257`).
- Keep the import inside the existing `try:` block's branch. An ImportError there is a programming error, but it was already inside the `try` at call time, so behaviour does not change.

---

## Implementation Blueprint

### Steps (in order)
1. Delete line 29 — *why*: it is the module-level edge to `builders`.
2. Add the function-local import right after `if envelope is not None:` (line 142) — *why*: the names are only needed there.
3. Run the Validation Commands, plus `python -X importtime -c "import parrot.bots.data" 2>&1 | grep a2ui.builders`, which must print nothing. Save the output to `artifacts/logs/FEAT-668-importtime-bots-data.txt` (spec AC6).

### `packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.outputs.a2ui.adapters.structured import SCHEMA_VERSION, root_component' artifacts.py) — line 29
# DELETE that line.

# occurrences: 1 (verified: grep -c '            surface_id = envelope\["createSurface"\]\["surfaceId"\]' artifacts.py) — line 143
# INSERT directly ABOVE `            surface_id = envelope["createSurface"]["surfaceId"]`:
            from parrot.outputs.a2ui.adapters.structured import (  # noqa: PLC0415 — lazy on purpose (FEAT-668)
                SCHEMA_VERSION,
                root_component,
            )
```
**Why**: `adapters.structured` → `builders` → catalog registration is the heaviest chain (≈314 ms). Building an artifact still loads it, but only at that point.

### FILL IN checklist
- [ ] none — mechanical. Confirm `ruff check` does not flag an unused import elsewhere.

---

## Acceptance Criteria

- [ ] `python -c "import sys, parrot.outputs.a2ui.artifacts; assert 'parrot.outputs.a2ui.builders' not in sys.modules"` succeeds.
- [ ] Artifact-envelope tests pass unchanged.
- [ ] importtime evidence saved (spec AC6).
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/artifacts.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_structured_artifact_v2.py -q`
- `pytest packages/ai-parrot/tests/bots/test_pandasagent_artifact_envelope.py -q`
- `pytest packages/ai-parrot/tests/bots/database/test_db_agent_structured_table_artifact.py -q`

---

## Test Specification

Covered by the existing artifact tests (behaviour) and TASK-4293 (import isolation).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug a2ui-lazy-imports --feature-id FEAT-668`).
2. Read the spec. 3. No dependencies. 4. Verify the Codebase Contract.
5. Mark `in-progress` in the per-spec index. 6. Implement. 7. Validate with `PYTHONPATH=packages/ai-parrot/src`.
8. Commit only the listed file. 9. `scripts/sdd/close_task.sh TASK-4290 a2ui-lazy-imports verified`. 10. Fill in the Completion Note and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
