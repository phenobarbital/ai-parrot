# TASK-5162: HTML5 renderer — BOOLEAN renders as Yes / No radios

**Feature**: FEAT-800 — Form Designer — boolean questions render as Yes / No (HTML5 + PDF)
**Spec**: `sdd/specs/formdesigner-boolean-yes-no.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1 (decision D1). A `FieldType.BOOLEAN` currently exports as a bare
checkbox in HTML5; it must render as two radios `Yes` / `No` (values `"true"` / `"false"`) using the
same markup as the radio select, on every BOOLEAN code path of `HTML5Renderer`.

---

## Scope

- Add module constant `_BOOLEAN_OPTIONS` and helper `_normalize_boolean(value) -> str`.
- Extend `_render_radio_group` with an optional `options` argument (default behaviour byte-identical).
- Add `_render_boolean_radio_group(field, value, locale)`.
- Replace the BOOLEAN branch of `_render_field_html` (label above group, optional description, then radios).
- Replace `_CheckboxRenderer` by `_BooleanRenderer` in the registry; remove the BOOLEAN entry of `_INPUT_TYPE_MAP`.
- Remove `_render_checkbox` only if no reference remains after the edits.

**NOT in scope**: PDF (TASK-5163), tests (TASK-5164), the REST-arguments boolean (~l.1490-1525, NG1), `adaptive_card.py` (NG2), version bump (NG3), i18n of Yes/No.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Boolean radios on every path |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..core.options import FieldOption   # NOT yet imported in html5.py (imports at html5.py:7-32); add it. verified: core/options.py:14
from typing import Any                   # html5.py:13 — add `Sequence` to this import (from typing import Any, Sequence)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py
_INPUT_TYPE_MAP: dict[FieldType, str] = {  # line 37;  FieldType.BOOLEAN: "checkbox",  # line 41
def _resolve(value: LocalizedString | None, locale: str = "en") -> str   # line 107
class _CheckboxRenderer:                                                  # line 199 (inner class of _build_registry)
    async def render(self_, field, *, locale="en", prefilled=None, error=None) -> Any: return self_._r._render_checkbox(field, prefilled)
FieldType.BOOLEAN: _CheckboxRenderer(self),                               # line 351
# _render_field_html: field_label/label_text/value/description/parts/render_as already in scope
elif ft == FieldType.BOOLEAN:                                             # line 791 (inline checkbox label, 791-796)
def _render_checkbox(self, field: FormField, value: Any) -> str           # line 1698
def _render_radio_group(self, field: FormField, value: Any, locale: str) -> str   # line 1816
    # selected = str(value) if value is not None else ""
    # '<div class="form-field__radio-group space-y-2">' + per option:
    # '<label class="form-field__radio-label inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">'
    # '<input type="radio" name="{field_id}" value="{opt.value}" class="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500"{checked}{disabled}{required}>'
# core/options.py:14  FieldOption(value: str, label: LocalizedString, description=None, disabled: bool=False, icon=None)
```

### Does NOT Exist
- ~~`HTML5Renderer._render_boolean_radio_group`~~, ~~`_BooleanRenderer`~~, ~~`_normalize_boolean`~~ — created by this task.
- ~~`parrot.formdesigner`~~ — the package is top-level `parrot_formdesigner`.
- ~~`FieldType.YES_NO`~~ — FIELD_YES_NO maps to `FieldType.BOOLEAN`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py#HTML5Renderer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Same markup/classes as `_render_radio_group` — never a third markup (navigator-svelte CSS targets `form-field__radio-group` / `form-field__radio-label`).
- SELECT `render_as: radio` output must stay byte-identical (regression test in TASK-5164).
- `data-depends-on` is emitted by the wrapper div before the branch — do not touch it.
- No `print`; strict type hints; 120 columns.

---

## Implementation Blueprint

### Steps (in order)
1. Add imports (`Sequence`, `FieldOption`) — *why*: the helpers are typed with them.
2. Remove `FieldType.BOOLEAN: "checkbox",` from `_INPUT_TYPE_MAP` — *why*: no BOOLEAN path may produce `type="checkbox"`; `_render_input` falls back to `"text"` via `.get(..., "text")` but BOOLEAN never reaches it any more.
3. Add `_BOOLEAN_OPTIONS` and `_normalize_boolean` next to `_resolve` — *why*: both are pure and shared by the form-field and registry paths.
4. Add the optional `options` argument to `_render_radio_group` — *why*: reuse the one markup instead of a third.
5. Add `_render_boolean_radio_group`; swap the registry class; rewrite the BOOLEAN branch.
6. `grep -n "_render_checkbox" html5.py`; delete the method only when nothing references it.

