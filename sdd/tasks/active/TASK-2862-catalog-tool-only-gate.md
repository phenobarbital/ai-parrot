# TASK-2862: `tool_only` registration gate — reject tool-only components in LLM-origin envelopes

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces, §3 Module 4, §7 "HtmlDocument is an HTML injection vector if
LLM-authorable". The catalog already gates action-bearing components by producer origin
(`requires_actions`, D10b: `ProducerOrigin.LLM` envelopes may not contain them). `HtmlDocument`
(TASK-2863) carries raw HTML and must be **tool-only**: deterministic tool builders may emit it,
the LLM producer path may not. This task adds the generic gate; no component uses it yet.

---

## Scope

- `catalog/base.py` — `ComponentDefinition` (`:220-248`) gains `tool_only: bool = False` with a
  docstring line ("Only deterministic tool producers may emit this component; LLM-origin
  envelopes containing it fail validation").
- `catalog/__init__.py` — `register_component()` (`:107-115`) gains keyword `tool_only: bool = False`
  and forwards it into the `ComponentDefinition` (`:156` area). `validate_envelope()` (`:386+`):
  next to the `requires_actions` check (`:490`), when `origin is ProducerOrigin.LLM` and the entry's
  `definition.tool_only` is true, append a `CatalogValidationError`-style problem
  ("component '<name>' is tool-only and cannot appear in an LLM-produced envelope") — same
  "report ALL problems" collection semantics as the existing check.
- `catalog/export.py` — if the exported catalog document lists per-component flags (check for
  `requires_actions` there), include `tool_only` alongside it; otherwise no change.
- Tests: `tests/outputs/a2ui/catalog/test_validation_v1.py` (extend) — register a throwaway
  component with `tool_only=True` under a test catalog id and assert LLM-origin rejection vs
  TOOL-origin acceptance; `tests/outputs/a2ui/test_catalog.py` for the definition default.

**NOT in scope**: the `HtmlDocument` component itself (TASK-2863); renderers; toolkit changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py` | MODIFY | `ComponentDefinition.tool_only` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | `register_component(tool_only=)`, `validate_envelope` gate |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py` | MODIFY (maybe) | export the flag if flags are exported |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_validation_v1.py` | MODIFY | origin gate tests |
| `packages/ai-parrot/tests/outputs/a2ui/test_catalog.py` | MODIFY | default `tool_only=False` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component, validate_envelope  # catalog/__init__.py:107, (get_component), :386
from parrot.outputs.a2ui.catalog.base import (ProducerOrigin, ComponentDefinition, RegisteredComponent,
    CatalogValidationError, ComponentContractError, DEFAULT_CATALOG_ID, BasicNode, BasicTree)   # base.py:85,220,275,299,291,53,97
from parrot.outputs.a2ui.models import Component, CreateSurface, UpdateComponents              # used by validate_envelope signature :387
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py
class ProducerOrigin(str, Enum): TOOL = "tool"; LLM = "llm"                          # :85-95 (docstring: LLM path is display-only, MUST NOT emit requires_actions)
class ComponentDefinition(BaseModel):                                                # :220
    name: str; catalog_id: str = DEFAULT_CATALOG_ID; schema_: dict = Field(alias="schema"); instructions: str = ""
    requires_actions: bool = False; is_primitive: bool = False
    allowed_parents: list[str] | None = None; allowed_children: list[str] | None = None   # :241-248 ← add tool_only
class RegisteredComponent:  # :275  (holds .definition and the component class)
class CatalogValidationError(CatalogError)  # :299

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py
def register_component(name: str, *, requires_actions: bool = False, catalog_id: str = DEFAULT_CATALOG_ID,
                       is_primitive: bool = False, allowed_parents: list[str] | None = None,
                       allowed_children: list[str] | None = None) -> Callable[[type], type]   # :107-115 ; builds ComponentDefinition(... requires_actions=requires_actions ...) :156
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None                     # :386-390 ; "Reports ALL problems found" :393-395
    # requires_actions gate: `entry_for_gate is not None and entry_for_gate.definition.requires_actions` :490  ← MIRROR
# basic primitives register via register_component(cls.__name__, catalog_id=BASIC_CATALOG_ID, is_primitive=True) — catalog/basic/__init__.py:202
```

### Does NOT Exist
- ~~`Origin`~~ enum — the class is `ProducerOrigin` (`base.py:85`).
- ~~`validate_envelope(..., strict=True)`~~ or any per-call allowlist parameter — only `origin` and `surface_catalog_id`.
- ~~`ComponentDefinition.tool_only`~~ — added by this task.
- ~~`build_surface(origin=ProducerOrigin.TOOL)` default~~ — `build_surface` defaults to `origin=ProducerOrigin.LLM` (`builders.py:57`); tool-only surfaces must pass `origin=ProducerOrigin.TOOL` explicitly (relevant to TASK-2863).

---

## Implementation Notes

### Pattern to Follow
The `requires_actions` gate at `catalog/__init__.py:485-495`: look up the registered entry for
the component name, check the definition flag, append a problem string to the collected list;
raise once at the end with all problems.

### Key Constraints
- Additive: every existing `register_component(...)` call keeps working (default `False`).
- Do not change `ProducerOrigin` semantics for `requires_actions`.
- Golden fixtures are unaffected (no lowering change).

### References in Codebase
- `packages/ai-parrot/tests/outputs/a2ui/catalog/test_validation_v1.py` — validation test style (origin parametrisation).
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py` — check whether flags are exported.

---

## Acceptance Criteria

- [ ] `register_component("X", tool_only=True)` sets `definition.tool_only is True`; default is `False`
- [ ] `validate_envelope(env_with_X, origin=ProducerOrigin.LLM)` raises `CatalogValidationError` naming `X`; `origin=ProducerOrigin.TOOL` passes
- [ ] The tool-only problem is reported together with other problems (not first-failure)
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/outputs/a2ui -q` green; `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog`

---

## Test Specification

```python
# tests/outputs/a2ui/catalog/test_validation_v1.py (add)
TEST_CATALOG = "https://parrot.dev/catalogs/test-tool-only"

@register_component("ToolOnlyProbe", catalog_id=TEST_CATALOG, tool_only=True)
class _ToolOnlyProbe:
    SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
    INSTRUCTIONS = ""
    def lower(self, component, data_model):
        return BasicTree(root=BasicNode(component="Text", text=component.model_extra.get("title", "")))

def _env():
    return CreateSurface(surfaceId="s", catalogId=TEST_CATALOG, components=[Component(id="root", component="ToolOnlyProbe", title="t")], dataModel={})

def test_tool_only_rejected_for_llm_origin():
    with pytest.raises(CatalogValidationError, match="ToolOnlyProbe"):
        validate_envelope(_env(), origin=ProducerOrigin.LLM, surface_catalog_id=TEST_CATALOG)

def test_tool_only_accepted_for_tool_origin():
    validate_envelope(_env(), origin=ProducerOrigin.TOOL, surface_catalog_id=TEST_CATALOG)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — read `catalog/__init__.py:380-500` fully to place the gate next to `requires_actions`
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2862-catalog-tool-only-gate.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
