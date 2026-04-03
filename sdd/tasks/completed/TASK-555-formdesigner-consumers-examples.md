# TASK-555: Update Consumers & Examples

**Feature**: formdesigner-package
**Feature ID**: FEAT-079
**Spec**: `sdd/specs/formdesigner-package.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-554
**Assigned-to**: unassigned

---

## Context

Implements Module 8 of FEAT-079. Simplifies `examples/forms/form_server.py` using the
new `setup_form_routes()` helper from `parrot-formdesigner`, reducing it from ~500 lines
to under 50. Also verifies MS Teams integration imports are unaffected.

---

## Scope

### Simplify `examples/forms/form_server.py`
Replace the entire file with a minimal server that uses `setup_form_routes()`:
```python
"""Example: aiohttp form server using parrot-formdesigner.

Usage:
    source .venv/bin/activate
    python examples/forms/form_server.py
"""
from aiohttp import web
from parrot.clients.factory import LLMFactory
from parrot.formdesigner.handlers import setup_form_routes
from parrot.models.google import GoogleModel


async def create_app() -> web.Application:
    app = web.Application()
    client = LLMFactory.get_client(GoogleModel)
    setup_form_routes(app, client=client)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=8080)
```

The resulting file must be **under 50 lines** (acceptance criterion from spec).

### Verify MS Teams Integration
Check `packages/ai-parrot/src/parrot/integrations/msteams/` for any direct
`parrot.forms.*` imports. They should continue to work unchanged via the re-export
shim (TASK-554). If any import breaks, fix it.

### Integration Test
Create `packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py`
verifying MS Teams dialog imports work unchanged.

**NOT in scope**: modifying MS Teams handler logic, adding new renderer types.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/forms/form_server.py` | MODIFY | Simplify to <50 lines using setup_form_routes() |
| `packages/parrot-formdesigner/tests/integration/__init__.py` | CREATE | Empty |
| `packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py` | CREATE | MS Teams compat integration test |

---

## Implementation Notes

### form_server.py Simplification
The new `examples/forms/form_server.py` no longer needs:
- Inline CSS (moved to `handlers/templates.py` in TASK-553)
- HTML page builders (moved to `handlers/templates.py`)
- `FormRegistry`, `FormValidator`, `HTML5Renderer` direct imports
- Handler class definitions
- Manual route registration

All that functionality now lives in `setup_form_routes()` from TASK-553.

### MS Teams Integration Locations
Check these files for `parrot.forms` imports:
- `packages/ai-parrot/src/parrot/integrations/msteams/`
- Look for imports of `FormSchema`, `FormField`, `AdaptiveCardRenderer`, etc.

If the re-export shim (TASK-554) is correctly implemented, NO changes should be needed.

---

## Acceptance Criteria

- [ ] `examples/forms/form_server.py` has fewer than 50 lines
- [ ] `python examples/forms/form_server.py` starts the server without errors
- [ ] `from parrot.formdesigner.handlers import setup_form_routes` used in example
- [ ] MS Teams integration imports work unchanged (verified by test)
- [ ] All integration tests pass: `pytest packages/parrot-formdesigner/tests/integration/ -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/integration/test_msteams_import_compat.py
"""Integration test: MS Teams integration imports are unaffected by parrot-formdesigner."""
import pytest


class TestMSTeamsIntegrationImports:
    def test_adaptive_card_renderer_import(self):
        """MS Teams dialogs use AdaptiveCardRenderer."""
        from parrot.forms.renderers.adaptive_card import AdaptiveCardRenderer
        assert AdaptiveCardRenderer is not None

    def test_form_schema_import(self):
        from parrot.forms import FormSchema, FormField, FieldType
        schema = FormSchema(
            form_id="msteams-dialog",
            title="MS Teams Dialog",
            fields=[
                FormField(name="choice", field_type=FieldType.TEXT, label="Choice"),
            ],
        )
        assert schema.form_id == "msteams-dialog"

    def test_example_form_server_is_short(self):
        """form_server.py must be under 50 lines as per spec acceptance criterion."""
        with open("examples/forms/form_server.py") as f:
            lines = [l for l in f.readlines() if l.strip()]  # non-empty lines
        assert len(lines) < 50, f"form_server.py has {len(lines)} non-empty lines, expected < 50"
```

---

## Agent Instructions

1. **Verify** TASK-554 is in `sdd/tasks/completed/` before starting
2. **Read** `examples/forms/form_server.py` in full before modifying
3. **Check** `packages/ai-parrot/src/parrot/integrations/msteams/` for form imports
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
5. **Implement** scope above
6. **Count lines** in simplified form_server.py — must be < 50
7. **Verify** acceptance criteria
8. **Move** to `sdd/tasks/completed/`
9. **Update index** → `"done"`
10. **Commit**: `sdd: implement TASK-555 update consumers and examples for parrot-formdesigner`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
