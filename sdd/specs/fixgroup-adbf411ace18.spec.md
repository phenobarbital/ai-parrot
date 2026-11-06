---
type: feature
base_branch: dev
projects: [formdesigner]
tags: [a2ui, security, request-limits, formdesigner, api]
---

# Feature Specification: Enforce A2UI request body-size limits before parsing

**Feature ID**: FEAT-822
**Date**: 2026-11-06
**Author**: /sdd-fix (agent:sdd-fix:e591e946)
**Status**: approved
**Target version**: 2.1.2

---

## 1. Motivation & Business Requirements

### Problem Statement

`issue:bf978b6bae8a` (major, discovered from `spec:FEAT-650` review item I2).
Every A2UI body-size limit in `parrot_formdesigner/api/handlers.py` is
**advisory**: it is spelled

```python
if request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES:
    ...413...
```

which fails open in two distinct ways:

1. **Chunked transfer-encoding bypasses the cap entirely.** aiohttp sets
   `request.content_length` to `None` when the client uses
   `Transfer-Encoding: chunked`, so the guard short-circuits and an unbounded
   body is read. This affects *all four* sites that have a check.
2. **The cap is checked after the body is already in memory.** In
   `create_form` the body is parsed by `await request.json()` (handlers.py:1572)
   and only then handed to `_import_a2ui_surface`, whose check sits at
   handlers.py:1629. Likewise the form-edit handler parses at :1416 and checks
   at :1425, and `submit_data` parses at :2060 and checks at :2073. By the time
   the 413 is produced the allocation the limit exists to prevent has already
   happened.

`export_forms` (`POST .../forms/export`, routes.py:437) has no limit at all.

FEAT-650 AC11 requires a 413 over the cap. Today a hostile or buggy client gets
a 200/400 and an uncapped allocation instead, which is a denial-of-service
surface on every A2UI POST route.

A second, related review item from the same source (S3) is in scope: in
`translate_form` the attacker-controlled `locale`, `form_id` and `title` are
passed to the translator without type validation, and the incoming JSON Schema
is neither size- nor depth-capped, so a deeply nested schema can exhaust the
recursion/parse budget inside `translate_jsonschema_to_a2ui`.

### Goals

- G1 — Reject an over-cap body with **413 before any body bytes are parsed**,
  on every A2UI-capable POST route.
- G2 — Close the chunked-body bypass: the cap must hold when
  `request.content_length is None`.
- G3 — Give `export_forms` the same cap as its siblings.
- G4 — Validate `locale` / `form_id` / `title` types and cap the size and
  nesting depth of the incoming JSON Schema in `translate_form`.
- G5 — Preserve each site's existing **error shape**: A2UI routes keep
  returning an A2UI `error_envelope` with the right `surfaceId`; plain-JSON
  routes keep returning `{"error": ..., "max_bytes": ...}`.

### Non-Goals (explicitly out of scope)

- Changing the value or the name of `A2UI_MAX_BODY_BYTES` / the
  `A2UI_MAX_DATA_MODEL_BYTES` environment variable.
- Streaming/multipart file upload limits (`test_file_upload.py` territory) —
  a separate mechanism, untouched here.
- `issue:e963c78a05de` (formdesigner CLI blocking Path calls, export filename
  sanitisation) — a different, unclaimed ledger issue on the same file.
- Rate limiting, auth, or RBAC changes.

---

## 2. Architectural Design

### Overview

Introduce one shared, cap-enforcing read helper in `api/a2ui_wire.py` — the
module that already owns `A2UI_MAX_BODY_BYTES` — and route every affected
handler through it instead of reading `request.content_length` by hand.

The helper reads at most `MAX + 1` bytes off the request stream. If it gets
`MAX + 1` bytes the body is over the cap *by construction*, whatever the
client declared in `Content-Length` and whether or not the body is chunked.
The check therefore no longer depends on a header the client controls, and it
happens strictly before `json.loads`.

