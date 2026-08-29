# TASK-2571: `export_functions`, `agent_capabilities`, and the two `AbstractTool` A2UI attributes

**Feature**: FEAT-469 — A2UI Agent Functions Runtime (v1.0 RPC leg)
**Spec**: `sdd/specs/a2ui-agent-functions.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2570
**Assigned-to**: unassigned

---

## Context

Implements **spec §3 Module 4** and goal **G4**. Without this, a v1.0 renderer
has no way to *discover* what it may invoke: the parrot catalog's
`catalog_definition.json` must declare each tool as a `FunctionDefinition` with
`allowedCallers` and `requiresUserActivation`, and the agent must publish an
`agent_capabilities` document.

Two `AbstractTool` class attributes are added here (both optional, both
defaulting to `False`, no signature change — spec's "sin cambios rompientes"):
- `a2ui_requires_user_activation` → `FunctionDefinition.requiresUserActivation`
- `a2ui_hidden` → excludes the tool from the export entirely (spec §8 resolved OQ)

`a2ui_hidden` is an **opt-OUT** escape hatch. The §8 decision stands: all
ToolManager tools are exposed by default; this only lets an operator hide a
specific destructive tool without reverting to an opt-in model.

---

## Scope

- Add `a2ui_requires_user_activation: bool = False` and `a2ui_hidden: bool = False`
  to `AbstractTool`.
- Implement `export_functions(executor)` → the `functions` map, **merged into**
  the existing `export_catalog_definition()` output.
- Implement `agent_capabilities(catalog_ids)`.
- UAX #31 name sanitization with an inverse map and hard failure on collision.
- Tests validating against the vendored `catalog_definition.json` and
  `agent_capabilities.json`.

**NOT in scope**: publishing capabilities on the Agent Card (TASK-2572) or over
HTTP (TASK-2573) — this task only produces the documents.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | Two optional class attributes on `AbstractTool` |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py` | MODIFY | `export_functions`, `agent_capabilities`, merge into `export_catalog_definition` |
| `packages/ai-parrot/tests/outputs/a2ui/catalog/test_export_functions.py` | CREATE | Unit tests |
| `packages/ai-parrot/tests/tools/test_tool_a2ui_attributes.py` | CREATE | Attribute defaults + inheritance |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ce716a032` (2026-08-29).

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import (            # catalog/__init__.py
    catalog_instructions,   # 205
    list_components,        # 176
    list_functions,         # 200
)
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, FunctionDefinition  # base.py:52, :246
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID, basic_components, load_spec
from parrot.tools.abstract import AbstractTool       # tools/abstract.py:235
```

### `export.py` as it exists TODAY — you are EXTENDING, not writing from scratch
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/export.py  (FEAT-470 TASK-2540)
__all__ = ["export_catalog_definition", "write_catalog_definition"]

def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID,
                              include_basic: bool = True) -> dict[str, Any]:
    """Returns {"$schema", "protocolVersion": "1.0", "catalogId",
                "instructions", "components", "functions"}"""

def write_catalog_definition(path: Path) -> None: ...
```
It **already builds a `functions` map** from two sources:
1. Every Basic Catalog function, copied **verbatim** from
   `load_spec("catalog")["functions"]`. The existing code carries an important
   comment explaining why: `catalog_definition.json#/$defs/FunctionDefinition`
   sets `unevaluatedProperties: false` and requires an inline `returnType`, so a
   bare `$ref` (which works for *components*) does **not** validate for
   *functions*. **Do not "optimise" these back into `$ref`s.**
2. Catalog-registered functions from `list_functions()`, emitted as
   `{**args_schema, "returnType", "allowedCallers", "requiresUserActivation"}`.

