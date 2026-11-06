# TASK-5241: Validate `translate_form` scalars and cap JSON-Schema depth

**Feature**: FEAT-822 — Enforce A2UI request body-size limits before parsing
**Spec**: `sdd/specs/fixgroup-adbf411ace18.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5239, TASK-5240
**Assigned-to**: unassigned
**Discovered-from**: `issue:bf978b6bae8a`

---

## Context

The second limb of `issue:bf978b6bae8a` (FEAT-650 review item S3): in
`translate_form` the caller-controlled `locale`, `form_id` and `title` are
forwarded to `translate_jsonschema_to_a2ui` with no type validation, and the
incoming JSON Schema is neither size- nor depth-capped. A deeply nested schema
can exhaust the recursion budget inside the translator, and a non-string
`locale` propagates an unexpected type into the renderer.

Size is handled by TASK-5240's byte cap. This task adds the type checks and the
depth cap.

## Scope

- In `translate_form`, reject non-string `locale` / `form_id` / `title` with
  400 before calling the translator.
- Reject a schema nested deeper than `a2ui_wire.A2UI_MAX_SCHEMA_DEPTH` with
  400, measured **iteratively**.
- Extend `test_a2ui_body_limits.py` with the S3 tests.

**NOT in scope**:
- Byte-size enforcement (TASK-5240).
- Any other handler, or any other `translate_form` behaviour.
- Validating the schema's *contents* beyond nesting depth (no JSON-Schema
  meta-validation).

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY |
| `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` | MODIFY |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `HEAD=ca4b0fc523`. **This task runs after TASK-5240 has rewritten
> `translate_form`'s body read**, so re-grep the anchors before editing — the
> line numbers below are pre-TASK-5240.

### Verified Imports

```python
from parrot_formdesigner.api import a2ui_wire   # handlers.py — already present as `a2ui_wire`
```

From TASK-5239: `a2ui_wire.A2UI_MAX_SCHEMA_DEPTH` (int, default 32,
env-overridable via `A2UI_MAX_SCHEMA_DEPTH`).

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
async def translate_form(self, request: web.Request) -> web.Response: ...  # line 1255, occurrences: 1

# Current body of translate_form, verified handlers.py:1271-1286:
#   schema = body.get("schema") if isinstance(body, dict) else None
#   if not isinstance(schema, dict):
#       return JSONResponse({"error": "schema (object) is required"}, status=400)
#   if get_renderer("a2ui") is None:
#       return JSONResponse({"supported": supported_formats()}, status=415)
#   from ..services.a2ui_translate import translate_jsonschema_to_a2ui
#   rendered = await translate_jsonschema_to_a2ui(
#       schema,
#       form_id=body.get("form_id"),
#       title=body.get("title"),
#       tenant=tenant,
#       locale=body.get("locale", "en"),
#   )
```

The translator is imported **lazily inside the handler** (handlers.py:1278) —
keep it that way.

### Does NOT Exist

- `a2ui_wire.validate_schema_depth`, `a2ui_wire.check_depth`,
  `handlers._schema_depth` — **the depth helper is created by this task**, as a
  module-level private function in `handlers.py`.
- There is no existing JSON-Schema validator, no `jsonschema` dependency in
  this package, and no `pydantic` model for the translate request body. Do not
  add a dependency.
- `translate_jsonschema_to_a2ui` has **no** `max_depth` parameter — do not pass
  one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormDesignerHandler.translate_form"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **The depth walk must not recurse.** Checking a hostile schema with a
  recursive function would hit `RecursionError` — the exact failure the cap
  exists to prevent. Use an explicit stack of `(node, depth)` pairs.
- **Short-circuit on the cap.** Stop walking the moment `depth > cap`; do not
  traverse the whole structure first and measure afterwards.
- `locale` keeps its `"en"` default — only a *present, non-string* value is an
  error. Same for `form_id` / `title`: absent or `None` is fine.
- Validate **before** the `get_renderer("a2ui") is None` 415 check, so a
  malformed request is a 400 regardless of renderer availability.

### References in Codebase

- `handlers.py:1271-1273` — the existing `{"error": "..."}` 400 shape to match.
- `a2ui_wire.py:39` — the sibling cap constant, for the style of the new one.

---

## Implementation Blueprint

### Steps (in order)

1. Add the iterative `_schema_depth_exceeds` helper at module level in
   `handlers.py` — module level, not a method, because it is pure and needs no
   handler state, which also makes it directly unit-testable.
2. Insert the scalar type checks and the depth check into `translate_form`
   immediately after the existing `schema` check, because that check already
   guarantees `body` is a dict and `schema` is a dict.
3. Add the tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — depth helper

