# TASK-4765: inline/emitter.py — config extraction, envelope build & presentation marker

**Feature**: FEAT-755 — Inline A2UI Component Routing
**Spec**: `sdd/specs/inline-a2ui-component-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4762, TASK-4763, TASK-4764
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (emitter half) — the heart of the feature and the piece every
other thread meets at. Takes the LLM's component config off the response, checks
feasibility, builds a validated A2UI surface, stamps the `parrot_presentation` marker,
and sets `response.a2ui_envelope`.

Two contracts it must honour exactly:

- **G3 — never raises.** Every failure path returns a `degraded` outcome with a reason
  code and leaves `a2ui_envelope` as `None`, so `PandasAgent.ask()` falls through to
  its existing `DEFAULT` degradation (`data.py:1957-1966`). An exception escaping here
  would break every routed turn.
- **`structured_output` first, free JSON second.** TASK-4767 advertises
  `component_model(hint)` to the client, so `response.structured_output` is the primary
  source. The free-JSON parse is RETAINED as a fallback because not every provider
  honours structured output on a tool-using turn.

This task also creates `inline/__init__.py` (last, once all three modules exist).

---

## Scope

- Create `inline/emitter.py`: `PRESENTATION_EXTENSION`, `InlineEmitOutcome`, `presentation_extension`, `extract_component_config`, `emit_inline_component`.
- Create `inline/__init__.py` re-exporting the package's public surface.
- Re-implement the JSON-from-text extraction locally (the helper lives in the visualizations satellite and core must not import it).
- Create `test_emitter.py` covering both outcomes and every degrade reason.

**NOT in scope**: Calling the emitter from `data.py` (TASK-4767), the conformance fixture (TASK-4770), and the UI (TASK-4768/4769).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py` | CREATE | Inline emitter + presentation marker |
| `packages/ai-parrot/src/parrot/outputs/a2ui/inline/__init__.py` | CREATE | Package exports |
| `packages/ai-parrot/tests/outputs/a2ui/inline/test_emitter.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED code references from the actual codebase. Use these exact
> imports, class names, and method signatures. DO NOT invent, guess, or assume any
> import, attribute, or method not listed here. Verified against `e21bc561e+ (dev @ 2026-10-27, re-verified at /sdd-task time)`.

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_surface            # verified: builders.py:79
from parrot.outputs.a2ui.catalog import ProducerOrigin              # verified: catalog/__init__.py:59
from parrot.outputs.a2ui.emission import finalize_a2ui_response     # verified: emission.py:18
from parrot.outputs.a2ui.models import Extensions, SurfaceMetadata  # verified: models.py:341,378
from parrot.outputs.a2ui.serialization import serialize             # verified: serialization.py:104

from parrot.outputs.a2ui.inline.feasibility import check_feasibility  # TASK-4764
from parrot.outputs.a2ui.inline.prompt import INLINE_COMPONENTS       # TASK-4763
```

### Existing Signatures to Use
```python
# VERIFY EACH OF THESE BEFORE USE — they are quoted from the spec's §6 contract and
# the exact signatures matter for build_surface's keyword arguments.
# parrot/outputs/a2ui/builders.py:79 — FULL verified signature
def build_surface(
    component: str,
    properties: dict[str, Any],
    *,
    surface_id: str,
    component_id: str = _ROOT_COMPONENT_ID,
    data_model: dict[str, Any] | None = None,
    origin: ProducerOrigin = ProducerOrigin.LLM,
    metadata: ComponentMetadata | None = None,      # component-level — NOT the marker's home
    surface_metadata: SurfaceMetadata | None = None,  # surface-level — the marker goes HERE
) -> CreateSurface: ...

# parrot/outputs/a2ui/serialization.py:104
def serialize(message: Serializable) -> dict[str, Any]: ...

# parrot/outputs/a2ui/emission.py:18
def finalize_a2ui_response(response: Any) -> None:
    """Sets response.output_mode = OutputMode.A2UI and fills a human-readable fallback
       in response.response (FEAT-273)."""

# parrot/outputs/a2ui/models.py:364-378
class ComponentMetadata(BaseModel):              # :364
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    extensions: Extensions | None = None         # :373
SurfaceMetadata = ComponentMetadata              # :378 — an ALIAS, not its own class
class Extensions(RootModel[dict[str, Any]]): ...  # :341 — construct as Extensions(root={...})
# parrot/outputs/a2ui/inline/feasibility.py (TASK-4764)
def check_feasibility(component, config, frame) -> FeasibilityResult: ...
```

