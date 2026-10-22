# TASK-4643: Docs page + parrot-formdesigner version bump (orphan cleanup)

**Feature**: FEAT-731 — FormDesigner orphan upload cleanup
**Spec**: `sdd/specs/formdesigner-orphan-upload-cleanup.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4639, TASK-4641, TASK-4642
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 and AC10. FieldSync FEAT-801 provisions the table, wires the
store and schedules `reap_once`; it needs one page describing the lifecycle and
its host responsibilities, and a version to pin. Include the operational rules
from the spec's Known Risks: dev/staging/prod share ONE S3 bucket, so (1) after
restoring a lower environment from a prod dump, TRUNCATE the pending table in
every schema; (2) never run a bucket-listing cleanup from any environment.

---

## Scope

- Write `docs/formdesigner-orphan-upload-cleanup.md`.
- Bump `parrot_formdesigner.version.__version__` to the next minor of whatever `dev` holds when this runs.

**NOT in scope**: the release itself (Jesús); FieldSync changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/formdesigner-orphan-upload-cleanup.md` | CREATE | lifecycle + host duties + ops rules |
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | version bump |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/version.py
__version__ = "1.2.4"   # :5 @ 28b3be0ac — FEAT-730 TASK-4637 may bump it first; bump the then-current minor
```
Docs style reference: `docs/formdesigner-autonomous-persistence.md`.

### Does NOT Exist
- ~~A parrot-side scheduler~~ — document that the host schedules `reap_once`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/formdesigner-orphan-upload-cleanup.md", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/version.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Write the docs page — *why*: hosts implement FEAT-801 from it.
2. Bump the version — *why*: FieldSync pins the release with `pending_uploads`.

### `docs/formdesigner-orphan-upload-cleanup.md` (CREATE)
```markdown
# FormDesigner — orphan upload cleanup (FEAT-731)

## Lifecycle
<!-- FILL IN: record on /file-upload (URL tenant, public_form = form.is_public); clear in store()'s
     transaction (also covers hosts calling store() directly); sink forms: best-effort clear;
     reap_once: TTL by form (48 h public / 7 d otherwise), safety check, strict delete. -->

## Host responsibilities
<!-- FILL IN: provision <tenant>.<table> (PendingUploadStore.initialize, table_name override);
     pass setup_form_api(pending_uploads=…); schedule PendingUploadReaper(...).reap_once per tenant. -->

## Operational rules (shared bucket)
<!-- FILL IN: TRUNCATE the pending table after restoring a lower env from a prod dump;
     never run a bucket-listing cleanup; pre-feature uploads are never swept; chunk uploads out of scope. -->
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__version__ = ' version.py)
# REPLACE the `__version__ = "<current>"` line with the next minor.
```

### FILL IN checklist
- [ ] Docs sections
- [ ] Version value

---

## Acceptance Criteria

- [ ] Docs page exists with lifecycle, host duties and the shared-bucket rules (AC10).
- [ ] Version bumped (AC10).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_file_upload_handler.py -q`

---

## Test Specification

No new tests.

---

## Agent Instructions

1. Feature worktree; all other FEAT-731 tasks `done`.
2. Exclusive task (package version). Commit only the listed files.
3. `scripts/sdd/close_task.sh TASK-4643 formdesigner-orphan-upload-cleanup verified`.

---

## Completion Note

*(Agent fills this in when done)*
