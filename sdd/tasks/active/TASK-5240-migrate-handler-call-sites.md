# TASK-5240: Migrate the six A2UI POST handlers to the capped body reader

**Feature**: FEAT-822 — Enforce A2UI request body-size limits before parsing
**Spec**: `sdd/specs/fixgroup-adbf411ace18.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5239
**Assigned-to**: unassigned
**Discovered-from**: `issue:bf978b6bae8a`

---

## Context

With TASK-5239's `read_capped_json` in place, replace every advisory
`content_length` guard in `handlers.py` with a read that is bounded before the
body is parsed, and give `export_forms` the cap it never had.

The four existing guards are identical text at handlers.py:1265, 1425, 1629 and
2073 (`grep -c` → 4), and `body = await request.json()` occurs **21 times** in
the file (lines 251, 720, 1186, 1268, 1352, 1417, 1525, 1572, 1701, 1782, 1838,
1904, 2061, 2250, 2443, 2799, 2870, 2921, 3007, 3082, 3183). Only the six sites
named below are in scope — **every MODIFY block in this task must be
disambiguated by surrounding context, never by the bare anchor line.**

## Scope

- Replace the body read at the six in-scope sites with
  `a2ui_wire.read_capped_json(request)`, handling `OverSizedBody` before the
  existing `json.JSONDecodeError` branch.
- Delete the four now-redundant `content_length` guards.
- Add the cap to `export_forms`, which has none.
- Extend `test_a2ui_body_limits.py` with route-level tests.

**NOT in scope**:
- `translate_form`'s locale/form_id/title and schema-depth validation — that is
  TASK-5241 (which edits the same file and therefore runs after this task).
- The other 15 `request.json()` sites in `handlers.py`.
- Changing any success-path status code or body.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY |
| `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` | MODIFY |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `HEAD=ca4b0fc523`. TASK-5239's symbols are **created by that
> task** — this task may rely on them but must not redefine them.

### Verified Imports

```python
from aiohttp import web                               # handlers.py — already present
from parrot_formdesigner.api import a2ui_wire         # handlers.py imports it as `a2ui_wire`
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope  # handlers.py:1630, LOCAL import
```

From TASK-5239 (same module, already imported as `a2ui_wire`):

```python
a2ui_wire.OverSizedBody            # exception
a2ui_wire.read_capped_json         # async, replaces `await request.json()`
a2ui_wire.oversized_json_response  # (limit) -> web.Response, status 413
a2ui_wire.oversized_a2ui_response  # (surface_id, message) -> web.Response, status 413
a2ui_wire.is_a2ui_content_type     # (request) -> bool, headers only
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
async def export_forms(self, request: web.Request) -> web.Response: ...   # line 1174, occurrences: 1
async def translate_form(self, request: web.Request) -> web.Response: ... # line 1255, occurrences: 1
async def create_form(self, request: web.Request) -> web.Response: ...    # line 1567, occurrences: 1
async def _import_a2ui_surface(self, request, body, *, tenant) -> web.Response: ...  # line 1627, occurrences: 1

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
app.router.add_post(f"{tp}/forms", _wrap_auth(handler.create_form))              # line 413
app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))      # line 437
app.router.add_post(f"{tp}/forms/translate", _wrap_auth(handler.translate_form)) # line 439
```

**In-scope edit sites** (re-verify each line before editing — the file moves):

| Site | `request.json()` | `content_length` guard |
|---|---|---|
| `export_forms` | 1186 | — (none today) |
| `translate_form` | 1268 | 1265 (pre-parse) |
| edit/patch handler | 1417 | 1425 (post-parse) |
| `create_form` | 1572 | — (its guard lives in the callee) |
| `_import_a2ui_surface` | — (receives parsed body) | 1629 (post-parse) |
| `submit_data` | 2061 | 2073 (post-parse) |

### Does NOT Exist

- `handlers.py` has **no** existing `OverSizedBody` handling, no
  `read_capped_json` call, no shared body helper — 0 hits for all of them.
- There is no `self._read_body`, no `BaseHandler.json_body`, no
  `@max_body_size` decorator in this package. Do not invent one.
- `web.Request.body` / `request.raw_body` do not exist — use
  `a2ui_wire.read_capped_json(request)`.
- `is_a2ui_request` requires the **parsed body** (a2ui_wire.py:140); it cannot
  be used in the oversize branch. Use `is_a2ui_content_type` there.

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
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormDesignerHandler.create_form",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormDesignerHandler.translate_form",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormDesignerHandler.export_forms",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormDesignerHandler._import_a2ui_surface"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Error-shape preservation (spec AC5).** A2UI routes must still answer with
  an `error_envelope` carrying the right `surfaceId`; plain routes must still
  answer `{"error": "body too large", "max_bytes": N}`.
- **The oversize branch cannot see the body.** On the edit and submit routes
  the current code picks the A2UI shape via `is_a2ui_request(request, body)`,
  which needs the parsed body. Since the cap now fires first, use
  `is_a2ui_content_type(request)` for that branch only. A non-A2UI oversize
  request on those routes therefore gets the plain-JSON 413 — a *new* status
  for a request that previously got an unbounded read, not a regression of any
  success path.
- **Exception order matters**: `except a2ui_wire.OverSizedBody` must precede
  `except (json.JSONDecodeError, ValueError)`, because `OverSizedBody` is not a
  `ValueError` but readers often reorder these blocks by habit.
- **`_import_a2ui_surface` loses its guard entirely** — its only caller
  (`create_form`, line 1579) now enforces the cap before parsing. Leaving both
  would be dead code that implies the callee is safe to call unguarded.

### References in Codebase

- `handlers.py:1630-1637` — the A2UI 413 envelope shape to preserve.
- `handlers.py:1266` — the plain-JSON 413 shape to preserve.
- `handlers.py:1426-1433`, `:2074-2081` — the two per-form A2UI 413s whose
  `surface_id` is `f"form-{form.form_uid}"`.

---

## Implementation Blueprint

### Steps (in order)

1. For each of the six sites, replace the read and delete the guard **one site
   at a time**, re-running `grep -n` after each edit — the anchors are
   near-duplicates and the line numbers shift as you go.
2. Delete the four `content_length` guards only after their replacement read is
   in place, so the file is never in a state with no limit at all.
3. Add route-level tests last, so they exercise the finished wiring.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — `create_form`

```python
# occurrences: 21 (verified: grep -c 'body = await request.json()' handlers.py)
# >1 occurrence — disambiguate by surrounding context, NOT by the bare anchor.
# REPLACE this exact 5-line window (verified: handlers.py:1570-1574):
#
#         await self._rbac_shadow_gate(request, "create_form")
#         try:
#             body = await request.json()
#         except (json.JSONDecodeError, ValueError):
#             return JSONResponse({"error": "Invalid JSON body"}, status=400)
#
# with:
        await self._rbac_shadow_gate(request, "create_form")
        try:
            body = await a2ui_wire.read_capped_json(request)
        except a2ui_wire.OverSizedBody as exc:
            # FEAT-822: the cap is enforced before parsing, so the error shape
            # is chosen from headers alone (the body is not available here).
            if a2ui_wire.is_a2ui_content_type(request):
                return a2ui_wire.oversized_a2ui_response("form-import", "body too large")
            return a2ui_wire.oversized_json_response(exc.limit)
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)
```

**Why**: `create_form` is the route that actually parsed before checking, so
this is the site that closes spec AC3. `"form-import"` matches the fallback
`surface_id` the deleted guard used at handlers.py:1636.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — `_import_a2ui_surface`

```python
# occurrences: 4 (verified: grep -c 'if request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES:' handlers.py)
# >1 occurrence — disambiguate: this is the one inside `async def _import_a2ui_surface`
# (verified: handlers.py:1629, the guard whose next line is
# `from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope`
# followed by `surface = body.get("createSurface")`).
# DELETE the whole guard block, handlers.py:1629-1638 inclusive.
```

**Why**: its only caller now enforces the cap before parsing, so this check can
never fire; leaving it would falsely suggest the callee is safe unguarded.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — `translate_form`

```python
# occurrences: 4 for the guard / 21 for the read — disambiguate: this is the pair
# inside `async def translate_form` (verified: handlers.py:1265 guard, :1268 read),
# identified by the preceding line `tenant = self._get_tenant(request)` and the
# following line `schema = body.get("schema") if isinstance(body, dict) else None`.
# REPLACE handlers.py:1265-1270 with:
        try:
            body = await a2ui_wire.read_capped_json(request)
        except a2ui_wire.OverSizedBody as exc:
            return a2ui_wire.oversized_json_response(exc.limit)
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)
```

**Why**: this route's guard was already pre-parse, so only the chunked bypass
needed closing; it keeps the plain-JSON 413 shape (spec AC5).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — edit handler and `submit_data`

```python
# occurrences: 4 guards / 21 reads — these are the two near-identical sites at
# handlers.py:1416-1433 and :2060-2081. Disambiguate by the line that FOLLOWS
# each guard block: the edit handler's is `try:\n    submission_in = a2ui_wire.unwrap_action(form, body)`
# preceded by `enforce_membership_unless_public(request, form, tenant)` (:1415);
# submit_data's guard is preceded by the comment block `# FEAT-544 (spec §3 Module 5): dual-wire`.
# For EACH site: replace the `body = await request.json()` read with the capped
# read below, then DELETE that site's `content_length` guard (keeping the
# `unwrap_action` try/except that follows it untouched).
        try:
            body = await a2ui_wire.read_capped_json(request)
        except a2ui_wire.OverSizedBody as exc:
            if a2ui_wire.is_a2ui_content_type(request):
                return a2ui_wire.oversized_a2ui_response(
                    f"form-{form.form_uid}",
                    "The submitted data model exceeds the maximum allowed size.",
                )
            return a2ui_wire.oversized_json_response(exc.limit)
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)
```

**Why**: both sites already resolve `form` before reading the body, so
`f"form-{form.form_uid}"` reproduces the exact `surface_id` the deleted guards
used (handlers.py:1429, :2077) and the message string is copied verbatim from
them — spec AC5.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY) — `export_forms`

```python
# occurrences: 21 for the read — disambiguate: the one inside
# `async def export_forms` (verified: handlers.py:1186), identified by the two
# preceding lines `tenant = self._get_tenant(request)` and
# `await self._rbac_shadow_gate(request, "export_forms")`.
# REPLACE that read's try/except with:
        try:
            body = await a2ui_wire.read_capped_json(request)
        except a2ui_wire.OverSizedBody as exc:
            return a2ui_wire.oversized_json_response(exc.limit)
        except (json.JSONDecodeError, ValueError):
            return JSONResponse({"error": "Invalid JSON body"}, status=400)