### Does NOT Exist
- ~~`StructuredOutputBase._extract_json_code` importable from core~~ — it lives in the visualizations satellite (`structured_base.py:202`); core MUST re-implement the extraction locally. Importing it is a layering violation and will fail at runtime for core-only installs.
- ~~`parrot.outputs.a2ui.inline` as an importable package~~ — this task creates its `__init__.py`.
- ~~`response.a2ui_envelope` pre-populated~~ — the emitter is called only when it is `None` (TASK-4767 guards the call site).
- ~~an `OutputMode.A2UI` renderer in the formats registry~~ — there is none and this task does not add one; the emitter is called directly from `ask()`.
- ~~`build_surface(..., metadata=...)`~~ — the keyword is `surface_metadata`; verify the real signature at `builders.py:79` before writing the call.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/inline/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/inline/test_emitter.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_surface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/serialization.py#serialize",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/emission.py#finalize_a2ui_response",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#ProducerOrigin",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#SurfaceMetadata",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#Extensions",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/inline/feasibility.py#check_feasibility",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/inline/prompt.py#INLINE_COMPONENTS"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never raises (G3).** Wrap the whole body; every failure returns `InlineEmitOutcome(status="degraded", ...)`. The emitter must not touch `response.output_mode` on failure — the same rule `_emit_a2ui_envelope` follows (`structured_base.py:156-159`) — so the existing `DEFAULT` degradation still applies.
- **Degrade reasons (fixed)**: `component_not_inline`, `config_unparseable`, the four feasibility codes, `catalog_validation_failed`, `unexpected_error`.
- `response.metadata["a2ui_inline"]` is written on **both** outcomes, so a caller can always see what happened.
- **Extraction order**: `response.structured_output` (a `BaseModel` → `model_dump(by_alias=True, exclude_none=True)`; a dict → as-is), then the first JSON object in `response.output` / `response.content` (fenced or bare), then `None`. `by_alias` matters (camelCase wire names) and `exclude_none` matters (an omitted field must stay omitted — `higherIsBetter` distinguishes null from absent).
- `surface_id` pattern: `f"{component.lower()}-{uuid4().hex[:8]}"` — the FEAT-224 pattern from `structured_base.py:149`.
- The marker is **surface-level** (`createSurface.metadata.extensions`), exactly like `parrot_data_sources` — never on the component.
- `origin=ProducerOrigin.LLM` so the catalog's LLM-origin gates apply (`action` rejected, `parrot_data_sources` rejected).
- Obey the a2ui one-way import rule (`builders.py:14`): no agents, no clients.

