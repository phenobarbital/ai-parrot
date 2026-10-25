# TASK-4699: formdesigner A2UI import/list membership + leak fixes

**Feature**: FEAT-743 — formdesigner A2UI import/list membership + leak fixes
**Spec**: `sdd/specs/fixgroup-03981db69a81.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Ledger issue `issue:08842f12f2bc` (major, `discovered_from: spec:FEAT-650`)
flags three related gaps in `parrot-formdesigner`'s A2UI dialect surface:

1. **I4**: `FormAPIHandler._import_a2ui_surface` lets `?overwrite=true`
   replace an existing private form without checking tenant membership —
   every other form-resolution path in this file does.
2. **I5**: `FormAPIHandler.list_forms(dialect=a2ui, include=surface)`
   inlines full surfaces without membership filtering, never dispatches
   the `onSchemaLoaded` lifecycle hook, and leaks raw exception text in
   `warnings` on a render failure.
3. **I6**: a `list_forms` descriptor sourced only from
   `FormStorage.list_forms()` omits the `"dialect"` key that
   memory-sourced descriptors always carry.

This task implements spec §2 Modules 1–3 in full (all three touch
`handlers.py`, so they are one task to avoid serializing three
sub-worktrees over the same file). See the spec for full rationale —
this task carries only what the executor needs to act.

---

## Scope

- Add a tenant-membership check before `_import_a2ui_surface` overwrites
  an existing form (M1).
- Make `list_forms`'s `include_surface` loop membership-aware, dispatch
  `onSchemaLoaded` and apply its overrides with the correct single-vs-
  multi envelope framing, and stop leaking exception text (M2).
- Make `FormStorage.list_forms()` always emit a `"dialect"` key, and make
  `list_forms`'s storage-only descriptor branch copy it through (M3).
- Update/add the unit tests listed in "Test Specification" below.

**NOT in scope**:
- `POST /forms/export`'s own RBAC/membership gap (`issue:3e191d955d4c`) —
  separate issue, separate file region, not touched here.
- The A2UI body-size/chunked-body check (`issue:bf978b6bae8a`) and the
  formdesigner CLI issues (`issue:e963c78a05de`).
- Any change to `core/tenant.py`'s authorization policy itself — this
  task only adds call sites to the already-shipped
  `enforce_membership_unless_public`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | M1 + M2: import `TenantForbiddenError`; membership check on import-overwrite; membership + onSchemaLoaded + leak fix + dialect in `list_forms`. |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` | MODIFY | M3: `FormStorage.list_forms()` emits `"dialect"`. |
| `packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py` | MODIFY | M1 tests: membership-aware overwrite, new forbidden-overwrite test. |
| `packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py` | MODIFY | M2/M3 tests: membership-aware inline surface, filtering, onSchemaLoaded, leak fix, dialect parity. |
| `packages/parrot-formdesigner/tests/unit/test_storage_list.py` | MODIFY | M3 tests: dialect fallback + update the exact-equality test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# handlers.py:34-38 (already present — EXTEND this tuple, do not add a new import line)
from .tenant import (
    TenantForbiddenError,          # NEW — api/tenant.py already re-exports it from core/tenant_errors.py
    assert_body_tenant_matches,
    declared_tenant,
    enforce_membership_unless_public,
)
# handlers.py:20-21 (already present, unchanged)
from ..core import FormDialect
from ..core.events import FormEventAbort, FormEventName
# handlers.py:29 (already present, unchanged)
from ..services.event_dispatcher import apply_schema_overrides, dispatch
# handlers.py:120 (already present, unchanged)
from .render import get_renderer, supported_formats  # noqa: E402
from .dialect import A2UI_LIST_MAX, render_a2ui_schema  # noqa: E402  (line ~120, verify exact line with grep before editing — this import is NOT being touched, listed for reference only)

