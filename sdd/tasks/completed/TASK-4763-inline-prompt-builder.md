# TASK-4763: inline/prompt.py — allowlist & catalog-driven prompt addon

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (prompt half). Builds the system-prompt addon that tells the
LLM to author one inline component in the main turn.

Crucially the addon carries **prose only** — `definition.instructions` plus
inline-specific authoring notes. The *schema* reaches the model as
`structured_output=component_model(hint)` (TASK-4762 / TASK-4767), exactly as
`STRUCTURED_CHART` advertises `StructuredChartConfig` rather than inlining its schema
(`data.py:1504-1515`). Keeping the schema out of the prompt is what stops prompt and
schema drifting apart (G6).

Independent of TASK-4762: this module reads `definition.instructions`, not the model.
It also owns `INLINE_COMPONENTS`, the v1 allowlist, which spans two catalogs —
KPICard/InfoCard/Timeline are Parrot-catalog, `Graph` is viz-core.

---

## Scope

- Create `inline/prompt.py` with `INLINE_COMPONENTS`, `INLINE_AUTHORING_NOTES` and `build_component_prompt(component)`.
- Write `INLINE_AUTHORING_NOTES["Graph"]` (the only v1 entry) per the spec's Known Risks guidance.
- Create `tests/outputs/a2ui/inline/__init__.py` and `test_prompt.py`.

