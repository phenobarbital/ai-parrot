# TASK-4757: Route label grammar & component hint channel

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. This is the foundation of the whole feature: the single
place that knows the composite route-label grammar (`a2ui:<Component>`) and how a
component hint travels on a `RequestContext`.

Today `output_mode_routes` keys are plain `OutputMode` values and
`configure_output_router` does `OutputMode(mode_value)` (`intent_router.py:197`),
so there is no way to say "route to `OutputMode.A2UI` *with* component KPICard".
Modules 2, 3, 4 and 7 all import from here, so this task lands first.

The module must stay **pure and light**: `parrot.registry.routing` is imported on
hot paths, so the catalog import is lazy, inside `is_inline_component` only.

---

## Scope

- Create `route_labels.py` with `A2UI_LABEL_PREFIX`, `OutputShape`, `make_route_label`, `parse_route_label`, `is_inline_component`, `set_output_shape`, `get_component_hint`.
- Write unit tests covering the grammar (valid, malformed, unknown OutputMode), the lazy catalog lookup, and the ctx read/write helpers.

**NOT in scope**: Changing `EmbeddingIntentRouter` (TASK-4758), the route-bank loader (TASK-4759), mixin wiring (TASK-4760), or adding `a2ui_component` to `RequestContext` (TASK-4761 — this module duck-types the ctx and must not import it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/routing/route_labels.py` | CREATE | Label grammar + hint channel |
| `packages/ai-parrot/tests/routing/test_route_labels.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.models.outputs import OutputMode  # verified: parrot/models/outputs.py:23

# LAZY — inside is_inline_component() ONLY, never at module scope:
from parrot.outputs.a2ui.catalog import get_component, CatalogError  # verified: catalog/__init__.py:209 (get_component)
```

### Existing Signatures to Use
```python
# parrot/models/outputs.py:23
class OutputMode(str, Enum):
    ...  # STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP / A2UI = "a2ui" / CARD (legacy)

# parrot/outputs/a2ui/catalog/__init__.py:209
def get_component(name: str, catalog_id: str | None = None) -> RegisteredComponent:
    """Raises KeyError if unregistered; CatalogError if the name is in >1 catalog."""

# parrot/outputs/a2ui/catalog/base.py:293-297
@dataclass
class RegisteredComponent:
    definition: ComponentDefinition
    component_cls: type

# parrot/outputs/a2ui/catalog/base.py:234,258-266
class ComponentDefinition(BaseModel):
    name: str
    catalog_id: str = DEFAULT_CATALOG_ID
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    instructions: str = ""
    requires_actions: bool = False
    tool_only: bool = False
```

### Does NOT Exist
- ~~`parrot.registry.routing.route_labels`~~ — the module this task creates; nothing imports it yet.
- ~~`RequestContext.a2ui_component`~~ — NOT an attribute yet (TASK-4761 adds it). `set_output_shape`/`get_component_hint` must duck-type the ctx (`setattr`/`getattr` with a default), never import or assume the class.
- ~~`ComponentDefinition.source_model` / `.model`~~ — no such field; `requires_actions` is the only gate this module reads.
- ~~`catalog.is_inline` / `catalog.list_inline_components()`~~ — do not exist; the allowlist lives in `inline/prompt.py` (TASK-4763).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/registry/routing/route_labels.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/routing/test_route_labels.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/outputs.py#OutputMode",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#get_component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#ComponentDefinition",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#RegisteredComponent"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Pure module**: no import of `parrot.outputs.a2ui.catalog` at module scope — `parrot.registry.routing` must stay light. The import goes *inside* `is_inline_component`.
- `is_inline_component` **never raises**: `KeyError` (unregistered) and `CatalogError` (ambiguous across catalogs) both return `False`.
- `parse_route_label` does **NOT** consult the catalog — it is pure grammar. Catalog membership is a separate question (`is_inline_component`), because CONFIGURE needs to distinguish "malformed label" from "unknown component".
- `set_output_shape` returns `shape.mode` so a cooperative `_resolve_output_mode` override can `return set_output_shape(ctx, ...)` in one line (the FEAT-756 hook contract, spec §2).
- `ctx` is duck-typed everywhere (`Any`): tolerate `None`, and tolerate a context object without the attribute.
- Google-style docstrings, strict type hints, 120 columns, `logging.getLogger(__name__)`.

### References in Codebase
- `parrot/registry/routing/embedding_router.py:37-56` — `RouteScore`, the NamedTuple style to mirror for `OutputShape`.
- `parrot/bots/mixins/intent_router.py:195-201` — the current `OutputMode(mode_value)` + `except ValueError` warn-and-skip branch this grammar slots in front of.
- `parrot/outputs/a2ui/catalog/__init__.py:209-250` — `get_component` resolution and the `CatalogError` ambiguity path.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `route_labels.py` with the constant, `OutputShape`, and the five functions — *why*: every downstream module imports from here, so the names are fixed by the spec's Interface Skeleton and are not renegotiable.
2. Keep the catalog import inside `is_inline_component` — *why*: `parrot.registry.routing` is on the hot import path and must not pull the A2UI catalog at module scope.
3. Write `test_route_labels.py` covering valid/malformed grammar, unknown OutputMode, the lazy catalog lookup (monkeypatched), and ctx tolerance — *why*: AC-1/AC-2.

### `packages/ai-parrot/src/parrot/registry/routing/route_labels.py` (CREATE)
```python
"""Composite route-label grammar and the A2UI component-hint channel (FEAT-755).

A phrase-bank key is either a plain :class:`OutputMode` value
(``"structured_chart"``) or a composite ``"a2ui:<ComponentName>"`` that resolves
to :attr:`OutputMode.A2UI` plus a component hint carried on the request context.

This module is deliberately pure: the A2UI catalog is imported lazily, inside
:func:`is_inline_component` only, so ``parrot.registry.routing`` stays light.
"""
from __future__ import annotations

import logging
from typing import Any, Final, NamedTuple, Optional

from parrot.models.outputs import OutputMode  # verified: parrot/models/outputs.py:23

logger = logging.getLogger(__name__)

__all__ = [
    "A2UI_LABEL_PREFIX", "OutputShape", "make_route_label", "parse_route_label",
    "is_inline_component", "set_output_shape", "get_component_hint",
]

A2UI_LABEL_PREFIX: Final[str] = "a2ui:"


class OutputShape(NamedTuple):
    """Resolved output shape: ``mode`` plus an optional A2UI ``component`` hint."""

    mode: OutputMode
    component: Optional[str] = None


def make_route_label(component: str) -> str:
    """Return ``"a2ui:<component>"``.

    Raises:
        ValueError: If ``component`` is empty or whitespace-only.
    """
    # FILL IN: strip + emptiness check, then return the prefixed label — bounded by AC-1


def parse_route_label(label: str) -> OutputShape:
    """Parse a phrase-bank key into an :class:`OutputShape`.

    ``"structured_chart"`` -> ``OutputShape(OutputMode.STRUCTURED_CHART)``;
    ``"a2ui:KPICard"`` -> ``OutputShape(OutputMode.A2UI, "KPICard")``.

    Does NOT consult the catalog — see :func:`is_inline_component`.

    Raises:
        ValueError: On an unknown OutputMode value or a malformed composite
            (empty component after the prefix).
    """
    # FILL IN: branch on A2UI_LABEL_PREFIX; else OutputMode(label) — bounded by AC-1/AC-2


def is_inline_component(component: str) -> bool:
    """True when ``component`` is registered in any catalog with ``requires_actions=False``.

    Never raises: an unregistered name (``KeyError``) or a name ambiguous across
    catalogs (``CatalogError``) both return ``False``.
    """
    from parrot.outputs.a2ui.catalog import CatalogError, get_component  # verified: catalog/__init__.py:209

    # FILL IN: get_component(component).definition.requires_actions is False,
    #          catching (KeyError, CatalogError) -> False — bounded by AC-3


def set_output_shape(ctx: Any, shape: OutputShape) -> OutputMode:
    """Write ``shape.component`` to ``ctx.a2ui_component`` and return ``shape.mode``.

    Public entry point for cooperative ``_resolve_output_mode`` overrides
    (the FEAT-756 hook contract). Tolerates ``ctx is None``.
    """
    # FILL IN: setattr only when ctx is not None; always return shape.mode — bounded by AC-4


def get_component_hint(ctx: Any) -> Optional[str]:
    """Return ``ctx.a2ui_component`` or ``None``; tolerant of ``None`` and duck-typed contexts."""
    # FILL IN: getattr(ctx, "a2ui_component", None) guarded on ctx — bounded by AC-4
```
**Why this shape**: the spec fixes these seven names (§3 M1 Interface Skeleton) because Modules 2/3/4/7 all import them — renaming anything here breaks four downstream tasks. `OutputShape` is a `NamedTuple` to mirror `RouteScore` (`embedding_router.py:37`) and stay cheap. `parse_route_label` must not touch the catalog so CONFIGURE can tell a *malformed* key from an *unknown component* and log the right warning.

### `packages/ai-parrot/tests/routing/test_route_labels.py` (CREATE)
```python
"""Unit tests for the composite route-label grammar (FEAT-755 TASK-4757)."""
from __future__ import annotations

import pytest

from parrot.models.outputs import OutputMode
from parrot.registry.routing.route_labels import (
    A2UI_LABEL_PREFIX, OutputShape, get_component_hint, is_inline_component,
    make_route_label, parse_route_label, set_output_shape,
)


class TestGrammar:
    def test_make_route_label(self):
        assert make_route_label("KPICard") == "a2ui:KPICard"

    @pytest.mark.parametrize("bad", ["", "   "])
    def test_make_route_label_rejects_empty(self, bad):
        with pytest.raises(ValueError):
            make_route_label(bad)

    def test_parse_plain_mode(self):
        assert parse_route_label("structured_chart") == OutputShape(OutputMode.STRUCTURED_CHART, None)

    def test_parse_composite(self):
        assert parse_route_label("a2ui:KPICard") == OutputShape(OutputMode.A2UI, "KPICard")

    # FILL IN: malformed composite ("a2ui:") and unknown mode ("nope") both raise ValueError — bounded by AC-2


class TestCatalogGate:
    # FILL IN: is_inline_component("KPICard") is True; an action-bearing component is False;
    #          an unregistered name returns False and does NOT raise — bounded by AC-3
    ...


class TestHintChannel:
    # FILL IN: set_output_shape(None, shape) returns the mode without raising;
    #          with a SimpleNamespace ctx it writes .a2ui_component and get_component_hint reads it back;
    #          get_component_hint(None) and a ctx lacking the attribute both return None — bounded by AC-4
    ...
```
**Why**: the tests pin the three behaviours downstream modules rely on — the grammar, the never-raises catalog gate, and ctx tolerance (which matters because `RequestContext.a2ui_component` does not exist until TASK-4761).

### FILL IN checklist
- [ ] `route_labels.py::make_route_label` — strip/validate then prefix; bounded by AC-1
- [ ] `route_labels.py::parse_route_label` — prefix branch vs `OutputMode(label)`; bounded by AC-1/AC-2
- [ ] `route_labels.py::is_inline_component` — catalog lookup catching `KeyError`/`CatalogError`; bounded by AC-3
- [ ] `route_labels.py::set_output_shape` / `get_component_hint` — ctx-tolerant read/write; bounded by AC-4
- [ ] `test_route_labels.py` — the three `FILL IN` test bodies; bounded by AC-1..AC-4

---

## Acceptance Criteria

- [ ] **AC-1**: `make_route_label("KPICard") == "a2ui:KPICard"`; `parse_route_label` round-trips both plain (`structured_chart`) and composite (`a2ui:KPICard`) keys.
- [ ] **AC-2**: `parse_route_label` raises `ValueError` for an unknown OutputMode value and for a malformed composite (`"a2ui:"`, `"a2ui:   "`).
- [ ] **AC-3**: `is_inline_component` returns `True` for a registered display-only component, `False` for an action-bearing one, and `False` (never raises) for an unregistered or cross-catalog-ambiguous name.
- [ ] **AC-4**: `set_output_shape` returns `shape.mode` and tolerates `ctx is None`; `get_component_hint` returns `None` for `None` and for a ctx without the attribute.
- [ ] No module-scope import of `parrot.outputs.a2ui.catalog` — `grep -n 'from parrot.outputs' route_labels.py` shows the import only inside `is_inline_component`.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/routing/test_route_labels.py -q`
- `pytest packages/ai-parrot/tests/routing/test_embedding_router.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/routing/test_route_labels.py` per the blueprint block above.

Required coverage:
- **Grammar**: plain + composite parse, round-trip through `make_route_label`, `ValueError` on unknown mode and malformed composite.
- **Catalog gate**: `is_inline_component` for a display-only component (`KPICard`), an action-bearing component, and an unregistered name — the last must return `False`, not raise.
- **Hint channel**: `set_output_shape` / `get_component_hint` against `SimpleNamespace()`, `None`, and an object lacking the attribute.

Use `SimpleNamespace` for the context — do NOT import `RequestContext`, which
does not carry `a2ui_component` until TASK-4761.

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

**Completed by**: sdd-worker orchestrator; implemented by codex/gpt-5.6-terra (attempt 1, 444s)
**Date**: 2026-10-27
**Notes**: Added route_labels.py (label grammar, OutputShape, set_output_shape/get_component_hint) and test_route_labels.py. Fidelity gate clean. Merge-tier validation (chunk 0) green: exit 0. Closed via close_task.sh because finalize_task needs a durable review EvidenceRef that coder_record_review does not return; review recorded as coder-review feedback ids.

**Deviations from spec**: none