# storage.py:59 (already present — EXTEND this line, do not add a new import line)
from ..core.schema import FormDialect, FormSchema  # FormDialect verified: core/schema.py:82
```

### Existing Signatures to Use
```python
# core/tenant.py:189
def enforce_membership_unless_public(request: web.Request, form: Any, tenant: str) -> None:
    """Raises TenantForbiddenError unless form.is_public or caller is a tenant member/superuser."""

# core/tenant_errors.py:53
class TenantForbiddenError(web.HTTPForbidden):
    """403 — caller is not entitled to the declared tenant."""

# services/event_dispatcher.py:102-112
async def dispatch(
    event: FormEventName, *, form: FormSchema, request: web.Request, tenant: str | None,
    auth_context: Any, payload: Mapping[str, Any] | None = None,
    schema_dump: Mapping[str, Any] | None = None, error: BaseException | None = None,
) -> EventResolution: ...
# get_schema calls it with a plain string literal "onSchemaLoaded" (handlers.py:1109-1117) — copy that exact call shape.

# core/events.py:182
class EventResolution(BaseModel):
    schema_overrides: dict[str, Any] | None  # among other optional fields

# api/dialect.py:70-94
async def render_a2ui_schema(
    form: FormSchema, *, locale: str = "en", overrides: Mapping[str, Any] | None = None
) -> tuple[list[dict[str, Any]], RenderedForm, list[str]]:
    """Returns (envelopes, rendered, warnings). ONE envelope when overrides
    is falsy; the base createSurface envelope PLUS one updateComponents
    envelope per translatable override when overrides is truthy."""

# api/handlers.py:195
self.schema_renderer = JsonSchemaRenderer()
# JsonSchemaRenderer.render is async: `rendered: RenderedForm = await self.schema_renderer.render(form)`
# `rendered.content` is the dict passed as dispatch(...)'s `schema_dump=` kwarg (handlers.py:1107-1117).

# api/a2ui_wire.py:293-311 — the framing convention to replicate (NOT this function itself,
# just its single-vs-multi rule; list_forms does not call it):
def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response:
    """len(envelopes) == 1 -> envelopes[0] (bare dict); else -> {"messages": envelopes}."""

# core/schema.py:82-92
class FormDialect(str, Enum):
    JSON_SCHEMA = "json_schema"  # default, core/schema.py:522 `dialect: FormDialect = FormDialect.JSON_SCHEMA`
    A2UI = "a2ui"

