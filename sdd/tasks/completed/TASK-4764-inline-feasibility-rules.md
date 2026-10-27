# TASK-4764: inline/feasibility.py — per-component data-feasibility rules

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4763
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (feasibility half). The rev-1 "layer 2" check, revived per
component and kept emitter-local — no `CapabilityRegistry` coupling.

An LLM can emit a schema-valid KPICard with no scalar `value`, or a Timeline with no
events. Rendering that is worse than not rendering it, so the emitter checks
feasibility after the config is parsed and degrades when it fails. The house precedent
is `StructuredChartRenderer._safe_x` / `_safe_y`, which silently falls back when the
LLM names a column that is not in the real data.

Pure, dependency-free and independently testable — it runs in the first wave.

---

## Scope

- Create `inline/feasibility.py` with `FeasibilityResult` and `check_feasibility(component, config, frame)`.
- Implement the four per-component rules and their fixed reason codes.
- Create `test_feasibility.py` reaching every reason code.

**NOT in scope**: Deciding what to degrade TO (the emitter owns that, TASK-4765), the prompt (TASK-4763), and any `CapabilityRegistry` lookup — explicitly excluded by the spec.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/feasibility.py` | CREATE | Per-component feasibility rules |
| `packages/ai-parrot/tests/outputs/a2ui/inline/test_feasibility.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
# No parrot imports — this module is pure and must stay that way.
from typing import Any, Mapping, NamedTuple, Optional
```

### Existing Signatures to Use
```python
# Nothing existing is called. The CONFIG SHAPES checked here come from the catalog
# schemas (read-only reference, do not import them):
#   KPICard  (catalog/parrot/kpicard.py):  label, value, unit, delta, trend, series, ...
#   InfoCard (catalog/parrot/infocard.py): title (REQUIRED), subtitle, body, image, badge, footer
#   Timeline (catalog/parrot/timeline.py): title, events[] (REQUIRED) each {timestamp, title, description}
#                                          with "required": ["title"] on each event
#   Graph    (catalog/viz_core/graph.py):  kind, direction, nodes[], edges[] {from, to, ...},
#                                          accessibleDescription
```

### Does NOT Exist
- ~~`parrot.registry.capabilities.CapabilityRegistry.not_for`~~ — the rev-1 layer-1 feasibility hook was never built and stays unbuilt; do not reach for it.
- ~~a shared `Feasible`/`Degraded` enum elsewhere in the tree~~ — `FeasibilityResult` is defined here.
- ~~pandas as a dependency of this module~~ — `frame` is typed `Any` and only duck-tested; never `import pandas` here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/inline/feasibility.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/inline/test_feasibility.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Pure module**: no parrot imports, no pandas import. `frame` is `Any` and is only duck-tested (e.g. `getattr(frame, "empty", None)`), so the module stays importable anywhere.
- **Reason codes are fixed strings** — the emitter logs them and tests assert on them: `kpicard_value_missing`, `timeline_events_missing`, `infocard_title_missing`, `graph_nodes_missing`, `graph_edge_dangling`.
- **Unknown component → feasible.** If a component has no rule, return feasible and let schema validation decide. This keeps the module open for FEAT-753/754 without edits.
- Never raises: a malformed `config` (wrong types, `None` where a list is expected) returns *infeasible with a reason*, not an exception.
- `KPICard`: `value` must be present AND scalar — a number, or a non-empty string. A dict (i.e. a binding descriptor) is NOT a renderable scalar for an inline card.
- `Timeline`: at least one event carrying a non-empty `title` (the catalog marks `title` required per event, `timestamp` optional).
- `Graph`: at least one node; and every edge's `from`/`to` must name an existing node id → otherwise `graph_edge_dangling`.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py` — `_safe_x`/`_safe_y`, the silent-fallback precedent.
- `parrot/outputs/a2ui/catalog/parrot/kpicard.py`, `infocard.py`, `timeline.py` and `catalog/viz_core/graph.py` — the config shapes being checked.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `feasibility.py` with the NamedTuple and the dispatch — *why*: the emitter imports `check_feasibility` by name.
2. Implement one small checker per component — *why*: each rule is independently testable and the dispatch stays a lookup.
3. Default unknown components to feasible — *why*: FEAT-753/754 add components without touching this module.
4. Write `test_feasibility.py` reaching every reason code — *why*: AC-5; the spec requires each code to be reachable in tests.

