# TASK-4205: Docs (`a2ui-renderer.md`) + integration round-trips + import-hygiene test

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4195, TASK-4197, TASK-4200, TASK-4203, TASK-4204
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (G9, AC12, AC13) and §4 Integration Tests. Closes the
feature: document the dialect flag, negotiation precedence, export, import,
translate and the loss rules in `packages/parrot-formdesigner/docs/a2ui-renderer.md`;
prove the round-trips end to end through the handlers; extend the AST
import-hygiene guard to every new module so parrot-formdesigner stays
importable without the `ai-parrot` extra.

---

## Scope

- Docs: new sections after `## Usage` — "Dialect flag and negotiation", "Bulk export", "Importing a surface", "Translating JSON Schema", "Loss rules (strict projection / heuristic map)".
- `tests/integration/test_a2ui_dialect_roundtrip.py`: `test_form_to_a2ui_to_form`, `test_jsonschema_to_a2ui_preserves_sections`, `test_export_then_import_tenant`, `test_fieldsync_golden_unchanged`.
- `tests/unit/test_a2ui_import_hygiene.py`: AST assertion (no top-level `parrot.` import) over `api/dialect.py`, `services/a2ui_export.py`, `services/a2ui_translate.py`, `extractors/a2ui.py`, `cli.py`, `extractors/__init__.py`.

