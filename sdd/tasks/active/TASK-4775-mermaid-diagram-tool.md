# TASK-4775: MermaidDiagramTool (render_mermaid_diagram) + parrot_tools mapping (M4)

**Feature**: FEAT-753 — A2UI MermaidDiagram (opaque Mermaid-source component in the Parrot catalog)
**Spec**: `sdd/specs/a2ui-mermaid-diagram.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4774
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / G5, D7. Lets any agent emit a diagram deterministically from text it already has.
The dict result is lifted by the bot into `response.a2ui_envelope` through the FEAT-611 lift, which TASK-4776
generalizes to `type: "a2ui_surface"`. Q5 (tool name) is open: use `render_mermaid_diagram` / mapping key
`mermaid_diagram` as the spec proposes unless the user overrides.

---

## Scope

- Create `parrot_tools/mermaid_diagram.py` with `MermaidDiagramArgs` + `MermaidDiagramTool`.
- Add the mapping entry `"mermaid_diagram": "parrot_tools.mermaid_diagram.MermaidDiagramTool",` after `publish_surface`.
- Write `packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py`.

**NOT in scope**: the bot lift membership test (TASK-4776); any LLM routing (FEAT-755).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/mermaid_diagram.py` | CREATE | args schema + tool |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | name → dotted-path mapping entry |
| `packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py` | CREATE | M4 tool tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `65144d730` (2026-10-27). Use these exact imports, names and
> signatures. If you need something not listed here, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.outputs.a2ui.builders import build_mermaid_diagram  # created by TASK-4774
from parrot.outputs.a2ui.catalog.base import CatalogValidationError  # verified: catalog/base.py:317
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema  # verified: parrot/tools/abstract.py:282, :238
from pydantic import Field  # verified: parrot_tools/ui_surfaces.py:27
```

### Existing Signatures to Use
```python
# parrot/tools/abstract.py
class AbstractToolArgsSchema(BaseModel)  # line 238
class AbstractTool(EventEmitterMixin, ABC): name: str; description: str; args_schema: Type[BaseModel]  # line 282, 296-299
    async def _execute(self, **kwargs) -> Any  # line 604 (subclass hook)
    async def execute(self, *args, **kwargs) -> ToolResult  # line 916 — wraps exceptions into a failed ToolResult
    def get_schema(self) -> dict  # used by test_publish_surface_tool.py:33 → schema["parameters"]["properties"]

# parrot_tools/ui_surfaces.py — precedent
class PublishSurfaceTool(AbstractTool): name = "publish_surface"; description; args_schema = PublishSurfaceArgs  # line 65
    async def _execute(self, *, kind, title, envelope, ..., **kwargs) -> dict[str, Any]  # line 127

# parrot_tools/__init__.py
    "publish_surface": "parrot_tools.ui_surfaces.PublishSurfaceTool",  # line 127 (inside the name → dotted-path dict)
```

### Does NOT Exist
- ~~`parrot_tools.mermaid_diagram`~~ / ~~`MermaidDiagramTool`~~ — new in this task.
- ~~adding `version` to the returned envelope~~ — the result carries the BARE `CreateSurface` dump; `_wrap_create_surface` adds `version` at lift time (bots/base.py:1044).
- ~~catching `CatalogValidationError` inside `_execute`~~ — let it propagate; `execute()` turns it into a failed `ToolResult`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/mermaid_diagram.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractToolArgsSchema",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool"
  ]
}
```

---

## Implementation Notes

- Result shape is fixed by spec §2 "Tool result shape".
- Tool docstring must mention the lift precedence (spec §7: do not call alongside an infographic render).
- Also reachable as `parrot.tools.mermaid_diagram` via the meta_path finder — test it like `test_publish_surface_tool.py` imports `parrot.tools.ui_surfaces`.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then
> complete every `# FILL IN:` marker. Never change a signature, class name or file path fixed here.

### Steps (in order)
1. Create the tool module — *why*: deterministic producer (G5).
2. Add the mapping entry — *why*: `test_tool_registered_in_mapping`, AC-6.
3. Write tests; run Validation Commands.

