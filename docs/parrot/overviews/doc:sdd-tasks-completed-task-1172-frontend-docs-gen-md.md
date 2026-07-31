---
type: Wiki Overview
title: 'TASK-1172: Auto-generated frontend implementation docs'
id: doc:sdd-tasks-completed-task-1172-frontend-docs-gen-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The form-runtime UI lives in a separate frontend repo (spec §1
---

# TASK-1172: Auto-generated frontend implementation docs

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 13)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1162, TASK-1167, TASK-1170
**Assigned-to**: unassigned

---

## Context

The form-runtime UI lives in a separate frontend repo (spec §1
Non-Goals). To avoid that repo re-deriving the contract from
JSON Schema, this task produces a human-readable doc at
`packages/parrot-formdesigner/docs/frontend/rest-field.md` from the
Pydantic models and the `x-parrot-rest` JSON-Schema extension. The
script is checked in so the doc can be regenerated on demand.

---

## Scope

- Create `packages/parrot-formdesigner/scripts/gen_frontend_docs.py`:
  - Read `RestFieldSpec` / `RestFieldResult` Pydantic schemas
    (`model_json_schema()`).
  - Read the JSON-Schema extension fragment from TASK-1167.
  - Emit a Markdown file covering: JSON-Schema fragment, upload
    endpoint contract (URL template, multipart body, headers
    including `X-Parrot-Prior-Blob-Ref`), response envelope, error
    codes (400 `in_progress`, 413 too-large, 415 unsupported MIME,
    plus the `success=false` resolver envelope cases), and a worked
    planogram example.
- Generate the output file `docs/frontend/rest-field.md` and commit it.
- An integration test invokes the script and asserts the output
  contains `FieldType.REST`, all three modes, and the response
  envelope keys.

**NOT in scope**: writing the actual frontend component (separate
repo); auto-publishing the doc to a docs site.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/scripts/gen_frontend_docs.py` | CREATE | Script |
| `packages/parrot-formdesigner/docs/frontend/rest-field.md` | CREATE | Generated output |
| `packages/parrot-formdesigner/tests/integration/test_docs_gen_rest.py` | CREATE | Smoke test |

---

## Codebase Contract (Anti-Hallucination)

### Verified

The script uses `model_json_schema()` on `RestFieldSpec` and
`RestFieldResult` (Pydantic v2 builtin). No new third-party deps.

### Does NOT Exist

- ~~`packages/parrot-formdesigner/scripts/`~~ may not exist as a
  directory yet — create it.
- ~~`packages/parrot-formdesigner/docs/frontend/`~~ does not exist
  yet — create it.

---

## Acceptance Criteria

- [ ] `python scripts/gen_frontend_docs.py` writes
      `docs/frontend/rest-field.md`.
- [ ] Output mentions `FieldType.REST`, all three modes, the
      response envelope keys, and the planogram example.
- [ ] Re-running is idempotent (same byte output unless schemas
      changed).
- [ ] Test asserts the file is produced and has the required content
      anchors.

---

## Test Specification

```python
import subprocess, pathlib

def test_frontend_docs_generated(tmp_path):
    subprocess.run(
        ["python", "packages/parrot-formdesigner/scripts/gen_frontend_docs.py",
         "--out", str(tmp_path / "rest-field.md")], check=True)
    content = (tmp_path / "rest-field.md").read_text()
    assert "FieldType.REST" in content
    assert "callback" in content and "remote" in content and "internal" in content
    assert "blob_ref" in content
    assert "planogram" in content.lower()
```

---

## Completion Note

Created `scripts/gen_frontend_docs.py` that reads RestFieldSpec + RestFieldResult Pydantic schemas via TypeAdapter and model_json_schema(), then generates `docs/frontend/rest-field.md`. Output covers: JSON-Schema x-parrot-rest extension, all three modes (remote/internal/callback), upload endpoint contract (URL template, multipart body, X-Parrot-Prior-Blob-Ref/X-Parrot-Tenant headers), response envelope shape, HTTP error codes (400/401/404/413/415/500), HTML5 component hints, and planogram worked example. Script accepts --out argument. Re-running is idempotent. Created integration test with 9 tests, all passing.
