# Feedback import identity amendment

Issue: `issue:fbc5627878da`. Implementation: `TASK-5704`.
Owner direction on 2026-11-16: preserve existing records, following the proposed
scope-aware import option with compatibility for existing records.

This supersedes D4 only for assigning new feedback import IDs. The permanent
`FEEDBACK_IMPORT_NAMESPACE` UUID stays unchanged. No schema migration, deletion,
ID rewrite, timestamp change, content rewrite or provenance backfill is performed.
Normal retraction/restoration still updates metadata and its modification timestamp
through the existing backend API; the original creation timestamp is preserved.

New IDs use UUID5 of that namespace and a canonical JSON name:

```text
["coder-feedback:v2", [tenant_id, agent_id, model_id, user_id, session_id, room_id, crew_id], feedback_id]
```

Encode with `json.dumps(..., separators=(",", ":"), ensure_ascii=True)`.
The field order is fixed; unset fields are explicit JSON nulls. Escaping distinguishes
delimiters and arbitrary field contents. This import ID rule includes model_id to
prevent write-once collisions between model-filtered imports; it does not change
the MemoryRef canonical-key or ReviewCommand dedupe-key field lists in D1.

For compatibility, look for the deployed `uuid5(namespace, feedback_id)` and then
the D4 `uuid5(namespace, "coder-feedback:" + feedback_id)` among episodes in the
**exact** requested namespace. Reuse a matching existing ID unchanged. Otherwise,
use the new scoped ID. Existing timestamps, content and provenance stay intact.

`MemoryNamespace.build_filter()` is a query filter, not an ownership test: its
omitted optional fields are wildcards. Compare all seven fields, including nulls,
before reusing any legacy episode or applying a tombstone/restoration. Re-importing
another namespace must persist a separate lesson and report the correct count.
Retraction updates only the namespace explicitly being imported; other namespaces
retain their records until their own import processes the ledger retraction.

The initial count is only a scan-size hint. Read one extra row and require an
unfilled result window before assigning IDs. A full window doubles the limit,
up to three attempts; continued growth raises a visible retry error before any
import writes. A stale count must never hide a legacy row and create its duplicate.

Tests use temporary SQLite files, reopen the database, cover all seven scope fields
and both broad/narrow import orders, and seed both legacy ID forms to verify
preservation and isolated tombstone/restoration replay.