# api/handlers.py:501
def _build_auth_context(self, request: web.Request) -> AuthContext: ...
```

### Does NOT Exist
- ~~`from ..core.tenant_errors import TenantForbiddenError` as a new import line in `api/handlers.py`~~ — this file imports tenant helpers exclusively through the `.tenant` compat shim (`api/tenant.py`); add the name to the EXISTING `from .tenant import (...)` tuple instead.
- ~~A `tenant` kwarg on `render_a2ui_schema`~~ — only `locale` and `overrides`.
- ~~A `"dialect"` key already present on `FormStorage.list_forms()`'s returned dicts~~ — verified absent; its `entry` only has `form_uid, form_id, version, tenant, created_at, title, description` today.
- ~~`request.session` existing by default on a `MagicMock(spec=web.Request)` in tests~~ — `web.Request` has no such attribute; the mock raises `AttributeError` unless the test explicitly sets `request.session = {...}`, which is exactly why `getattr(request, "session", None)` is how `core/tenant.py` reads it.

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
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/test_storage_list.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py#enforce_membership_unless_public",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant_errors.py#TenantForbiddenError",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py#render_a2ui_schema",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormDialect"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Catch `TenantForbiddenError` and `FormEventAbort` **before** the
  existing generic `except Exception as exc:` clause in `list_forms` —
  Python evaluates `except` clauses in order.
- Do not change `_import_a2ui_surface`'s behavior for the `overwrite=False`
  (409 conflict) branch — the membership check only guards the actual
  mutation when `overwrite=True`.
- Do not introduce a new helper/abstraction for the `onSchemaLoaded` +
  `render_a2ui_schema` sequence — duplicate `get_schema`'s shape inline,
  matching this codebase's existing style (both already duplicate
  dialect-resolution independently).

### References in Codebase
- `handlers.py:1096-1140` (`get_schema`) — the exact membership +
  lifecycle + overrides sequence this task reuses for the list loop.
- `test_get_schema_dialect.py:65-75,114-128,143-147` — the `session`
  fixture pattern and `TenantForbiddenError` assertion pattern to mirror
  in both test files this task edits.

---

## Implementation Blueprint

> Write each block below nearly verbatim, then complete the one `FILL IN`
> marker. Re-verify every anchor's occurrence count before editing — grep
> for it in the current working tree, since the spec was written against
> `81ccf8e03` and the tree may have moved since.

### Steps (in order)
1. In `handlers.py`, add `TenantForbiddenError` to the existing
   `from .tenant import (...)` tuple — *why*: both M1 and M2 need to
   reference it (M1 lets it propagate uncaught, M2 catches it).
2. In `handlers.py`'s `_import_a2ui_surface`, insert the membership check
   right after the overwrite-conflict return and before the version bump
   — *why*: this is the exact point `existing` is confirmed non-`None`
   and overwrite was explicitly requested; checking any earlier would
   also gate the harmless 409-conflict read, checking any later would
   leave a window where the form could be mutated first.
3. In `handlers.py`'s `list_forms`, replace the `include_surface` loop's
   `try`/`except` body — *why*: the single combined block is clearer than
   three separate edits to adjacent lines inside the same small loop.
4. In `handlers.py`'s `list_forms` storage-only descriptor branch, add the
   `"dialect"` key — *why*: parity with the memory-sourced and merged
   branches just above it.
5. In `storage.py`, extend the `FormSchema` import and add dialect
   extraction to `list_forms` right after `description` is set — *why*:
   placed inside the existing `try` so a malformed `schema_json` still
   falls back cleanly in the existing `except` branch, same pattern as
   `title`/`description`.
6. Update the five test files per the Test Specification table below —
   *why*: several existing tests assert the exact pre-fix shape (no
   membership gate, no dialect key, raw exception text) and will fail
   once the fix lands unless updated to assert the new, correct shape.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^    enforce_membership_unless_public,$' api/handlers.py)
# REPLACE the 4-line tuple below (handlers.py:34-38) with:
from .tenant import (
    TenantForbiddenError,
    assert_body_tenant_matches,
    declared_tenant,
    enforce_membership_unless_public,
)
```
**Why**: `api/tenant.py` is a compat shim that already re-exports
`TenantForbiddenError` from `core/tenant_errors.py` alongside the names
this file already imports from it — adding it here keeps a single,
consistent import style for this whole symbol family in this file.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — M1)
```python
# occurrences: 1 (verified: grep -c '                return JSONResponse({"error": "form already exists", "form_uid": str(form.form_uid)}, status=409)' api/handlers.py)
# AFTER — insert below that exact line (verified: handlers.py:1608), BEFORE the existing
# `form = form.model_copy(update={"version": _bump_version(existing.version)})` line:
            enforce_membership_unless_public(request, existing, tenant)
```
**Why**: `existing` is already tenant-scoped (`self.registry.get(form.form_uid,
tenant=tenant)`); this is the same call every other form-resolution path in
this file makes (`handlers.py:1045,1073,1106,1370,2012`) before acting on a
resolved form. Letting `TenantForbiddenError` propagate uncaught matches
every one of those call sites — no new `try`/`except` here.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — M2)
```python
# occurrences: 1 (verified: grep -c '                except Exception as exc:  # noqa: BLE001 — one bad form must not 500 the list' api/handlers.py)
# REPLACE the try/except block below (handlers.py:1002-1011) with:
                try:
                    form = await self.registry.get(descriptor["form_uid"], tenant=tenant)
                    enforce_membership_unless_public(request, form, tenant)
                    rendered = await self.schema_renderer.render(form)
                    resolution = await dispatch(
                        "onSchemaLoaded",
                        form=form,
                        request=request,
                        tenant=tenant,
                        auth_context=self._build_auth_context(request),
                        schema_dump=rendered.content,
                    )
                    envelopes, _rendered, warnings = await render_a2ui_schema(
                        form,
                        locale=request.query.get("locale", "en"),
                        overrides=resolution.schema_overrides,
                    )
                    descriptor["surface"] = envelopes[0] if len(envelopes) == 1 else {"messages": envelopes}
                    descriptor["warnings"] = warnings
                except (TenantForbiddenError, FormEventAbort):
                    continue
                except Exception as exc:  # noqa: BLE001 — one bad form must not 500 the list
                    self.logger.warning("list_forms: a2ui render failed for %s: %s", descriptor["form_uid"], exc)
                    descriptor["surface"], descriptor["warnings"] = None, ["render_failed"]
```
**Why**: Mirrors `get_schema`'s exact membership → render → `onSchemaLoaded`
→ `render_a2ui_schema(overrides=...)` sequence (`handlers.py:1106-1140`),
applied per list descriptor. `TenantForbiddenError`/`FormEventAbort` are
caught BEFORE the generic `except Exception` (order matters) and simply
`continue` — the descriptor keeps its `surface_url` (set on the line above
this block, unchanged) but gets no `"surface"`/`"warnings"` keys, so an
unauthorized or aborted form degrades to manifest-only instead of
breaking the whole list. The multi-envelope `{"messages": envelopes}`
framing is required — `render_a2ui_schema` returns 2+ envelopes whenever
`overrides` is truthy (`api/dialect.py:70-94`), and keeping only
`envelopes[0]` (the pre-fix behavior) would silently drop the override.
The leaked-exception fix is the literal replacement of
`[f"render_failed: {exc}"]` with the fixed string `["render_failed"]` —
`exc` stays in the `self.logger.warning(...)` call only.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — M3 consumer)
```python
# occurrences: 1 (verified: grep -c '                        "created_at": row.get("created_at"),' api/handlers.py)
# AFTER — insert ABOVE that exact line (verified: handlers.py:987), inside the same dict literal:
                        "dialect": row.get("dialect", FormDialect.JSON_SCHEMA.value),
```
**Why**: Parity with the memory-sourced branch a few lines above
(`"dialect": form.dialect.value,`) and the merged branch, which already
has a `"dialect"` key via the memory entry it started from. `FormDialect`
is already imported in this file (`handlers.py:20`).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` (MODIFY — M3 producer, import)
```python
# occurrences: 1 (verified: grep -c 'from ..core.schema import FormSchema' services/storage.py)
# REPLACE that exact line (storage.py:59) with:
from ..core.schema import FormDialect, FormSchema
```
**Why**: Both symbols live in the same module; no new import line needed.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py` (MODIFY — M3 producer, logic)
```python
# occurrences: 1 (verified: grep -c '                entry\["description"\] = str(desc) if desc else None' services/storage.py)
# AFTER — insert below that exact line (verified: storage.py:690), BEFORE the `except Exception as exc:` line:

                raw_dialect = data.get("dialect", FormDialect.JSON_SCHEMA.value)
                try:
                    entry["dialect"] = FormDialect(raw_dialect).value
                except ValueError:
                    entry["dialect"] = FormDialect.JSON_SCHEMA.value
```
**Why**: Mirrors the `title`/`description` fallback pattern directly above
it — placed inside the outer `try` so the dialect read shares the same
"malformed `schema_json`" safety net, but with its own inner `try` so an
invalid `dialect` string alone doesn't blank out an already-correctly-parsed
title/description. Also add `entry["dialect"] = FormDialect.JSON_SCHEMA.value`
to the existing `except Exception as exc:` branch (alongside the existing
`entry["title"] = ""` / `entry["description"] = None` lines) so the
malformed-JSON fallback path also always sets the key.