`export_functions(executor)` is a **third** source (the agent's tools) and must
**merge** into that same map. Follow the existing emission shape exactly.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/base.py:246
class FunctionDefinition(BaseModel):
    model_config = ConfigDict(populate_by_name=True)     # 259
    name: str                                            # 261
    catalog_id: str                                      # 262
    args_schema: dict[str, Any] = Field(default_factory=dict)   # 263
    return_type: str = "any"                             # 264
    allowed_callers: Literal["rendererOnly", "agentOnly", "rendererOrAgent"] = "rendererOnly"  # 265
    requires_user_activation: bool = False               # 266

# packages/ai-parrot/src/parrot/tools/abstract.py:235
class AbstractTool(EventEmitterMixin, ABC):
    async def _execute(self, **kwargs) -> Any:      # 490
    def get_schema(self) -> Dict[str, Any]:         # 502
    def get_tool_schema(self) -> Dict[str, Any]:    # 582
    async def execute(self, *args, **kwargs) -> ToolResult:   # 797

# packages/ai-parrot/src/parrot/tools/manager.py:1121
def get_tool_schemas(self, provider_format: ToolFormat = ToolFormat.GENERIC) -> List[Dict[str, Any]]:
    # each schema dict carries a '_tool_instance' key holding the tool object —
    # that is how you reach a2ui_hidden / a2ui_requires_user_activation
```

### Does NOT Exist
- ~~`AbstractTool.a2ui_requires_user_activation` / `.a2ui_hidden`~~ — this task adds both.
- ~~`AbstractTool.a2ui_exposed`~~ — explicitly rejected; the model is opt-OUT.
- ~~`export_functions` / `agent_capabilities` in `export.py`~~ — this task adds them.
- ~~a UAX #31 helper in the codebase~~ — none exists; you must write the sanitizer. `catalog/__init__.py:289` has `_unicode_aware_jsonschema()`, which is about jsonschema unicode handling, **not** identifier validation — do not mistake it for one.
- ~~`ToolDefinition` (the `@tool` decorator path) having these attributes~~ — it is a different type from `AbstractTool`; use `getattr(obj, "a2ui_hidden", False)` so both paths work.

---

## Implementation Notes

### The two attributes
```python
class AbstractTool(EventEmitterMixin, ABC):
    #: Whether invoking this tool as an A2UI function requires a direct user
    #: gesture. Surfaced as FunctionDefinition.requiresUserActivation; enforced
    #: by the RENDERER, never by the agent (spec §8).
    a2ui_requires_user_activation: bool = False

    #: Opt-OUT: exclude this tool from the exported A2UI function catalog and
    #: from callAgentFunction dispatch. Default False — all tools are exposed
    #: (spec §8). Use for destructive/return_direct tools.
    a2ui_hidden: bool = False
```
Class attributes with defaults — **no `__init__` signature change**, so every
existing tool and toolkit keeps working untouched.

### `export_functions(executor)`
```python
def export_functions(executor: "FunctionExecutor") -> dict[str, dict[str, Any]]:
```
Per tool: skip when `a2ui_hidden`; derive `args` from the tool's schema;
`returnType: "any"`; `allowedCallers: "rendererOrAgent"` (spec §2 — this is what
makes a tool renderer-invocable at all); `requiresUserActivation` from the attribute.

**Merge order matters.** Basic Catalog functions are protocol-defined and must
win: if a tool name collides with a Basic Catalog function or an already
registered catalog function, that is a **hard error at export time**, not a
silent overwrite. The spec says the same for post-sanitization collisions.

### UAX #31 sanitization (spec §7 "Nombres de tools no UAX #31")
A2UI function names must be valid identifiers; ai-parrot tool names routinely
contain `-` or `.`. Rules:
- Sanitize to a UAX #31-conformant name (leading char `XID_Start`, rest `XID_Continue`).
- Keep an **inverse map** sanitized → original, so TASK-2569's dispatch can
  resolve an incoming call back to the real tool name.
- Log a **warning** per sanitized name.
- Two tools sanitizing to the same name ⇒ **raise** at export time. Silent
  collision would let a renderer invoke the wrong tool — a security issue, not
  a cosmetic one.

Python's `str.isidentifier()` implements UAX #31 for the ASCII and unicode cases
you need; combine it with a per-character check. Do not add a dependency.

### `agent_capabilities(catalog_ids)`
```python
def agent_capabilities(catalog_ids: list[str]) -> dict[str, Any]:
    return {"v1.0": {"supportedCatalogIds": list(catalog_ids),
                     "acceptsInlineCatalogs": False}}
```
`acceptsInlineCatalogs` is **hard `False`** — spec §1 Non-Goals excludes the
renderer's `inlineCatalogs` function. Validate the result against the vendored
`agent_capabilities.json` in tests.

### References in Codebase
- `outputs/a2ui/catalog/export.py` — the file you are extending; mirror its docstring and emission style.
- `outputs/a2ui/catalog/basic/spec/catalog_definition.json` — `$defs/FunctionDefinition`, `unevaluatedProperties: false`.
- `outputs/a2ui/catalog/basic/spec/agent_capabilities.json` — the capabilities schema.
- `outputs/a2ui/catalog/base.py:246` — `FunctionDefinition`.

---

## Acceptance Criteria

- [ ] `AbstractTool.a2ui_requires_user_activation` and `.a2ui_hidden` both exist and default to `False`; no existing tool needs changes.
- [ ] `export_functions()` omits every tool with `a2ui_hidden=True`.
- [ ] Exported functions carry `allowedCallers: "rendererOrAgent"` and the tool's `requiresUserActivation`.
- [ ] The merged `export_catalog_definition()` output still validates against the vendored `catalog_definition.json`, with the Basic Catalog functions still present verbatim.
- [ ] A tool name colliding with a Basic Catalog function raises at export time.
- [ ] Non-UAX #31 tool names are sanitized, a warning is logged, and the inverse map resolves back to the original.
- [ ] Two tools sanitizing to the same name raise at export time.
- [ ] `agent_capabilities(["parrot", "basic"])` validates against `agent_capabilities.json` and sets `acceptsInlineCatalogs: False`.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/catalog packages/ai-parrot/tests/tools -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/catalog packages/ai-parrot/src/parrot/tools/abstract.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/catalog/test_export_functions.py
import pytest
from jsonschema import Draft202012Validator

from parrot.outputs.a2ui.catalog.export import (
    agent_capabilities, export_catalog_definition, export_functions,
)


class TestExportFunctions:
    def test_hidden_tool_is_omitted(self, executor_with_hidden_tool):
        assert "danger_drop_table" not in export_functions(executor_with_hidden_tool)

    def test_allowed_callers_and_activation(self, executor): 
        fn = export_functions(executor)["get_weather"]
        assert fn["allowedCallers"] == "rendererOrAgent"
        assert fn["requiresUserActivation"] is False

    def test_merged_definition_validates(self, executor, v1_schemas):
        doc = export_catalog_definition()
        Draft202012Validator(v1_schemas["catalog_definition"]).validate(doc)

    def test_basic_catalog_functions_survive_merge(self, executor):
        """Basic functions are copied verbatim — a $ref does not satisfy
        unevaluatedProperties:false. Merging tools must not drop them."""
        ...

    def test_collision_with_basic_function_raises(self, executor_colliding):
        with pytest.raises(ValueError, match="collision"):
            export_functions(executor_colliding)


class TestUAX31:
    def test_non_identifier_name_sanitized_with_warning(self, executor_dashed, caplog):
        fns = export_functions(executor_dashed)
        assert all(n.isidentifier() for n in fns)
        assert "sanitiz" in caplog.text.lower()

    def test_sanitization_collision_raises(self, executor_two_dashed):
        with pytest.raises(ValueError):
            export_functions(executor_two_dashed)


class TestAgentCapabilities:
    def test_shape(self, v1_schemas):
        caps = agent_capabilities(["https://parrot.dev/catalogs/v1"])
        assert caps["v1.0"]["acceptsInlineCatalogs"] is False
        Draft202012Validator(v1_schemas["agent_capabilities"]).validate(caps)
```

```python
# packages/ai-parrot/tests/tools/test_tool_a2ui_attributes.py
def test_defaults_are_false():
    from parrot.tools.abstract import AbstractTool
    assert AbstractTool.a2ui_requires_user_activation is False
    assert AbstractTool.a2ui_hidden is False

def test_subclass_can_override():
    ...
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 4 (including its "Nota de integración"), §7 "Nombres de tools no UAX #31", §8 resolved OQ on `a2ui_hidden`.
2. **Check dependencies** — TASK-2570 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — **read `catalog/export.py` in full first**;
   it already emits `functions` and you must merge into it, not replace it.
   Re-confirm `FunctionDefinition`'s fields at `catalog/base.py:246`.
4. **Update status** in the index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** every acceptance criterion, especially schema validation.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
