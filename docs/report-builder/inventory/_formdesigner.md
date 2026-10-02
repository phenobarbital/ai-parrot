# parrot-formdesigner — HTTP/WS endpoint inventory

Repo: `ai-parrot` · package root `packages/parrot-formdesigner/src/parrot_formdesigner` (paths below are relative to it unless prefixed).
Host wiring: `app.py:257-290` — `PostgresFormStorage(schema="navigator", table_name="form_schemas", tenant=None)` → `FormRegistry(app, storage)`; `setup_form_api(app, registry, client=LLMFactory.create("google"), base_path="/api/v1", transcriber=FasterWhisperBackend(...), token_validator=TokenValidator())`; `setup_form_ui(app, registry, base_path="", protect_pages=False)`.
**Not passed by app.py** (so these stay `None`): `submission_storage`, `forwarder`, `partial_store`, `blob_storage`, `resolver`, `synthesizer`, `org_graph_service`, `project_service`, `rbac_service`, `workday_adapter`, `venue_service`, `alias_registry`, `public_base_url`/`teams_renderer`; `rbac_enforcing=False` (default, `api/routes.py:211`).

## Auth model (legend for the "Auth" column)

| Code | Meaning | Source |
|---|---|---|
| **A+T** | `_wrap_auth(tenant="required")`: navigator-auth `is_authenticated(content_type="application/json")` + `user_session()` + `requires_tenant(public=False)` → 400 `tenant_not_declared` if `{tenant}` empty, 404 if tenant is a reserved literal segment, 403 `tenant_forbidden` unless `tenant ∈ session["session"]["programs"]` or `superuser` | `api/routes.py:84-125`, `api/tenant.py:76-160`, `api/errors.py:27,55,82` |
| **A+Tp** | `_wrap_auth(tenant="public")`: same auth decorators, tenant declared but membership NOT checked at decorator; handler then calls `enforce_membership_unless_public()` (skips if `form.is_public`). When `form.is_public=True` the 5 paths are added to navigator-auth exclude list (`services/public_forms.py:13-53`, wired `api/routes.py:556-657`) so they become anonymous | `api/routes.py:385-421`, `api/tenant.py:190-218` |
| **A** | `_wrap_auth(tenant="none")`: auth decorators only, no tenant layer; tenant inferred from `session.programs[0]` or registry default (`_session_tenant`, `api/handlers.py:297-321`) | `api/routes.py:426-429, 519-554` |
| **RBACs** | `_rbac_shadow_gate(codename)` — no-op when `rbac_service is None` (true in app.py); log-only when `rbac_enforcing=False` | `api/handlers.py:2291-2356` |
| **T-only** | UI `_page_wrap(protect=False)`: **no navigator-auth**; `requires_tenant(public=True)` (declare-only, no membership). `protect_pages=False` in app.py ⇒ all UI HTML pages are anonymous | `ui/routes.py:80-144` |
| **WS-JWT** | Not wrapped. JWT from `Sec-WebSocket-Protocol` subprotocol or first `{"type":"auth","token":...}` msg (10 s timeout), validated by `TokenValidator`; tenant only checked non-empty + `form.tenant == {tenant}`; **no program-membership check** | `api/audio_ws.py:173-340`, `api/audio_ws.py:~457-483` |

All `/{tenant}/forms/{form_uid}` handlers parse `form_uid` as UUID (400 otherwise, `api/handlers.py:39-62`) and do tenant-scoped `registry.get(form_uid, tenant)` + `_assert_form_tenant` (404, `api/handlers.py:323-354`).

## A. JSON REST API — `setup_form_api` (`api/routes.py:192-696`), mounted at `/api/v1`

`tp = /api/v1/{tenant}` (`api/routes.py:372`).

### A1. Form CRUD / authoring

