# TASK-3267: Ontology seam — `OntologyGraphStore` out of `graphindex/persist.py` module level

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3257
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7**. `parrot/knowledge/ontology/schema.py` is import-clean and
stays the shared model source; once TASK-3257 makes the `ontology` package root
lazy, the nine `from parrot.knowledge.ontology.schema import …` call sites in
`graphindex/` become cheap. What remains is moving the two `OntologyGraphStore`
imports "behind the arango seam — injected or lazily imported, never at module
level":

- `graphindex/persist.py:36` — used **only** as the type annotation of
  `GraphIndexPersistence.__init__(self, graph_store: OntologyGraphStore)` (line
  225); `from __future__ import annotations` is already at line 27. The instance
  is injected by the caller. → move under `if TYPE_CHECKING:`.
- `graphindex/loader.py:34` — **handled by TASK-3266**, which relocates
  `GraphIndexLoader` (the only user, instantiating `OntologyGraphStore` at
  loader.py:305) to the framework side `parrot/loaders/graphindex.py`. Do not
  touch `graphindex/loader.py` here.

---

## Scope

- In `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py`, move
  `from parrot.knowledge.ontology.graph_store import OntologyGraphStore` under
  `if TYPE_CHECKING:` and add `TYPE_CHECKING` to the existing `typing` import.
- Add a test asserting (AST) that `persist.py` has no module-level
  `parrot.knowledge.ontology.graph_store` import outside `TYPE_CHECKING`, and
  that `GraphIndexPersistence(graph_store=MagicMock())` still constructs.
- Run the existing persist tests.

**NOT in scope**:
- `graphindex/loader.py` (TASK-3266 relocates `GraphIndexLoader`).
- `persist_sqlite.py` / `persist_postgres.py` `ontology.schema` imports — they stay (schema is cheap after TASK-3257).
- `ontology/graph_store.py` itself (imports only `logging`, `re`, `typing`, `pydantic`, `.schema` — already cheap).
- The repo-wide AST scan test — TASK-3268.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` | MODIFY | `OntologyGraphStore` import → `TYPE_CHECKING` |
| `packages/ai-parrot/tests/knowledge/graphindex/test_persist_seam.py` | CREATE | AST + construction test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.knowledge.graphindex.persist import GraphIndexPersistence       # persist.py:213
from parrot.knowledge.ontology.graph_store import OntologyGraphStore        # ontology/graph_store.py (TYPE_CHECKING only after this task)
from typing import TYPE_CHECKING, Any, Optional                             # persist.py:34 today: `from typing import Any, Optional`
import ast, pathlib                                                          # stdlib (test)
from unittest.mock import MagicMock                                          # stdlib (test)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py (903 lines)
from __future__ import annotations                                           # line 27
import asyncio                                                               # line 29
from typing import Any, Optional                                             # line 34
from parrot.knowledge.ontology.graph_store import OntologyGraphStore         # line 36  ← move
from parrot.knowledge.ontology.schema import TenantContext                   # line 37  (stays)
from parrot.knowledge.graphindex.meta_ontology import (...)                  # line 38
from parrot.knowledge.graphindex.schema import (...)                         # line 42
class GraphIndexPersistence:                                                 # line 213
    def __init__(self, graph_store: OntologyGraphStore) -> None:             # line 225  ← only runtime-visible use (annotation)
#   Other occurrences of "OntologyGraphStore" (lines 4, 77, 119, 220) are docstrings.

# packages/ai-parrot/tests/knowledge/graphindex/test_persist.py
def make_graph_store() -> MagicMock:                                         # line 62
    GraphIndexPersistence(graph_store=store)                                 # line 148
```

### Does NOT Exist
- ~~A runtime `isinstance(..., OntologyGraphStore)` in `persist.py`~~ — verified: none (only the annotation at :225 and docstrings).
- ~~`parrot.knowledge.graphindex.arango_seam`~~ / any "arango seam" module — the seam is simply injection + `TYPE_CHECKING`; do not create a module.
- ~~`test_persist_seam.py`~~ — created by this task.

---

## Implementation Notes

