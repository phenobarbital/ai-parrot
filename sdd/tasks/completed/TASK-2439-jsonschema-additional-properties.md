# TASK-2439: JSON Schema renderer states a `reject` policy

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2432
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 10

---

## Context

A client that generates its payload from the rendered JSON Schema currently has no
way to know a form will refuse undeclared keys — the renderer says nothing about
extra properties at all. Under `reject`, emitting `additionalProperties: false`
makes the rendered schema self-describing, so a standards-compliant client
validates locally and never sends a submission the server will `422`.

`drop` and `keep` emit nothing, keeping the output byte-identical for every
existing form.

> **Merge note**: FEAT-456/TASK-2414 also edits this file (`x-relation` emission).
> A textual conflict is likely; a semantic one is not. Rebase, do not wait.

Implements spec section 3 Module 10.

---

## Scope

- In `JsonSchemaRenderer._build_structural_schema` (`renderers/jsonschema.py:365`),
  where the schema dict is assembled (`:421-432`), add
  `schema["additionalProperties"] = False` when
  `form.unknown_fields is UnknownFieldsPolicy.REJECT`.
- Emit nothing for `drop` and `keep` — do NOT emit `additionalProperties: true`,
  which would change existing output and is the JSON Schema default anyway.
- Document the new behaviour in the class docstring's extension list
  (`:281-295`), which already enumerates what the renderer emits.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/test_jsonschema_additional_properties.py`.

**NOT in scope**: Any other renderer — `html5`, `adaptive_card`, `xforms`, `pdf`,
`telegram`, `audio` are untouched. Emitting the policy value itself as an
`x-unknown-fields` extension — resolved: `unknown_fields` is NOT surfaced to
clients as a field; the only client-visible consequence is this
`additionalProperties`. Any change to `_field_to_property` (`:434`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | `additionalProperties: false` under `reject` + docstring |
| `packages/parrot-formdesigner/tests/unit/test_jsonschema_additional_properties.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import or attribute.

### Verified Imports

```python
# NEW import this task adds (TASK-2432):
from ..core.schema import UnknownFieldsPolicy
# `FormSchema` is already imported in renderers/jsonschema.py — verify and reuse.
```

### Existing Signatures to Use

```python
# renderers/jsonschema.py:275
class JsonSchemaRenderer(AbstractFormRenderer):
    """Renders FormSchema as a structural JSON Schema with x- extensions.

    Output format:
    - content: JSON Schema dict (type=object, $schema, title, properties, required)
    - style_output: StyleSchema dict
    - content_type: "application/schema+json"

    Extensions used:            # :288-295 — the list to extend in the docstring
    - x-field-type, x-section, x-depends-on, x-post-depends,
      x-options-source, x-placeholder, x-read-only
    """
    def __init__(self) -> None: ...                    # line 304
    def _build_registry(self) -> None: ...             # line 311
    async def render(                                  # line 332
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm: ...
    def _build_structural_schema(...) -> dict[str, Any]: ...   # line 365  ← THIS METHOD
    def _field_to_property(self, ...) -> dict[str, Any]: ...   # line 434

# renderers/jsonschema.py:421-432 — the EXACT assembly block to edit:
        schema: dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": _resolve(form.title, locale) if form.title else form.form_id,
            "properties": properties,
        }
        if form.description:
            schema["description"] = _resolve(form.description, locale)
        if required:
            schema["required"] = required

        return schema

# renderers/base.py:57
class AbstractFormRenderer(ABC):
    async def render(...) -> RenderedForm: ...   # line 68

# core/schema.py (TASK-2432)
class UnknownFieldsPolicy(str, Enum):
    DROP = "drop"; KEEP = "keep"; REJECT = "reject"
```

### Does NOT Exist

- ~~`additionalProperties` anywhere in `renderers/`~~ — verified: a repo-wide grep
  over the renderers package returns nothing. There is no existing handling to
  extend, and no other renderer emits it.
- ~~`x-unknown-fields`~~ — not an existing extension, and resolved as out of scope.
- ~~`form.unknown_fields`~~ before TASK-2432 lands.
- ~~A shared "schema post-processing" hook~~ — the dict is assembled inline at
  `:421-432` and returned directly; there is no hook to register into.
- ~~`JsonSchemaRenderer.render()` returning a bare dict~~ — it returns a
  `RenderedForm`; the dict is `result.content`.

---

## Implementation Notes

### Pattern to Follow