### `packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _request(body: dict' tests/unit/api/test_import_a2ui.py)
# REPLACE the _request() signature and body (test_import_a2ui.py:26-34) with:
def _request(
    body: dict, *, content_length: int | None = None, overwrite: str = "", session: dict | None = None
) -> MagicMock:
    """Build the request contract consumed by ``create_form``."""
    request = MagicMock(spec=web.Request)
    request.content_type = "application/json"
    request.content_length = content_length if content_length is not None else len(json.dumps(body))
    request.query = {"overwrite": overwrite} if overwrite else {}
    request.json = AsyncMock(return_value=body)
    request.get = MagicMock(side_effect=lambda key, default=None: TENANT if key == "tenant" else default)
    request.app.get = MagicMock(return_value="/forms")
    if session is not None:
        request.session = {"session": session}
    return request
```
```python
# REPLACE test_conflict_then_overwrite_bumps_version's body (test_import_a2ui.py:86-97):
async def test_conflict_then_overwrite_bumps_version(handler: FormAPIHandler, surface: dict) -> None:
    """The same surface conflicts unless overwrite is explicitly requested, and overwrite requires membership."""
    first = await handler.create_form(_request(surface))
    conflict = await handler.create_form(_request(surface))
    overwritten = await handler.create_form(
        _request(surface, overwrite="true", session={"programs": [TENANT]})
    )

    assert first.status == 201
    assert conflict.status == 409
    assert json.loads(conflict.body)["form_uid"] == json.loads(first.body)["form_uid"]
    assert overwritten.status == 201
    form_uid = uuid.UUID(json.loads(first.body)["form_uid"])
    assert (await handler.registry.get(form_uid, tenant=TENANT)).version == "1.1"


