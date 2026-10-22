---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [forms, file-upload, blob-storage, retention, orphan-cleanup]
---

# Feature Specification: FormDesigner orphan upload cleanup

**Feature ID**: FEAT-731
**Date**: 2026-10-22
**Author**: Juan Francisco Ruffato (with Claude)
**Status**: draft
**Target version**: next minor after FEAT-730

> Cross-repo initiative, one spec per repo (decided by Juan 2026-10-22):
> **FEAT-731** (this spec, ai-parrot / parrot-formdesigner — the mechanism) →
> **FEAT-801** fieldsync `sdd/specs/orphan-upload-cleanup.spec.md` (provisioning,
> wiring, nightly schedule). Juan chose "Option 3 — pending-upload registry +
> nightly sweep" and required the SAME mechanism for the anonymous share page
> (FEAT-797 M4) and the authenticated app. It is a separate feature from the
> public-forms trio (FEAT-730 / FEAT-796 / FEAT-797).
> Deploy order: ai-parrot FEAT-731 (+ ai-parrot-server lockstep) → fieldsync
> FEAT-801 (migration first).

---

## 1. Motivation & Business Requirements

### Problem Statement

`POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/file-upload`
(FEAT-460, `api/file_upload.py:169`) writes the blob to storage **at upload
time** (key `{prefix}{form_uid}/{field_uid}/{blob_id}`,
`services/blob_storage.py:242`), plus a thumbnail for images
(`api/file_upload.py:606-608`). Nothing ever deletes it if the answer never
reaches a stored submission:

- a public-form respondent picks a photo and closes the tab (FEAT-797 M4 makes
  the share page upload on pick);
- `/data` rejects the submission (FEAT-730 409 `form_closed` /
  `response_limit_reached` / `duplicate_response`, a validation 422, a sink
  error) after the files were uploaded;
- a rep in the app picks a photo, replaces it without the prior-ref header, or
  discards the visit form.

The code already admits it: `api/file_upload.py:75` — "no expiry/GC in V1".
The blob and its thumbnail stay in the bucket forever, unreferenced and
unattributable.

### Goals

- G1. Every blob returned by `/file-upload` is **recorded** as pending in the
  caller's tenant schema (`fs_pending_uploads` in FieldSync), with its
  thumbnail ref, form/field uids and whether the caller was anonymous.
- G2. A pending record is **cleared in the same transaction** that stores a
  submission referencing the blob — for every host path that calls
  `FormSubmissionStorage.store()` (the parrot pipeline AND hosts that call it
  directly, e.g. FieldSync execution/visits) — and by FEAT-730's
  `store_guarded()`.
- G3. A **reaper** deletes the blob (and thumbnail) of every pending record
  older than its TTL — 48 h for anonymous uploads, 7 days for authenticated
  ones — after a safety check that no stored submission references it.
- G4. Same mechanism for anonymous (public share page) and authenticated (app)
  uploads; only the TTL differs.
- G5. Feature off by default: with no `pending_uploads` passed to
  `setup_form_api`, behaviour is byte-for-byte today's.
- G6. Parrot schedules nothing; the host calls `reap_once` per tenant.

### Non-Goals (explicitly out of scope)

- REST-field uploads (`api/uploads.py`, FEAT-170), audio recordings
  (FEAT-701), chunk blobs of an abandoned chunked upload (`_CHUNK_BUFFERS`,
  `api/file_upload.py:69-76`) — only the four upload field types via
  `/file-upload` (FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD).
- Back-filling blobs uploaded before this feature (no record exists; listing a
  bucket is out of scope).
- S3 lifecycle rules / object tagging (rejected: S3-only, infra change on a
  shared bucket — fieldsync brainstorm discussion 2026-10-22).
- Scheduling, config keys, migrations, provisioning — FieldSync FEAT-801.
- Deleting blobs referenced only by a FEAT-457 `persistence` sink row whose
  post-write clear failed (see §7 Known Risks).

---

## 2. Architectural Design

### Overview

1. **Registry table** (per tenant schema; name configurable, FieldSync uses
   `fs_pending_uploads`):
   ```sql
   CREATE TABLE IF NOT EXISTS <schema>.<table> (
       blob_ref       TEXT PRIMARY KEY,
       thumbnail_ref  TEXT,
       form_uid       UUID        NOT NULL,
       field_uid      UUID        NOT NULL,
       tenant         TEXT        NOT NULL,
       anonymous      BOOLEAN     NOT NULL,
       uploaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
   );
   CREATE INDEX IF NOT EXISTS "idx_<table>_uploaded_at" ON <schema>.<table> (uploaded_at);
   ```
   Owned by `PendingUploadStore` (`initialize`, `record`, `clear`,
   `expired`, `delete_rows`). Same identifier-validated, pool-based pattern as
   `FormSubmissionStorage`.