**NOT in scope**: new behaviour; any fix found here goes back to the owning task (or a ledger issue if it is merged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/docs/a2ui-renderer.md` | MODIFY | FEAT-650 sections |
| `packages/parrot-formdesigner/tests/integration/test_a2ui_dialect_roundtrip.py` | CREATE | end-to-end round-trips |
| `packages/parrot-formdesigner/tests/unit/test_a2ui_import_hygiene.py` | CREATE | AST import guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api.handlers import FormAPIHandler                     # api/handlers.py (pattern: tests/integration/test_a2ui_form_cycle.py:26)
from parrot_formdesigner.services.registry import FormRegistry                  # services/registry.py:240
from parrot_formdesigner.renderers import A2UIFormRenderer, JsonSchemaRenderer  # renderers/__init__.py
from parrot_formdesigner.extractors import A2UIExtractor, JsonSchemaExtractor   # TASK-4201 / extractors/__init__.py:8
from parrot_formdesigner.services.a2ui_export import A2UIExportService          # TASK-4196
from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui   # TASK-4199
```

### Existing Signatures to Use
```python
# tests/integration/test_a2ui_form_cycle.py:15-60 — builds FormAPIHandler directly with FormRegistry + AsyncMock/MagicMock submission storage,
#   `pytest.importorskip("parrot.outputs.a2ui")` at module top, `_make_form(is_public=True)` helper. Mirror it.
# tests/unit/renderers/test_a2ui_export.py:19-30 — AST pattern: parse inspect.getsource(module), assert no ast.Import/ImportFrom with a `parrot.` prefix
# docs/a2ui-renderer.md headings: ## Overview (3) · ## Installing (17) · ## Usage (33: ### Rendering a surface 35, ### Submitting an A2UI action 66) ·
#   ## FieldType coverage (118) · ## v1 non-goals (157) · ## See also (170)
# golden fixture from TASK-4194: tests/unit/api/fixtures/golden_schema_legacy.json
```

### Does NOT Exist
- ~~`docs/formdesigner/` at the repo root~~ — formdesigner docs live in `packages/parrot-formdesigner/docs/`.
- ~~a `pytest-aiohttp` `aiohttp_client` fixture in this environment~~ — integration tests here build handlers directly (see the cycle test's docstring).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/docs/a2ui-renderer.md", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/integration/test_a2ui_dialect_roundtrip.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_a2ui_import_hygiene.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py#FormRegistry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Docs state the precedence rule verbatim (`?dialect=` > `Accept` > stored), that `GET /forms/{uid}` never changes, the strict projection list and the heuristic table (copy from spec §7), the 409/`overwrite` policy, and the no-`--all-tenants` limitation.
- Round-trip assertions are on the strict projection only (AC9) — never on descriptions/dependencies.

---

## Implementation Blueprint

### Steps (in order)
1. Hygiene test first (cheap, catches a stray top-level import from any earlier task).
2. Integration round-trips through `FormAPIHandler` (same wiring as the cycle test).
3. Docs.

### `packages/parrot-formdesigner/tests/unit/test_a2ui_import_hygiene.py` (CREATE)
```python
"""parrot-formdesigner must import without the ai-parrot extra — FEAT-650 TASK-4205 (AC12)."""

from __future__ import annotations

import ast
import importlib
import inspect

import pytest

MODULES = [
    "parrot_formdesigner.api.dialect",
    "parrot_formdesigner.services.a2ui_export",
    "parrot_formdesigner.services.a2ui_translate",
    "parrot_formdesigner.extractors.a2ui",
    "parrot_formdesigner.extractors",
    "parrot_formdesigner.cli",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_no_top_level_parrot_import(module_name):
    mod = importlib.import_module(module_name)
    tree = ast.parse(inspect.getsource(mod))
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert not any(a.name.startswith("parrot.") for a in node.names), f"{module_name}: {ast.dump(node)}"
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("parrot."), f"{module_name}: {node.module}"
```

### `packages/parrot-formdesigner/tests/integration/test_a2ui_dialect_roundtrip.py` (CREATE)
```python
"""FEAT-650 end-to-end round-trips (TASK-4205, spec §4 Integration Tests)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.extractors import A2UIExtractor  # noqa: E402
from parrot_formdesigner.renderers import A2UIFormRenderer, JsonSchemaRenderer  # noqa: E402
from parrot_formdesigner.services.a2ui_export import A2UIExportService  # noqa: E402
from parrot_formdesigner.services.a2ui_translate import translate_jsonschema_to_a2ui  # noqa: E402
from parrot_formdesigner.services.registry import FormRegistry  # noqa: E402

GOLDEN = Path(__file__).parents[1] / "unit" / "api" / "fixtures" / "golden_schema_legacy.json"


def _form(fid="rt", tenant="navigator") -> FormSchema:
    return FormSchema(form_id=fid, title={"en": "RT"}, tenant=tenant, is_public=True, sections=[
        FormSection(section_id="s1", title={"en": "One"}, fields=[
            FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}, required=True),
            FormField(field_id="nps", field_type=FieldType.NPS, label={"en": "NPS"})]),
        FormSection(section_id="s2", title={"en": "Two"}, fields=[FormSubsection(subsection_id="s2a", title={"en": "A"}, fields=[
            FormField(field_id="color", field_type=FieldType.SELECT, label={"en": "Color"}, options=[{"value": "r", "label": "Red"}])])]),
    ])


# FILL IN: `handler` fixture — FormAPIHandler + FormRegistry wiring copied from tests/integration/test_a2ui_form_cycle.py:26-60 — bounded by that file


async def test_form_to_a2ui_to_form(handler):
    # FILL IN: register _form(); GET /schema?dialect=a2ui via handler.get_schema (make_mocked_request with match_info/tenant like the cycle test);
    #          POST the envelope to handler.create_form with ?overwrite=true; GET /forms/{uid} → compare strict projection to the original — bounded by AC9/G9


async def test_jsonschema_to_a2ui_preserves_sections():
    rendered = await JsonSchemaRenderer().render(_form())
    surface = await translate_jsonschema_to_a2ui(rendered.content, tenant="navigator", renderer=A2UIFormRenderer())
    cards = [c for c in surface.content["createSurface"]["components"] if c["component"] == "Card"]
    assert [c["id"] for c in cards] == ["sec-s1", "sec-s2"]


async def test_export_then_import_tenant():
    src = FormRegistry(storage=None, default_tenant="a")
    for fid in ("x", "y"):
        await src.register(_form(fid, tenant="a"), tenant="a")
    rows = [r async for r in A2UIExportService(src, renderer=A2UIFormRenderer()).export_tenant("a")]
    dst = FormRegistry(storage=None, default_tenant="b")
    for r in rows:
        await dst.register(A2UIExtractor().extract(r.envelope, tenant="b").form.model_copy(update={"tenant": "b"}), tenant="b")
    assert sorted(f.form_id for f in await dst.list_forms(tenant="b")) == ["x", "y"] and await src.list_forms(tenant="b") == []


async def test_fieldsync_golden_unchanged(handler):
    # FILL IN: register the SAME fixture form TASK-4194 used for the golden; GET /schema (no override) → body == json.loads(GOLDEN.read_text()) — bounded by AC2
```

### `packages/parrot-formdesigner/docs/a2ui-renderer.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Usage' packages/parrot-formdesigner/docs/a2ui-renderer.md) -->
<!-- AFTER — insert a new top-level section BELOW the whole `## Usage` section, i.e. ABOVE `## FieldType coverage` (verified: docs/a2ui-renderer.md:118) -->
## Dialect flag and negotiation (FEAT-650)

`FormSchema.dialect` (`json_schema` default | `a2ui`) is persisted inside `schema_json` (no migration) and editable
with `PATCH /forms/{uid}`. The contract endpoints resolve the effective dialect as
**`?dialect=` query > `Accept: application/a2ui+json` > stored `form.dialect`**; `?dialect=json_schema` always forces the
legacy body. `GET /forms/{uid}` never changes (it is the form's identity). `GET /forms` exposes `dialect` per in-memory
entry and, with `?dialect=a2ui`, a `surface_url` manifest (`&include=surface` inlines envelopes, capped by
`FORMDESIGNER_A2UI_LIST_MAX`). Errors: 400 unknown dialect, 415 `{"supported": [...]}` when the extra is missing.
`onSchemaLoaded.schema_overrides` are translated into `updateComponents`/`updateDataModel` envelopes
(`{"messages": [...]}` framing); untranslatable keys become `override_not_translatable:<key>` warnings.

## Bulk export
<!-- FILL IN: POST /forms/export body/NDJSON contract, `parrot formdesigner export --tenant T [--tenant U] --out DIR`, report file, exit codes, NO --all-tenants (why) — bounded by spec §2/§3 M3/M7 -->

## Importing a surface
<!-- FILL IN: POST /forms dual-wire detection, 201 payload with import report, 409 unless ?overwrite=true, 413/422, tenant stamping, CLI import --dry-run/--overwrite — bounded by spec §3 M6 -->

## Translating JSON Schema
<!-- FILL IN: library translate_jsonschema_to_a2ui, POST /forms/translate (stateless), CLI translate — bounded by spec §3 M4 -->

## Loss rules
<!-- FILL IN: the strict projection list and the heuristic primitive map + check mapping + structural rules, copied from spec §7 — bounded by spec §7 -->
```

### FILL IN checklist
- [ ] `test_a2ui_dialect_roundtrip.py` — handler fixture + two `FILL IN` tests; bounded by AC2/AC9.
- [ ] `docs/a2ui-renderer.md` — the four `FILL IN` sections; bounded by spec §2/§3/§7.

---

## Acceptance Criteria

- [ ] All four integration round-trips pass (G9); the golden body is unchanged (AC2).
- [ ] Hygiene test passes for every new module (AC12).
- [ ] Docs cover flag, precedence, export, import, translate and loss rules (AC13).
- [ ] `pytest` on the three Validation Commands green; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_a2ui_import_hygiene.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_a2ui_dialect_roundtrip.py -q`
- `pytest packages/parrot-formdesigner/tests/integration/test_a2ui_form_cycle.py -q`

---

## Test Specification

See the CREATE blocks above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §4 Integration Tests, §7 (projection + heuristic map), and `tests/integration/test_a2ui_form_cycle.py`
3. **Check dependencies** — TASK-4195, 4197, 4200, 4203, 4204 `"done"`
4. **Verify the Codebase Contract** — `grep -n '^## ' packages/parrot-formdesigner/docs/a2ui-renderer.md`; `ls packages/parrot-formdesigner/tests/unit/api/fixtures/golden_schema_legacy.json`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the three files
9. **Close** with `scripts/sdd/close_task.sh TASK-4205 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