### Key Constraints
- `from __future__ import annotations` (line 27) makes the annotation a string, so `TYPE_CHECKING` is safe at runtime. Anything that calls `typing.get_type_hints(GraphIndexPersistence.__init__)` would now fail — grep for `get_type_hints` usage on it before landing (none known).
- Keep `TenantContext` import at module level — `ontology.schema` is the shared, cheap model source (spec §3 Module 7).

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py:29,41` — existing `TYPE_CHECKING` pattern in the same package.

---

## Implementation Blueprint

### Steps (in order)
1. Write `test_persist_seam.py` and see the AST test fail — *why*: proves the scan catches the current import.
2. Edit `persist.py` per the block below — *why*: spec §3 Module 7 "never at module level".
3. Run `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist.py packages/ai-parrot/tests/knowledge/graphindex/test_persist_seam.py packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py -q` and `ruff check` both files.

### `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^from typing import Any, Optional$' packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py)
# REPLACE line 34 `from typing import Any, Optional` with:
from typing import TYPE_CHECKING, Any, Optional

# occurrences: 1 (verified: grep -c '^from parrot.knowledge.ontology.graph_store import OntologyGraphStore$' packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py)
# DELETE line 36 `from parrot.knowledge.ontology.graph_store import OntologyGraphStore`
# occurrences: 1 (verified: grep -c '^logger = logging.getLogger(__name__)$' packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py)
# BEFORE — insert above `logger = logging.getLogger(__name__)` (verified: persist.py:52),
# i.e. right after the closing `)` of `from parrot.knowledge.graphindex.schema import (` (lines 42-50)
if TYPE_CHECKING:
    # Annotation only (FEAT-540): the graph store is injected by the caller,
    # so the graph tree never imports the ontology store at module level.
    from parrot.knowledge.ontology.graph_store import OntologyGraphStore
```
**Why**: the store is already injected via `__init__`; only the annotation needs the name, and `from __future__ import annotations` keeps it lazy.

### `packages/ai-parrot/tests/knowledge/graphindex/test_persist_seam.py` (CREATE)
```python
"""FEAT-540 Module 7 — persist.py keeps OntologyGraphStore out of module level."""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import parrot.knowledge.graphindex.persist as persist_mod
from parrot.knowledge.graphindex.persist import GraphIndexPersistence


def _module_level_imports(tree: ast.Module) -> list[str]:
    """Collect module names imported at module level, skipping ``if TYPE_CHECKING:`` blocks."""
    names: list[str] = []
    # FILL IN: walk tree.body (recurse into If/Try bodies, handlers, orelse) but skip any
    # `ast.If` whose test unparses to contain "TYPE_CHECKING"; collect Import alias names and
    # ImportFrom modules — bounded by D12's scan semantics (same rules as TASK-3268's scan).
    return names


def test_persist_has_no_module_level_graph_store_import() -> None:
    """``parrot.knowledge.ontology.graph_store`` is imported only under ``TYPE_CHECKING``."""
    tree = ast.parse(Path(persist_mod.__file__).read_text(encoding="utf-8"))
    assert "parrot.knowledge.ontology.graph_store" not in _module_level_imports(tree)


def test_persistence_accepts_injected_store() -> None:
    """The store is still injected and stored unchanged."""
    store = MagicMock()
    persistence = GraphIndexPersistence(graph_store=store)
    assert persistence.graph_store is store
```

### FILL IN checklist
- [ ] `persist.py` — confirm the `TYPE_CHECKING` block sits after all module-level imports (anchor verified at :52).
- [ ] `test_persist_seam.py::_module_level_imports` — AST walk skipping `TYPE_CHECKING`; bounded by D12 scan semantics.

---

## Acceptance Criteria

- [ ] `persist.py` has no module-level (non-`TYPE_CHECKING`) import of `parrot.knowledge.ontology.graph_store`
- [ ] `GraphIndexPersistence(graph_store=<store>)` behaviour unchanged
- [ ] `pytest packages/ai-parrot/tests/knowledge/graphindex/test_persist.py packages/ai-parrot/tests/knowledge/graphindex/test_persist_seam.py packages/ai-parrot/tests/knowledge/graphindex/test_persist_commit_protocol.py -q` passes
- [ ] `ruff check` clean on both files

---

## Test Specification

See the `test_persist_seam.py` CREATE block above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3257 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `grep -n OntologyGraphStore packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py`; if a runtime (non-annotation) use appeared, switch to a lazy import inside that function instead and note it
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`
6. In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/TASK-3267-ontology-graph-store-seam.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: `graphindex/loader.py:34` half of Module 7 is delivered by TASK-3266 (GraphIndexLoader relocation), not here.
