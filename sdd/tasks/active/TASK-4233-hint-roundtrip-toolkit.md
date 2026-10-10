# TASK-4233: hint/llm_validation round-trip: YAML extractor, create_form prompt schema, EditToolkit.update_field, api/operations

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4209
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 / §9 S9 / AC19 (second half). `FormField` is `extra="forbid"` (`core/schema.py:121`), so
once TASK-4209 adds `hint` and `llm_validation`, every **authoring path** must carry them or they are
silently lost (YAML extractor builds `FormField(...)` from an explicit kwarg list) or never proposed
(LLM creation prompt schema). This task makes `hint`, `llm_validation` (field) and the typed form blocks
`voice` / `llm_validation` (form) round-trip through YAML extraction, the `create_form` prompt schema, and
the granular edit path (`EditToolkit.update_field` → `api/operations.py::_apply_update_field`).

---

## Scope

- `extractors/yaml.py::_parse_field`: read `hint` (localized) and `llm_validation` (bool | None) and pass them to `FormField(...)`.
- `extractors/yaml.py::_parse_schema`: read form-level `voice` and `llm_validation` mappings and pass them to `FormSchema(...)` (Pydantic validates the typed blocks).
- `tools/create_form.py::_SYSTEM_PROMPT_TEMPLATE`: add `"hint"` and `"llm_validation"` to the field schema.
- `api/operations.py::_apply_update_field`: normalise an empty `hint` (`""` or `{}`) in the patch to removal
  (`None`), so the UI can clear a hint with an empty input; everything else already flows through
  `FormField.model_validate(merged)`.
- `tools/edit_toolkit.py::update_field`: document `hint` / `llm_validation` in the docstring (the LLM-facing
  tool description) — the signature stays `(section_uid, field_uid, patch)`.
- Tests for all four paths.