2. **Record** — `handle_file_upload`, after the response value is built and the
   prior-ref replacement is done, records every returned envelope (single or
   list; chunked uploads record only the final envelope). `thumbnail_ref` is
   the `ref` query parameter of `thumbnail_url` (the envelope carries the
   thumbnail only as a URL, `api/file_upload.py:608`). `tenant` = the
   **declared URL tenant** (`declared_tenant(request)`), never
   `X-Parrot-Tenant` — the clear runs in the submission's tenant schema, which
   is the URL tenant. `anonymous` = no authenticated navigator user on the
   request (`is_anonymous_caller`, §3 M2). Upsert on `blob_ref`
   (FEAT-652 idempotent uploads re-send the same blob: `uploaded_at` is
   refreshed, nothing duplicated). Fail-soft: a record failure is logged and
   the upload still answers 200 (the blob is merely untracked — today's state).
   A successful prior-ref replacement also deletes the prior's pending row.

3. **Clear on store** — `FormSubmissionStorage` gains an optional attached
   `PendingUploadStore`. When attached, `store()` runs the INSERT and
   `pending.clear(iter_blob_refs(submission.data), tenant=…, conn=conn)` in
   ONE transaction. `iter_blob_refs` walks dicts/lists recursively and yields
   every `str` value of a `blob_ref` key (covers `FileEnvelope`, lists of
   envelopes, and the legacy `{answer, blob_ref, display}` multi-upload item).
   A missing pending table (`asyncpg.UndefinedTableError`) is swallowed inside a
   SAVEPOINT so the submission still commits. FEAT-730's `store_guarded()`
   calls the same private helper inside its own transaction (whichever feature
   lands second wires it — §7). Because the clear lives in `store()`, hosts
   that bypass the pipeline (FieldSync `execution/services.py:645`,
   `visits/services.py:1189`) are covered with zero host code.
   `setup_form_api(pending_uploads=…)` attaches the store to the
   `submission_storage` it receives.

4. **Sink path** (FEAT-457 `form.persistence`) — the generic storage is never
   called there (`services/submission_pipeline.py:231-257`), so the pipeline
   clears after a successful `sink.write` (best-effort, NOT transactional with
   the sink; a failure is logged).

5. **Reaper** — `PendingUploadReaper(pending, blob_storage, submissions)`;
   `reap_once(*, tenant, anonymous_ttl, authenticated_ttl, batch=500)`:
   - selects up to `batch` expired rows (`anonymous` rows older than
     `anonymous_ttl`, others older than `authenticated_ttl`) with
     `FOR UPDATE SKIP LOCKED` inside a short transaction that only reads;
   - **safety check** per row: `submissions.references_blob(form_uid,
     blob_ref, tenant=…)` — if a stored submission references it, drop the
     pending row only (`still_referenced`);
   - otherwise `blob_storage.delete(blob_ref, strict=True)` then the thumbnail;
     on success delete the row (`deleted`); on failure keep the row
     (`failed`) for the next run;
   - returns `ReapResult(deleted, failed, still_referenced)`.
   - Defaults exported: `DEFAULT_ANONYMOUS_TTL = timedelta(hours=48)`,
     `DEFAULT_AUTHENTICATED_TTL = timedelta(days=7)`.

6. **Strict delete** — `AbstractBlobStorage.delete()` today swallows every
   non-404 error with a warning (`services/blob_storage.py:323-341`), so the
   reaper could never see a failure. `delete(blob_ref, *, strict: bool =
   False)`: `strict=True` re-raises non-"missing" errors; default unchanged for
   every existing caller.

7. **In-passing fix (same handler, same subject)** — the multi-file rejection
   cleanup passes `orphan.thumbnail_url` (a URL path) to
   `blob_storage.delete()` (`api/file_upload.py:291`); `_from_ref` raises
   `ValueError` on it (`services/blob_storage.py:262-265`), caught as a
   warning, so the thumbnail of a rejected multi-file upload is always leaked.
   It now deletes the extracted thumbnail ref.

**Why 7 days for authenticated uploads (Juan, 2026-10-22: "30 días es demasiado… una semana… que se pierda la foto y tenga que llenarlo de nuevo").** Parrot's own server-side drafts do
NOT justify it: `PartialSaveStore` is Redis with a default TTL of 1 hour
(`services/partial_saves.py:37-38, :54`), refreshed on write. The long TTL is
for the HOST's clients: the FieldSync app uploads on pick and may hold the
resulting `blob_ref` in its offline queue / visit draft on the device for days
before the submit drains (navigator-svelte `src/lib/services/offline/pendingUploads.ts`,
FEAT-651/652). Deleting earlier would destroy a photo a rep is still going to
submit. The host can tune both TTLs (FEAT-801 config keys).

### Component Diagram
```
client ──POST …/fields/{field_uid}/file-upload──▶ handle_file_upload
                                                     │ blob_storage.put (+ thumbnail)
                                                     ▼
                                      PendingUploadStore.record(anonymous, uploaded_at)
                                                     │
client ──POST …/data (pipeline) ─▶ SubmissionPipeline ─▶ FormSubmissionStorage.store()/store_guarded()
host (FieldSync execution/visits) ────────────────────▶   └─ INSERT + PendingUploadStore.clear(refs)  [one txn]
                                  └─ persistence sink ─▶ sink.write → PendingUploadStore.clear(refs) [best-effort]

host scheduler (FieldSync FEAT-801, nightly, per tenant)
   └─▶ PendingUploadReaper.reap_once ─▶ expired() ─▶ references_blob()? ─┬─ yes → delete_rows
                                                                          └─ no  → blob_storage.delete(strict) (+thumb) → delete_rows
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `api/file_upload.py::handle_file_upload` | modifies | record envelopes; clear prior's row; fix thumbnail cleanup |
| `services/submissions.py::FormSubmissionStorage` | extends | `attach_pending_uploads`, transactional clear in `store()`, `references_blob` |
| `services/submission_pipeline.py::SubmissionPipeline.submit` | modifies | clear after a successful sink write |
| `services/blob_storage.py::AbstractBlobStorage.delete` (+ manager-backed impl) | extends | `strict` kwarg |
| `api/routes.py::setup_form_api` | extends | `pending_uploads` kwarg; stash + attach (via a helper — function already over budget) |
| `core/tenant.py` | extends | `is_anonymous_caller(request)` |
| FEAT-730 `FormSubmissionStorage.store_guarded` | coordinates | must call the same clear helper in its transaction |

### Data Models
```python
class PendingUpload(BaseModel):
    blob_ref: str
    thumbnail_ref: str | None = None
    form_uid: uuid.UUID
    field_uid: uuid.UUID
    tenant: str
    anonymous: bool
    uploaded_at: datetime | None = None   # None on record → DB default now()

class ReapResult(BaseModel):
    deleted: int = 0
    failed: int = 0
    still_referenced: int = 0
```

### New Public Interfaces
```python
from parrot_formdesigner.services.pending_uploads import (
    PendingUpload, PendingUploadStore, PendingUploadReaper, ReapResult,
    iter_blob_refs, DEFAULT_ANONYMOUS_TTL, DEFAULT_AUTHENTICATED_TTL,
)
setup_form_api(app, registry, ..., pending_uploads: PendingUploadStore | None = None)
FormSubmissionStorage.attach_pending_uploads(store: PendingUploadStore | None) -> None
FormSubmissionStorage.references_blob(form_uid, blob_ref, *, tenant) -> bool
AbstractBlobStorage.delete(blob_ref, *, strict: bool = False) -> None
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: PendingUploadStore + models | yes | DDL §2.1; methods §3 M1; `qualified_table`/`validate_identifier` | — |
| M2: Record on upload | yes | record point after prior-ref block; URL tenant; `is_anonymous_caller`; fail-soft | — |
| M3: Clear on store + references_blob | yes | one transaction, SAVEPOINT around clear, `iter_blob_refs` | — |
| M4: Strict delete + reaper | yes | algorithm §2.5 | — |
| M5: Wiring + sink-path clear + exports | yes | `setup_form_api` kwarg via helper; pipeline after `sink.write` | — |
| M6: Docs | yes | — | — |

### Module 1: Pending-upload store and models
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/pending_uploads.py` (CREATE)
- **Responsibility**: Table DDL, upsert/clear/expired/delete, the blob-ref walker, TTL constants, result models.
- **Depends on**: nothing.
- **Interface Skeleton**:
  ```python
  # services/pending_uploads.py (new)
  from ._identifiers import qualified_table, validate_identifier  # verified: services/submissions.py:25

  DEFAULT_TABLE = "pending_uploads"            # FieldSync passes table_name="fs_pending_uploads"
  DEFAULT_ANONYMOUS_TTL = timedelta(hours=48)
  DEFAULT_AUTHENTICATED_TTL = timedelta(days=7)

  def iter_blob_refs(data: Any) -> set[str]:
      """Every str value under a `blob_ref` key, walking dicts/lists recursively."""

  class PendingUploadStore:
      def __init__(self, pool: Any, *, schema: str = "navigator", table_name: str = DEFAULT_TABLE) -> None: ...
      async def initialize(self, *, tenant: str | None = None) -> None:
          """CREATE TABLE/INDEX IF NOT EXISTS in <tenant or schema>."""
      async def record(self, entry: PendingUpload, *, tenant: str) -> None:
          """INSERT … ON CONFLICT (blob_ref) DO UPDATE SET uploaded_at = now(), thumbnail_ref = EXCLUDED.thumbnail_ref."""
      async def clear(self, blob_refs: Iterable[str], *, tenant: str | None, conn: Any | None = None) -> int:
          """DELETE … WHERE blob_ref = ANY($1); uses `conn` when given (caller's transaction). No-op on empty input."""
      async def expired(self, *, tenant: str, anonymous_ttl: timedelta, authenticated_ttl: timedelta,
                        limit: int, conn: Any | None = None) -> list[PendingUpload]:
          """Rows with (anonymous AND uploaded_at < now()-anon) OR (NOT anonymous AND uploaded_at < now()-auth),
          oldest first, FOR UPDATE SKIP LOCKED when `conn` is in a transaction."""
      async def delete_rows(self, blob_refs: Iterable[str], *, tenant: str) -> int: ...
  ```

### Module 2: Record on upload
- **Path**: `api/file_upload.py`, `core/tenant.py`
- **Responsibility**: Record every returned envelope; drop the prior's row on replacement; fix the thumbnail cleanup at :291.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # core/tenant.py (new function, next to enforce_membership_unless_public :189)
  def is_anonymous_caller(request: web.Request) -> bool:
      """True when navigator-auth's user_session attached no user (request.user absent/None
      and request.get("user") falsy). Shared with FEAT-730 M4's blob-tenant rule."""

  # api/file_upload.py
  def _thumbnail_ref(thumbnail_url: str | None) -> str | None:
      """The `ref` query param of a thumbnail_url built at :608, unquoted; None when absent."""

  async def handle_file_upload(request: web.Request) -> web.Response:  # verified: api/file_upload.py:169
      """…unchanged… After the prior-ref block (:325-337) and before the response (:339):
      if app["form_pending_uploads"] is set, record each envelope as PendingUpload(
      blob_ref, thumbnail_ref=_thumbnail_ref(env.thumbnail_url), form_uid=form.form_uid,
      field_uid=field.field_uid, tenant=declared_tenant, anonymous=is_anonymous_caller(request));
      on a successful prior delete also delete_rows([prior_blob_ref]). Any exception → logger.warning.
      Multi-file rejection cleanup (:291) deletes orphan.blob_ref and _thumbnail_ref(orphan.thumbnail_url)."""
  ```

### Module 3: Clear on store + reference check
- **Path**: `services/submissions.py`
- **Responsibility**: Transactional clear in `store()`; shared helper for FEAT-730 `store_guarded`; `references_blob`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  class FormSubmissionStorage:                                    # verified: services/submissions.py:122
      def attach_pending_uploads(self, store: "PendingUploadStore | None") -> None:
          """Late binding (hosts construct the storage before setup_form_api)."""
      async def _clear_pending(self, conn: Any, submission: FormSubmission, tenant: str | None) -> None:
          """When attached: SAVEPOINT; pending.clear(iter_blob_refs(submission.data), tenant, conn=conn);
          UndefinedTableError → rollback to savepoint, debug log. Used by store() AND store_guarded()."""
      async def store(self, submission: FormSubmission, *, tenant: str | None = None) -> str:  # verified: :313
          """Unchanged when nothing is attached. When attached: `async with conn.transaction()`:
          INSERT (:334-357) then _clear_pending — both commit or neither."""
      async def references_blob(self, form_uid: uuid.UUID, blob_ref: str, *, tenant: str | None) -> bool:
          """SELECT EXISTS(SELECT 1 FROM <qt> WHERE form_uid = $1
             AND jsonb_path_exists(data, '$.** ? (@.blob_ref == $ref)', jsonb_build_object('ref', $2::text)))."""
  ```

### Module 4: Strict delete + reaper
- **Path**: `services/blob_storage.py`, `services/pending_uploads.py`
- **Responsibility**: Let the reaper observe delete failures; reap expired rows per tenant.
- **Depends on**: M1, M3 (`references_blob`).
- **Interface Skeleton**:
  ```python
  # services/blob_storage.py
  class AbstractBlobStorage(ABC):                                  # verified: :119
      async def delete(self, blob_ref: str, *, strict: bool = False) -> None:   # verified: :169
          """strict=True: re-raise anything that is not 'missing' (FileNotFoundError / NoSuchKey / 404)."""
  class _ManagerBackedBlobStorage(AbstractBlobStorage):            # verified: :199
      async def delete(self, blob_ref: str, *, strict: bool = False) -> None:   # verified: :323
          """Non-strict path byte-identical to today (:324-341)."""

  # services/pending_uploads.py
  class PendingUploadReaper:
      def __init__(self, pending: PendingUploadStore, blob_storage: AbstractBlobStorage,
                   submissions: FormSubmissionStorage) -> None: ...
      async def reap_once(self, *, tenant: str, anonymous_ttl: timedelta = DEFAULT_ANONYMOUS_TTL,
                          authenticated_ttl: timedelta = DEFAULT_AUTHENTICATED_TTL,
                          batch: int = 500) -> ReapResult:
          """§2.5. A ref whose scheme does not match the backend (ValueError from _from_ref,
          e.g. a pre-FEAT-460-fix `temp://` ref) counts as failed and is logged, never raised."""
  ```

### Module 5: Wiring, sink-path clear, exports
- **Path**: `api/routes.py`, `services/submission_pipeline.py`, `services/__init__.py`
- **Responsibility**: `setup_form_api(pending_uploads=…)`; clear after sink write; public exports.
- **Depends on**: M1, M3.
- **Interface Skeleton**:
  ```python
  # api/routes.py — setup_form_api (signature :192-215, last kwarg teams_renderer :214)
      pending_uploads: "PendingUploadStore | None" = None,
  # body: ONE call to a new helper (setup_form_api is already over the complexity budget, :170-172):
  def _wire_pending_uploads(app, submission_storage, pending_uploads) -> None:
      """_stash_without_clobbering(app, "form_pending_uploads", pending_uploads);
      if both present: submission_storage.attach_pending_uploads(pending_uploads)."""

  # services/submission_pipeline.py (after `await sink.write(submission, payload)` :247)
  #   best-effort: pending.clear(iter_blob_refs(submission.data), tenant=tenant) when the
  #   generic storage has one attached; exception → logger.warning.
  ```

### Module 6: Documentation
- **Path**: `packages/parrot-formdesigner/docs/` (the file-upload page) — record/clear/reap lifecycle, TTLs, host responsibilities (provision table, schedule `reap_once`), the `strict` delete flag.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_iter_blob_refs_shapes` | M1 | single envelope, list, nested group/array, legacy `{answer, blob_ref, display}`, non-str ignored, no refs → empty |
| `test_thumbnail_ref_from_url` | M2 | URL from `_finalize_envelope` → original ref; None/absent → None |
| `test_is_anonymous_caller` | M2 | request through the real `_wrap_auth` chain built with `make_mocked_request`: no session → True; session with user → False |
| `test_upload_records_pending` | M2 | single + list (`image_dropzone`) uploads record one row per envelope with thumbnail_ref, URL tenant (NOT `X-Parrot-Tenant`), anonymous flag |
| `test_upload_record_failure_is_soft` | M2 | store raising → 200, envelope returned, warning logged |
| `test_prior_replacement_clears_prior_row` | M2 | `X-Parrot-Prior-Blob-Ref` → prior blob deleted AND its row deleted |
| `test_multi_file_rejection_deletes_thumbnail` | M2 | rejected 2nd part → `delete` called with the THUMBNAIL REF, never the URL. **Mutation: restore `orphan.thumbnail_url` → RED** |
| `test_store_without_pending_unchanged` | M3 | no attach → single execute, no transaction, no clear (G5) |
| `test_delete_strict` | M4 | strict re-raises a 500-type error; NoSuchKey/FileNotFound still silent; non-strict unchanged |
| `test_reaper_ttls_and_outcomes` | M4 | fake blob storage: expired anonymous (49 h) deleted, anonymous 47 h kept, authenticated 29 d kept / 31 d deleted; referenced → `still_referenced`, blob untouched; delete failure → row kept, `failed` |
| `test_reaper_bad_scheme_counts_failed` | M4 | `temp://…` ref on an S3 backend → failed, no raise |
| `test_setup_form_api_wires_pending` | M5 | kwarg set → app key + `attach_pending_uploads` called; absent → key `None`, nothing attached |
| `test_sink_path_clears_after_write` | M5 | persistence form → clear called after `sink.write`; sink error → no clear |

### Integration Tests (real Postgres)
| Test | Description |
|---|---|
| `test_store_clears_pending_in_same_transaction` | record 2 refs; store a submission referencing 1 → that row gone, other kept. **Mutation: move the clear outside the transaction / drop it → RED** |
| `test_store_rolls_back_clear_on_insert_failure` | duplicate `submission_id` → INSERT fails → pending row still present |
| `test_store_with_missing_pending_table` | attached store, table not created → submission committed, no error |
| `test_references_blob_jsonpath` | envelope nested in a list inside a group → True; other form_uid → False; a different ref that is a prefix → False |
| `test_reaper_skip_locked_concurrent` | two `reap_once` in parallel → each row processed once |

### Validation Contract
- `pytest packages/parrot-formdesigner/tests/unit -k "pending or reaper or blob_delete or file_upload" -q`
- `pytest packages/parrot-formdesigner/tests/integration -k pending -q` (needs the integration Postgres)
- `ruff check` + `flake8 --max-complexity` on changed files; `setup_form_api` complexity must not grow.

---

## 5. Acceptance Criteria

- [ ] AC1 — Without `pending_uploads`, every existing upload, storage and pipeline test is green and `store()` issues the same single statement (G5).
- [ ] AC2 — Every `/file-upload` response (single or list) leaves exactly one pending row per returned envelope, in the URL tenant's schema, with `thumbnail_ref`, uids and the right `anonymous` flag; a retried idempotent upload refreshes `uploaded_at` without duplicating.
- [ ] AC3 — A failure to record never fails the upload.
- [ ] AC4 — `store()` with an attached store deletes the pending rows of every `blob_ref` in the submission's data in the SAME transaction as the INSERT; a failed INSERT leaves them.
- [ ] AC5 — A host calling `FormSubmissionStorage.store()` directly (no pipeline) gets the clear with no host code.
- [ ] AC6 — `reap_once` deletes blob + thumbnail + row for expired unreferenced rows (48 h anonymous / 30 d authenticated by default), drops only the row when a submission still references the blob, and keeps the row when the delete fails.
- [ ] AC7 — `delete(strict=True)` surfaces non-missing errors; `delete()` without the flag is unchanged.
- [ ] AC8 — The multi-file rejection cleanup deletes the thumbnail by ref (mutation-checked).
- [ ] AC9 — FEAT-730's `store_guarded` (whichever lands second) calls `_clear_pending` inside its transaction; a test pins it.
- [ ] AC10 — Docs updated; package version bumped; ai-parrot-server released in lockstep.

---

## 6. Codebase Contract

> Verified against ai-parrot `dev` @ `a0bb15f9d` (2026-10-22). Paths are relative
> to `packages/parrot-formdesigner/src/parrot_formdesigner/`.

### Verified Imports
```python
from ._identifiers import qualified_table, validate_identifier          # services/submissions.py:25
from ..services.blob_storage import AbstractBlobStorage, BlobMetadata   # api/file_upload.py:61
from .tenant import declared_tenant                                     # api/file_upload.py:65 (core/tenant.py:166)
from .handlers import extract_form_uid, extract_uid                     # api/file_upload.py:64
from .submissions import CORE_METADATA_COLUMNS, FormSubmission, FormSubmissionStorage  # services/__init__.py:26-30
```

### Existing Class Signatures
```python
# api/file_upload.py
_CHUNK_BUFFERS: dict[tuple[str, str, str], dict[int, str]]                         # :76 ("no expiry/GC in V1" :75)
def _get_blob_storage(app) -> AbstractBlobStorage                                  # :79 (app["blob_storage"] or TempBlobStorage)
async def handle_file_upload(request: web.Request) -> web.Response                 # :169
    form_uid = extract_form_uid(request); field_uid = extract_uid(request, "field_uid"); tenant = declared_tenant(request)  # :202-204
    single = is_single_cardinality(field.field_type)                               # :236
    blob_tenant = request.headers.get("X-Parrot-Tenant") or tenant                 # :238
    # multi-file rejection cleanup: for ref in (orphan.blob_ref, orphan.thumbnail_url): await blob_storage.delete(ref)  # :291-299 (BUG: URL)
    result = envelopes[0] if single else envelopes                                 # :321
    prior_blob_ref = request.headers.get("X-Parrot-Prior-Blob-Ref")               # :325
    if prior_blob_ref and prior_blob_ref not in written: await blob_storage.delete(prior_blob_ref)  # :327-337
    if isinstance(result, list): return web.json_response([...])                   # :339-341
async def _finalize_envelope(...)                                                  # :540
    thumbnail_ref = await thumbnail_service.generate(file_bytes, blob_meta)        # :606
    thumbnail_url = f"{thumbnail_base_path}?ref={quote(thumbnail_ref, safe='')}"   # :608

# services/blob_storage.py
class AbstractBlobStorage(ABC)                                                     # :119
    async def put(self, stream, *, metadata: BlobMetadata) -> str                  # :131
    async def delete(self, blob_ref: str) -> None                                  # :169 ("Idempotent — no error if missing")
class _ManagerBackedBlobStorage(AbstractBlobStorage)                               # :199
    def _build_key(self, metadata) -> str   # f"{prefix}{form_uid}/{field_uid}/{blob_id}"  :230-242
    def _to_ref(self, key) -> str           # "{scheme}://{bucket}/{key}" | "{scheme}://{key}"  :244-252
    def _from_ref(self, blob_ref) -> str    # raises ValueError on scheme mismatch    :254-276
    async def delete(self, blob_ref: str) -> None                                  # :323 — swallows non-404 with a warning (:337-341)
class S3BlobStorage / GCSBlobStorage / LocalBlobStorage / TempBlobStorage          # :347 / :428 / :482 / :533

# services/submissions.py
DEFAULT_SCHEMA = "navigator"; DEFAULT_TABLE = "form_data"                          # :31-32
class FormSubmissionStorage                                                        # :122
    def __init__(self, pool, *, schema=DEFAULT_SCHEMA, table_name=DEFAULT_TABLE, tenant=None)  # :140-156
    def _qualified(self, tenant) -> str                                            # :170
    def _create_table_sql(self, tenant) -> str   # columns incl. form_uid UUID, data JSONB NOT NULL, context JSONB, extra_data JSONB; idx on form_uid  :177-219
    async def initialize(self, *, tenant=None) -> None                             # :297
    async def store(self, submission, *, tenant=None) -> str                       # :313 — one acquire, one execute, NO explicit transaction (:333-357)
    async def get_submission(...)                                                  # :420
    async def list_revisions(...)                                                  # :442

# services/submission_pipeline.py
#   persistence sink branch: `if form.persistence is not None:` … `await sink.write(submission, payload)`  :234 / :247
#   generic branch: `await self.submission_storage.store(submission)`             :259 (FEAT-730 changes it to store/store_guarded with tenant)

# services/partial_saves.py
class PartialSaveStore                                                             # :24 — Redis, ttl_seconds default 3600 (:37-38, :54)

# api/routes.py
def _stash_without_clobbering(app, key, value) -> None                             # :167-189 (explicit wins, None only ensures key)
def setup_form_api(app, registry, *, client=None, submission_storage=None, …, teams_renderer=None) -> None  # :192-215 (complexity already 26: :170-172)
    _stash_without_clobbering(app, "blob_storage", blob_storage)                   # :307
    _stash_without_clobbering(app, "rest_resolver", resolver)                      # :308
    file-upload route: _wrap_auth(file_upload_module.handle_file_upload)           # :452-455 (FEAT-730 → tenant="public")
def _wrap_auth(handler, *, tenant="required")                                      # :84 — user_session() sets request.user only when a user exists

# core/tenant.py
def declared_tenant(request) -> str                                                # :166
def enforce_membership_unless_public(request, form, tenant) -> None                # :189
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `PendingUploadStore.record` | `handle_file_upload` | call before the response | `api/file_upload.py:339` |
| `FormSubmissionStorage._clear_pending` | `store()` INSERT | same `conn`, transaction | `services/submissions.py:333` |
| `PendingUploadStore.clear` | pipeline sink branch | after `sink.write` | `services/submission_pipeline.py:247` |
| `_wire_pending_uploads` | `setup_form_api` | one call after `:308` | `api/routes.py:308` |
| `PendingUploadReaper` | `AbstractBlobStorage.delete(strict=True)` | method call | `services/blob_storage.py:169/:323` |

### Does NOT Exist (Anti-Hallucination)
- ~~`PendingUploadStore`, `pending_uploads` table, `iter_blob_refs`, any reaper/GC~~ — none exist (`:75` "no expiry/GC in V1").
- ~~`FileEnvelope.thumbnail_ref`~~ — the envelope only has `thumbnail_url`; the ref is its `ref` query param.
- ~~A transaction in `FormSubmissionStorage.store()`~~ — today a bare execute.
- ~~`delete(..., strict=)`~~ — new; today's `delete` never raises on backend errors.
- ~~`FormSubmissionStorage.references_blob` / any jsonpath query in parrot~~ — new.
- ~~`is_anonymous_caller`~~ — new (FEAT-730 M4 describes the same rule in prose; one helper serves both).
- ~~A scheduler in parrot-formdesigner~~ — the host schedules `reap_once`.

### Edit Sites (Blueprint Anchors)

Verified against: `a0bb15f9d`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `services/pending_uploads.py` | CREATE | — | — | — |
| `api/file_upload.py` | MODIFY | `for ref in (orphan.blob_ref, orphan.thumbnail_url):` | `:291` | 1 |
| same | MODIFY | `if prior_blob_ref and prior_blob_ref not in written:` | `:327` | 1 |
| same | MODIFY | `    if isinstance(result, list):` | `:339` | 1 |
| same | MODIFY | `# leaves its entry and chunk blobs orphaned — no expiry/GC in V1.` (comment: chunk blobs remain out of scope) | `:75` | 1 |
| `core/tenant.py` | MODIFY | `def enforce_membership_unless_public(request: web.Request, form: Any, tenant: str) -> None:` | `:189` | 1 |
| `services/submissions.py` | MODIFY | `    async def store(` | `:313` | 1 |
| same | MODIFY | `    def __init__(` | `:140` | 1 |
| `services/blob_storage.py` | MODIFY | `    async def delete(self, blob_ref: str) -> None:` (1st = abstract :169, 2nd = manager-backed :323 — anchor with the following docstring/`key = self._from_ref(blob_ref)` line) | `:169/:323` | 2 |
| `services/submission_pipeline.py` | MODIFY | `                    await sink.write(submission, payload)` | `:247` | 1 |
| `api/routes.py` | MODIFY | `    teams_renderer: "AbstractFormRenderer \| None" = None,` | `:214` | 1 |
| same | MODIFY | `    _stash_without_clobbering(app, "rest_resolver", resolver)` | `:308` | 1 |
| `services/__init__.py` | MODIFY | `from .submissions import (` block (`FormSubmissionStorage` appears twice: import + `__all__`) | `:26-30` | 2 |
| `tests/unit/services/test_pending_uploads.py` | CREATE | — | — | — |
| `tests/unit/api/test_file_upload_pending.py` | CREATE | — | — | — |
| `tests/integration/test_pending_uploads_pg.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `FormSubmissionStorage` for SQL style: identifier-validated names, `qualified_table`, pool `acquire()`, `initialize()` with `IF NOT EXISTS`.
- `_stash_without_clobbering` for the app key; never grow `setup_form_api`'s complexity (Rule 4) — one helper call.
- Fail-soft on the upload path, transactional on the store path, observable failures on the reaper path.
- Tests build requests through the real `_wrap_auth` chain with `make_mocked_request` (no `Mock` request with hand-set `.user`/`.session`).

### Known Risks / Gotchas
- **FEAT-730 overlap**: FEAT-730 M2 adds `store_guarded` (same file, same transaction concern) and M4 rewires the file-upload route and blob tenant. Whichever lands second must (a) call `_clear_pending` inside `store_guarded`'s transaction, (b) keep recording under the URL tenant. FEAT-728 also edits the pipeline submit block (:231-260).
- **Late submit after TTL**: an authenticated device that submits more than 7 days after uploading references a deleted blob. The safety check cannot help (no submission yet). ACCEPTED by Juan: after a week the rep re-takes the photo and fills the form again; host-tunable TTL.
- **Sink forms**: rows stored by a FEAT-457 sink are invisible to `references_blob` (it reads the generic table). If the post-sink clear fails, the reaper deletes a referenced blob after the TTL. Logged at warning level on the clear; accepted (sink forms are rare and the clear is a single DELETE).
- **Pending rows in another tenant**: rows are recorded under the URL tenant; a host that stores the submission under a different tenant than the upload URL will not clear them (FieldSync uses the programme for both).
- **Cost of the safety check**: `jsonb_path_exists` is evaluated only on rows of the pending row's `form_uid` (existing `idx_<table>_form_uid`), at most `batch` times per tenant per night. Upper bound ≈ batch × submissions-per-form JSON scans; acceptable for a nightly job. No new index on `data`.
- **Thumbnails** live in the same bucket under the thumbnail service's own key; deleted by ref alongside the blob. A blob whose thumbnail generation failed has `thumbnail_ref = NULL`.
- `temp://` refs from before the FEAT-460 wiring fix are never recorded (recording starts with this feature); the bad-scheme branch is defensive only.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `asyncpg` | existing | `UndefinedTableError`, transactions/savepoints |
| PostgreSQL | ≥ 12 | `jsonb_path_exists` |

---

## 8. Open Questions

- [x] Which cleanup strategy? — *Resolved 2026-10-22 (Juan)*: pending-upload registry + nightly sweep (Option 3), not S3 lifecycle and not upload-on-submit.
- [x] Same mechanism for the app and the public share page? — *Resolved 2026-10-22 (Juan)*: yes, one mechanism; separate feature from public forms.
- [x] TTLs? — *Contract default*: 48 h anonymous / 7 days authenticated (Juan, 2026-10-22), host-configurable (FieldSync FEAT-801 config keys).
- [ ] Should the reaper also handle abandoned chunk-upload blobs (`_CHUNK_BUFFERS`)? Out of scope v1. — *Owner: Juan*
- [ ] Should `is_anonymous_caller` also become the source of FEAT-730's `SubmittedEvent.anonymous` (FEAT-730 Q2)? — *Owner: Juan*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (cross-repo split; contract decided with Juan)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree; sub-worktree per task.
- **Module graph**: M2 → M1; M3 → M1; M4 → M1 + M3 (`references_blob`); M5 → M1 + M3; M6 last. M2 and M3 run concurrently after M1; M4 and M5 concurrently after M3.
- **Shared files**: `services/pending_uploads.py` (M1, M4) — serialized.
- **Exclusive resources**: none (no migration in parrot; FieldSync owns provisioning). Version bump + lockstep ai-parrot-server release at the end.
- **Cross-feature**: FEAT-730 (same `submissions.py`, `file_upload.py`, `routes.py`, pipeline lines) and FEAT-728 (pipeline submit block) — rebase on whichever merged first; FieldSync FEAT-801 consumes this release.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-22 | Juan Francisco Ruffato (with Claude) | Initial draft from the orphan-upload contract (Option 3) |
| 0.2 | 2026-10-22 | Juan Francisco Ruffato (with Claude) | Authenticated TTL 30 → 7 days (Juan) |