```python
# renderers/jsonschema.py — inside _build_structural_schema, in the assembly block
# at :421-432, following the existing conditional-key style (`if form.description`,
# `if required`) rather than always writing the key:
        if form.unknown_fields is UnknownFieldsPolicy.REJECT:
            # The server will 422 an undeclared key, so say so in the schema: a
            # standards-compliant client validates locally instead of round-tripping
            # a submission that cannot succeed. `drop`/`keep` emit nothing, keeping
            # output byte-identical for every pre-FEAT-458 form.
            schema["additionalProperties"] = False

        return schema
```

### Key Constraints

- Use `is` identity comparison against the enum member, not `== "reject"`, so a
  future member cannot silently match.
- **Do not emit the key at all** for `drop`/`keep`. Emitting `True` is a behaviour
  change for every existing form and buys nothing (`true` is the spec default).
- Keep the conditional next to the `if form.description` / `if required` lines so
  the assembly reads as one block.
- Async signature untouched; this is a synchronous private method.

### References in Codebase

- `renderers/jsonschema.py:426-431` — the `if form.description` / `if required`
  conditional-key style to match.
- `renderers/jsonschema.py:281-295` — the class docstring output/extension list to
  update.

---

## Acceptance Criteria

- [ ] A `reject` form renders with `content["additionalProperties"] is False`.
- [ ] A `drop` form renders with no `additionalProperties` key at all.
- [ ] A `keep` form renders with no `additionalProperties` key at all.
- [ ] For a `drop` form, the rendered dict is byte-identical to pre-FEAT-458 output
      (spec AC22) — assert against a golden dict, not just key absence.
- [ ] `$schema`, `type`, `title`, `properties`, `required` and `description` are
      unchanged in every case.
- [ ] The class docstring documents the new emission.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_jsonschema_additional_properties.py -v`
- [ ] No regression: `pytest packages/parrot-formdesigner/tests/ -k jsonschema -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_jsonschema_additional_properties.py
import pytest
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer


class TestAdditionalProperties:
    async def test_reject_emits_false(self, form_factory):
        form = form_factory(unknown_fields="reject")
        result = await JsonSchemaRenderer().render(form)
        assert result.content["additionalProperties"] is False

    @pytest.mark.parametrize("policy", ["drop", "keep"])
    async def test_non_reject_omits_key(self, form_factory, policy):
        form = form_factory(unknown_fields=policy)
        result = await JsonSchemaRenderer().render(form)
        assert "additionalProperties" not in result.content

    async def test_drop_output_unchanged(self, form_factory):
        """Spec AC22 — byte-identical for a default form."""
        drop = await JsonSchemaRenderer().render(form_factory(unknown_fields="drop"))
        keep = await JsonSchemaRenderer().render(form_factory(unknown_fields="keep"))
        assert drop.content == keep.content

    async def test_other_schema_keys_intact(self, form_factory):
        result = await JsonSchemaRenderer().render(form_factory(unknown_fields="reject"))
        assert result.content["type"] == "object"
        assert result.content["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "properties" in result.content

    async def test_content_type_unchanged(self, form_factory):
        result = await JsonSchemaRenderer().render(form_factory(unknown_fields="reject"))
        assert result.content_type == "application/schema+json"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-26
**Notes**: Added `UnknownFieldsPolicy` to the existing top-level
`from ..core.schema import (...)` in `renderers/jsonschema.py`. In
`_build_structural_schema`'s assembly block, added
`if form.unknown_fields is UnknownFieldsPolicy.REJECT: schema[
"additionalProperties"] = False` right after the existing `if required`
conditional-key line, matching that style exactly (identity comparison,
no key emitted for `drop`/`keep`). Extended the class docstring with a
paragraph documenting the new emission. 7 new unit tests in
`tests/unit/test_jsonschema_additional_properties.py` (local `_form()`
helper matching the `test_jsonschema_post_depends.py` precedent, no
`form_factory` fixture existed in the codebase so one was not assumed).
No merge conflict encountered with FEAT-456/TASK-2414's `x-relation`
emission (both landed cleanly). Regression: `pytest -k jsonschema` — 99
passed, same 9 pre-existing unrelated collection errors; full-suite
`git stash` diff — zero new failures. `ruff check`: 0 new findings (the
file's 1 pre-existing `UP037` finding, confirmed via `git stash`, is
untouched; my own import addition required wrapping into the existing
multi-line style to stay `I001`-clean).

**Deviations from spec**: none.
