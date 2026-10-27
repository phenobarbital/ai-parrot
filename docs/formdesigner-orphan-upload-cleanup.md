# FormDesigner — orphan upload cleanup (FEAT-731)

> **Applies to**: `parrot-formdesigner` >= 1.3.0

A file uploaded through `/file-upload` that is never attached to a stored
submission is an orphan: it stays in the blob bucket forever. This feature
tracks every upload in a *pending-upload* table, clears the entry when the
submission is stored, and lets the host reap what is left after a TTL.

## Lifecycle

1. **Record.** `/file-upload` writes one row per blob (and its thumbnail) into
   `<tenant>.<table>`. The tenant is the one in the URL; `public_form` is
   `form.is_public` at upload time. Re-uploading the same `blob_ref` refreshes
   `uploaded_at`. A failure to record never fails the upload.
2. **Clear.** `FormSubmissionStorage.store()` deletes the rows of every
   `blob_ref` found in the submission data, in the **same transaction** as the
   INSERT (so a host calling `store()` directly is covered too). A missing
   pending table never aborts the submission. Forms with a `persistence:` sink
   never reach `store()`: the pipeline clears best-effort right after a
   successful `sink.write` (not transactional with the sink).
3. **Reap.** `PendingUploadReaper.reap_once(tenant=...)` selects expired rows
   with `FOR UPDATE SKIP LOCKED` (concurrent runs never handle the same row).
   TTL is decided **by form**: 48 h for a public form
   (`DEFAULT_PUBLIC_FORM_TTL`), 7 days otherwise (`DEFAULT_TTL`); there is no
   anonymous/authenticated distinction. Per row:
   - a stored submission of the same form still references the blob → only the
     row is dropped (`still_referenced`);
   - otherwise blob and thumbnail are deleted with `delete(..., strict=True)`
     and the row dropped (`deleted`);
   - any failure (backend error, bad scheme) keeps the row for the next run
     (`failed`). `reap_once` never raises for a per-row problem.

## Host responsibilities

- **Provision** the table in each tenant schema:
  `await PendingUploadStore(pool, table_name="fs_pending_uploads").initialize(tenant=tenant)`
  (`table_name` is overridable; default `pending_uploads`).
- **Wire it**: `setup_form_api(app, registry, ..., pending_uploads=store)`. This
  publishes `app["form_pending_uploads"]` for the upload handler and attaches
  the store to the `submission_storage` you pass. Without it nothing changes.
- **Schedule** the reaper (parrot-formdesigner ships no scheduler), per tenant:
  `await PendingUploadReaper(store, blob_storage, submission_storage).reap_once(tenant=tenant)`
  e.g. nightly. Tune with `public_form_ttl`, `ttl`, `batch` (default 500).

## Operational rules (shared bucket)

dev, staging and prod share **one** bucket, so:

1. After restoring a lower environment from a prod dump, **TRUNCATE the pending
   table in every schema** — otherwise that environment's reaper would delete
   blobs that prod rows (restored with the dump) still own.
2. **Never run a bucket-listing cleanup** from any environment; only blobs
   recorded in this environment's own pending table are ever deleted.

Limits: uploads made before this feature were never recorded and are never
swept; chunked uploads are out of scope.