| Method | Full path | Handler (file:line) · reg line | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/{tenant}/forms` | `FormAPIHandler.list_forms` `api/handlers.py:724` · reg `routes.py:375` | List forms (memory ∪ storage); `?slug=` filter via `get_by_slug` | query `slug?` | `{"forms":[{form_uid,form_id,title,description,version,source:"memory"\|"db",created_at}]}` sorted by form_id | A+T | reads registry + `PostgresFormStorage.list_forms(tenant)` |
| POST | `/api/v1/{tenant}/forms` | `create_form` `handlers.py:1135` · `routes.py:376` | LLM (NL prompt) form generation via `CreateFormTool` | `{"prompt": str}` | `{form_uid,form_id,title,url:"{ui_prefix}/{tenant}/forms/{uid}"}`; 503 if no LLM | A+T, RBACs(`create_form`) | `persist=True` → registry + storage |
| POST | `/api/v1/{tenant}/forms/from-db` | `load_from_db` `handlers.py:1970` · `routes.py:377` | Import legacy form definition (default service `networkninja`) via `DatabaseFormTool` | `{"formid":int,"orgid":int? (else session org),"service":str="networkninja"}` | `{form_uid,form_id,title,url}`; stores `ImportDiffReport` in-memory | A+T | `persist=True`; import report only in handler dict `_import_reports[(tenant,uid)]` (`handlers.py:2043-2047`, non-durable) |
| POST | `/api/v1/{tenant}/forms/blank` | `create_blank_form` `handlers.py:1075` · `routes.py:381` | Create empty form without LLM | `{"title": LocalizedString, "form_id"?: slug, "tenant"?: cross-check}` | 201 `{form_uid,form_id,title,url}`; 409 slug exists | A+T | `registry.register(persist=has_storage, overwrite=False)` |
| GET | `/api/v1/{tenant}/forms/{form_uid}` | `get_form` `handlers.py:847` · `routes.py:385` | Full `FormSchema` JSON; fires `onBeforeOpen` lifecycle | – | `FormSchema.model_dump(exclude_none)`; header `X-Form-CSRF-Token` if any `events.*.remote` binding | A+Tp (public-form glob) | registry read |
| PUT | `/api/v1/{tenant}/forms/{form_uid}` | `update_form` `handlers.py:1329` · `routes.py:389` | Full replace (may rename slug); bumps `version`; `published_version` forced to existing; tenant stamped from URL | full `FormSchema` body; `form_uid` must match URL | updated `FormSchema`; 422 validation / `check_schema`; 409 slug clash | A+T, RBACs(`update_form`) | `register(overwrite=True)` → UPSERT `ON CONFLICT (form_uid, version)` (`services/storage.py:179-199`) |
| PATCH | `/api/v1/{tenant}/forms/{form_uid}` | `patch_form` `handlers.py:1396` · `routes.py:390` | RFC 7396 merge-patch (arrays replaced wholesale); form_uid/form_id immutable; bumps version | partial `FormSchema` dict | updated `FormSchema` | A+T, RBACs(`patch_form`) | same UPSERT |
| DELETE | `/api/v1/{tenant}/forms/{form_uid}` | `delete_form` `handlers.py:1456` · `routes.py:391` | Remove form; guarded by `FormVersionService.can_delete` (has_responses hook — none wired ⇒ always allowed, `services/form_version.py:572-588`) | – | 204; 409 if has responses | A+T, RBACs(`delete_form`) | `registry.unregister` + `storage.delete(form_uid, tenant)` |
| POST | `/api/v1/{tenant}/forms/{form_uid}/edit` | `edit_form` `handlers.py:1190` · `routes.py:394` | NL-prompt edit (LLM refine of existing form) | `{"prompt": str}` | `{form_uid,form_id,title,url}` | A+T, RBACs(`edit_form`) | `persist=True` |
| POST | `/api/v1/{tenant}/forms/{form_uid}/clone` | `clone_form` `handlers.py:1261` · `routes.py:397` | Deep copy under new slug + new uid, optional merge-patch (de-facto "template" mechanism) | `{"new_form_id": str, "patch"?: dict, "tenant"?: cross-check}` | 201 full cloned `FormSchema`; 404/409/422 | A+T | `registry.clone_form` (persists) |
| PATCH | `/api/v1/{tenant}/forms/{form_uid}/operations` | `handle_operations` `api/operations.py:521` · `routes.py:432` | Atomic batched structural edits (layout/sections/fields), optimistic concurrency via `If-Match: <version>` (412) | `OperationsEnvelope{operations:[Operation]}` (`operations.py:183`); discriminated by `op`: `add_section{section,position?}` (:61), `add_field{section_uid,field,position?}` (:69), `move_field{from:{section_uid,field_uid},to:{section_uid,position}}` (:89), `remove_field{section_uid,field_uid}` (:108), `update_field{section_uid,field_uid,patch}` (:121), `update_section_meta{section_uid,patch}` (:139), `update_form_meta{patch}` (:152), `duplicate_field{from,as_field_id}` (:159) | 200 `{"form": FormSchema}`; 422 `{"errors":[{index,op,message}]}` | A+T | bumps version; `register(persist=True, overwrite=True)` (`operations.py:645`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/schema` | `get_schema` `handlers.py:884` · `routes.py:401` | Structural JSON Schema (`JsonSchemaRenderer`), `onSchemaLoaded` may apply `schema_overrides` | – | JSON Schema (`application/schema+json` content from `renderers/jsonschema.py:392`, served as JSON) | A+Tp | – |
| GET | `/api/v1/{tenant}/forms/{form_uid}/style` | `get_style` `handlers.py:916` · `routes.py:405` | Style schema = `form.meta["style"]` | – | `StyleSchema` dict or `{}` | A+T | – |
| GET | `/api/v1/form-controls` | `controls.handle_form_controls` `api/controls.py:20` · `routes.py:426` | Toolbar catalog of field-type controls (widget palette) | – | `{"controls":[FieldControlMetadata]}` (seeded by `controls/builtin.py`) | A (no tenant) | static |