### References in Codebase
- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py:87-199` — `_route_envelope` / `_emit_a2ui_envelope`, the dual-emit shape to mirror (and `:149` for the surface_id pattern, `:202` for the extraction helper to re-implement).
- `parrot/outputs/a2ui/emission.py:18-43` — `finalize_a2ui_response`.
- `docs/outputs/a2ui-linked-surfaces.md` — `parrot_data_sources`, the surface-level extension precedent.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Business-logic branches, edge
> cases and test bodies are `FILL IN` stubs by design. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `emitter.py` with the constant, outcome tuple and three functions — *why*: TASK-4767 and TASK-4770 import `emit_inline_component` by name.
2. Re-implement JSON extraction locally — *why*: the satellite helper is not importable from core; copying the behaviour is deliberate, not duplication by accident.
3. Make `structured_output` the first source — *why*: TASK-4767 advertises the component model, so this is the normal path; the text parse is the fallback.
4. Wrap everything so no exception escapes — *why*: G3; an exception here breaks every routed turn.
5. Create `__init__.py` last — *why*: it re-exports all three modules, so it is written once they exist.
6. Write `test_emitter.py` — *why*: AC-1..AC-7.

### `packages/ai-parrot/src/parrot/outputs/a2ui/inline/emitter.py` (CREATE)
```python
"""Inline A2UI component emitter (FEAT-755).

Turns the component config the LLM authored in the main turn into a validated A2UI
envelope on ``response.a2ui_envelope``, stamped with the surface-level
``parrot_presentation`` marker so a renderer knows it was produced as an inline chat
answer rather than inferring it from the root component.

NEVER raises (spec G3): every failure is a ``degraded`` outcome and the caller's
existing ``DEFAULT`` degradation takes over.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Final, Literal, NamedTuple, Optional
from uuid import uuid4

from parrot.outputs.a2ui.builders import build_surface            # verified: builders.py:79
from parrot.outputs.a2ui.catalog import ProducerOrigin            # verified: catalog/__init__.py:59
from parrot.outputs.a2ui.emission import finalize_a2ui_response   # verified: emission.py:18
from parrot.outputs.a2ui.models import Extensions, SurfaceMetadata  # verified: models.py:341,378
from parrot.outputs.a2ui.serialization import serialize           # verified: serialization.py:104

from parrot.outputs.a2ui.inline.feasibility import check_feasibility
from parrot.outputs.a2ui.inline.prompt import INLINE_COMPONENTS

logger = logging.getLogger(__name__)

__all__ = ["PRESENTATION_EXTENSION", "InlineEmitOutcome", "presentation_extension",
           "extract_component_config", "emit_inline_component"]

PRESENTATION_EXTENSION: Final[str] = "parrot_presentation"


class InlineEmitOutcome(NamedTuple):
    """What the emitter did, for logging and for ``response.metadata["a2ui_inline"]``."""

    status: Literal["emitted", "degraded"]
    component: str
    reason: Optional[str] = None
    surface_id: Optional[str] = None


def presentation_extension(component: str) -> dict[str, Any]:
    """The surface-level marker payload for ``component``."""
    return {"kind": "widget", "inline": True, "origin": "chat_turn", "component": component}


def extract_component_config(response: Any) -> Optional[dict[str, Any]]:
    """Pull the component config off ``response``.

    Order:
      1. ``response.structured_output`` — the PRIMARY path, since the caller advertises
         ``component_model(component)`` to the client. A ``BaseModel`` is dumped with
         ``model_dump(by_alias=True, exclude_none=True)`` (camelCase wire names, and an
         omitted field stays omitted — load-bearing for ``higherIsBetter``); a dict is
         taken as-is.
      2. The first JSON object in ``response.output`` / ``response.content``, fenced or
         bare. RETAINED, not vestigial: some providers ignore structured output on a
         tool-using turn, and G3 requires degrading rather than failing.
      3. ``None`` when nothing parses.
    """
    # FILL IN: the three-step extraction. Re-implement the fenced/bare JSON scan locally —
    #          StructuredOutputBase._extract_json_code is NOT importable from core
    #          — bounded by AC-2


def emit_inline_component(response: Any, component: str, *, frame: Any | None = None,
                          surface_id: Optional[str] = None) -> InlineEmitOutcome:
    """Author, validate and attach an inline A2UI envelope. Never raises.

    Steps: allowlist check -> extract config -> feasibility -> ``build_surface``
    (which validates) -> ``response.a2ui_envelope = serialize(surface)`` ->
    ``finalize_a2ui_response(response)``.

    ``response.metadata["a2ui_inline"]`` is written on BOTH outcomes.

    Degrade reasons: ``component_not_inline``, ``config_unparseable``, the four
    feasibility codes, ``catalog_validation_failed``, ``unexpected_error``.
    """
    # FILL IN: the pipeline above, wrapped so NOTHING escapes. On any degrade, leave
    #          response.a2ui_envelope as None and do NOT touch response.output_mode —
    #          the caller's existing DEFAULT degradation must still apply
    #          (mirrors structured_base.py:156-159) — bounded by AC-1/AC-3..AC-6
    #
    #          The surface build is:
    #            sid = surface_id or f"{component.lower()}-{uuid4().hex[:8]}"
    #            surface = build_surface(
    #                component, config, surface_id=sid, origin=ProducerOrigin.LLM,
    #                surface_metadata=SurfaceMetadata(
    #                    extensions=Extensions(root={PRESENTATION_EXTENSION: presentation_extension(component)})
    #                ),
    #            )
    #          VERIFY build_surface's real signature at builders.py:79 before writing it.
```
**Why this shape**: `build_surface` validates internally, so catalog conformance is enforced by construction rather than by a separate check. The marker goes on `surface_metadata` because it describes the *surface's provenance*, not a node's presentation role — the same reasoning that put `parrot_data_sources` at surface level.

### `packages/ai-parrot/src/parrot/outputs/a2ui/inline/__init__.py` (CREATE)
```python
"""Inline A2UI component authoring for a single chat turn (FEAT-755)."""
from parrot.outputs.a2ui.inline.emitter import (
    PRESENTATION_EXTENSION, InlineEmitOutcome, emit_inline_component,
    extract_component_config, presentation_extension,
)
from parrot.outputs.a2ui.inline.feasibility import FeasibilityResult, check_feasibility
from parrot.outputs.a2ui.inline.prompt import (
    INLINE_AUTHORING_NOTES, INLINE_COMPONENTS, build_component_prompt,
)

__all__ = [
    "PRESENTATION_EXTENSION", "InlineEmitOutcome", "emit_inline_component",
    "extract_component_config", "presentation_extension",
    "FeasibilityResult", "check_feasibility",
    "INLINE_AUTHORING_NOTES", "INLINE_COMPONENTS", "build_component_prompt",
]
```
**Why**: written in this task (not TASK-4763/4764) because it names symbols from all three modules — creating it earlier would make the package unimportable until the last one landed.

### `packages/ai-parrot/tests/outputs/a2ui/inline/test_emitter.py` (CREATE)
```python
"""Inline emitter outcomes and marker (FEAT-755 TASK-4765)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from parrot.outputs.a2ui.inline.emitter import (
    PRESENTATION_EXTENSION, emit_inline_component, extract_component_config,
    presentation_extension,
)


