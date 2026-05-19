---
id: F002
query: Q002
type: read
file: packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py
---

## FormSubmission Model & Storage (217 lines)

**FormSubmission** (Pydantic BaseModel, lines 35-68):
- submission_id: str (uuid4 default)
- form_id, form_version, data (dict), is_valid, forwarded, forward_status/error
- created_at: datetime (UTC)
- tenant: str | None

**FormSubmissionStorage** — PostgreSQL persistence:
- Table: `navigator.form_data` (or `{tenant}.form_data`)
- Uses `asyncpg` pool, identifier-validated SQL
- `initialize()` creates table, `store()` inserts record
- Per-tenant schema resolution via `_resolve_schema()`

**Key insight**: Submissions are durable, final records. Partial saves are
ephemeral, pre-submission data. They serve different lifecycle stages.
The partial save should NOT reuse FormSubmission — it needs its own model
optimized for incremental field-by-field updates.