```
             ┌─ create_form ──────────┐
             ├─ _import_a2ui_surface ─┤
POST body ──→├─ translate_form ───────┤──→ read_capped_json(request, …)
             ├─ edit/patch handler ───┤        │
             ├─ submit_data ──────────┤        ├─ content.read(MAX+1)
             └─ export_forms ─────────┘        ├─ len > MAX → OverSizedBody
                                               └─ json.loads → dict
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `a2ui_wire.A2UI_MAX_BODY_BYTES` | reuses | the cap value is unchanged |
| `a2ui_wire.a2ui_response` | reuses | A2UI-shaped 413 envelopes |
| `parrot.outputs.a2ui.runtime.models.error_envelope` | reuses | `A2UIErrorCode.INTERNAL` |
| `FormDesignerHandler.create_form` et al. | modifies | replaces the inline `content_length` guards |
| `aiohttp.web.Request.content` | uses | `StreamReader.read(n)` is the hard cap |

### New Public Interfaces

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py

class OverSizedBody(Exception):
    """Raised when a request body exceeds ``A2UI_MAX_BODY_BYTES``."""

    def __init__(self, *, limit: int) -> None: ...

    limit: int


async def read_capped_body(request: web.Request, *, limit: int | None = None) -> bytes:
    """Read the request body, refusing to buffer more than ``limit`` bytes.

    Reads ``limit + 1`` bytes from ``request.content``; the extra byte is what
    proves the body is over the cap without trusting ``Content-Length``. Works
    identically for chunked bodies, where ``content_length`` is ``None``.

    Raises:
        OverSizedBody: when the body exceeds ``limit``.
    """


async def read_capped_json(request: web.Request, *, limit: int | None = None) -> Any:
    """Read and JSON-decode a request body under a hard size cap.

    Raises:
        OverSizedBody: when the body exceeds ``limit`` (before any parsing).
        json.JSONDecodeError: when the capped bytes are not valid JSON.
    """


def oversized_json_response(limit: int) -> web.Response:
    """Return the plain-JSON 413 used by non-A2UI routes."""


def oversized_a2ui_response(surface_id: str, message: str) -> web.Response:
    """Return the A2UI-enveloped 413 used by A2UI routes."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: capped body reader | yes | signatures above; `read(limit+1)`; `len > limit` → raise | — |
| M2: handler call-site migration | yes | five named sites, each keeps its current error shape | — |
| M3: translate_form input validation | yes | type checks + depth/size caps, 400 on violation | — |

### Module 1: Capped body reader
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py`
- **Responsibility**: own the single hard-cap read path and the two 413
  response shapes.
- **Depends on**: `A2UI_MAX_BODY_BYTES` (same file, line 39), `a2ui_response`
  (same file, line 293).
- **Interface Skeleton**: as in §2 *New Public Interfaces*.
- **Contract**:
  - `limit=None` resolves to `A2UI_MAX_BODY_BYTES` **at call time**, not at
    import time, so the environment variable stays overridable in tests.
  - A body of exactly `limit` bytes is accepted; `limit + 1` is rejected.
  - `read_capped_json` never calls `request.json()` and never reads more than
    `limit + 1` bytes.

### Module 2: Handler call-site migration
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: replace every advisory `content_length` guard with the
  capped read, preserving the current status codes and bodies.
- **Depends on**: Module 1.
- **Sites** (all line numbers verified against dev, §6):

  | Site | Current | After |
  |---|---|---|
  | `create_form` :1572 | `await request.json()` | `await a2ui_wire.read_capped_json(request)`; `OverSizedBody` → A2UI 413 when the raw bytes look like a surface body, else plain 413 |
  | `_import_a2ui_surface` :1629 | post-parse `content_length` check | guard **deleted** — the cap is enforced by its caller before parsing |
  | `translate_form` :1265 | pre-parse `content_length` check, then `request.json()` :1268 | single `read_capped_json`; `OverSizedBody` → `oversized_json_response` |
  | edit handler :1416/:1425 | parse, then check | `read_capped_json`; `OverSizedBody` → `oversized_a2ui_response(f"form-{form.form_uid}", …)` |
  | `submit_data` :2060/:2073 | parse, then check | same as the edit handler |
  | `export_forms` :1184+ | no limit | `read_capped_json` with the same cap |
