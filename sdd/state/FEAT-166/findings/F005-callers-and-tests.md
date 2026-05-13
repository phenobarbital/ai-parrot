---
id: F005
title: Callers of DatabaseFormTool / DatabaseFormInput — backward-compat scope
source_queries: [Q006, Q007]
---

## Production callers (1)

`packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`:

```python
# line 67-74
from ..tools.database_form import DatabaseFormTool
...
self._db_tool = DatabaseFormTool(
    registry=self.registry
)
```

Constructed with only `registry=` — uses defaults for everything else.
**Backward-compat requirement**: as long as `DatabaseFormTool(registry=…)`
keeps working AND `service` defaults to `"networkninja"`, this caller is
unaffected. No changes needed here unless we choose to plumb `service`
through the HTTP layer.

## Test callers (3)

1. **`tests/forms/test_database_form.py`** (27 test functions across
   `TestFieldTypeMapping`, `TestConditionalLogic`, `TestValidationMapping`,
   `TestQuestionBlockSections`, `TestFullFormGeneration`).
   - Imports via `from parrot.forms import DatabaseFormTool, FormRegistry`.
   - Builds `DatabaseFormTool(registry=registry, dsn="postgres://fake/db")`.
   - Patches `_fetch_form_row` with mocked rows; asserts on the resulting
     `FormSchema`.
   - **Heavy refactor target**: nearly all assertions exercise
     `_FIELD_TYPE_MAP`, `_map_logic_groups`, `_collect_select_options`,
     etc. After migration those tests must target
     `NetworkninjaFormService` directly (constructing it and calling its
     `build_form_schema` / `fetch_form_row` methods), with a smaller suite
     remaining at the tool level to assert dispatch behavior.

2. `packages/parrot-formdesigner/tests/unit/test_tools.py`:
   - Trivial smoke tests (class exists, has docstring). No refactor needed.

3. `packages/parrot-formdesigner/tests/unit/test_create_form_tool.py` /
   `test_request_form_tool.py`:
   - Unrelated tools; unaffected.

## Tooling import path

`parrot_formdesigner.tools.__init__` re-exports `DatabaseFormTool`
(see tools/__init__.py). The new `tools/services` sub-package is **not**
re-exported via `parrot_formdesigner.tools.*` by default — it lives one
level deeper. New public symbols (`AbstractFormService`,
`NetworkninjaFormService`) should be re-exported through
`parrot_formdesigner.tools.services.__init__`.
