# TASK-4774: build_mermaid_diagram builder (M3)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4773
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / G5, D3. The one deterministic Python entry point every tool/adapter uses. It
normalizes BEFORE building, so a directive never reaches validation from the tool lane.

---

## Scope

- Add `build_mermaid_diagram` to `builders.py`, immediately before `def build_graph(`; add it to `__all__`.
- Import `detect_diagram_type`, `normalize_mermaid_source` next to the graph imports.
- Write `test_builders_mermaid.py` (§4 M3 rows).

**NOT in scope**: the tool (TASK-4775); the conformance suite additions (TASK-4782).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` | MODIFY | new build_mermaid_diagram + __all__ entry + import |
| `packages/ai-parrot/tests/outputs/a2ui/test_builders_mermaid.py` | CREATE | M3 unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_surface  # verified: builders.py:79
from parrot.outputs.a2ui.catalog import ProducerOrigin  # verified: builders.py:36-40 already imports it
from parrot.outputs.a2ui.models import ComponentMetadata, CreateSurface  # verified: builders.py:54 already imports them
from parrot.outputs.a2ui.graph.mermaid_source import detect_diagram_type, normalize_mermaid_source  # created by TASK-4772
from parrot.outputs.a2ui.catalog.base import CatalogValidationError  # verified: catalog/base.py:317 (tests)
```

### Existing Signatures to Use
```python
# builders.py
__all__ = [ ... "build_graph", "build_html_document", ... ]  # lines 57-69; `    "build_html_document",` line 62
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                  data_model: dict[str, Any] | None = None, origin: ProducerOrigin = ProducerOrigin.LLM,
                  metadata: ComponentMetadata | None = None, surface_metadata: SurfaceMetadata | None = None) -> CreateSurface  # line 79
def build_html_document(*, title, html=None, src_url=None, theme=None, surface_id="html-document", metadata=None) -> CreateSurface  # line 278 (shape precedent)
def build_graph(  # line 330 — insert the new builder immediately BEFORE this line
# graph import block: `from parrot.outputs.a2ui.graph import (` … `)` lines 42-53
```

### Does NOT Exist
- ~~`builders.build_mermaid_diagram`~~ — new in this task.
- ~~a Python-side pre-check before `build_surface`~~ — forbidden: one validation path (`validate_envelope`).
- ~~`ProducerOrigin.LLM` as default~~ — default is TOOL, like `build_graph`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/outputs/a2ui/builders.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/outputs/a2ui/test_builders_mermaid.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_surface",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/builders.py#build_html_document"
  ]
}
```

---

## Implementation Notes

- Explicit `theme` argument wins over the lifted one.
- `diagram_type` argument is passed through as `diagramType` WITHOUT overriding — a wrong declared type must surface as
  `CatalogValidationError` (`test_build_mermaid_diagram_rejects_declared_mismatch`).
- Purity: identical inputs → byte-identical envelope (compare `model_dump_json()` twice).

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Add the import next to the graph imports — *why*: builder normalizes before building.
2. Insert `build_mermaid_diagram` before `def build_graph(` — *why*: spec §6 edit site.
3. Add `"build_mermaid_diagram",` to `__all__` after `"build_html_document",` — *why*: `test_build_mermaid_diagram_in_all`.
4. Write tests; run Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/builders.py` (MODIFY)
```python
# (a) occurrences: 1 (verified: grep -c '    "build_html_document",' builders.py) — line 62; AFTER it add:
    "build_mermaid_diagram",

# (b) AFTER the `from parrot.outputs.a2ui.graph import (...)` block (ends line 53) add:
from parrot.outputs.a2ui.graph.mermaid_source import detect_diagram_type, normalize_mermaid_source

# (c) occurrences: 1 (verified: grep -c 'def build_graph(' builders.py) — line 330; insert BEFORE it:
def build_mermaid_diagram(
    *,
    source: str,
    title: str | None = None,
    caption: str | None = None,
    theme: str | None = None,
    accessible_description: str | None = None,
    diagram_type: str | None = None,
    surface_id: str = "mermaid-diagram",
    origin: ProducerOrigin = ProducerOrigin.TOOL,
    metadata: ComponentMetadata | None = None,
) -> CreateSurface:
    """Build a validated single-component ``MermaidDiagram`` ``CreateSurface`` (FEAT-753).

    Normalizes ``source`` first (directives stripped, ``theme`` lifted — an explicit ``theme`` wins),
    fills ``diagramType`` from :func:`detect_diagram_type` unless given, then delegates to
    :func:`build_surface`. Pure: same input -> byte-identical envelope.

    Args:
        source: Mermaid source.
        title: Optional title.
        caption: Optional caption.
        theme: Optional theme hint (``default``/``neutral``/``dark``/``forest``/``base``).
        accessible_description: One-sentence screen-reader summary.
        diagram_type: Declared type; a mismatch with the detected one fails validation.
        surface_id: Envelope surface id.
        origin: Producer origin (default TOOL; pass ``ProducerOrigin.LLM`` to apply the LLM gates).
        metadata: Optional component-level metadata forwarded to ``build_surface``.

    Returns:
        The validated ``CreateSurface``.

    Raises:
        CatalogValidationError: size cap, unsafe statement, or declared ``diagram_type`` mismatch.
    """
    normalized, lifted_theme = normalize_mermaid_source(source)
    props: dict[str, Any] = {
        "source": normalized,
        "diagramType": diagram_type or detect_diagram_type(normalized),
    }
    # FILL IN: add "title", "caption", "theme" (theme or lifted_theme), "accessibleDescription" only when not None
    return build_surface("MermaidDiagram", props, surface_id=surface_id, origin=origin, metadata=metadata)
```
**Why**: spec §3 M3 skeleton; `build_html_document` shape (props only when set).

### `packages/ai-parrot/tests/outputs/a2ui/test_builders_mermaid.py` (CREATE)
```python
"""FEAT-753 M3 — build_mermaid_diagram."""

from __future__ import annotations

import pytest

from parrot.outputs.a2ui import builders
from parrot.outputs.a2ui.builders import build_mermaid_diagram
from parrot.outputs.a2ui.catalog import ProducerOrigin
from parrot.outputs.a2ui.catalog.base import CatalogValidationError

SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"
DIRECTIVE_SRC = '%%{init: {"theme": "dark", "flowchart": {"htmlLabels": true}}}%%\nflowchart TD\n    a --> b\n'


def test_build_mermaid_diagram_in_all() -> None:
    assert "build_mermaid_diagram" in builders.__all__


# FILL IN: test_build_mermaid_diagram_normalizes_and_detects (AC-3: no directive, theme dark, diagramType flowchart,
#   byte-identical across two calls, explicit theme= wins), test_build_mermaid_diagram_rejects_declared_mismatch,
#   test_build_mermaid_diagram_llm_origin_passes
```

### FILL IN checklist
- [ ] optional props in `build_mermaid_diagram`
- [ ] the M3 test bodies (AC-3)

---

## Acceptance Criteria

- [ ] AC-3 holds (`build_mermaid_diagram(source=DIRECTIVE_SRC)` → no directive, `theme="dark"`, `diagramType="flowchart"`, deterministic).
- [ ] `test_builders.py` and `test_builders_graph.py` still green.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_builders_mermaid.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_builders.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/outputs/a2ui/test_builders_graph.py -q`

---

## Test Specification

See the test-file block above.

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
**Notes**: Added `build_mermaid_diagram` (+ `__all__`, import) to builders.py and 6 tests; test_builders*.py and test_lazy_imports.py green.

**Deviations from spec**: none