```

**Why**: spec G3 — this route accepts a POST body today with no limit at all.
It is not an A2UI route, so it gets the plain-JSON 413.

### `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'def test_oversized_json_response_shape' test_a2ui_body_limits.py — created by TASK-5239)
# AFTER — append below `def test_oversized_json_response_shape():`

# --- Route-level tests (TASK-5240) -------------------------------------------
# FILL IN: reuse this package's existing aiohttp app fixture — bounded by the
# constraint that these must be real route calls, not fake requests. Locate it
# in packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py and
# test_translate_forms.py and import/reuse rather than building a new app.


async def test_create_form_413_over_cap(...):
    """Spec AC1: POST /forms over the cap -> 413."""
    ...


async def test_create_form_413_chunked_over_cap(...):
    """Spec AC2: the chunked bypass is closed."""
    # FILL IN: send the body as an async generator so aiohttp uses
    # Transfer-Encoding: chunked and content_length is None — bounded by AC2.
    ...


async def test_import_a2ui_413_keeps_envelope_shape(...):
    """Spec AC5: A2UI import over the cap -> error_envelope, status 413."""
    ...


async def test_translate_form_413_over_cap(...): ...
async def test_translate_form_413_chunked_over_cap(...): ...
async def test_submit_data_413_chunked_over_cap(...): ...
async def test_export_forms_413_over_cap(...):
    """Spec AC1/G3: the route that had no limit now has one."""
    ...


