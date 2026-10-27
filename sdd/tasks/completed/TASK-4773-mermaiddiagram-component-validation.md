# TASK-4773: MermaidDiagram catalog component + validate_envelope pass (M2)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4772
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 / G1, G2, G3, decisions D1–D3, D6. Registers the opaque, LLM-authorable
`MermaidDiagram` Parrot-catalog component (schema, instructions, lowering) and adds the envelope-level gate
`_validate_mermaid_sources` that runs for EVERY origin and for both `CreateSurface` and `UpdateComponents`.

---

## Scope

- Create `catalog/parrot/mermaiddiagram.py` (`MERMAIDDIAGRAM_SCHEMA`, `MERMAIDDIAGRAM_INSTRUCTIONS`,
  `MermaidDiagramComponent` with `lower()`), following the `htmldocument.py` layout.
- Import it in `catalog/parrot/__init__.py` for its registration side effect.
- Add `_validate_mermaid_sources` to `catalog/__init__.py` and call it after the linked-sources block, at
  function-body indentation, BEFORE `if issues:`.
- Write `test_components_mermaiddiagram.py` (§4 M2 rows) and freeze `golden/mermaiddiagram_lowered.json`.

**NOT in scope**: the builder (TASK-4774); renderer degradations (TASK-4777/4778/4779); docs (TASK-4783); adding `MermaidDiagram` to any renderer's `supported_components`/`_INTERCEPTED` (D5 forbids it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py` | CREATE | registered component: schema, instructions, lower() |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py` | MODIFY | import mermaiddiagram for registration |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | import check_mermaid_source + _validate_mermaid_sources pass |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_mermaiddiagram.py` | CREATE | M2 unit tests |
| `packages/ai-parrot/tests/outputs/a2ui/golden/mermaiddiagram_lowered.json` | CREATE | frozen lowered tree |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, validate_envelope, catalog_instructions, DEFAULT_CATALOG_ID, ProducerOrigin  # verified: catalog/__init__.py:71-93 (__all__), :114, :209, :743, :314
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, CatalogValidationError  # verified: catalog/base.py:111, :170, :317
from parrot.outputs.a2ui.catalog.export import export_catalog_definition  # verified: catalog/export.py:215
from parrot.outputs.a2ui.models import Component, CreateSurface  # verified: models.py:400, :446
from parrot.outputs.a2ui.graph.mermaid_source import (  # created by TASK-4772
    MERMAID_DIAGRAM_TYPES, MERMAID_SOURCE_MAX_BYTES, MERMAID_THEMES, check_mermaid_source, detect_diagram_type,
)
```

### Existing Signatures to Use
```python
# catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID, is_primitive: bool = False,
                       allowed_parents: list[str] | None = None, allowed_children: list[str] | None = None, tool_only: bool = False)  # line 114
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None  # line 743
#   issues: list[dict[str, Any]] each {"code", "message", "path"}
    if isinstance(envelope, CreateSurface):                                   # line 963
        _validate_linked_sources(envelope, origin=origin, issues=issues)      # line 964
                                                                              # line 965 blank
    if issues:                                                                # line 966
#   import block from catalog.base: `    TRANSFORM_REF_UNKNOWN,` at line 48 (inside `from parrot.outputs.a2ui.catalog.base import (` L37-61)

# catalog/parrot/__init__.py — alphabetical side-effect imports; `    htmldocument,  # noqa: F401` line 17, `    map,` line 21