**NOT in scope**: `propose_voice_hints` / `VoiceOptimizer` (TASK-4234 — same `edit_toolkit.py`, runs after
this task); renderers (TASK-4231/4232); the model fields themselves (TASK-4209); a new operations op for
form-level `voice`/`llm_validation` blocks (form blocks round-trip through YAML and full PUT/PATCH only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py` | MODIFY | field `hint`/`llm_validation`; form `voice`/`llm_validation` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py` | MODIFY | prompt schema keys |
| `packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py` | MODIFY | `update_field` docstring |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py` | MODIFY | empty-hint normalisation |
| `packages/parrot-formdesigner/tests/formdesigner/test_hint_roundtrip_toolkit.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.extractors.yaml import YamlExtractor        # extractors/yaml.py:109 ; extract_from_string(content) -> FormSchema :145
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection   # core/schema.py:65, :401, :229
from parrot_formdesigner.core.types import FieldType                 # core/types.py:16
from parrot_formdesigner.tools.edit_toolkit import EditToolkit       # tools/edit_toolkit.py:63
from parrot_formdesigner.api.operations import UpdateField, _apply_update_field, OperationError   # api/operations.py:121, :404, :196
```
Provided by dependency tasks:
- `FormField.hint: LocalizedString | None`, `FormField.llm_validation: bool | None` — TASK-4209 (`core/schema.py`).
- `FormSchema.voice: VoiceFormConfig | None`, `FormSchema.llm_validation: LLMValidationConfig | None` — TASK-4209.

### Existing Signatures to Use
```python
# extractors/yaml.py
def _parse_schema(self, data: dict[str, Any]) -> FormSchema            # :181 ; description :193 ; meta :196 ; FormSchema(...) :213-223 (cancel_allowed=cancel_allowed, :221)
def _parse_field(self, data: Any) -> FormField | None                  # :266 ; placeholder :311 ; meta = field_config.get("meta") :351 ; FormField(...) :353-370 (placeholder=placeholder, :358)
def _parse_localized(self, value: Any) -> LocalizedString | None       # :663 ; used :193, :310-311

# tools/create_form.py
_SYSTEM_PROMPT_TEMPLATE = """…"""                                      # :71 ; field keys :84-101 ; "placeholder": "string (optional)", :89
_SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.replace("__FIELD_TYPES__", …)   # :152 (str.replace — braces are literal, NOT .format)
form = FormSchema.model_validate(data)                                  # :780

# tools/edit_toolkit.py
class EditToolkit(AbstractToolkit):                                     # :63
    def __init__(self, form: FormSchema, **kwargs: Any) -> None         # :87
    async def update_field(self, section_uid: str, field_uid: str, patch: dict) -> dict   # :318 → UpdateField + _apply_update_field

# api/operations.py
class UpdateField(_OpBase): op: Literal["update_field"]; section_uid: uuid.UUID; field_uid: uuid.UUID; patch: dict[str, Any]   # :121-136
def _apply_update_field(form: FormSchema, op: UpdateField) -> FormSchema   # :404 ; existing = container[fi].model_dump() :420 ; merged = _deep_merge(existing, op.patch) :421 ; FormField.model_validate(merged) :432
# api/_utils.py
def _deep_merge(base: dict, patch: dict) -> dict                        # :11 (None removes key; dict merges; else replaces)
```

### Does NOT Exist
- ~~`EditToolkit.update_field(..., hint=..., llm_validation=...)` keyword parameters~~ — the real signature is a
  merge-patch `(section_uid, field_uid, patch)`; the spec skeleton's kwargs form is NOT adopted (it would change
  the LLM tool contract). `hint`/`llm_validation` are accepted **through `patch`**.
- ~~`UpdateFormSettings` / `update_form_voice` operation~~ — not added here.
- ~~A key whitelist in `create_form.py`~~ — LLM output goes straight to `FormSchema.model_validate` (:780).
- ~~`FormField.audio_hint`~~, ~~`meta["audio_hint"]`~~.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/tools/create_form.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_hint_roundtrip_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/tools/edit_toolkit.py#EditToolkit.update_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py#UpdateField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/operations.py#_apply_update_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py#_deep_merge",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- YAML: absent keys → `None` (never an empty string); `llm_validation` must stay tri-state (`None` = inherit).
- `_deep_merge` replaces a dict hint with a string patch and vice-versa (non-dict values replace) — no change needed for that; only the empty-value normalisation is new.
- Do not reorder or rename existing prompt keys in `_SYSTEM_PROMPT_TEMPLATE` — existing tests snapshot parts of it.
- `edit_toolkit.py` is also modified by TASK-4234 afterwards — keep this diff to the `update_field` docstring.

---

## Implementation Blueprint

### Steps (in order)
1. YAML field parse + FormField kwargs — *why*: `extra="forbid"` means the explicit kwarg list is the only path.
2. YAML form-level blocks — *why*: typed blocks are validated by Pydantic; pass the raw mapping through.
3. Prompt schema keys — *why*: the LLM only proposes keys it is shown.
4. Operations empty-hint normalisation — *why*: UI clears a hint by sending `""`.
5. `update_field` docstring — *why*: it is the LLM-facing tool description.
6. Tests.

### `extractors/yaml.py` (MODIFY) — field
```python
# occurrences: 1 (verified: grep -c '        meta = field_config.get("meta")' extractors/yaml.py)
# AFTER — insert below `        meta = field_config.get("meta")` (verified: extractors/yaml.py:351)
        # FEAT-649: spoken/visible help text and LLM plausibility opt-in (None inherits the form default).
        hint = self._parse_localized(field_config.get("hint")) if "hint" in field_config else None
        llm_validation = field_config.get("llm_validation")
        # FILL IN: coerce llm_validation to bool | None (YAML "yes"/"no" already parse to bool; reject other
        #   types with a warning → None) — bounded by tri-state semantics (None = inherit).

# occurrences: 1 (verified: grep -c '            placeholder=placeholder,' extractors/yaml.py)
# AFTER — insert below `            placeholder=placeholder,` (verified: extractors/yaml.py:358)
            hint=hint,
            llm_validation=llm_validation,
```

### `extractors/yaml.py` (MODIFY) — form
```python
# occurrences: 1 (verified: grep -c '        meta = data.get("meta") or data.get("metadata")' extractors/yaml.py)
# AFTER — insert below that line (verified: extractors/yaml.py:196)
        voice_block = data.get("voice")
        llm_validation_block = data.get("llm_validation")

# occurrences: 1 (verified: grep -c '            cancel_allowed=cancel_allowed,' extractors/yaml.py)
# AFTER — insert below `            cancel_allowed=cancel_allowed,` (verified: extractors/yaml.py:221)
            voice=voice_block,
            llm_validation=llm_validation_block,
```
**Why**: `FormSchema` validates the mappings into `VoiceFormConfig` / `LLMValidationConfig` (TASK-4209); `None`
keeps today's behaviour.

### `tools/create_form.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '          "placeholder": "string (optional)",' tools/create_form.py)
# AFTER — insert below `          "placeholder": "string (optional)",` (verified: tools/create_form.py:89)
          "hint": "string (optional) — short help read aloud after the question and shown under the input",
          "llm_validation": "true/false (optional) — ask an LLM to sanity-check the answer before submit",
