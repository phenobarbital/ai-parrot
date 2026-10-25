# TASK-4704: Strict ASCII-decimal parsing for render section_index

**Feature**: FEAT-745 — MS Teams FormDesigner mixin — wizard fall-through fix + hardening
**Spec**: `sdd/specs/msteams-formdesigner-mixin-tech-debt.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:cc81b5eee807`

---

## Context

Implements spec module M4 — sub-item (e) of `issue:cc81b5eee807`: the
FormDesigner render endpoint parses `section_index` with bare `int()`,
which accepts `" 1"`, `"+1"`, `"_"`-free unicode decimals such as `"١"`.
`section_index` is a non-negative array index; only ASCII digits are valid.

---

## Scope

- In `handle_render` (`packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py`,
  `section_index` parsing around line 215): guard with
  `raw_section.isascii() and raw_section.isdecimal()` before `int()`,
  returning the existing
  `{"error": "section_index must be an integer"}` 400 otherwise. The range
  check below stays unchanged.
- Tests: `" 1"`, `"+1"`, `"١"`, `"-1"` → 400; `"1"` → still accepted.

**NOT in scope**: anything in `ai-parrot-integrations` (TASK-4703); other
query params of `handle_render`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | ASCII-decimal guard |
| `packages/parrot-formdesigner/tests/` (existing render test module) | MODIFY | 4 new param cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Symbols (dev, 2026-10-25)
- `render.py:209-217`: `raw_section = request.query.get("section_index")`;
  `try: section_index = int(raw_section) except ValueError:` →
  `web.json_response({"error": "section_index must be an integer"}, status=400)`.
- Range check at `:218-219` (`0 <= section_index < len(form.sections)`).

### Does NOT Exist
- No helper for integer query parsing in `parrot_formdesigner.api` — the
  inline guard is the decided shape; do not create a utils module.

---

## Acceptance Criteria

- `" 1"`, `"+1"`, `"١"`, `"-1"` as `section_index` → HTTP 400 with the
  existing error body; `"1"` behaves as before.
- `ruff check` clean on changed files.

## Validation Commands

```bash
PYTHONPATH=packages/parrot-formdesigner/src \
  pytest packages/parrot-formdesigner/tests -q -k "render or section"
ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py
```

## Test Specification

Parametrized test over the render endpoint (use the existing aiohttp test
client fixture that render tests already use) asserting status 400 for the
four bad inputs and the prior success path for `"1"`.

## Agent Instructions

One guard, no refactors.

## Completion Note

Implemented in commit 8428a7cc1. section_index now requires isascii()+isdecimal() before int(); ' 1', '+1', unicode digits and '1_0' now 400. Render dispatcher tests green.
