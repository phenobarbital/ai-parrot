---
id: F003
query_id: Q003
type: grep
intent: Find all internal consumers of parrot.forms
executed_at: 2026-05-28T13:11:03+02:00
depth: 0
---

# F003 — Two consumer surfaces: MS Teams dialogs (8 files) + legacy form tests (19 files)

## Summary

`grep -rln "parrot\.forms\b" packages/ --include="*.py"` returns two distinct
groups: (a) 8 production files in `parrot/integrations/msteams/`
(wrapper.py, dialogs/orchestrator.py, dialogs/factory.py, and 5 dialog
presets) and (b) 19 test files in `packages/ai-parrot/tests/unit/forms/`.
Many of the msteams imports target submodules (`.renderers`, `.validators`,
`.extractors.tool`, `.tools`) that bypass the shim's `__init__.py`
re-exports — so today they always resolve to the local fallback code.

## Citations

- path: `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/orchestrator.py`
  lines: 17-22, 208
  excerpt: |
    from parrot.forms.tools import RequestFormTool
    from parrot.forms import FormSchema, StyleSchema
    from parrot.forms.extractors.tool import ToolExtractor
    from parrot.forms.renderers import AdaptiveCardRenderer
    from parrot.forms import FormCache
    ...
    from parrot.forms import FieldOption  # local import avoids cycles

- path: `packages/ai-parrot/src/parrot/integrations/msteams/wrapper.py`
  lines: 36-39
  excerpt: |
    from parrot.forms import FormSchema, StyleSchema
    from parrot.forms.renderers import AdaptiveCardRenderer
    from parrot.forms.validators import FormValidator
    from parrot.forms import FormCache

- path: `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/presets/wizard.py`
  lines: 13-15
  excerpt: |
    from parrot.forms import FormSchema, StyleSchema
    from parrot.forms.renderers import AdaptiveCardRenderer
    from parrot.forms.validators import FormValidator

- path: `packages/ai-parrot/src/parrot/integrations/msteams/dialogs/factory.py`
  lines: 4
  excerpt: |
    from parrot.forms import FormSchema, StyleSchema, LayoutType

- path: `packages/ai-parrot/tests/unit/forms/test_constraints.py`
  lines: 1-10
  excerpt: |
    """Unit tests for field constraints and dependency rules."""
    import pytest
    from parrot.forms import (
        ConditionOperator,
        DependencyRule,
        FieldCondition,
        FieldConstraints,
    )

## Notes

Full list of msteams files importing parrot.forms:
- `parrot/integrations/msteams/wrapper.py`
- `parrot/integrations/msteams/dialogs/orchestrator.py`
- `parrot/integrations/msteams/dialogs/factory.py`
- `parrot/integrations/msteams/dialogs/presets/base.py`
- `parrot/integrations/msteams/dialogs/presets/wizard.py`
- `parrot/integrations/msteams/dialogs/presets/wizard_summary.py`
- `parrot/integrations/msteams/dialogs/presets/conversational.py`
- `parrot/integrations/msteams/dialogs/presets/simple_form.py`

Legacy tests directory `packages/ai-parrot/tests/unit/forms/` has 19
files covering: constraints, cache, registry, jsonschema_extractor,
pydantic_extractor, style, storage, yaml_extractor, adaptive_card_renderer,
create_form_tool, validators, html5_renderer, request_form_tool,
jsonschema_renderer, schema, tool_extractor, registry_lifecycle. These
test the local fallback implementation, not parrot-formdesigner.