### A2. Rendering, validation, submissions, uploads, partials, events

| Method | Full path | Handler · reg | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/api/v1/{tenant}/forms/{form_uid}/render/{format}` | `render.handle_render` `api/render.py:165` · `routes.py:408` | Render dispatcher. Formats seeded `render.py:42-88`: `html` (HTML5Renderer, text/html), `adaptive` (AdaptiveCardRenderer, JSON), `xml` (XFormsRenderer, application/xml), `pdf` (PdfRenderer, application/pdf), `audio` (AudioFormRenderer manifest, JSON), `a2ui` (A2UIFormRenderer, only if `parrot.outputs.a2ui` importable), `teams` (only if `public_base_url`/`FORMDESIGNER_PUBLIC_URL` set — not set in app.py, `render.py:117-147`) | query `locale=en`, `with_meta=true` (JSON envelope `{content, content_type, content_encoding:"base64"?, warnings, metadata}`) | raw rendered body w/ renderer content-type; 415 `{"supported":[...]}` unknown format; 400 renderer refusal | A+Tp | – |
| POST | `/api/v1/{tenant}/forms/{form_uid}/validate` | `validate` `handlers.py:1004` · `routes.py:414` | Dry-run validation; dual-wire legacy JSON or A2UI v1.0 action envelope (`api/a2ui_wire.py`) | answers dict `{field_id: value, "visit_context"?: {...}}` or A2UI `action` | 200/422 `{"is_valid", "errors"}` (reject policy → `errors.__unknown__`); A2UI: `{"messages":[]}` / VALIDATION_FAILED envelopes; 413 oversize | A+Tp | none |
| POST | `/api/v1/{tenant}/forms/{form_uid}/data` | `submit_data` `handlers.py:1498` · `routes.py:418` | Submission pipeline: optional `?merge_partials=true` → `onBeforeSubmit` → `FormValidator.validate` → `unknown_fields` policy (drop/keep/reject) → metadata enrichment → persist → forward (`submit.action_type=="endpoint"`) → `onAfterSubmit` | answers dict (+ `visit_context`) or A2UI action; query `merge_partials` | 200 `{submission_id, is_valid:true, forwarded, forward_status, forward_error}`; 422 `{is_valid:false, errors}`; 503/422/501 sink errors | A+Tp | builds `FormSubmission` (`services/submissions.py:~97`). If `form.persistence` set → per-form sink via `SinkFactory` (inactive: no `alias_registry` ⇒ 503 `SinkUnavailableError`, `handlers.py:1846-1864`). Else `submission_storage.store()` → `PostgresSubmissionStorage` default `navigator.form_data` (`services/submissions.py:31-32`) — **but app.py passes none ⇒ submission is validated and NOT stored** (`handlers.py:1871-1877`) |
| POST | `/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/upload` | `uploads.handle_rest_upload` `api/uploads.py:145` · `routes.py:438` | REST-field (FieldType.REST) multipart upload → blob → `RestFieldResolver` callback | multipart `file` (+ additional_args); header `X-Parrot-Prior-Blob-Ref` | `{success, answer, raw_value, blob_ref, display, warnings, error}` (`uploads.py:343-354`); 404/413/415 | A+T | blob storage: `app["blob_storage"]` else lazy `TempBlobStorage` (process-local temp dir, `uploads.py:113-140`) — app.py wires none |
| POST | `/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload` | `file_upload.handle_file_upload` `api/file_upload.py:132` · `routes.py:444` | Raw FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD upload; SHA-256, inline `data_url` ≤ max_inline, thumbnails; basic chunking (`X-Parrot-Upload-Id/Offset/Length` → 202 per chunk) | multipart `file` part(s) or raw chunk; `X-Parrot-Prior-Blob-Ref`, `X-Parrot-Tenant` | `FileEnvelope{filename, content_type, size, blob_ref, data_url, thumbnail_url, checksum}` or list (`file_upload.py:550-558`) | A+T | same blob storage (`TempBlobStorage` default, `file_upload.py:79-100`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/thumbnail` | `file_upload.handle_get_thumbnail` `file_upload.py:560` · `routes.py:450` | Stream thumbnail by blob ref | query `ref` (URL-encoded blob_ref) | `image/webp` bytes | A+T | blob read (unsigned) |
| POST | `/api/v1/{tenant}/forms/{form_uid}/partial` | `save_partial` `handlers.py:541` · `routes.py:456` | Merge & per-field-validate draft answers | `{"answers": {field_id: value}}` | `PartialFormData` `{form_uid/form_id, session_id, data, field_errors}`; **503 since no partial_store** | A+T | Redis `PartialSaveStore` (TTL 3600 s, keyed form_uid+session_id, data keyed by field_uid) — not wired |
| GET | `/api/v1/{tenant}/forms/{form_uid}/partial` | `get_partial` `handlers.py:650` · `routes.py:457` | Read draft | – | `PartialFormData` / 404; 503 (not wired) | A+T | Redis |
| DELETE | `/api/v1/{tenant}/forms/{form_uid}/partial` | `delete_partial` `handlers.py:692` · `routes.py:458` | Clear draft | – | 204; 503 (not wired) | A+T | Redis |
| POST | `/api/v1/{tenant}/forms/{form_uid}/events/{event_name}` | `remote_event` `handlers.py:927` · `routes.py:461` | Remote lifecycle bridge for bindings with `remote:true` (event must be in `FormEventName` Literal) | header `X-CSRF-Token`/`X-Form-CSRF-Token` (issued by GET form); body `{payload?, schema_dump?}` | `EventResolution` JSON; 403 CSRF; status from `FormEventAbort` | A+T + per-session CSRF | – |