- **Error-shape preservation**: the edit handler and `submit_data` only emit the
  A2UI-shaped 413 when the request is an A2UI request. Because the cap now fires
  before the body is available, the decision is made on the request headers
  (`a2ui_wire.is_a2ui_request` currently needs the parsed body) — therefore M2
  adds a headers-only predicate `is_a2ui_content_type(request)` and uses it for
  the oversize branch only. A non-A2UI oversize request on those routes gets the
  plain-JSON 413. This is a *new* status for a request that previously got
  an unbounded read, not a regression of an existing success path.

### Module 3: `translate_form` input validation
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
- **Responsibility**: S3 — validate caller-controlled scalars and bound the
  incoming JSON Schema before translation.
- **Depends on**: Module 2 (runs after the capped read).
- **Contract**:
  - `locale`, `form_id`, `title` must each be `str` or absent/`None`; anything
    else → `400 {"error": "<field> must be a string"}`. `locale` keeps its
    `"en"` default.
  - The schema's nesting depth is capped at `A2UI_MAX_SCHEMA_DEPTH` (new
    module-level constant in `a2ui_wire`, default `32`, env-overridable via
    `A2UI_MAX_SCHEMA_DEPTH`); over it → `400 {"error": "schema too deeply nested", "max_depth": N}`.
  - Depth is measured iteratively (explicit stack), never by recursion, so a
    hostile schema cannot blow the Python stack while being checked.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_read_capped_body_accepts_exactly_limit` | M1 | a body of exactly `limit` bytes is returned intact |
| `test_read_capped_body_rejects_over_limit` | M1 | `limit + 1` bytes raises `OverSizedBody` |
| `test_read_capped_body_rejects_chunked_over_limit` | M1 | chunked body (`content_length is None`) over the cap still raises |
| `test_read_capped_body_never_reads_whole_stream` | M1 | reader is asked for at most `limit + 1` bytes |
| `test_read_capped_json_raises_before_parse` | M1 | an over-cap body of invalid JSON raises `OverSizedBody`, not `JSONDecodeError` |
| `test_create_form_413_over_cap` | M2 | `POST /forms` over the cap → 413 |
| `test_create_form_413_chunked_over_cap` | M2 | same via `Transfer-Encoding: chunked` → 413 (the bypass) |
| `test_import_a2ui_413_keeps_envelope_shape` | M2 | A2UI surface import over the cap → A2UI `error_envelope`, status 413 |
| `test_translate_form_413_over_cap` | M2 | `POST /forms/translate` over the cap → 413 `{"error","max_bytes"}` |
| `test_translate_form_413_chunked_over_cap` | M2 | chunked variant → 413 |
| `test_submit_data_413_chunked_over_cap` | M2 | submit route chunked variant → A2UI 413 |
| `test_export_forms_413_over_cap` | M2 | `POST /forms/export` over the cap → 413 (new limit) |
| `test_under_cap_requests_unchanged` | M2 | every migrated route still succeeds on a normal body |
| `test_translate_form_rejects_non_string_locale` | M3 | `locale: 5` → 400 |
| `test_translate_form_rejects_non_string_form_id_title` | M3 | `form_id`/`title` non-string → 400 |
| `test_translate_form_rejects_deep_schema` | M3 | schema deeper than the cap → 400 with `max_depth` |
| `test_translate_form_depth_check_is_iterative` | M3 | a 10 000-deep schema returns 400 without `RecursionError` |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py
- packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py
- packages/parrot-formdesigner/tests/unit/api/test_translate_forms.py
- packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def tiny_cap(monkeypatch):
    """Shrink the cap so tests never allocate megabytes."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 1024)
    return 1024
```

Chunked requests are produced by passing an async generator (or an iterable)
as `data=` to the aiohttp test client, which makes aiohttp use
`Transfer-Encoding: chunked` and leaves `request.content_length` as `None`.

---

## 5. Acceptance Criteria

- [ ] AC1 — Every route in the M2 table returns **413** for a body over
      `A2UI_MAX_BODY_BYTES`, including `export_forms`.
- [ ] AC2 — The same routes return 413 when the over-cap body is sent with
      `Transfer-Encoding: chunked` (`content_length is None`).