async def test_overwrite_without_membership_is_forbidden(handler: FormAPIHandler, surface: dict) -> None:
    """A caller with no tenant-membership session cannot overwrite a private form."""
    from parrot_formdesigner.core.tenant_errors import TenantForbiddenError

    first = await handler.create_form(_request(surface))
    assert first.status == 201

    with pytest.raises(TenantForbiddenError):
        await handler.create_form(_request(surface, overwrite="true"))

    form_uid = uuid.UUID(json.loads(first.body)["form_uid"])
    assert (await handler.registry.get(form_uid, tenant=TENANT)).version == "1.0"
```
**Why**: The `surface` fixture builds a `FormSchema` with no `is_public`
set, which defaults to `False` (`core/schema.py:516`) — so it is a private
form and, once M1 lands, overwriting it requires membership. The updated
conflict/overwrite test grants `programs=[TENANT]` so the legitimate
re-import case keeps passing; the new test asserts the forbidden case and
that the form was left unmodified (`version == "1.0"`, the pre-overwrite
value).
**FILL IN**: none — both test bodies are complete as written above.

### `packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def get(self, target: str) -> _Response:' tests/unit/api/test_list_forms_dialect.py)
# REPLACE that method (test_list_forms_dialect.py:58-65) with:
    async def get(self, target: str, *, session: dict | None = None) -> _Response:
        """Build the request contract consumed by ``list_forms``."""
        parsed = urlsplit(target)
        request = MagicMock(spec=web.Request)
        request.query = dict(parse_qsl(parsed.query))
        request.app = {"_form_prefix": "/api/v1"}
        request.get = MagicMock(side_effect=lambda key, default=None: "navigator" if key == "tenant" else default)
        if session is not None:
            request.session = {"session": session}
        return _Response(await self._handler.list_forms(request))