```
**Why**: the template is rendered with `str.replace` (`:152`), so literal text is safe.

### `api/operations.py` (MODIFY)
```python
# occurrences: 2 (verified: grep -c '    merged = _deep_merge(existing, op.patch)' api/operations.py → :421 update_field, :458 update_form_meta)
# FILL IN: disambiguate — insert ABOVE the update_field occurrence, using this unique context (verified :420-421):
#     existing = container[fi].model_dump()
#     merged = _deep_merge(existing, op.patch)
    patch = dict(op.patch)
    if "hint" in patch and patch["hint"] in ("", {}):
        patch["hint"] = None  # FEAT-649: an empty hint clears it (RFC 7396 null = remove)
# …and change the merge line of THIS occurrence to:  merged = _deep_merge(existing, patch)
```
**Why**: keeps the RFC 7396 semantics; only the empty-value shorthand is added.

### `tools/edit_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def update_field(' tools/edit_toolkit.py)
# In the docstring of update_field (verified: tools/edit_toolkit.py:318-338), AFTER the line
#   `            patch: RFC 7396 merge-patch dict with fields to update.` add:
                Voice/LLM keys (FEAT-649): ``hint`` (string or ``{locale: text}``;
                ``""`` clears it) and ``llm_validation`` (``true``/``false``;
                ``null`` inherits the form default).
```

### FILL IN checklist
- [ ] `yaml.py::_parse_field` — `llm_validation` coercion; tri-state.
- [ ] `operations.py::_apply_update_field` — disambiguated insertion + local `patch` used for the merge.
- [ ] Test bodies.

---

## Acceptance Criteria

- [ ] S9: a YAML form with field `hint`/`llm_validation` and form `voice`/`llm_validation` extracts with all four preserved.
- [ ] S9: `_SYSTEM_PROMPT` contains `"hint"` and `"llm_validation"`.
- [ ] AC19: `EditToolkit.update_field(section_uid, field_uid, {"hint": {...}, "llm_validation": True})` persists both; `{"hint": ""}` clears it.
- [ ] Existing tests pass: `tests/test_edit_toolkit.py`, `tests/test_create_form_toolkit.py`.
- [ ] `ruff check` passes on the four modified files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_hint_roundtrip_toolkit.py -q`
- `pytest packages/parrot-formdesigner/tests/test_edit_toolkit.py -q`
- `pytest packages/parrot-formdesigner/tests/test_create_form_toolkit.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_hint_roundtrip_toolkit.py
from __future__ import annotations

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.yaml import YamlExtractor
from parrot_formdesigner.tools.create_form import _SYSTEM_PROMPT
from parrot_formdesigner.tools.edit_toolkit import EditToolkit

YAML_FORM = """
form_id: demo
title: Demo
voice: {max_questions: 4}
llm_validation: {enabled: true, threshold: 0.8}
sections:
  - section_id: s
    fields:
      - field_id: name
        field_type: text
        label: Name
        hint: {en: First name, es: Nombre}
        llm_validation: false
"""


def test_yaml_roundtrip_field_and_form_blocks():
    form = YamlExtractor().extract_from_string(YAML_FORM)
    field = form.sections[0].fields[0]
    # FILL IN: assert field.hint == {"en": "First name", "es": "Nombre"}; field.llm_validation is False;
    #   form.voice.max_questions == 4; form.llm_validation.threshold == 0.8
    ...


def test_create_form_prompt_mentions_hint_and_llm_validation():
    assert '"hint"' in _SYSTEM_PROMPT and '"llm_validation"' in _SYSTEM_PROMPT


async def test_update_field_sets_and_clears_hint():
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
    section = FormSection(section_id="s", fields=[field])
    tk = EditToolkit(FormSchema(form_id="demo", title="Demo", tenant="acme", sections=[section]))
    res = await tk.update_field(str(section.section_uid), str(field.field_uid), {"hint": {"es": "Nombre"}, "llm_validation": True})
    assert res["success"] and res["updated_field"]["hint"] == {"es": "Nombre"}
    assert res["updated_field"]["llm_validation"] is True
    res = await tk.update_field(str(section.section_uid), str(field.field_uid), {"hint": ""})
    assert res["updated_field"]["hint"] is None
```
Note: the existing `test_edit_toolkit.py` / `test_create_form_toolkit.py` live at the tests root
(`packages/parrot-formdesigner/tests/`), not under `tests/formdesigner/` (verified).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 Module 13, §9 S9, AC19).
3. **Check dependencies** — TASK-4209 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — confirm the YAML extractor class name; re-run every `grep -c`.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — only the listed files.
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4233 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: `EditToolkit.update_field` keeps its merge-patch signature (spec skeleton showed kwargs) — decided at task time; confirm or describe.