**NOT in scope**: `inline/__init__.py` (TASK-4765 creates it, so this task's module is imported by full path), feasibility (TASK-4764), the emitter (TASK-4765), and `component_model` (TASK-4762 — the prompt never touches the schema).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/prompt.py` | CREATE | Allowlist + prompt addon builder |
| `packages/ai-parrot/tests/outputs/a2ui/inline/__init__.py` | CREATE | Test package marker |
| `packages/ai-parrot/tests/outputs/a2ui/inline/test_prompt.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import get_component  # verified: catalog/__init__.py:209
```

### Existing Signatures to Use
```python
# parrot/outputs/a2ui/catalog/__init__.py:209
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent:
    """Resolves across catalogs when catalog_id is omitted; KeyError if unregistered."""

# parrot/outputs/a2ui/catalog/base.py:258-266 — what the prompt reads
class ComponentDefinition(BaseModel):
    instructions: str = ""        # <- the prose the addon carries
    requires_actions: bool = False

# The four v1 components and their catalogs (verified):
#   KPICard, InfoCard, Timeline  -> parrot catalog  (catalog/parrot/*.py)
#   Graph                        -> VIZ_CORE_CATALOG_ID (catalog/viz_core/graph.py)
# All four already ship INSTRUCTIONS; GRAPH_INSTRUCTIONS is at viz_core/graph.py:42.
```

### Does NOT Exist
- ~~`parrot/outputs/a2ui/inline/`~~ — the package does not exist; this task creates `prompt.py` inside it. `__init__.py` is created by TASK-4765, so until then import by full module path.
- ~~`catalog.catalog_instructions()` used here~~ — it exists (`catalog/__init__.py:313`) but aggregates MANY components; this addon is single-component and must read `definition.instructions` directly.
- ~~a per-component prompt constant for KPICard/InfoCard/Timeline~~ — forbidden by G6; only `INLINE_AUTHORING_NOTES` may add prose, and only where catalog instructions fall short.
- ~~serializing `definition.schema_` into the prompt~~ — explicitly removed; the schema travels as `structured_output`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/inline/prompt.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/inline/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/inline/test_prompt.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#get_component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#ComponentDefinition"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No schema in the prompt.** Do not `json.dumps(definition.schema_)` anywhere in this module — that is the decision TASK-4762 exists to replace, and a reviewer will check for it.
- `build_component_prompt` raises `KeyError` for an unregistered component (propagate `get_component`'s contract); the emitter catches it.
- `INLINE_COMPONENTS` is a `frozenset[str]` of exactly `{"KPICard", "InfoCard", "Timeline", "Graph"}` in v1. Resolution is by name across catalogs — do NOT hard-code a catalog id, because `Graph` lives in viz-core and the other three do not.
- `INLINE_AUTHORING_NOTES` has exactly one v1 entry (`Graph`). Other components rely on their catalog instructions; adding an entry for them would violate G6's "only hand-written per-component text" clause.
- The fixed rules in the addon: compute every figure in the tool loop (KPICard `value`/`delta` are literals, never bindings); never emit rows, positions or `action`. Keep the "no prose/markdown/fences" line — it still governs the free-JSON fallback path in the emitter.
- Google docstrings, 120 columns, `logging.getLogger(__name__)`.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py:40-100` — `STRUCTURED_CHART_SYSTEM_PROMPT`, the contract style to mirror (minus the schema dump).
- `parrot/outputs/a2ui/catalog/viz_core/graph.py:42` — `GRAPH_INSTRUCTIONS`, which the Graph notes ADD to, never restate.
- `parrot/outputs/a2ui/catalog/__init__.py:290-313` — `catalog_header_instructions` / `catalog_instructions`, for reference on how instructions are normally aggregated.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `prompt.py` with the allowlist, notes and builder — *why*: the emitter and `data.py` both import `build_component_prompt` by name.
2. Read `definition.instructions` rather than any aggregate helper — *why*: the addon is single-component and must not leak other components' guidance into the turn.
3. Write the Graph authoring notes — *why*: Graph is the hardest component to author and the only one whose catalog instructions need inline-specific additions.
4. Write `test_prompt.py`, asserting the schema is absent from the output — *why*: AC-4 is the regression guard for the G6 decision.

### `packages/ai-parrot/src/parrot/outputs/a2ui/inline/prompt.py` (CREATE)
```python
"""System-prompt addon for authoring one inline A2UI component (FEAT-755).

The addon carries PROSE ONLY — the component's catalog ``instructions`` plus any
inline-specific authoring notes. The schema reaches the model as
``structured_output=component_model(component)`` (catalog/_model.py), mirroring how
``STRUCTURED_CHART`` advertises ``StructuredChartConfig`` instead of inlining its
schema (``bots/data.py:1504-1515``). Keeping the two apart is what keeps prompt and
schema from drifting (spec G6).
"""
from __future__ import annotations

import logging
from typing import Final

from parrot.outputs.a2ui.catalog import get_component  # verified: catalog/__init__.py:209

logger = logging.getLogger(__name__)

__all__ = ["INLINE_COMPONENTS", "INLINE_AUTHORING_NOTES", "build_component_prompt"]

#: v1 allowlist. Display-only components only (``requires_actions=False``). Spans two
#: catalogs: KPICard/InfoCard/Timeline are Parrot-catalog, Graph is viz-core — which is
#: why membership is resolved by NAME and no catalog id is hard-coded.
INLINE_COMPONENTS: Final[frozenset[str]] = frozenset({"KPICard", "InfoCard", "Timeline", "Graph"})

#: Inline-specific guidance ADDED ON TOP of a component's catalog ``instructions``.
#: Graph is the only v1 entry: GRAPH_INSTRUCTIONS (viz_core/graph.py:42) already covers
#: the vocabulary, but not the constraints an inline chat bubble imposes.
INLINE_AUTHORING_NOTES: Final[dict[str, str]] = {
    "Graph": (
        # FILL IN: <= 25 nodes; stable, slug-like node ids; always set `direction`;
        #          always set `accessibleDescription`; never emit positions; pick `kind`
        #          per the catalog instructions — bounded by AC-3
    ),
}


def build_component_prompt(component: str) -> str:
    """Return the system-prompt addon for authoring ``component`` inline.

    Sections, in order: a header (``"INLINE A2UI <Name> OUTPUT MODE"``), the component's
    catalog ``instructions``, ``INLINE_AUTHORING_NOTES`` for it (when present), and the
    fixed rules.

    Raises:
        KeyError: If ``component`` is not registered in any catalog.
    """
    definition = get_component(component).definition
    # FILL IN: assemble header + definition.instructions + notes + FIXED RULES.
    #          FIXED RULES must state: compute every figure yourself in the tool loop
    #          (value/delta are literals, never bindings); never emit data rows,
    #          positions or `action`; return only the component config, no prose,
    #          no markdown fences. Do NOT serialize definition.schema_ — bounded by AC-1/AC-4
```
**Why this shape**: `get_component(component)` with no `catalog_id` resolves across catalogs, which is required because `Graph` is registered under `VIZ_CORE_CATALOG_ID` while the other three are Parrot-catalog. The "no prose/fences" rule stays even though `structured_output` normally makes it moot — the emitter keeps a free-JSON fallback for providers that ignore structured output on a tool-using turn.

### `packages/ai-parrot/tests/outputs/a2ui/inline/__init__.py` (CREATE)
```python
```
**Why**: the sibling test directories in this tree carry an `__init__.py`; without it the new `inline/` test package will not be collected consistently.

### `packages/ai-parrot/tests/outputs/a2ui/inline/test_prompt.py` (CREATE)
```python
"""Inline component prompt addon (FEAT-755 TASK-4763)."""
from __future__ import annotations

import pytest

from parrot.outputs.a2ui.inline.prompt import (
    INLINE_AUTHORING_NOTES, INLINE_COMPONENTS, build_component_prompt,
)


class TestAllowlist:
    def test_v1_components(self):
        assert INLINE_COMPONENTS == {"KPICard", "InfoCard", "Timeline", "Graph"}

    # FILL IN: every allowlisted component resolves via get_component and is
    #          display-only (requires_actions is False) — bounded by AC-2


class TestPrompt:
    # FILL IN: the addon contains the component's catalog instructions verbatim;
    #          Graph's addon ALSO contains INLINE_AUTHORING_NOTES["Graph"] and the other
    #          three do NOT carry any notes;
    #          an unregistered component raises KeyError
    #          — bounded by AC-1/AC-3

    def test_schema_is_not_serialized(self):
        """G6: the schema travels as structured_output, never as prompt text."""
        # FILL IN: assert a distinctive schema-only token (e.g. '"properties"' or
        #          '"higherIsBetter"') is ABSENT from build_component_prompt("KPICard")
        #          — bounded by AC-4
```
**Why**: `test_schema_is_not_serialized` is the regression guard for the emitter-contract decision — without it, someone "helpfully" re-adding the schema dump would pass every other test.

### FILL IN checklist
- [ ] `prompt.py::INLINE_AUTHORING_NOTES["Graph"]` — the inline-specific Graph guidance; bounded by AC-3
- [ ] `prompt.py::build_component_prompt` — section assembly and the fixed rules; bounded by AC-1/AC-4
- [ ] `test_prompt.py` — allowlist, prompt-content and no-schema tests; bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] **AC-1**: `build_component_prompt("KPICard")` contains the component's catalog `instructions` verbatim and the fixed rules; an unregistered component raises `KeyError`.
- [ ] **AC-2**: every name in `INLINE_COMPONENTS` resolves through `get_component` and is display-only (`requires_actions is False`) — including `Graph`, which lives in viz-core.
- [ ] **AC-3**: `INLINE_AUTHORING_NOTES` has exactly one key (`Graph`), and only Graph's addon includes notes.
- [ ] **AC-4 (G6)**: the addon does NOT contain serialized JSON Schema — no `json.dumps(definition.schema_)` in the module, asserted by a test on a schema-only token.
- [ ] `ruff check` clean on all three files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/inline/test_prompt.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/outputs/a2ui/inline/__init__.py` and `packages/ai-parrot/tests/outputs/a2ui/inline/test_prompt.py` per the blueprint.

`test_schema_is_not_serialized` is mandatory — it is the only thing preventing a
future change from quietly reverting the emitter contract decided in spec §8.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug inline-a2ui-component-routing --feature-id FEAT-755`)
2. **Read the spec** at `sdd/specs/inline-a2ui-component-routing.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/inline-a2ui-component-routing.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/inline-a2ui-component-routing.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <ID> inline-a2ui-component-routing verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by native/sonnet (attempt 1)
**Date**: 2026-10-27
**Notes**: Added inline/prompt.py (INLINE_COMPONENTS, INLINE_AUTHORING_NOTES, build_component_prompt) and tests (16 passed per coder). Fidelity gate clean. Merge-tier validation (chunk 0) green: exit 0. Closed via close_task.sh because finalize_task needs a durable review EvidenceRef that coder_record_review does not return; review recorded as coder-review feedback ids.

**Deviations from spec**: Contract gap: prompt.py needs side-effect imports of the parrot and viz_core catalog subpackages (noqa F401) or get_component raises KeyError. TASK-4765's emitter relies on the same registration.
