---
type: Wiki Overview
title: 'TASK-1324: `InfographicToolkit` auxiliary tools (list/get_contract/validate)'
id: doc:sdd-tasks-completed-task-1324-infographic-toolkit-aux-tools-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: TASK-1323 ships the core `render` tool. To make the LLM's job feasible
relates_to:
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1324: `InfographicToolkit` auxiliary tools (list/get_contract/validate)

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 1 — tool surface)
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1323
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

TASK-1323 ships the core `render` tool. To make the LLM's job feasible
the toolkit also exposes three read-only helpers so the model can:
- discover available templates,
- fetch a single template's positional contract (block_specs +
  declared js_bundles),
- dry-run block validation without persisting.

These are pure reads; they don't touch `ArtifactStore` and don't
allocate artifacts.

---

## Scope

Add the three async methods on `InfographicToolkit`. The toolkit's
`tool_prefix="infographic"` will yield tool names
`infographic_list_templates`, `infographic_get_template_contract`,
`infographic_validate_blocks`.

- `async def list_templates(self) -> List[Dict[str, str]]`:
  Wraps `infographic_registry.list_templates_detailed()` (line 406 of
  `infographic_templates.py` — verify the exact name) into the
  serializable shape `[{"name": ..., "description": ...}]`. Add a
  fallback: if `list_templates_detailed` is absent, build the same shape
  from `list_templates()` + per-template lookups.

- `async def get_template_contract(self, template_name: str) -> Dict[str, Any]`:
  Returns a JSON-serializable dict:
  ```python
  {
      "name": str,
      "description": str,
      "default_theme": Optional[str],
      "block_specs": [
          {
              "position": int,
              "block_type": str,
              "required": bool,
              "description": Optional[str],
              "min_items": Optional[int],
              "max_items": Optional[int],
              "constraints": Dict[str, str],
          }, ...
      ],
      "js_bundles": [
          {"name": str, "url": Optional[str], "scope": str}
          for b in template.js_bundles or []
      ],
  }
  ```
  Raise `InfographicValidationError(code="TEMPLATE_UNKNOWN")` on miss.

- `async def validate_blocks(self, template_name: str, blocks: List[Dict[str, Any]]) -> Dict[str, Any]`:
  Runs the validation pipeline from TASK-1323 against `blocks` WITHOUT
  rendering or persisting. Returns:
  ```python
  {"ok": True}                                           # on success
  {"ok": False, "code": <code>, "detail": <detail>}      # on failure
  ```
  This tool MUST NOT raise — it always returns a dict so the LLM can
  branch on `ok`. (`render` continues to raise so the user sees errors.)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/infographic_toolkit.py` | MODIFY | Add three async methods. |
| `packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_aux.py` | CREATE | Tests for the three helpers. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicValidationError,
)  # from TASK-1323

from parrot.models.infographic_templates import (
    InfographicTemplate, infographic_registry,
)
# infographic_registry has .list_templates() AND
# .list_templates_detailed() per spec §6.
```

### Existing Signatures to Use

```python
# parrot/models/infographic_templates.py
class InfographicTemplateRegistry:                # line 398
    def list_templates(self) -> List[str]: ...
    def list_templates_detailed(self) -> List[Dict[str, str]]: ...
```

### Does NOT Exist
- ~~`InfographicTemplate.to_json_contract()`~~ — no such method; build the
  dict manually as documented above.
- ~~`InfographicToolkit.preview()`~~ — not a tool in v1.

---

## Implementation Notes

### Pattern