```python
# occurrences: 1 (verified: grep -c 'async def translate_form' handlers.py)
# BEFORE — insert at module level, immediately above the class that defines
# `async def translate_form` (verified: handlers.py:1255 is the method; place the
# helper near the other module-level helpers at the top of the file, NOT inside
# the class body).

def _schema_depth_exceeds(schema: Any, max_depth: int) -> bool:
    """Return whether ``schema`` nests deeper than ``max_depth``.

    Walks iteratively with an explicit stack and short-circuits as soon as the
    cap is passed, so a hostile schema can neither exhaust the Python stack nor
    force a full traversal (FEAT-822 / issue:bf978b6bae8a S3).

    Args:
        schema: The decoded JSON value to measure.
        max_depth: The maximum permitted nesting depth.

    Returns:
        ``True`` when some path nests deeper than ``max_depth``.
    """
    stack: list[tuple[Any, int]] = [(schema, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            return True
        # FILL IN: push each child of a dict/list as (child, depth + 1);
        # scalars have no children — bounded by the requirement that the walk
        # never recurses and never revisits a node.
        ...
    return False
```

**Why**: an explicit stack is the only shape that satisfies AC7's
"without raising `RecursionError`"; short-circuiting keeps the check O(cap)
rather than O(size) for the hostile case it defends against.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — `translate_form`

```python
# occurrences: 1 (verified: grep -c 'return JSONResponse({"error": "schema (object) is required"}, status=400)' handlers.py)
# AFTER — insert below `            return JSONResponse({"error": "schema (object) is required"}, status=400)`
# (verified: handlers.py:1273; re-grep after TASK-5240, which rewrites the lines above it)

        for _field in ("locale", "form_id", "title"):
            _value = body.get(_field)
            if _value is not None and not isinstance(_value, str):
                return JSONResponse({"error": f"{_field} must be a string"}, status=400)

        if _schema_depth_exceeds(schema, a2ui_wire.A2UI_MAX_SCHEMA_DEPTH):
            return JSONResponse(
                {"error": "schema too deeply nested", "max_depth": a2ui_wire.A2UI_MAX_SCHEMA_DEPTH},
                status=400,
            )
```

**Why**: placed after the `schema` check so `body` and `schema` are both known
dicts, and before the 415 renderer check so a malformed request is always a
400. The response bodies match the file's existing `{"error": ...}` convention
(handlers.py:1272).

### `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_under_cap_requests_unchanged' test_a2ui_body_limits.py — added by TASK-5240)
# AFTER — append below `async def test_under_cap_requests_unchanged(...)`

# --- translate_form input validation (TASK-5241, spec AC7) -------------------

async def test_translate_form_rejects_non_string_locale(...):
    """Spec AC7: `locale: 5` -> 400."""
    ...


async def test_translate_form_rejects_non_string_form_id_title(...):
    """Spec AC7: non-string form_id / title -> 400, one case each."""
    ...


async def test_translate_form_rejects_deep_schema(...):
    """Spec AC7: over A2UI_MAX_SCHEMA_DEPTH -> 400 carrying `max_depth`."""
    # FILL IN: monkeypatch a2ui_wire.A2UI_MAX_SCHEMA_DEPTH small — bounded by
    # the need to keep the payload under TASK-5240's byte cap.
    ...


def test_translate_form_depth_check_is_iterative():
    """Spec AC7: a 10 000-deep schema returns True without RecursionError."""
    # FILL IN: build the nested dict with a loop, not recursion, and call
    # _schema_depth_exceeds directly — bounded by the AC's explicit
    # "without raising RecursionError".
    ...


async def test_translate_form_accepts_valid_scalars(...):
    """Spec AC6: a normal translate request still succeeds unchanged."""
    ...
```

**Why**: the 10 000-deep case is the one that fails loudly against a recursive
implementation, so it is the test that actually pins AC7's requirement.

### FILL IN checklist

- [ ] `_schema_depth_exceeds`: child-push logic for dict and list.
- [ ] Depth-cap monkeypatch kept under the byte cap.
- [ ] 10 000-deep schema built iteratively.
- [ ] All five test bodies.

---

## Acceptance Criteria

- [ ] Non-string `locale` / `form_id` / `title` → 400 `{"error": "<field> must be a string"}` (spec AC7).
- [ ] Absent or `None` for those fields still works; `locale` keeps its `"en"` default (AC6).
- [ ] A schema deeper than `A2UI_MAX_SCHEMA_DEPTH` → 400 with `max_depth` (AC7).
- [ ] A 10 000-deep schema is rejected **without** `RecursionError` (AC7).
- [ ] A valid translate request behaves exactly as before (AC6).
- [ ] `ruff check` clean on both files (AC9).

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py -q`

## Test Specification

Spec §4 rows `test_translate_form_rejects_non_string_locale`,
`test_translate_form_rejects_non_string_form_id_title`,
`test_translate_form_rejects_deep_schema`,
`test_translate_form_depth_check_is_iterative`.
Run with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src`.

## Agent Instructions

TASK-5240 rewrites the lines just above this task's anchor — re-grep
`'return JSONResponse({"error": "schema (object) is required"}, status=400)'`
before editing and use the fresh line number. Touch only `translate_form` and
the new module-level helper.

## Completion Note

<!-- filled at close -->