# catalog/parrot/htmldocument.py — layout precedent
@register_component("HtmlDocument", allowed_parents=["root", "Column"], tool_only=True)  # line 60
class HtmlDocumentComponent:  # line 61 — SCHEMA, INSTRUCTIONS, def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree (line 67)
#   lower returns BasicNode(id=component.id, component="Card", child=BasicNode(component="Column", children=[...]),
#                           metadata={"extensions": {"parrot_variant": "html-document"}})
# Component: extra="allow" — wire props live in component.model_extra (models.py:400)
```

### Does NOT Exist
- ~~a per-component `validate()` hook~~ — `register_component` only enforces `lower()` (catalog/__init__.py:160-168); component checks are hard-coded passes inside `validate_envelope` (precedent `_validate_filter_params` :521).
- ~~`derive_schema` for this component~~ — the schema is hand-written (D2).
- ~~`tool_only=True`~~ — MermaidDiagram is LLM-authorable (G1); `test_validate_envelope_llm_origin_accepts_clean_source` is the inverse of the HtmlDocument gate test.
- ~~a committed Parrot `catalog_definition.json`~~ — nothing to regenerate.
- ~~`catalog/parrot/mermaid.py`~~ — the module name is `mermaiddiagram.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/test_components_mermaiddiagram.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/golden/mermaiddiagram_lowered.json",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#register_component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py#validate_envelope",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py#BasicNode",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#Component",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/htmldocument.py#HtmlDocumentComponent"
  ]
}
```

---

## Implementation Notes

- Import in `catalog/__init__.py` at MODULE level is cycle-free (mermaid_source imports only `catalog.base` + `graph.*`).
  `graph/__init__.py` imports `layout`/`models` only — verify the fresh-interpreter probe from TASK-4772 still passes.
- `_validate_mermaid_sources` iterates `envelope.components`, filters `c.component == "MermaidDiagram"`, reads
  `source`/`diagramType` from `c.model_extra`, maps each `MermaidSourceIssue` to `{"code","message","path": c.id}`.
  A missing/non-string source → one `MERMAID_SOURCE_TOO_LARGE` issue "empty source".
- Lowered tree is spec §2 "Lowered tree" table exactly; description text defaults to `f"Mermaid {diagram_type} diagram"`.
- Golden: produce ONCE by dumping `lower(...)` of the §4 fixture component (`_mermaid_component()`), then freeze.
  Use the same `_dump` helper style as `test_components_htmldocument.py:41-45`.
- Instructions text = spec §7 "LLM instructions" verbatim (one string, implicit concatenation).

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Create `mermaiddiagram.py` from the block — *why*: registration side effect + schema/instructions are what FEAT-755 consumes.
2. Add the import in `catalog/parrot/__init__.py` after `map,` (alphabetical) — *why*: the package import registers every Parrot composite.
3. Add the import + `_validate_mermaid_sources` + call site in `catalog/__init__.py` — *why*: G2 gate for every producer.
4. Write tests and freeze the golden.
5. ruff/black + Validation Commands (the existing catalog/htmldocument/graph suites must stay green — AC-11).

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/mermaiddiagram.py` (CREATE)
```python
"""A2UI ``MermaidDiagram`` catalog component (FEAT-753, Module 2).

The second opaque Parrot-catalog component after ``HtmlDocument`` — with the opposite trust posture:
Mermaid source is a declarative text DSL, so the component is LLM-authorable (NOT ``tool_only``). Safety
lives in :func:`~parrot.outputs.a2ui.graph.mermaid_source.check_mermaid_source`, run by
``validate_envelope`` for every origin. Python never draws: ``lower()`` emits a readable Basic tree whose
last Text carries the exact source under ``parrot_role: "mermaid-source"``.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.catalog import register_component
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree
from parrot.outputs.a2ui.graph.mermaid_source import (
    MERMAID_DIAGRAM_TYPES,
    MERMAID_SOURCE_MAX_BYTES,
    MERMAID_THEMES,
    detect_diagram_type,
)
from parrot.outputs.a2ui.models import Component

MERMAIDDIAGRAM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "minLength": 1,
            "maxLength": MERMAID_SOURCE_MAX_BYTES,
            "description": "Mermaid diagram source. No %%{init}%% directives, no click/link/callback statements.",
        },
        "diagramType": {
            "type": "string",
            "enum": list(MERMAID_DIAGRAM_TYPES),
            "description": "Detected from the first statement of `source`; a mismatch fails validation.",
        },
        "title": {"type": "string"},
        "caption": {"type": "string"},
        "theme": {
            "type": "string",
            "enum": list(MERMAID_THEMES),
            "description": "Renderer hint only; the renderer may override it with the host theme.",
        },
        "accessibleDescription": {
            "type": "string",
            "description": "Screen-reader summary; first line of the lowered fallback.",
        },
    },
    "required": ["source"],
}

MERMAIDDIAGRAM_INSTRUCTIONS = (
    # FILL IN: spec §7 "LLM instructions" verbatim, as implicit string concatenation — bounded by AC-9
)


@register_component("MermaidDiagram", allowed_parents=["root", "Column"])
class MermaidDiagramComponent:
    """The ``MermaidDiagram`` Parrot-catalog component: opaque, display-only Mermaid source."""

    SCHEMA = MERMAIDDIAGRAM_SCHEMA
    INSTRUCTIONS = MERMAIDDIAGRAM_INSTRUCTIONS

    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:
        """Lower to ``Card{Column[description, title?, caption?, source]}`` (spec §2 "Lowered tree").

        Deterministic: identical input -> byte-identical tree. Never validates (``validate_envelope`` did).
        """
        props = component.model_extra or {}
        source = str(props.get("source") or "")
        diagram_type = props.get("diagramType") or detect_diagram_type(source)
        theme = props.get("theme")
        children: list[BasicNode] = [
            BasicNode(
                component="Text",
                text=props.get("accessibleDescription") or f"Mermaid {diagram_type} diagram",
                metadata={"extensions": {"parrot_role": "description"}},
            ),
        ]
        # FILL IN: optional title Text (parrot_role "title") then caption Text (parrot_role "caption") — order fixed by spec §2
        source_ext: dict[str, Any] = {"parrot_role": "mermaid-source", "parrot_diagram_type": diagram_type}
        if theme:
            source_ext["parrot_mermaid_theme"] = theme
        children.append(BasicNode(component="Text", text=source, metadata={"extensions": source_ext}))
        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "mermaid-diagram"}},
        )
```
**Why this shape**: D1 (Parrot catalog, default flags), D2 (hand-written schema), spec §2 lowered tree.
The schema derives `enum`/`maxLength` from the M1 constants so `test_schema_shape` can never drift.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    map,' catalog/parrot/__init__.py) — line 21
# AFTER — insert below `    map,` (keeps alphabetical order):
    mermaiddiagram,  # noqa: F401