### A3. Versioning / question bank / import report (FEAT-300/433)

| Method | Full path | Handler · reg | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| POST | `/api/v1/{tenant}/forms/{form_uid}/publish` | `publish_form` `handlers.py:2116` · `routes.py:501` | Promote CURRENT live version to published (immutable, in place — no bump) | – | `{form_uid, version}`; 404; 409 already published | A+T | `FormVersionService` → `storage.promote()` guarded UPDATE on same `form_schemas` row (`services/form_version.py:716-760`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/versions` | `list_versions` `handlers.py:2187` · `routes.py:504` | Version history (all stored rows, draft+published) | – | `{form_uid, versions:[{version, published_at, published_by:null, is_current, is_published}]}` | A+T | `storage.list_versions` (one row per `(form_uid, version)`) |
| GET | `/api/v1/{tenant}/forms/{form_uid}/versions/{version}` | `get_version` `handlers.py:2237` · `routes.py:505` | Fetch stored snapshot (draft or published) | – | full `FormSchema` / 404 | A+T | storage |
| GET | `/api/v1/{tenant}/forms/{form_uid}/import-report` | `get_import_report` `handlers.py:2264` · `routes.py:509` | Last `ImportDiffReport` from `/from-db` | – | `ImportDiffReport` / 404 | A+T | in-process dict only (lost on restart) |
| GET | `/api/v1/{tenant}/fields` | `list_fields` `handlers.py:2146` · `routes.py:502` | Question bank — reusable fields | – | `{"fields":[ReusableField]}` | A+T | `QuestionBankService(storage=registry.storage, tenant)` (`services/question_bank.py`) |
| POST | `/api/v1/{tenant}/fields` | `create_field` `handlers.py:2160` · `routes.py:503` | Add reusable field | `FormField` JSON | 201 `ReusableField`; 422 | A+T | question bank |

### A4. Audio WebSocket (conditional)

| Method | Full path | Handler · reg | Purpose | Protocol | Auth | Persistence |
|---|---|---|---|---|---|---|
| GET (WS upgrade) | `/api/v1/{tenant}/forms/{form_uid}/audio/ws` | `AudioFormWSHandler.handle_websocket` `api/audio_ws.py:173` · reg `routes.py:479-496` (**only if** `synthesizer or transcriber or token_validator` — true in app.py) | Voice Q&A form session (max 10 questions, `audio_ws.py:58`), TTS (SuperTonic→Google→text) + Whisper STT | Client JSON `type`: `start_session` (config: locale, tts_backend, tts_voice, tts_mime_format, auto_advance, enumerate_options, stt_confirm_threshold), `answer_text`, `answer_selection`, `answer_payload`, `confirm_answer`, `skip_question`, `go_back`, `repeat_question`, `end_session`, `ping`, `auth` (`audio_ws.py:368-378`); binary frames = audio. Server: `session_started`, questions, `form_complete{submission_id, answers}`, errors | WS-JWT | `_finish_session` stores `FormSubmission` via `submission_storage` (None in app.py ⇒ not stored; also uses `registry.get(..., tenant=None)` and hard-coded `form_version="1"`, `audio_ws.py:1115-1160`) |

### A5. `/org/*` (FEAT-302/330) — mounted unconditionally, all return 501 in app.py (services not wired)

| Method | Full path | Handler (handlers.py) · reg (routes.py) | Purpose / body | Auth | Backend |
|---|---|---|---|---|---|
| GET | `/api/v1/org/graph` | `get_org_graph` :2362 · :519 | Org graph for session org | A | `OrgGraphService` (None ⇒ 501) |
| POST | `/api/v1/org/projects` | `create_project` :2394 · :520 | `{accounting_code, name?, client_id}` (org_id from session) | A | `ProjectService` (None ⇒ 501) |
| POST | `/api/v1/org/cost-centers/{project_id}/workday-map` | `map_project_workday` :2462 · :521 | `{workday_code}` | A | ProjectService |
| POST | `/api/v1/org/users/{user_id}/assign` | `assign_user_role` :2511 · :525 | `{codename, scope:RBACScope, program_id}`; always enforces `manage_roles`; writes `fieldsync.auth_policies` | A + hard RBAC | `RBACService` |
| POST | `/api/v1/org/sync/workday` | `sync_workday_identities` :2605 · :529 | `{user_id, action:provision\|deprovision, org_id}` → 202 stub | A | `WorkdayIdentitySyncAdapter` |
| GET | `/api/v1/org/stores/{store_id}/sites` | `list_sites` :2654 · :535 | list `Site` | A | `VenueService` |
| POST | `/api/v1/org/stores/{store_id}/sites` | `create_site` :2682 · :539 | `{client_id, name}` | A | VenueService |
| GET | `/api/v1/org/sites/{site_id}/locations` | `list_locations` :2741 · :543 | list `Location` | A | VenueService |
| POST | `/api/v1/org/sites/{site_id}/locations` | `create_location` :2771 · :547 | `{client_id, name, location_type="kiosk", latitude, longitude, geofence_radius_m}` | A | VenueService |
| GET | `/api/v1/org/locations/{location_id}` | `get_location` :2846 · :551 | one `Location` | A | VenueService |

## B. HTML / Telegram UI — `setup_form_ui` (`ui/routes.py:147-236`), mounted at `""` (root), `protect_pages=False`

| Method | Full path | Handler · reg | Purpose | Request | Response | Auth | Persistence |
|---|---|---|---|---|---|---|---|
| GET | `/{tenant}/` | `FormPageHandler.index` `ui/handlers.py:58` · `ui/routes.py:183` | Builder landing page (prompt box + DB loader; JS calls the API) | – | HTML (`ui/templates.py`) | T-only (anonymous) | – |
| GET | `/{tenant}/gallery` | `gallery` `ui/handlers.py:86` · `routes.py:184` | List tenant forms with Open/Schema links | – | HTML | T-only | registry read |
| GET | `/{tenant}/forms/{form_uid}/schema` | `view_schema` `ui/handlers.py:197` · `routes.py:187` | Pretty JSON Schema + Style schema page | – | HTML | T-only | – |
| GET | `/{tenant}/forms/{form_uid}` | `render_form` `ui/handlers.py:139` · `routes.py:191` | Render form via `HTML5Renderer` with `?layout=` (`LayoutType`: single_column, two_column, wizard, accordion, tabs, inline — `core/style.py:16-24`) | query `layout` | HTML page, `<form action=... method=post>` | T-only | – |
| POST | `/{tenant}/forms/{form_uid}` | `submit_form` `ui/handlers.py:253` · `routes.py:195` | Validate urlencoded POST and show result / re-render with errors | form-urlencoded | HTML | T-only | **none** (validation only) |
| GET | `/{tenant}/forms/{form_uid}/telegram` | `TelegramWebAppHandler.serve_webapp` `ui/telegram.py:49` · `routes.py:207` | Form as Telegram WebApp (Jinja `telegram_webapp.html.j2`) | – | HTML | T-only (by design) | – |
| POST | `/api/v1/{tenant}/forms/{form_uid}/telegram-submit` | `rest_fallback` `ui/telegram.py:90` · `routes.py:212` | REST fallback for WebApp payloads > 4 KB | JSON answers (`_form_uid` stripped) | `{is_valid, errors}` 200/422 | T-only (anonymous) | **none** (validation only) |

Note: UI handlers use `request.match_info["form_uid"]` raw (no UUID parse) and do NOT call `_assert_form_tenant`/membership; telegram uses `declared_tenant` (`ui/telegram.py:61,102`).

## C. Persistence summary

| Store | Location | Used by | Wired in app.py? |
|---|---|---|---|
| `PostgresFormStorage` | table `form_schemas`; schema = **tenant slug** when tenant given (`_resolve_schema`, `services/storage.py:135-148`), else `navigator`. Columns `id, form_uid UUID, form_id, version, schema_json JSONB, style_json JSONB, tenant, created_at, updated_at, created_by`, `UNIQUE(form_uid,version)`, `UNIQUE(tenant,form_id,version)` (`storage.py:159-176`). UPSERT on `(form_uid,version)` (`:179-199`); `promote()` for publish (`:447`); `list_versions` (`:703`) | registry save/load/delete, versions, question bank | Yes (`app.py:257-263`). Registry `default_tenant="navigator"` (`services/registry.py:280`) and `register()` saves with `tenant=resolved` (`registry.py:662`) ⇒ forms for tenant `X` land in **`X.form_schemas`**, only default-tenant forms in `navigator.form_schemas`; schema must pre-exist |
| `PostgresSubmissionStorage` | default `navigator.form_data` (tenant overrides schema) (`services/submissions.py:31-32,123-155`) | `/data`, audio WS finish | **No** ⇒ submissions not persisted |
| Per-form sinks (FEAT-457) | `services/sinks/*` (postgres_table, asyncdb_store), mapped via `sinks/mapper.py` | `/data` when `form.persistence` set | **No** (`alias_registry` absent ⇒ 503) |
| `PartialSaveStore` (Redis) | `services/partial_saves.py:24` TTL 3600 s | `/partial` | **No** ⇒ 503 |
| Blob storage | `app["blob_storage"]`, lazy `TempBlobStorage` fallback (S3/GCS/Local available in `services/blob_storage.py`) | uploads/thumbnail | **No** ⇒ process-local temp (lost on restart) |
| Import reports | in-memory dict on handler | `/from-db`, `/import-report` | n/a (non-durable) |
| Forwarder | `services/forwarder.py` | `/data` when `submit.action_type=="endpoint"` | **No** ⇒ never forwarded |

## D. Domain notes (templates, versioning, layout, formats, export)

- **Form model** `FormSchema` (`core/schema.py:401`): `form_uid` (immutable UUID), `form_id` (slug), `version` ("1.0", auto-bumped on PUT/PATCH/operations), `title`/`description` (LocalizedString), `sections: list[FormSection]`, `submit: SubmitAction` (`:300`), `meta` (holds `style`), `tenant`, `metadata` (enrichment fields), `events` (lifecycle bindings), `form_type` (SIMPLE/PRODUCT/SURVEY, `:33`), `product_bindings`, `published_version`, `is_public`, `persistence`, `unknown_fields` (drop/keep/reject). `FormSection` (`:229`): `section_uid, section_id, title, description, fields: list[FormField|FormSubsection]` (`SectionItem`, `:226`), `depends_on`, `meta`. `FormField` at `:65`.
- **Layout / widgets**: `StyleSchema`/`LayoutType` (`core/style.py:16,52`); widget palette via `GET /form-controls` (`controls/builtin.py`); structural editing via `/operations`.
- **Templates**: no dedicated template endpoint. Reuse = `/clone` (+patch) and question bank `/fields`. (`ui/templates.py` is only HTML page chrome.)
- **Versioning**: draft rows per `(form_uid, version)`; `publish` freezes current version in place (409 on re-publish); `published_version` immutable via API (`handlers.py:1359-1362, 1432`); delete guarded only if a `has_responses` hook exists (none).
- **Render formats / export**: html, adaptive (Adaptive Cards), xml (XForms), pdf, audio (manifest), a2ui (optional), teams (conditional); JSON Schema via `/schema`. PDF/XML = the export paths; `?with_meta=true` base64-wraps binary. No submissions export / list / read endpoint exists.
- **Lifecycle events**: `onBeforeOpen`, `onSchemaLoaded`, `onBeforeSubmit`, `onAfterSubmit`, `onError` dispatched in handlers; remote bridge via `/events/{event_name}`.

## E. Gaps / risks spotted

1. **Audio WS auth-exclude path mismatch**: `app.py:310` excludes `/api/v1/forms/*/audio/ws`, but the real route is `/api/v1/{tenant}/forms/{form_uid}/audio/ws` (`routes.py:493`). If the navigator-auth middleware enforces on non-excluded paths, the WS upgrade from a browser (no Authorization header) may be rejected before reaching `AudioFormWSHandler`. Also `app.py:268` comment shows the stale path.
2. Audio WS has **no tenant membership check** (any valid JWT + any tenant whose form uid is known) and `_finish_session` re-resolves the form with `tenant=None` (`audio_ws.py:1137`) and hard-codes `form_version="1"`.
3. `protect_pages=False` ⇒ UI pages (`/{tenant}/...`) are fully anonymous and declare-only for tenant: any form (public or not) of any tenant is renderable/validatable by UUID; gallery lists all forms of any tenant.
4. Root-mounted `/{tenant}/` and `/{tenant}/gallery` capture every 1-segment path of the host app (tenant collisions with literal routes → 404 via reserved-segment guard, `api/tenant.py:150-156`).
5. Submissions, partials, blob durability, forwarding, RBAC and per-form sinks are all **inactive** in this host (nothing wired); `/data` returns 200 with a `submission_id` that is never stored.
6. RBAC on create/update/patch/delete/edit is shadow-only and no-op (no `rbac_service`).
7. Per-tenant physical schema: tenant slug becomes the Postgres schema for `form_schemas` (must pre-exist), not `navigator`.