@pytest.fixture
def kpi_response():
    """AIMessage-like response carrying a fenced KPICard config (spec §4 fixture)."""
    return SimpleNamespace(
        output='```json\n{"label": "Worked hours", "value": 1234.5, "unit": "h", "delta": 0.12, "trend": "up"}\n```',
        content=None, structured_output=None, response="", data=None, metadata={},
        a2ui_envelope=None, output_mode=None,
    )


class TestExtraction:
    # FILL IN: BaseModel via model_dump(by_alias=True, exclude_none=True) wins over text;
    #          a dict structured_output is taken as-is; fenced and bare JSON in output/content;
    #          nothing parseable -> None — bounded by AC-2


class TestEmitted:
    # FILL IN: envelope on response.a2ui_envelope; createSurface.metadata.extensions
    #          carries parrot_presentation with kind/inline/origin/component;
    #          output_mode == A2UI and response.response is non-empty (finalize ran);
    #          metadata["a2ui_inline"]["status"] == "emitted" — bounded by AC-1/AC-7


class TestDegraded:
    # FILL IN: each reason reachable — component_not_inline (e.g. "DataTable"),
    #          config_unparseable, a feasibility code, catalog_validation_failed;
    #          in EVERY case a2ui_envelope stays None, output_mode is UNTOUCHED,
    #          nothing raises, and metadata["a2ui_inline"] is written
    #          — bounded by AC-3/AC-4/AC-5/AC-6
```
**Why**: `TestDegraded` asserting `output_mode` is untouched is the subtle one — if the emitter set it on failure, `ask()` would try to render an A2UI response with no envelope and the user would get an empty bubble.

### FILL IN checklist
- [ ] `emitter.py::extract_component_config` — three-source extraction, local JSON scan; bounded by AC-2
- [ ] `emitter.py::emit_inline_component` — the pipeline, never-raises wrapper, both-outcome metadata; bounded by AC-1/AC-3..AC-6
- [ ] `test_emitter.py` — the three test classes, every degrade reason reached; bounded by AC-1..AC-7

---

## Acceptance Criteria

- [ ] **AC-1**: a valid KPICard config produces `response.a2ui_envelope`, `output_mode == OutputMode.A2UI`, non-empty `response.response`, and `metadata["a2ui_inline"]["status"] == "emitted"`.
- [ ] **AC-2**: extraction prefers `structured_output` (BaseModel dumped `by_alias=True, exclude_none=True`; dict as-is), then fenced JSON, then bare JSON, then `None`.
- [ ] **AC-3**: the marker is at `createSurface.metadata.extensions.parrot_presentation` with `kind="widget"`, `inline=true`, `origin="chat_turn"`, `component=<Name>`, and passes `Extensions` validation.
- [ ] **AC-4**: every degrade reason is reachable — `component_not_inline`, `config_unparseable`, a feasibility code, `catalog_validation_failed`, `unexpected_error`.
- [ ] **AC-5 (G3)**: no exception escapes `emit_inline_component` for any input, including `None` config, a malformed response object, and a component that fails catalog validation.
- [ ] **AC-6**: on every degraded outcome `a2ui_envelope` stays `None` and `response.output_mode` is left untouched.
- [ ] **AC-7**: `metadata["a2ui_inline"]` is written on both outcomes.
- [ ] No import of `StructuredOutputBase` or anything from `ai-parrot-visualizations`; no agent/client import.
- [ ] `ruff check` clean on all three files.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/inline/test_emitter.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_emission_wiring.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/test_builders.py -q`

---

## Test Specification

Create `packages/ai-parrot/tests/outputs/a2ui/inline/test_emitter.py` per the blueprint, using the spec's `kpi_response`
fixture shape (§4 Test Data / Fixtures).

The degrade tests are the important ones: assert for each reason that nothing raised,
`a2ui_envelope is None`, and `response.output_mode` is unchanged from its pre-call
value. That triple is what keeps a failed emit invisible to the user instead of
producing an empty bubble.

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

**Completed by**: sdd-worker orchestrator; implemented by codex/gpt-5.6-sol (attempt 1, 293s)
**Date**: 2026-10-27
**Notes**: Added inline/emitter.py, inline/__init__.py package exports, and test_emitter.py. Merge-tier validation (chunk 2) green: 337 passed. Reviewed for file fidelity only (no line-level diff review). Closed via close_task.sh (no durable review EvidenceRef available for finalize_task).

**Deviations from spec**: none