```
**Why**: the package import is what registers every Parrot composite.

### `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` (MODIFY)
```python
# (a) module-level import — place right after the `from parrot.outputs.a2ui.catalog.base import (...)` block
#     (that block contains `    TRANSFORM_REF_UNKNOWN,` — occurrences: 1, line 48; block ends line 61)
from parrot.outputs.a2ui.graph.mermaid_source import check_mermaid_source

# (b) call site — occurrences: 1 (verified: grep -c '        _validate_linked_sources(envelope, origin=origin, issues=issues)') line 964
#     Replace lines 963-966 so they read:
    if isinstance(envelope, CreateSurface):
        _validate_linked_sources(envelope, origin=origin, issues=issues)

    _validate_mermaid_sources(envelope, issues)

    if issues:

# (c) helper — define next to _validate_linked_sources (module level, before validate_envelope):
def _validate_mermaid_sources(envelope: CreateSurface | UpdateComponents, issues: list[dict[str, Any]]) -> None:
    """Append one issue per :func:`check_mermaid_source` finding for every ``MermaidDiagram`` component.

    Runs for EVERY origin and for BOTH CreateSurface and UpdateComponents (FEAT-753 G2). Each issue is
    ``{"code", "message", "path": <component id>}``. A missing/non-string ``source`` is reported as
    ``MERMAID_SOURCE_TOO_LARGE`` ("empty source").
    """
    for comp in envelope.components:
        if comp.component != "MermaidDiagram":
            continue
        props = comp.model_extra or {}
        # FILL IN: source = props.get("source"); non-str -> ""; declared = props.get("diagramType");
        #   for finding in check_mermaid_source(source, declared_type=declared): issues.append({...,"path": comp.id})
