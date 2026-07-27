# TASK-1937: Clean-break migration — delete legacy tool, swap registry, final sweep

**Feature**: FEAT-379 — MultiStoreSearch Toolkit with PageIndex, GraphIndex & ParrotWiki Origins
**Spec**: `sdd/specs/multistoresearchtool-parrotwiki.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1931, TASK-1936
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 8 — the clean break (resolved decision: no
deprecation shim). By this point core no longer references `parrot_tools`
(TASK-1931) and the new toolkit is fully functional (TASK-1936). This task
removes the legacy tool, swaps the lazy-registry entry, and sweeps the two
packages for stragglers.

---

## Scope

- Delete `parrot_tools/multistoresearch/_legacy_tool.py` (the old
  `MultiStoreSearchTool`, moved there by TASK-1932) and its re-export from the
  package `__init__.py`.
- In `packages/ai-parrot-tools/src/parrot_tools/__init__.py`: replace the lazy
  map entry (line 119)
  `"multi_store_search": "parrot_tools.multistoresearch.MultiStoreSearchTool"`
  with `"multi_store_search_toolkit": "parrot_tools.multistoresearch.MultiStoreSearchToolkit"`
  (match the surrounding key style — read neighboring entries first).
- Sweep: `grep -rn "MultiStoreSearchTool\b"` across `packages/` — fix or
  remove every remaining reference (tests, docstrings, comments). Expected
  survivors: none in code; historical SDD artifacts under `sdd/` are ignored.
- Update `packages/ai-parrot/src/parrot/registry/routing/models.py:31` FAN_OUT
  docstring (references `MultiStoreSearchTool._execute()`) to describe the
  protocol-based delegation instead.
- Verify `tests/integration/rag/test_store_router_integration.py` (already
  protocol-based since TASK-1931) still passes with the real toolkit
  optionally plugged in.
- Add a release-notes/changelog entry flagging the removal (find the repo's
  changelog convention first; if none exists, note it in the migration doc
  planned for TASK-1938 instead).

**NOT in scope**: documentation guide (TASK-1938); any behavior change in the
toolkit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/_legacy_tool.py` | DELETE | Old tool removed |
| `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/__init__.py` | MODIFY | Drop legacy re-export |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Registry entry swap (line 119) |
| `packages/ai-parrot/src/parrot/registry/routing/models.py` | MODIFY | FAN_OUT docstring (line 31) |
| `packages/ai-parrot-tools/tests/multistoresearch/test_registry.py` | CREATE | Registry resolution test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.multistoresearch import MultiStoreSearchToolkit  # TASK-1936 — verify before starting
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py
# line 119 (pre-task): "multi_store_search": "parrot_tools.multistoresearch.MultiStoreSearchTool",
# — read the surrounding lazy-registry mechanism (__getattr__/importlib) before editing.

# packages/ai-parrot/src/parrot/registry/routing/models.py
# line 31: FAN_OUT docstring — "Delegate to ``MultiStoreSearchTool._execute()`` for parallel"
```

### Does NOT Exist (after this task)
- ~~`parrot_tools.multistoresearch.MultiStoreSearchTool`~~ — REMOVED by this task; any import of it must fail.
- ~~`MultiStoreSearchSchema`~~ — dies with the legacy tool (the toolkit's tools get auto-generated schemas from type hints).
- ~~deprecation shim / warning re-export~~ — explicitly rejected (clean break decision); do not add one.

---

## Implementation Notes

### Key Constraints
- This is the point of no return — run the FULL test suites of BOTH packages
  after the deletion, not just the new tests:
  `pytest packages/ai-parrot-tools/tests/ packages/ai-parrot/tests/ -x -q`
  (respect any repo-standard pytest scoping; check for slow/e2e markers to skip).
- The grep sweep is an acceptance criterion, not a suggestion — paste its
  empty output into the Completion Note.
- `sdd/` and `docs/` historical references to the old tool are NOT code; only
  update docs that claim current behavior (defer prose docs to TASK-1938).

### References in Codebase
- Spec §5 acceptance criteria (removal + registry + decoupling greps).
- Spec §2 Integration Points table — the full blast-radius list.

---

## Acceptance Criteria

- [ ] `python -c "from parrot_tools.multistoresearch import MultiStoreSearchTool"` FAILS (ImportError).
- [ ] `python -c "from parrot_tools.multistoresearch import MultiStoreSearchToolkit"` works; lazy registry resolves the new name.
- [ ] `grep -rn "MultiStoreSearchTool\b" packages/` → no matches in code (report output).
- [ ] `grep -rn "parrot_tools" packages/ai-parrot/src/parrot/` → no matches (re-check of TASK-1931 criterion).
- [ ] FAN_OUT docstring in `routing/models.py` updated.
- [ ] Full affected test suites pass.
- [ ] `ruff check` clean on modified files.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/multistoresearch/test_registry.py
import importlib
import pytest

def test_new_toolkit_resolvable_from_registry():
    import parrot_tools
    # follow the package's lazy-attr convention; adjust to actual mechanism:
    tk_cls = getattr(parrot_tools, "multi_store_search_toolkit", None) or \
        importlib.import_module("parrot_tools.multistoresearch").MultiStoreSearchToolkit
    assert tk_cls.__name__ == "MultiStoreSearchToolkit"

def test_legacy_tool_gone():
    mod = importlib.import_module("parrot_tools.multistoresearch")
    assert not hasattr(mod, "MultiStoreSearchTool")
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1931 and TASK-1936 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing ANY code (read the lazy-registry mechanism in `parrot_tools/__init__.py` first)
4. **Update status** in `sdd/tasks/index/multistoresearchtool-parrotwiki.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria (paste grep outputs into the Completion Note)
6. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