```
```python
# REPLACE test_descriptor_carries_dialect_for_memory_entries (test_list_forms_dialect.py:102-109):
async def test_descriptor_carries_dialect_for_memory_entries(client: _HandlerClient) -> None:
    """Every descriptor — memory, a2ui-dialect, and storage-only — carries dialect."""
    response = await client.get("/api/v1/navigator/forms")
    forms = {form["form_id"]: form for form in (await response.json())["forms"]}
    assert forms["f1"]["dialect"] == "json_schema"
    assert forms["f2"]["dialect"] == "a2ui"
    assert forms["f3"]["dialect"] == "json_schema"
    assert "surface_url" not in forms["f1"]
```
```python
# REPLACE test_include_surface_inlines_envelopes (test_list_forms_dialect.py:125-132):
async def test_include_surface_inlines_envelopes(client: _HandlerClient) -> None:
    """An authorized tenant member gets every descriptor's inline envelope + warnings."""
    response = await client.get(
        "/api/v1/navigator/forms?dialect=a2ui&include=surface",
        session={"programs": ["navigator"]},
    )
    body = await response.json()

    assert response.status == 200
    assert all("createSurface" in form["surface"] for form in body["forms"])
    assert all(isinstance(form["warnings"], list) for form in body["forms"])


async def test_include_surface_filters_unauthorized_forms(client: _HandlerClient) -> None:
    """Without membership, descriptors keep surface_url but drop the inline body."""
    response = await client.get("/api/v1/navigator/forms?dialect=a2ui&include=surface")
    body = await response.json()

    assert response.status == 200
    assert all(form["surface_url"].endswith("/schema?dialect=a2ui") for form in body["forms"])
    assert all("surface" not in form for form in body["forms"])
    assert all("warnings" not in form for form in body["forms"])