async def test_under_cap_requests_unchanged(...):
    """Spec AC6: every migrated route still succeeds on a normal body."""
    ...
```

**Why**: the chunked variants are the tests that would have caught the original
bug; the `under_cap` test is the regression guard for AC6.

### FILL IN checklist

- [ ] Per-call read size / app fixture reuse in the route tests.
- [ ] Chunked request construction (async generator as `data=`).
- [ ] All nine route-test bodies.
- [ ] Confirm `grep -c 'request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES' handlers.py` returns **0** when done (spec AC4).

---

## Acceptance Criteria

- [ ] All six routes return 413 for an over-cap body (spec AC1), including
      `export_forms`.
- [ ] All six return 413 for an over-cap **chunked** body (spec AC2).
- [ ] No `request.content_length ... A2UI_MAX_BODY_BYTES` comparison remains in
      `handlers.py` (spec AC4) — `grep -c` returns 0.
- [ ] A2UI routes still return an `error_envelope` with the correct
      `surfaceId`; plain routes still return `{"error","max_bytes"}` (AC5).
- [ ] Under-cap requests behave exactly as before (AC6).
- [ ] `ruff check` clean on both files (AC9).

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py -q`

## Test Specification

Spec §4 rows `test_create_form_*`, `test_import_a2ui_413_keeps_envelope_shape`,
`test_translate_form_413_*`, `test_submit_data_413_chunked_over_cap`,
`test_export_forms_413_over_cap`, `test_under_cap_requests_unchanged`.
Run with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src`.

## Agent Instructions

Edit one site at a time and re-grep between edits — the four guards are
byte-identical and the 21 `request.json()` reads are near-identical. Never
match a bare anchor. Do not touch the 15 out-of-scope `request.json()` sites.

## Completion Note

<!-- filled at close -->