### `html5.py` — module level (MODIFY)
```python
# AFTER the `def _resolve(...)` function (anchor `def _resolve(value: LocalizedString | None, locale: str = "en") -> str:`
# occurrences: 1 (verified: grep -c -F 'def _resolve(value' html5.py), line 107) — insert below the whole function body:
_BOOLEAN_OPTIONS: tuple[tuple[str, str], ...] = (("true", "Yes"), ("false", "No"))


def _normalize_boolean(value: Any) -> str:
    """Normalize a boolean-ish prefill to ``"true"``, ``"false"`` or ``""``.

    Args:
        value: Prefilled value (bool, int, str or None).

    Returns:
        ``"true"`` for True/"true"/"True"/1/"1", ``"false"`` for False/"false"/"False"/0/"0", else ``""``.
    """
    # FILL IN: compare with `is True`/`is False` first (bool is an int subclass), then the str/int sets — bounded by AC "True/"true"/"True"/1/"1" → Yes; False/"false"/"False"/0/"0" → No; None → nothing"
    raise NotImplementedError
```

### `html5.py` — `_render_radio_group` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'def _render_radio_group(' html5.py), line 1816
# Change the signature to add `options: Sequence[FieldOption] | None = None` (last parameter) and,
# in the body, iterate `options if options is not None else field.options` instead of `field.options`.
# FILL IN: keep the output byte-identical when `options is None` — bounded by AC "SELECT render_as: radio unchanged".

    def _render_boolean_radio_group(self, field: FormField, value: Any, locale: str) -> str:
        """Render a Yes/No radio group for a BOOLEAN field.

        Args:
            field: BOOLEAN FormField.
            value: Prefilled value (normalized internally).
            locale: Locale (labels are fixed English literals per spec D1).

        Returns:
            HTML radio group string (values ``"true"`` / ``"false"``).
        """
        options = [FieldOption(value=v, label=text) for v, text in _BOOLEAN_OPTIONS]
        return self._render_radio_group(field, _normalize_boolean(value), locale, options)
```
**Why**: delegating to the existing method guarantees identical markup; `required` and `checked` come from `_render_radio_group`.

### `html5.py` — registry (MODIFY)
```python
# AFTER — replace `class _CheckboxRenderer:` (line 199, occurrences 1) with:
        class _BooleanRenderer:
            def __init__(self_, renderer: "HTML5Renderer") -> None:
                self_._r = renderer

            async def render(
                self_, field: FormField, *, locale: str = "en", prefilled: Any = None, error: str | None = None
            ) -> Any:
                return self_._r._render_boolean_radio_group(field, prefilled, locale)
# and replace `FieldType.BOOLEAN: _CheckboxRenderer(self),` (line 351, occurrences 1) with `FieldType.BOOLEAN: _BooleanRenderer(self),`
```

### `html5.py` — form-field branch (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'elif ft == FieldType.BOOLEAN:' html5.py), line 791 — replace the whole branch body (791-796) with:
        elif ft == FieldType.BOOLEAN:
            parts.append(
                f'<label class="block text-sm font-medium text-gray-700 mb-1">{label_text}</label>'
            )
            if description:
                parts.append(f'<span class="form-field__help text-xs text-gray-500 mb-1 block">{description}</span>')
            parts.append(self._render_boolean_radio_group(field, value, locale))
```
**Why**: the question label is the field label above the group (like other fields), appearing exactly once; no `for=` because radios share a name and have no single id.

### FILL IN checklist
- [ ] `_normalize_boolean` body — bounded by the value table in spec §2 Overview.
- [ ] `_render_radio_group` options iteration — bounded by "output unchanged for SELECT".
- [ ] `_render_checkbox` removal decision — only if `grep` shows zero remaining references.

---

## Acceptance Criteria

- [ ] BOOLEAN renders two radios Yes/No (values true/false), same markup/classes; no `type="checkbox"` for BOOLEAN on any path
- [ ] None → none checked; True/"true"/1 → Yes; False/"false"/0 → No
- [ ] `required` emitted on radios when required; label once; `data-depends-on` unchanged
- [ ] SELECT `render_as: radio` output unchanged
- [ ] `ruff check` clean on `html5.py`; existing `tests/unit/test_renderers.py` passes

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_renderers.py -q`

---

## Test Specification

Tests are written in TASK-5164 (they depend on this task). Smoke check here:

```python
# python -c style smoke (run with PYTHONPATH=packages/parrot-formdesigner/src)
html = HTML5Renderer()._render_boolean_radio_group(FormField(field_id="a", field_type=FieldType.BOOLEAN, label="A"), True, "en")
assert 'value="true" ' in html and "checked" in html and 'type="checkbox"' not in html
```

---

## Agent Instructions

Follow the standard procedure: worktree via `parrot sdd worktree ensure`, verify the contract, set `in-progress` in `sdd/tasks/index/formdesigner-boolean-yes-no.json`, implement from the blueprint, run Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`, commit only the listed file, close with `parrot sdd task close TASK-5162 formdesigner-boolean-yes-no verified`, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet, sequential, no coder seats)
**Date**: 2026-11-04
**Notes**: Implemented in html5.py: `_BOOLEAN_OPTIONS`, `_normalize_boolean`, `_render_radio_group(options=)`, `_render_boolean_radio_group`, `_BooleanRenderer` (replaces `_CheckboxRenderer`); BOOLEAN removed from `_INPUT_TYPE_MAP`; label-above-group branch; unused `_render_checkbox` removed (no other callers, grep-verified).

**Deviations from spec**: none | describe if any