```
**Why**: spec §3 M2 — the pass must NOT be nested under `isinstance(envelope, CreateSurface)`. Verify
`UpdateComponents` is already imported in `catalog/__init__.py` (it is used in `validate_envelope`'s signature).

### `packages/ai-parrot/tests/outputs/a2ui/test_components_mermaiddiagram.py` (CREATE)
```python
"""FEAT-753 M2 — MermaidDiagram registration, schema, lowering golden and validation gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import parrot.outputs.a2ui.catalog.parrot  # noqa: F401 — registration
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin, catalog_instructions, get_component, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.catalog.parrot.mermaiddiagram import MERMAIDDIAGRAM_INSTRUCTIONS, MermaidDiagramComponent
from parrot.outputs.a2ui.models import Component, CreateSurface

GOLDEN = Path(__file__).parent / "golden" / "mermaiddiagram_lowered.json"
SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"


def _mermaid_component() -> Component:
    return Component(id="blk-000", component="MermaidDiagram", source=SEQUENCE_SRC, diagramType="sequence",
                     title="Login flow", caption="Happy path", theme="neutral", accessibleDescription="Alice greets Bob")


# FILL IN: test_registration_flags, test_schema_shape, test_lowering_golden, test_lowering_roles_and_extensions,
#   test_lowering_emits_only_basic_primitives, test_validate_envelope_llm_origin_accepts_clean_source,
#   test_validate_envelope_rejects_unsafe_for_both_origins, test_validate_mermaid_create_and_update,
#   test_instructions_in_catalog_instructions (AC-9) — spec §4 M2 rows
```

### FILL IN checklist
- [ ] `MERMAIDDIAGRAM_INSTRUCTIONS` — spec §7 verbatim
- [ ] `lower()` title/caption children — order description/title/caption/source
- [ ] `_validate_mermaid_sources` loop body — path = component id, every finding
- [ ] the 9 M2 test bodies + freeze `golden/mermaiddiagram_lowered.json` (`json.dumps(..., indent=2, sort_keys=True)`)

---

## Acceptance Criteria

- [ ] AC-1: `get_component("MermaidDiagram")` flags as specified; `export_catalog_definition()` lists it.
- [ ] AC-2: unsafe sources rejected for both origins and both message kinds, `path == component id`.
- [ ] AC-4 (unit part): lowering golden-stable and Basic-only.
- [ ] AC-9: `MERMAIDDIAGRAM_INSTRUCTIONS` appears in `catalog_instructions()`.
- [ ] Existing catalog / htmldocument / graph / parity / lazy-import suites green (AC-11).

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_components_mermaiddiagram.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_components_htmldocument.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_lazy_imports.py -q`

---

## Test Specification

See the test-file block — one function per §4 M2 row; parametrize TOOL/LLM × CreateSurface/UpdateComponents.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-mermaid-diagram --feature-id FEAT-753`).
2. **Read the spec** `sdd/specs/a2ui-mermaid-diagram.spec.md` (§2 decisions D1–D7, §6 contract, §7 constraints).
3. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/a2ui-mermaid-diagram.json`.
4. **Verify the Codebase Contract** — re-run the `grep -c` of every MODIFY anchor before editing; a count of 0 is drift: stop and report.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** the blueprint, then complete every `FILL IN` — touch only the files listed above.
7. **Validate**: `ruff check --fix <files>`, `black -l 120 <files>`, then the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src`.
8. **Close** with `scripts/sdd/close_task.sh <TASK-ID> a2ui-mermaid-diagram verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-10-27
**Notes**: Added `catalog/parrot/mermaiddiagram.py` (schema, instructions, lower), registration import, `_validate_mermaid_sources` pass (every origin, Create + Update), tests and frozen golden. 170 tests green across the M2 file, test_catalog, parity, htmldocument, lazy_imports and graph/. `UpdateComponents` validation needs `surface_catalog_id=` (it carries no catalog id), so the tests pass `DEFAULT_CATALOG_ID` via a `_validate` helper. Test components use `id="root"`.

**Deviations from spec**: none