async def test_include_surface_honors_on_schema_loaded(
    client: _HandlerClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onSchemaLoaded overrides reach the inlined descriptor as a multi-envelope message list."""

    async def resolve(*_args, **_kwargs):
        from parrot_formdesigner.core.events import EventResolution

        return EventResolution(schema_overrides={"title": "Overridden"})

    monkeypatch.setattr(handlers_module, "dispatch", resolve)
    response = await client.get(
        "/api/v1/navigator/forms?dialect=a2ui&include=surface",
        session={"programs": ["navigator"]},
    )
    body = await response.json()

    assert response.status == 200
    for form in body["forms"]:
        assert "messages" in form["surface"]
        assert any("updateComponents" in m for m in form["surface"]["messages"])
```
```python
# REPLACE test_inline_render_failure_is_isolated (test_list_forms_dialect.py:155-167):
async def test_inline_render_failure_is_isolated(client: _HandlerClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """One rendering exception produces a generic warning, never the raw exception text."""

    async def fail_render(_form: FormSchema, **_kwargs: Any) -> NoReturn:
        raise RuntimeError("broken surface")

    monkeypatch.setattr(handlers_module, "render_a2ui_schema", fail_render)
    response = await client.get(
        "/api/v1/navigator/forms?dialect=a2ui&include=surface",
        session={"programs": ["navigator"]},
    )
    body = await response.json()

    assert response.status == 200
    assert all(form["surface"] is None for form in body["forms"])
    assert all(form["warnings"] == ["render_failed"] for form in body["forms"])
```
**Why**: `_form()` in this test file also leaves `is_public` unset
(defaults `False`), so once M2 lands every descriptor needs a `programs`
grant to be inlined at all — `test_manifest_does_not_render` and
`test_cap_returns_400` are untouched because neither reaches the
membership-gated code path (manifest mode never enters the loop body
past `continue`; the cap check returns before the loop runs). The new
filter test deliberately omits `session` to assert the degrade-to-manifest
behavior. The new `onSchemaLoaded` test checks the `{"messages": [...]}`
shape rather than a bare `"createSurface"` key, per M2's framing rule.
**FILL IN**: none — all test bodies are complete as written above.

### `packages/parrot-formdesigner/tests/unit/test_storage_list.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    assert out == \[{' tests/unit/test_storage_list.py)
# REPLACE that assertion block (test_storage_list.py:77-85) with:
    assert out == [{
        "form_uid": "uid-f-1",
        "form_id": "f-1",
        "version": "1.0",
        "title": "Hello",
        "description": "Daily report",
        "tenant": None,
        "dialect": "json_schema",
        "created_at": "2026-04-12T10:31:00+00:00",
    }]
```
```python
# APPEND this new test at the end of the file:
@pytest.mark.asyncio
async def test_list_forms_dialect_fallback_and_passthrough(storage_factory) -> None:
    """A row with no dialect falls back to json_schema; an explicit a2ui dialect passes through."""
    rows = [
        _StubRow(
            form_uid="uid-no-dialect",
            form_id="no-dialect",
            version="1.0",
            schema_json=json.dumps({"title": "No Dialect"}),
            tenant=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        _StubRow(
            form_uid="uid-a2ui",
            form_id="a2ui-form",
            version="1.0",
            schema_json=json.dumps({"title": "A2UI Form", "dialect": "a2ui"}),
            tenant=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
        _StubRow(
            form_uid="uid-malformed-dialect",
            form_id="malformed-dialect",
            version="1.0",
            schema_json=json.dumps({"title": "Bad Dialect", "dialect": "xml"}),
            tenant=None,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    ]
    out = await storage_factory(rows).list_forms()
    assert out[0]["dialect"] == "json_schema"
    assert out[1]["dialect"] == "a2ui"
    assert out[2]["dialect"] == "json_schema"
```
**Why**: `test_list_forms_localized_title_flattens` asserts the FULL
output dict via `assert out == [{...}]`; once `entry["dialect"]` is always
set, the expected literal must gain `"dialect": "json_schema"` (its
`schema_json` has no `dialect` key) or the test fails on the added key
alone. The new test covers the three paths M3's producer code takes:
missing key, valid explicit value, and an invalid value that must not
raise — falling back to `json_schema` like the missing-key case.
**FILL IN**: none.

### FILL IN checklist

None — every block above is complete and mechanical; there are no open
judgement calls left for this task (see spec §8).

---

## Acceptance Criteria

- [ ] `_import_a2ui_surface` calls `enforce_membership_unless_public` on
  the pre-existing form before overwriting it.
- [ ] `list_forms(dialect=a2ui, include=surface)` skips the inline body
  (not the whole response) for a descriptor the caller cannot access.
- [ ] `list_forms(dialect=a2ui, include=surface)` dispatches
  `onSchemaLoaded` per descriptor and reflects `schema_overrides` using
  the `{"messages": [...]}` framing when there is more than one envelope.
- [ ] No raw exception text appears in any `list_forms` response body.
- [ ] Every `list_forms` descriptor carries a `"dialect"` key regardless
  of source.
- [ ] All tests in the Validation Commands below pass.
- [ ] `ruff check --fix` on the five touched files is clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_import_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_list_forms_dialect.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_storage_list.py -q`

---

## Test Specification

Covered in full by the Implementation Blueprint's test-file blocks above
(this task edits existing test files rather than creating a new one, so
there is no separate scaffold to add here).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-03981db69a81 --feature-id FEAT-743`)
2. **Read the spec** at `sdd/specs/fixgroup-03981db69a81.spec.md` for full context
3. **Check dependencies** — none (`Depends-on: none`)
4. **Verify the Codebase Contract** — before writing ANY code, re-run every
   `grep -c` in the Implementation Blueprint blocks above and confirm the
   occurrence count is still `1`. If any anchor moved or the count
   changed, stop and re-locate it rather than guessing.
5. **Update status** in `sdd/tasks/index/fixgroup-03981db69a81.json` →
   `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — apply the blueprint blocks in the order listed in
   "Steps", then update the five test files
7. **Verify** all acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the five files this task lists
   (never `git add .` / `-A`)
9. **Close the task** with
   `scripts/sdd/close_task.sh TASK-4699 fixgroup-03981db69a81 verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

<!-- Filled in by the implementing agent on close. -->