- [ ] AC3 — No handler calls `await request.json()` before its size cap; a
      grep for `request.json()` in `handlers.py` returns only sites that are
      provably under a cap (or none).
- [ ] AC4 — No `request.content_length ... A2UI_MAX_BODY_BYTES` comparison
      remains in `handlers.py`.
- [ ] AC5 — A2UI routes still return an A2UI `error_envelope` with the correct
      `surfaceId` on 413; plain routes still return `{"error","max_bytes"}`.
- [ ] AC6 — Requests under the cap behave exactly as before (status, body).
- [ ] AC7 — `translate_form` rejects non-string `locale`/`form_id`/`title`
      with 400, and a schema over `A2UI_MAX_SCHEMA_DEPTH` with 400, without
      raising `RecursionError`.
- [ ] AC8 — The Validation Contract suites pass:
      `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src pytest packages/parrot-formdesigner/tests/unit/api -q`
- [ ] AC9 — `ruff check` clean on every changed file.

---

## 6. Codebase Contract

> Verified against `origin/dev` on 2026-11-06.

### Verified Imports

```python
from aiohttp import web                                   # handlers.py:top
from parrot_formdesigner.api import a2ui_wire             # handlers.py imports as `a2ui_wire`
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope  # handlers.py:1630 (local import)
```

### Existing Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))  # line 39
def is_a2ui_surface_body(request: web.Request, body: Any) -> bool: ...   # line 126
def is_a2ui_request(request: web.Request, body: Any) -> bool: ...        # line 140
def unwrap_action(form: FormSchema, body: dict[str, Any]) -> A2UIActionSubmission: ...  # line 182
def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response: ... # line 293

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
async def export_forms(self, request: web.Request) -> web.Response: ...        # line 1174
async def translate_form(self, request: web.Request) -> web.Response: ...      # line 1255
#   content_length guard line 1265; request.json() line 1268
#   edit handler: request.json() line 1416; content_length guard line 1425
async def create_form(self, request: web.Request) -> web.Response: ...         # line 1567
#   request.json() line 1572; dispatch to _import_a2ui_surface line 1579
async def _import_a2ui_surface(self, request, body, *, tenant) -> web.Response: ...  # line 1627
#   content_length guard line 1629
#   submit_data: request.json() line 2060; content_length guard line 2073

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
app.router.add_post(f"{tp}/forms", _wrap_auth(handler.create_form))            # line 413
app.router.add_post(f"{tp}/forms/export", _wrap_auth(handler.export_forms))    # line 437
app.router.add_post(f"{tp}/forms/translate", _wrap_auth(handler.translate_form))  # line 439
```

### Does NOT Exist (do not reference)

- `a2ui_wire.read_capped_body` / `read_capped_json` / `OverSizedBody` /
  `oversized_json_response` / `oversized_a2ui_response` / `is_a2ui_content_type`
  / `A2UI_MAX_SCHEMA_DEPTH` — **all created by this feature**.
- `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` — new.
- There is no existing shared body-reading helper in this package; every
  handler calls `await request.json()` directly today.

### Integration Points

`read_capped_json` replaces `await request.json()`; the existing
`except (json.JSONDecodeError, ValueError): return 400 "Invalid JSON body"`
blocks stay, with `OverSizedBody` handled in a separate `except` that precedes
them.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| `request.content.read(n)` behaves differently from `request.json()` for an empty body | M1 returns `b""`; call sites keep their existing 400-on-invalid-JSON branch, which already covers the empty case |
| The oversize branch on the edit/submit routes cannot consult the parsed body to pick the error shape | M2 adds a headers-only `is_a2ui_content_type`; documented in §3 M2 |
| An aiohttp version difference in chunked handling makes the test unreliable | the cap does not depend on chunking at all — it is a byte count; the chunked tests assert the same 413 the sized tests do |

---

## 8. Traceability

- **Discovered-from**: `issue:bf978b6bae8a` (major, bug)
- **Source**: FEAT-650 code review, items I2 and S3
- **Fix group**: `fixgroup:adbf411ace18`