### `packages/ai-parrot-tools/src/parrot_tools/mermaid_diagram.py` (CREATE)
```python
"""``MermaidDiagramTool`` — render Mermaid source as an inline A2UI ``MermaidDiagram`` surface (FEAT-753).

Reachable via the legacy path too (``parrot.tools`` meta_path finder):
``from parrot.tools.mermaid_diagram import MermaidDiagramTool``.
"""

from __future__ import annotations

from typing import Any

from parrot.outputs.a2ui.builders import build_mermaid_diagram
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from pydantic import Field


class MermaidDiagramArgs(AbstractToolArgsSchema):
    """Arguments for rendering a Mermaid diagram as an inline A2UI surface."""

    source: str = Field(
        description=(
            "Mermaid source (flowchart, sequenceDiagram, classDiagram, erDiagram, gantt, pie, mindmap, …). "
            "No %%{init}%% directives, no click statements."
        )
    )
    title: str | None = Field(default=None, description="Optional title shown above the diagram.")
    caption: str | None = Field(default=None, description="Optional caption shown below the diagram.")
    theme: str | None = Field(
        default=None, description="Optional Mermaid theme hint: default, neutral, dark, forest, base."
    )
    accessible_description: str | None = Field(
        default=None, description="One-sentence screen-reader summary of what the diagram shows."
    )


class MermaidDiagramTool(AbstractTool):
    """Render Mermaid source as an inline A2UI ``MermaidDiagram`` surface.

    Use it when the answer is best shown as a diagram (sequence, class, ER, state, flowchart, gantt, pie,
    mindmap, gitGraph, C4, …). The source is validated (size cap, no init directives, no click/javascript
    statements) and returned as an A2UI envelope the chat UI renders inline; text-only channels show the
    source. The bot lifts the envelope only when no interactive/infographic envelope was produced in the
    same turn — do not call it alongside an infographic render.
    """

    name = "render_mermaid_diagram"
    description = (
        "Render Mermaid diagram source (sequence, class, ER, state, flowchart, gantt, pie, mindmap, C4, …) as an "
        "inline A2UI diagram surface; pass source and optionally title, caption, theme, accessible_description."
    )
    args_schema = MermaidDiagramArgs

    async def _execute(
        self,
        *,
        source: str,
        title: str | None = None,
        caption: str | None = None,
        theme: str | None = None,
        accessible_description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return the lift-shaped dict (spec §2 "Tool result shape").

        Raises:
            CatalogValidationError: invalid source — propagated so ``execute()`` reports the issue codes.
        """
        envelope = build_mermaid_diagram(
            source=source, title=title, caption=caption, theme=theme, accessible_description=accessible_description
        )
        root = envelope.components[0].model_extra or {}
        diagram_type = root.get("diagramType")
        # FILL IN: return {"a2ui_envelope": envelope.model_dump(by_alias=True, mode="json"),
        #   "artifacts": [{"type": "a2ui_surface", "component": "MermaidDiagram", "surface_id": envelope.surface_id,
        #   "diagram_type": diagram_type}], "diagram_type": diagram_type, "source": root.get("source")} — bounded by spec §2
```
**Why**: spec §3 M4 skeleton; `self.logger` exists on `AbstractTool` — add a `self.logger.debug` line with the diagram type.

### `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "publish_surface": "parrot_tools.ui_surfaces.PublishSurfaceTool",' parrot_tools/__init__.py) — line 127
# AFTER it:
    "mermaid_diagram": "parrot_tools.mermaid_diagram.MermaidDiagramTool",
```

### `packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py` (CREATE)
```python
"""FEAT-753 M4 — MermaidDiagramTool."""

from __future__ import annotations

import pytest
from parrot.tools.mermaid_diagram import MermaidDiagramArgs, MermaidDiagramTool

SEQUENCE_SRC = "sequenceDiagram\n    participant A as Alice\n    A->>B: hello\n"


def test_tool_schema_and_docstring() -> None:
    tool = MermaidDiagramTool()
    assert tool.name == "render_mermaid_diagram"
    assert tool.args_schema is MermaidDiagramArgs
    props = tool.get_schema()["parameters"]["properties"]
    for field in ("source", "title", "caption", "theme", "accessible_description"):
        assert field in props


# FILL IN: test_tool_execute_returns_lift_shape (await tool._execute(source=SEQUENCE_SRC); no "version" key in a2ui_envelope;
#   artifacts[0]["type"] == "a2ui_surface"; diagram_type == "sequence")
# FILL IN: test_tool_propagates_validation_error (click statement -> execute() returns a failed ToolResult whose error names
#   MERMAID_UNSAFE_INTERACTION, or _execute raises CatalogValidationError)
# FILL IN: test_tool_registered_in_mapping (resolve "mermaid_diagram" through the parrot_tools mapping -> MermaidDiagramTool;
#   find the mapping's variable name in parrot_tools/__init__.py before writing the assertion)
```

### FILL IN checklist
- [ ] `_execute` return dict — spec §2 shape exactly
- [ ] the three FILL IN tests (check the mapping dict's actual variable name first)

---

## Acceptance Criteria

- [ ] AC-6 (tool part): `render_mermaid_diagram` resolvable from the mapping, returns the §2 result shape.
- [ ] `test_publish_surface_tool.py` still green.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot-tools/tests/test_mermaid_diagram_tool.py -q`
- `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-visualizations/src pytest packages/ai-parrot-tools/tests/test_publish_surface_tool.py -q`

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

*(Agent fills this in when done)*

**Completed by**: [agent name]
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