```python
async def list_templates(self) -> List[Dict[str, str]]:
    detailed = getattr(infographic_registry, "list_templates_detailed", None)
    if callable(detailed):
        return detailed()
    return [
        {"name": n, "description": infographic_registry.get(n).description}
        for n in infographic_registry.list_templates()
    ]


async def get_template_contract(self, template_name: str) -> Dict[str, Any]:
    template = self._validate_template(template_name)  # raises TEMPLATE_UNKNOWN
    return {
        "name": template.name,
        "description": template.description,
        "default_theme": template.default_theme,
        "block_specs": [
            {
                "position": idx,
                "block_type": s.block_type.value,
                "required": s.required,
                "description": s.description,
                "min_items": s.min_items,
                "max_items": s.max_items,
                "constraints": s.constraints or {},
            } for idx, s in enumerate(template.block_specs)
        ],
        "js_bundles": [
            {"name": b.name, "url": b.url, "scope": b.scope}
            for b in (template.js_bundles or [])
        ],
    }


async def validate_blocks(
    self, template_name: str, blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        template = self._validate_template(template_name)
        self._validate_blocks(template, blocks)
        return {"ok": True}
    except InfographicValidationError as exc:
        return {"ok": False, "code": exc.code, "detail": exc.detail}
```

### Key Constraints
- These three tools MUST be safe to call repeatedly with no side
  effects. No artifact creation, no DataFrame access.
- `validate_blocks` is the only async toolkit method that intentionally
  does NOT raise. Document this in the docstring.

---

## Acceptance Criteria

- [ ] `infographic_list_templates` returns at least the seven built-in
      templates with name + description.
- [ ] `infographic_get_template_contract("does-not-exist")` raises
      `InfographicValidationError(code="TEMPLATE_UNKNOWN")`.
- [ ] `infographic_get_template_contract("basic")` returns the documented
      dict shape with `block_specs[i].position == i`.
- [ ] `infographic_validate_blocks` returns `{"ok": True}` on success.
- [ ] `infographic_validate_blocks` returns
      `{"ok": False, "code": "SLOT_MISSING", "detail": {...}}` on failure
      (no exception).
- [ ] Tool names are correctly prefixed (`infographic_list_templates`
      etc.) via `tool_prefix="infographic"`.
- [ ] `pytest packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_aux.py -v` passes.
- [ ] `ruff check` clean on the modified file.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/tools/test_infographic_toolkit_aux.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicValidationError,
)
from parrot.models.infographic_templates import infographic_registry


@pytest.fixture
def toolkit():
    store = MagicMock()
    store.save_artifact = AsyncMock()
    store.get_public_url = AsyncMock(return_value="https://signed/x")
    return InfographicToolkit(artifact_store=store)


async def test_list_templates_includes_builtins(toolkit):
    items = await toolkit.list_templates()
    names = {it["name"] for it in items}
    assert {"basic", "executive", "dashboard"} <= names


async def test_get_template_contract_unknown_raises(toolkit):
    with pytest.raises(InfographicValidationError) as ei:
        await toolkit.get_template_contract("nope")
    assert ei.value.code == "TEMPLATE_UNKNOWN"


async def test_get_template_contract_shape(toolkit):
    c = await toolkit.get_template_contract("basic")
    assert c["name"] == "basic"
    assert isinstance(c["block_specs"], list)
    for i, s in enumerate(c["block_specs"]):
        assert s["position"] == i
        assert "block_type" in s


async def test_validate_blocks_ok(toolkit):
    template = infographic_registry.get("basic")
    blocks = _fixture_blocks_for(template)  # build minimum valid blocks
    out = await toolkit.validate_blocks("basic", blocks)
    assert out == {"ok": True}


async def test_validate_blocks_failure_does_not_raise(toolkit):
    out = await toolkit.validate_blocks("basic", [])
    assert out["ok"] is False
    assert out["code"] in {"SLOT_MISSING", "TEMPLATE_UNKNOWN"}


async def test_tool_names_prefixed(toolkit):
    tools = toolkit.get_tools()
    names = {t.name for t in tools}
    assert {"infographic_render", "infographic_list_templates",
            "infographic_get_template_contract",
            "infographic_validate_blocks"} <= names
```

---

## Agent Instructions

1. Make sure TASK-1323 is merged.
2. Add the three methods on `InfographicToolkit`.
3. Write the helper `_fixture_blocks_for(template)` in the test file so
   the success path can be exercised against the built-in `basic`
   template.
4. Run `pytest packages/ai-parrot/tests/unit/tools/ -v`.
5. Move to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
