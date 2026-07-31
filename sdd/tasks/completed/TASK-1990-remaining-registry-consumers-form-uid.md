# TASK-1990: Remaining FormRegistry/storage consumers — form_uid only

**Feature**: FEAT-389 — Stable UUID-Based Form Identity
**Spec**: `sdd/specs/form-uid-stable-identity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL
**Depends-on**: TASK-1973, TASK-1974, TASK-1976, TASK-1981
**Assigned-to**: unassigned

---

## Context

**This task exists because the spec's Module Breakdown is incomplete.** While
implementing TASK-1973 (`FormRegistry` re-keyed on `form_uid`), a full grep of
every `registry.get(`/`registry.unregister(`/`registry.contains(`/
`registry.clone_form(`/`storage.load(`/`storage.save(`/`storage.delete(` call
site in `packages/parrot-formdesigner/src/` found **7 production files** that
call these methods with a slug-shaped `form_id` and are **not mentioned
anywhere** in the spec's Module Breakdown, Integration Points table, or any of
TASK-1972 through TASK-1982:

- `api/render.py` (`handle_render` — `GET /forms/{form_uid}/render/{format}`)
- `api/uploads.py` (`handle_rest_upload` — `POST /forms/{form_uid}/fields/{field_id}/upload`)
- `api/audio_ws.py` (`AudioFormWSHandler` — `GET /forms/{form_uid}/audio/ws`)
- `renderers/telegram/router.py` (`TelegramFormRouter.start_form()` — bot-driven, NOT route-based)
- `services/form_version.py` (`FormVersionService` — calls both registry AND storage directly)
- `ui/handlers.py` (`FormPageHandler` — HTML page routes)
- `ui/telegram.py` (`TelegramWebAppHandler` — Telegram WebApp routes)

Two more files construct Pydantic models that carry a `form_id`-shaped
identity through to a URL or session that becomes `form_uid`-keyed once the
above are fixed, so they must change too:

- `audio/models.py` (`AudioSessionConfig`, `AudioFormManifest`,
  `AudioSessionState` — all three have a `form_id: str` field populated
  directly from the request path / registry lookup in `audio_ws.py`)
- `renderers/audio.py` (`AudioFormRenderer` builds `ws_endpoint` and
  `AudioFormManifest(form_id=form.form_id, ...)` — the endpoint URL must
  match the real, `form_uid`-keyed WS route)

Per explicit product direction: **nothing is out of scope** — every
consumer still keying off `form_id` for registry/storage identity must be
migrated to `form_uid`, full stop. This task is the catch-all for that
audit, so the feature does not silently ship 7 broken production surfaces
(rendering, uploads, audio WS, Telegram bot, versioning, and the HTML UI)
alongside a spec-faithful `FormRegistry`.

**Explicitly NOT covered by this task** (legitimate, non-identity uses of
`form_id` — do NOT touch): `services/event_registry.py`,
`services/event_dispatcher.py`, `services/csrf.py`, `services/cache.py`,
`services/partial_saves.py`, `services/metadata_callbacks.py`,
`services/metadata_enricher.py`, `services/public_forms.py`,
`services/rest_field_resolver.py`, `renderers/pdf.py`, `renderers/xforms.py`,
`renderers/jsonschema.py`, `renderers/html5.py`,
`renderers/telegram/models.py`,
`extractors/*.py`, `tools/database_form.py`, `tools/edit_toolkit.py`,
`tools/request_form.py`, `tools/services/networkninja.py`,
`core/partial.py`, `core/events.py` — these use
`form_id` as a human-readable label, a YAML/JSON source field, or a
config/event lookup key (never as a `FormRegistry`/`PostgresFormStorage`
primary-key lookup). Changing them would be scope creep per the spec's own
Goals section ("Keep `form_id` as a human-readable slug for display and
search — never as a primary key").

**CORRECTED (found during this task's own execution)**:
`renderers/telegram/renderer.py` was originally listed above as fully
excluded, but one line in it is NOT a label — `TelegramRenderer.render()`'s
WebApp-mode branch builds
`webapp_url = f"{self.base_url}/forms/{form.form_id}/telegram"`, which is
a real dispatch URL that must match the `ui/routes.py` Telegram route
(renamed to `{form_uid}` by TASK-1981). Left as `form.form_id` it would
send Telegram users to a URL that 404s against the renamed route — a
direct consequence of this task's own item #9 (`ui/telegram.py`) and
TASK-1981 landing. This ONE line was corrected to
`f"{self.base_url}/forms/{form.form_uid}/telegram"` as part of this task
(not deferred further — it directly depends on/duplicates this task's own
route-consistency work). Every OTHER `form_id` use in that same file
(`TelegramFormPayload.form_id`, the `metadata["form_id"]` field, and the
`_form_hash(form.form_id)` call used only for the INLINE mode's per-field
keyboard callback tagging — confirmed opaque/decorative, never compared
against `router.py`'s own independently-computed `_form_hash`, see this
task's Completion Note) remains untouched — those really are labels/opaque
tags, not lookups or dispatch keys.

**SECOND correction (also found during this task's own execution, same
class of gap)**: `ui/templates.py` was likewise originally listed above as
fully excluded, but `schema_page()` builds FIVE real navigable URLs, not
labels — a "View Form" link to `{prefix}/forms/{form_id}` (the UI route
renamed to `{form_uid}` by TASK-1981) and four "API Endpoints" example
URLs under `{prefix}/api/v1/forms/{form_id}/...` (the REST routes renamed
to `{form_uid}` by TASK-1976). `schema_page()`'s `form_id` parameter was
renamed to `form_uid` and used in all five interpolations (the one purely
descriptive line, "Structural JSON Schema for form ...", now also shows
the uid instead of the slug — a minor, accepted display trade-off in
exchange for the four URLs being correct; the page's `<h1>` title still
shows the human-readable form title separately, unaffected). Its sole
caller, `ui/handlers.py::view_schema()` (already in this task's own scope,
item #8), was updated to pass the resolved `form_uid` instead of the old
`form_id` local variable. No other function in `ui/templates.py`
(`gallery_page`, `form_page`, `index_page`, `error_page`, `page_shell`,
etc.) builds a `/forms/{form_id}`-shaped URL — verified via a full grep of
the file — so nothing else in it needed to change.

---

## Scope

### 1. `api/render.py`
- `handle_render()`: change `form_id = request.match_info["form_id"]` to use
  `form_uid` (the route param is renamed by TASK-1976 in `routes.py`, so
  `match_info` now carries `"form_uid"`). Use `extract_form_uid()` from
  TASK-1976 if importable without a circular import; otherwise inline
  equivalent UUID validation (`uuid.UUID(form_uid)` → 400 JSON on
  `ValueError`).
- `registry.get(form_id, ...)` → `registry.get(form_uid, ...)`.
- Update the 404 error message and docstring to reference `form_uid`.

### 2. `api/uploads.py`
- `handle_rest_upload()`: `form_id: str = request.match_info["form_id"]` →
  `form_uid` (same route-rename dependency as above).
- `registry.get(form_id, ...)` → `registry.get(form_uid, ...)`.
- `BlobMetadata(form_id=form_id, ...)` construction → add `form_uid=form_uid`
  (TASK-1980 adds the field to `BlobMetadata`; this is the actual call site
  that must populate it — TASK-1980 only touches `blob_storage.py` itself).
  Keep `form_id=form.form_id` too (kept for backwards-compat metadata per
  spec's Data Models section).
  **CONFIRMED during TASK-1980**: `BlobMetadata.form_uid` is a REQUIRED
  field (no default) — this call site currently raises `ValidationError`
  in addition to the pre-existing `match_info["form_id"]` `KeyError` (this
  endpoint has been completely non-functional since TASK-1976's route
  rename; fixing the match_info key alone is not sufficient — form_uid=
  MUST be added to the `BlobMetadata(...)` call in the same pass, or the
  endpoint will still 500 with `ValidationError` instead of `KeyError`).

### 3. `api/audio_ws.py`
- `AudioFormWSHandler.handle_websocket()`: `request.match_info.get("form_id", "")`
  → `request.match_info.get("form_uid", "")`.
- `registry.get(form_id, tenant=None)` → `registry.get(form_uid, tenant=None)`.
- `_build_session_config()`, `_handle_start_session()`: rename the
  `form_id` local variable/parameter to `form_uid` throughout (threads into
  `AudioSessionConfig`/`AudioSessionState`, see below) and update the
  `ws_endpoint=f"/api/v1/forms/{form_id}/audio/ws"` f-string to use
  `form_uid`.
- **Added during TASK-1979**: `FormSubmission(form_id=session.form_id, ...)`
  at ~line 1095 must also pass `form_uid=` — `FormSubmission.form_uid` is
  now a REQUIRED field (TASK-1979), so this construction currently raises
  `ValidationError` on every audio-form submission attempt. This is caught
  by the surrounding `try/except` (logs a warning, session continues
  without a persisted submission) — a graceful-but-silent failure, not a
  crash, and no worse than the PRE-EXISTING breakage where this same call
  site read an already-stale `form_id` from a route that TASK-1976 renamed
  to `{form_uid}`. Fix both in the same pass: use `form_uid=` (renamed from
  `session.form_id`, see the `AudioSessionState` rename above) alongside
  `form_id=` if a slug is still available on the session, or omit `form_id`
  if none is tracked.

### 4. `audio/models.py`
- Rename `form_id: str` → `form_uid: str` on `AudioSessionConfig`,
  `AudioFormManifest`, and `AudioSessionState`. Update each class's
  docstring accordingly. These are pure data carriers populated exclusively
  from `audio_ws.py` / `renderers/audio.py` (both in this task's scope) —
  verify no other file constructs them with `form_id=` before renaming.

### 5. `renderers/audio.py`
- `AudioFormRenderer.render()`: `ws_endpoint = f"/api/v1/forms/{form.form_id}/audio/ws"`
  → use `form.form_uid`. `AudioFormManifest(form_id=form.form_id, ...)` →
  `AudioFormManifest(form_uid=form.form_uid, ...)` (matching the Module 4
  renamed field).

### 6. `services/form_version.py`
- `FormVersionService.publish()`, `get_published()`, `list_versions()`,
  `_probe_storage_versions()`: rename the `form_id` parameter to `form_uid`
  throughout. Update `self._registry.get(form_id, ...)` →
  `self._registry.get(form_uid, ...)` and every
  `self._storage.load/save/delete(form_id, ...)` call to pass `form_uid`
  (TASK-1974 makes storage's `load`/`save`/`delete` operate on `form_uid`).
  `VersionMeta.form_id` stays as-is (human-readable metadata field per its
  own docstring) UNLESS it is used as a lookup key elsewhere in this file —
  verify via read before deciding.
- Update `self._meta[tenant][form_id]` internal dict keys to `form_uid` for
  consistency with the registry/storage rekey.
- The only caller, `api/handlers.py` (`publish_form`/`get_versions`/
  `get_published_version` handlers), is already updated by TASK-1976 to
  extract `form_uid` from the path — verify (do not re-edit `handlers.py`,
  it is out of this task's file scope).

### 7. `renderers/telegram/router.py`
- `TelegramFormRouter.start_form(form_id, ...)` is a **public, bot-facing
  entrypoint** — external callers pass a human-typed slug (confirmed: no
  in-package caller exists; it's invoked by bot command wiring outside this
  package). Resolve the slug via
  `form = await self.registry.get_by_slug(form_id, tenant=tenant)` (added
  by TASK-1973) instead of `self.registry.get(form_id, tenant=tenant)`.
  Keep the `form_id` PARAMETER NAME unchanged (external API — do not break
  callers' kwarg name), but internally use `form.form_uid` for everything
  downstream: FSM state persistence (`state.update_data(...)`),
  `_form_hash()`, the re-fetch in `_start_inline`/`_handle_field_callback`/
  `_submit_form`/`rest_fallback`-equivalent paths (lines ~396, ~446 per the
  pre-change grep), and the `on_submit` callback signature — rename to
  `on_submit(form_uid, data, chat_id)` and update the docstring at line 55
  (confirmed zero external producers of this callback within
  `packages/parrot-formdesigner/src/`, but grep the wider monorepo before
  changing the signature, same audit discipline as TASK-1245).

### 8. `ui/handlers.py`
- `FormPageHandler.render_form()`, `view_schema()`, `submit_form()`:
  `form_id = request.match_info["form_id"]` → `form_uid` (route rename
  lands via TASK-1981 in `ui/routes.py`).
- `registry.get(form_id, tenant=None)` → `registry.get(form_uid, tenant=None)`.
- `gallery()`: `fid = form.form_id` used to build `<a href="{p}/forms/{fid}">`
  links — change to `form.form_uid` so gallery links resolve against the
  new route shape.
- Update HTML fragments that embed `form_id` in action URLs
  (`f'<form action="{p}/forms/{escape(form_id)}" ...'` etc.) to use
  `form_uid`. Display text (titles, labels) referencing the human-readable
  slug may keep using `form.form_id` where it's genuinely just a label, not
  a URL.

### 9. `ui/telegram.py`
- `TelegramWebAppHandler.serve_webapp()`, `rest_fallback()`:
  `form_id = request.match_info["form_id"]` → `form_uid`.
  `registry.get(form_id, tenant=tenant)` → `registry.get(form_uid, tenant=tenant)`.
  `fallback_url = f"{prefix}/api/v1/forms/{form_id}/telegram-submit"` → use
  `form_uid`.

**NOT in scope**: `api/routes.py`, `api/handlers.py`, `ui/routes.py`
(owned by TASK-1976/TASK-1981 — do not re-edit route templates), any file
listed in the "Explicitly NOT covered" list above.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/render.py` | MODIFY | `form_uid` path param + registry lookup |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/uploads.py` | MODIFY | `form_uid` path param, registry lookup, `BlobMetadata.form_uid` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `form_uid` path param, registry lookup, session config threading |
| `packages/parrot-formdesigner/src/parrot_formdesigner/audio/models.py` | MODIFY | Rename `form_id` → `form_uid` on 3 models |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/audio.py` | MODIFY | `ws_endpoint` + `AudioFormManifest` construction use `form_uid` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py` | MODIFY | `form_id` → `form_uid` throughout; registry/storage calls |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/router.py` | MODIFY | `start_form()` resolves via `get_by_slug()`, threads `form_uid` internally |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py` | MODIFY (scoped exception — see Scope note above) | ONE line: `webapp_url` built from `form.form_uid`, not `form.form_id` |
| `packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py` | MODIFY | `test_webapp_render_produces_url` asserted a hardcoded slug-based URL; updated to assert against `form.form_uid` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py` | MODIFY (scoped exception — see Scope note above) | `schema_page()`'s `form_id` param renamed to `form_uid`; used in its 5 URL/label interpolations |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/templates/telegram_webapp.html.j2` | MODIFY | `FORM_ID`/`_form_id` JS constant + payload key renamed to `FORM_UID`/`_form_uid` (companion to `ui/telegram.py` + `renderers/telegram/router.py`'s `_handle_webapp_data`, both of which read this wire key) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/handlers.py` | MODIFY | `form_uid` path param, registry lookup, gallery links |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/telegram.py` | MODIFY | `form_uid` path param, registry lookup, fallback URL |
| `packages/parrot-formdesigner/tests/unit/test_telegram_router.py` | MODIFY | Update mocks: `mock_registry.get_by_slug` instead of/alongside `.get` |
| `packages/parrot-formdesigner/tests/integration/test_registry_multi_tenancy_e2e.py` | MODIFY | Update URLs/assertions to `form_uid`-based routing |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_integration.py` | MODIFY | Update fixtures/URLs for `form_uid` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_routes.py` | MODIFY | Update fixtures/URLs for `form_uid` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_handler.py` | MODIFY | Update fixtures for `form_uid` |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_form_renderer.py` | MODIFY | Update `AudioFormManifest`/`ws_endpoint` assertions |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_models.py` | MODIFY | Update model field assertions (`form_id` → `form_uid`) |
| `packages/parrot-formdesigner/tests/integration/test_render_pdf.py` | MODIFY | Verified broken: route registration + request URL used `form_id`; renamed both to `form_uid` |
| `packages/parrot-formdesigner/tests/integration/test_render_xml.py` | MODIFY | Same fix as `test_render_pdf.py` |
| `packages/parrot-formdesigner/tests/unit/api/test_render_dispatcher.py` | MODIFY | Update URLs/assertions for `form_uid` |
| `packages/parrot-formdesigner/tests/integration/test_upload_rest.py` | MODIFY | Update URLs/assertions for `form_uid` |
| `packages/parrot-formdesigner/tests/unit/ui/test_setup_form_ui_protect_pages.py` | MODIFY (verify) | Check for `form_id`-based UI URLs |
| `packages/parrot-formdesigner/tests/integration/test_feat300_integration.py` | MODIFY | Verified broken: `test_inflight_response_keeps_version` called `svc.publish("recap", ...)`/`get_published("recap", ...)`/`registry.get("recap", ...)` — switched to `original.form_uid` |
| `packages/parrot-formdesigner/tests/unit/test_version_backfill.py` | MODIFY | Verified broken: `reg.get(<slug>, ...)` → `reg.get_by_slug(<slug>, ...)`; `svc.list_versions(<slug>, ...)` → `form.form_uid` (captured from `_legacy_form()`'s return) |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | Verified broken: `_registry_with_form()` now returns `(registry, form)` with a fixed shared `form_uid` default; `InMemoryStorage` test double rekeyed from `form_id` to `form_uid` (mirrors TASK-1974's production rekey — otherwise `save()` and `load()` never agreed on a key); all `svc.publish/get_published/list_versions/safe_delete` and `registry.get`/`_make_request(form_id=...)` call sites updated to `form_uid` |
| `packages/parrot-formdesigner/tests/unit/test_form_version.py` | MODIFY | Update `FormVersionService` tests for `form_uid` |

The "(verify)" files may or may not need changes — read each first; only
touch if it actually breaks. Do not modify a file that isn't broken by
this task's changes.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services.registry import FormRegistry  # verified: services/registry.py:146
from parrot_formdesigner.core.schema import FormSchema           # verified: core/__init__.py
from parrot_formdesigner.services.blob_storage import BlobMetadata  # verified: services/blob_storage.py:55
import uuid  # stdlib
```

### Existing Signatures to Use (verified via read + grep during TASK-1973 investigation)
```python
# api/render.py:113
form_id = request.match_info["form_id"]
# api/render.py:131
form = await registry.get(form_id, tenant=tenant)

# api/uploads.py:232-242
form_id: str = request.match_info["form_id"]
form = await registry.get(form_id, tenant=tenant)

# api/audio_ws.py:206, 442
form_id = request.match_info.get("form_id", "")
form = await self.registry.get(form_id, tenant=None)

# audio/models.py:59, 129, 183
class AudioSessionConfig(BaseModel):
    form_id: str
class AudioFormManifest(BaseModel):
    form_id: str
class AudioSessionState(BaseModel):
    form_id: str

# renderers/audio.py:404-408
ws_endpoint = f"/api/v1/forms/{form.form_id}/audio/ws"
manifest = AudioFormManifest(form_id=form.form_id, ...)

# services/form_version.py:181, 259, 299, 320, 332, 383, 438, 511
form = await self._registry.get(form_id, tenant=tenant)
snap = await self._storage.load(form_id, version=version, tenant=tenant)
await self._storage.delete(form_id, tenant=tenant)
await self._storage.save(snapshot, tenant=tenant)

# renderers/telegram/router.py:81-113 (start_form, public entrypoint)
async def start_form(self, form_id: str, chat_id, bot, state, mode=..., *, tenant=None):
    form = await self.registry.get(form_id, tenant=tenant)
# on_submit callback docstring (line 55): "async def on_submit(form_id, data, chat_id) -> None"

# ui/handlers.py:121-244 (render_form, view_schema, submit_form, gallery)
form_id = request.match_info["form_id"]
form = await self.registry.get(form_id, tenant=None)
fid = form.form_id  # gallery() link building

# ui/telegram.py:79-135 (serve_webapp, rest_fallback)
form_id = request.match_info["form_id"]
form = await self.registry.get(form_id, tenant=tenant)
fallback_url = f"{prefix}/api/v1/forms/{form_id}/telegram-submit"
```

### New methods this task depends on (added by earlier tasks — verify they exist before using)
```python
# Added by TASK-1973:
async def FormRegistry.get_by_slug(self, form_id: str, *, tenant=None) -> FormSchema | None: ...

# Added by TASK-1974:
async def PostgresFormStorage.load(self, form_uid: str, version=None, *, tenant=None) -> FormSchema | None: ...
async def PostgresFormStorage.load_by_slug(self, form_id: str, tenant: str, version=None) -> FormSchema | None: ...

# Renamed by TASK-1976 (routes.py) — route templates for render/upload/audio_ws
# paths now use {form_uid} instead of {form_id}; extract_form_uid() helper
# added in api/handlers.py — importable from there if no circular import.

# Renamed by TASK-1981 (ui/routes.py) — UI route templates now use {form_uid}.
```

### Does NOT Exist
- ~~`AudioSessionConfig.form_uid`~~ / ~~`AudioFormManifest.form_uid`~~ /
  ~~`AudioSessionState.form_uid`~~ — do not exist yet. This task renames
  the existing `form_id` field to `form_uid` on each.
- ~~`TelegramFormRouter.start_form(form_uid=...)`~~ — the parameter stays
  named `form_id` (external, slug-based API) per this task's design; do
  NOT rename the parameter itself, only its internal resolution.
- ~~A `get_by_uid()` method~~ — `FormRegistry.get()` IS the UID lookup
  post-TASK-1973; there is no separate `get_by_uid()`.

---

## Implementation Notes

### Key Constraints
- Verify TASK-1973, TASK-1974, TASK-1976, and TASK-1981 are actually
  `"done"` in the per-spec index before starting — this task's route-param
  assumptions (`match_info["form_uid"]`) only hold once TASK-1976/TASK-1981
  have landed.
- Do NOT re-edit `api/routes.py`, `api/handlers.py`, or `ui/routes.py` —
  those are owned by earlier tasks; touching them here risks duplicate/
  conflicting edits in the same worktree.
- For `renderers/telegram/router.py`, preserve `start_form`'s public
  parameter name (`form_id`) — it's a slug-based, bot-facing API, not a
  URL path param. Only its *internal* resolution changes.
- Before renaming `on_submit`'s callback signature, grep the wider
  monorepo (not just `packages/parrot-formdesigner/`) for producers —
  follow the TASK-1245 audit pattern (categorize producer / doc-reference /
  firing-site / test, update each).
- If any "(verify)" test file in the Files table turns out unaffected,
  leave it untouched and say so explicitly in the Completion Note — do not
  make cosmetic edits just to justify listing it.

### Known Risks / Gotchas
- `services/form_version.py`'s `VersionMeta.form_id` field may be pure
  display metadata (per its own docstring: "The form's canonical
  identifier" — note this docstring itself may be stale post-FEAT-389 and
  need a wording update even if the field name doesn't change) — read the
  full file before deciding whether to rename it too.
- `AudioSessionConfig`/`AudioFormManifest`/`AudioSessionState` are
  constructed ONLY from `audio_ws.py` and `renderers/audio.py` per the
  grep performed during this task's drafting — re-verify with a fresh
  grep before renaming, in case another producer was missed.

---

## Acceptance Criteria

- [ ] `api/render.py::handle_render` looks up forms by `form_uid`
- [ ] `api/uploads.py::handle_rest_upload` looks up forms by `form_uid`;
      `BlobMetadata` receives `form_uid`
- [ ] `api/audio_ws.py` extracts and uses `form_uid` from the WS path
- [ ] `AudioSessionConfig`, `AudioFormManifest`, `AudioSessionState` use
      `form_uid` instead of `form_id`
- [ ] `renderers/audio.py` builds `ws_endpoint` and `AudioFormManifest`
      using `form.form_uid`
- [ ] `FormVersionService` resolves forms via `form_uid` against both the
      registry and storage
- [ ] `TelegramFormRouter.start_form()` resolves the incoming slug via
      `get_by_slug()` and threads `form_uid` through the rest of the
      conversation flow (FSM state, hashing, `on_submit` callback)
- [ ] `ui/handlers.py` and `ui/telegram.py` extract and use `form_uid` from
      their routes; gallery links use `form.form_uid`
- [ ] No file outside this task's list (or the earlier tasks' lists) was
      modified
- [ ] All existing tests updated and passing:
      `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] Existing integration test
      `test_registry_multi_tenancy_e2e.py::test_handlers_pass_tenant_to_registry`
      and `::test_telegram_router_tenant_propagation` still pass

---

## Agent Instructions

1. Verify TASK-1973, TASK-1974, TASK-1976, TASK-1981 are `"done"` in the
   per-spec index.
2. Re-run the discovery greps from this task's Context section against the
   CURRENT worktree state (line numbers above were captured before
   TASK-1973 through TASK-1981 landed and will have shifted) — correct the
   Codebase Contract in this file first if anything is stale, per the
   standard anti-hallucination discipline.
3. Implement each of the 9 source-file changes in Scope, in the order
   listed (dependencies flow roughly top-to-bottom: audio model changes
   before the audio renderer/handler that construct them).
4. Update each affected test file. For "(verify)" entries, read first;
   only edit if genuinely broken.
5. Run: `pytest packages/parrot-formdesigner/tests/ -v`
6. Update this task's status and move it to `sdd/tasks/completed/`.

---

## Completion Note

All 9 in-scope source files migrated to `form_uid` exactly per Scope,
including both discovered corrections (telegram renderer's `webapp_url`,
`ui/templates.py::schema_page`'s 5 URL/label interpolations). All listed
test files updated except two verified genuinely unaffected (see below).

**Verified unaffected (left untouched, per instructions)**:
- `tests/formdesigner/test_audio_routes.py` — zero `form_id`/`form_uid`
  references (route-mounting/renderer-seeding tests only).
- `tests/unit/ui/test_setup_form_ui_protect_pages.py` — same, zero
  references.

**Pre-existing bug discovered during validation (NOT a TASK-1990 defect)**:
While running the full acceptance-criteria test suite
(`pytest packages/parrot-formdesigner/tests/ -v`), 3 tests in
`tests/formdesigner/test_audio_integration.py::TestHybridVoiceFlows`
(`test_ws_low_confidence_confirm`, `test_ws_low_confidence_reject_reprompts`,
`test_ws_high_confidence_auto_advance`) were found to **hang indefinitely**
in `AudioFormWSHandler`'s binary audio-frame / confirm-answer flow.
Root-caused as **pre-existing and unrelated to FEAT-389**: reproduced
identically against an unmodified `dev` checkout (byte-for-byte identical
code path once FEAT-389's `form_id`→`form_uid` renames are excluded from
the diff). Filed separately as **FEAT-395**
(`sdd/specs/audio-ws-confirm-answer-deadlock.spec.md`) per user decision;
all 3 tests are `@pytest.mark.skip`-annotated with a pointer to that spec
(this task's file list already included `test_audio_integration.py`, so
the skip markers land here rather than in TASK-1982).

**Separately discovered regression, deferred to TASK-1982**: the full
suite also surfaced 40 genuine `KeyError: 'form_uid'` failures in
`tests/test_partial_handlers.py`, `tests/test_partial_saves_integration.py`,
and `tests/test_submit_merge.py` — caused by TASK-1976's `api/handlers.py`
route rename (`extract_form_uid(request)` now requires
`match_info["form_uid"]`), but those 3 test files were never in TASK-1990's
or TASK-1982's original file lists. Confirmed via a `dev`-baseline diff
that these are NEW failures (not present on unmodified `dev`), so this is
in-scope for FEAT-389, not FEAT-395. Handed to TASK-1982 (whose Scope
already says "Update ALL API test URLs from `/{form_id}` to `/{form_uid}`
paths") with its file list extended accordingly, rather than pulled into
this task (out of TASK-1990's own file scope, and TASK-1982 is the
test-only closer task for the whole feature).

Acceptance criteria met: all 9 source files migrated, `pytest` run
performed (see notes above for the 2 deferred/skip items), no files
touched outside this task's list.