### `packages/ai-parrot/src/parrot/outputs/a2ui/inline/feasibility.py` (CREATE)
```python
"""Per-component data-feasibility checks for the inline emitter (FEAT-755).

A schema-valid config can still be unrenderable — a KPICard with no scalar value, a
Timeline with no events. The emitter runs these checks after parsing and degrades
instead of emitting an empty-looking card. Emitter-local by design: no
``CapabilityRegistry`` coupling (the rev-1 layer-1 hook was never built).

Pure module: no parrot imports, no pandas. ``frame`` is duck-tested only.
"""
from __future__ import annotations

from typing import Any, Mapping, NamedTuple, Optional

__all__ = ["FeasibilityResult", "check_feasibility"]


class FeasibilityResult(NamedTuple):
    """Outcome of a feasibility check; ``reason`` is a fixed code when infeasible."""

    feasible: bool
    reason: Optional[str] = None


def _check_kpicard(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """``value`` must be present and scalar (number, or non-empty string).

    A Mapping value is a binding descriptor, not a renderable scalar for an inline card.
    """
    # FILL IN: -> FeasibilityResult(False, "kpicard_value_missing") when absent/non-scalar
    #          — bounded by AC-1


def _check_timeline(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """>= 1 event carrying a non-empty ``title``."""
    # FILL IN: -> "timeline_events_missing" — bounded by AC-2


def _check_infocard(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """Non-empty ``title``."""
    # FILL IN: -> "infocard_title_missing" — bounded by AC-3


def _check_graph(config: Mapping[str, Any], frame: Any) -> FeasibilityResult:
    """>= 1 node, and every edge endpoint names an existing node id."""
    # FILL IN: -> "graph_nodes_missing" / "graph_edge_dangling" — bounded by AC-4


_CHECKS = {
    "KPICard": _check_kpicard,
    "Timeline": _check_timeline,
    "InfoCard": _check_infocard,
    "Graph": _check_graph,
}


def check_feasibility(component: str, config: Mapping[str, Any], frame: Any | None) -> FeasibilityResult:
    """Run ``component``'s feasibility rule against ``config``.

    An unknown component is feasible — schema validation decides for it, which keeps
    this module closed to edits when FEAT-753/754 register new components.

    Never raises: a malformed ``config`` yields an infeasible result, not an exception.
    """
    # FILL IN: dispatch through _CHECKS with a feasible default, wrapping the call in a
    #          broad except that returns the component's own reason code
    #          — bounded by AC-5/AC-6
```
**Why this shape**: one checker per component keeps each rule independently testable and makes the dispatch a dict lookup, so a new component is a two-line change here (or none at all, since unknown defaults to feasible). The reason codes are fixed strings because the emitter logs them and `/sdd-done`-level tests assert on them.

### `packages/ai-parrot/tests/outputs/a2ui/inline/test_feasibility.py` (CREATE)
```python
"""Per-component feasibility rules (FEAT-755 TASK-4764)."""
from __future__ import annotations

import pytest

from parrot.outputs.a2ui.inline.feasibility import FeasibilityResult, check_feasibility


class TestKPICard:
    # FILL IN: numeric value feasible; non-empty string feasible; missing/None/empty-string
    #          infeasible with "kpicard_value_missing"; a {"path": "/p"} binding is
    #          infeasible for an inline card — bounded by AC-1
    ...


class TestTimeline:
    # FILL IN: one titled event feasible; [] and events without a title ->
    #          "timeline_events_missing" — bounded by AC-2
    ...


class TestInfoCard:
    # FILL IN: title present feasible; missing/blank -> "infocard_title_missing" — bounded by AC-3
    ...


class TestGraph:
    # FILL IN: nodes+valid edges feasible; no nodes -> "graph_nodes_missing";
    #          an edge naming a missing node -> "graph_edge_dangling" — bounded by AC-4
    ...


class TestDispatch:
    # FILL IN: unknown component feasible; malformed configs (None, wrong types) return a
    #          FeasibilityResult rather than raising — bounded by AC-5/AC-6
    ...
```
**Why**: the spec's G10 requires each of the four feasibility reasons plus the schema-failure reason to be reachable in tests; this module owns four of the five.

### FILL IN checklist
- [ ] `feasibility.py::_check_kpicard` — scalar-value rule; bounded by AC-1
- [ ] `feasibility.py::_check_timeline` — titled-event rule; bounded by AC-2
- [ ] `feasibility.py::_check_infocard` — title rule; bounded by AC-3
- [ ] `feasibility.py::_check_graph` — node + dangling-edge rules; bounded by AC-4
- [ ] `feasibility.py::check_feasibility` — dispatch, feasible default, never-raises wrapper; bounded by AC-5/AC-6
- [ ] `test_feasibility.py` — the five test classes; bounded by AC-1..AC-6

---

## Acceptance Criteria

- [ ] **AC-1**: KPICard — a number or non-empty string `value` is feasible; absent, `None`, blank, or a Mapping (binding) yields `kpicard_value_missing`.
- [ ] **AC-2**: Timeline — ≥1 event with a non-empty `title` is feasible; otherwise `timeline_events_missing`.
- [ ] **AC-3**: InfoCard — non-empty `title` feasible; otherwise `infocard_title_missing`.
- [ ] **AC-4**: Graph — ≥1 node feasible; no nodes yields `graph_nodes_missing`; an edge whose `from`/`to` names a missing node yields `graph_edge_dangling`.
- [ ] **AC-5**: an unknown component is feasible (no rule means schema validation decides).
- [ ] **AC-6**: `check_feasibility` never raises — malformed configs (`None`, wrong types) return a `FeasibilityResult`.
- [ ] The module imports nothing from `parrot` and does not import pandas.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/inline/test_feasibility.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/outputs/a2ui/inline/test_feasibility.py` per the blueprint. Every one of the five reason
codes must be reached by at least one test (spec G10).

`packages/ai-parrot/tests/outputs/a2ui/inline/__init__.py` is owned by TASK-4763 — that is
the only reason this task depends on it. Do NOT create or modify that file here; if it is
missing, TASK-4763 has not landed and this task is not ready.

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

**Completed by**: sdd-worker orchestrator; implemented by native/opus (attempt 1)
**Date**: 2026-10-27
**Notes**: Added inline/feasibility.py (FeasibilityResult, check_feasibility, 5 reason codes; never raises) and tests (30 passed per coder). Merge-tier validation (chunk 1) green: 313 passed. Reviewed for file fidelity only (no line-level diff review). Closed via close_task.sh (no durable review EvidenceRef available for finalize_task).

**Deviations from spec**: none. Choices beyond text: bool KPICard value is not a number; Graph nodes without ids -> graph_nodes_missing. Source inline/ has no __init__.py (namespace package works); TASK-4765 owns it.
