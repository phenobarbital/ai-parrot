# TASK-2154: NotificationBatchRecipient model + DDL (flat tracking table)

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. `NotifyWorker` publishes **no** result stream, so delivery
truth is unobtainable (spec §1 Non-Goals). What we *can* record is what we
published — one row per recipient — which powers `GET /sender/{batch_id}` and
the retry endpoint.

This table also encodes the **duplicate-delivery containment** decision
(spec §2 state machine): a `publishing` marker written before the `xadd`
distinguishes "never published" from "published, status update lost".

Leaf task — no dependencies.

---

## Scope

- Implement `NotificationBatchRecipient` asyncdb `Model`.
- Author the DDL with indexes on `batch_id` and `status`, plus the
  `updated_at` trigger.
- Encode the status vocabulary as a CHECK constraint.
- Export from `handlers/models/__init__.py`.
- Unit tests for defaults, `Meta`, and the DDL's constraint/index presence.

**NOT in scope**:
- Writing/reading rows (TASK-2158 owns persistence logic).
- The aggregation query (TASK-2158).
- Templates table (TASK-2153).
- Executing the DDL.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_batches.py` | CREATE | `NotificationBatchRecipient(Model)` |
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_batches_creation.sql` | CREATE | Flat table + indexes + CHECK + trigger |
| `packages/ai-parrot-server/src/parrot/handlers/models/__init__.py` | MODIFY | Export the model |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_models.py` | MODIFY | Add tests (file also created by TASK-2153) |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06.

### Verified Imports

```python
import uuid
from datetime import datetime
from typing import Optional

from datamodel import Field
from asyncdb.models import Model             # verified: models/users_prompts.py:16
from parrot.conf import PARROT_SCHEMA        # verified live → "navigator"
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py:55-63
class Meta:
    driver = "pg"
    name = "users_prompts"
    schema = PARROT_SCHEMA
    strict = True
    frozen = False
```

```sql
-- users_prompts_creation.sql:42-56 — trigger shape to copy (rename per table)
CREATE OR REPLACE FUNCTION update_users_prompts_updated_at() ...
CREATE TRIGGER trigger_users_prompts_updated_at BEFORE UPDATE ON ... ;
```

### Does NOT Exist

- ~~A separate `navigator.notification_batches` *header* table~~ — the spec
  explicitly chose a **single flat table**; batch totals come from aggregation.
  Do NOT create a second table.
- ~~`packages/ai-parrot/src/parrot/handlers/models/`~~ — wrong path; models live
  under `ai-parrot-server`.
- ~~A `delivered` status~~ — **not obtainable**. `NotifyWorker.check_stream()`
  (`notify/server/server.py:269-280`) only `xack`s and logs; no result stream
  exists. The vocabulary tops out at `queued`.

---

## Implementation Notes

### Required columns (spec §2 Data Models)

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | `DEFAULT uuid_generate_v4()` |
| `batch_id` | `UUID NOT NULL` | **Indexed**; repeated across the batch's rows |
| `row_number` | `INTEGER` | Source row index, for the skip report |
| `provider` | `VARCHAR NOT NULL` | Resolved per row |
| `recipient_name` | `VARCHAR` | |
| `recipient_address` | `VARCHAR` | email / phone / channel id |
| `status` | `VARCHAR NOT NULL` | CHECK in the 5-value vocabulary below |
| `reason` | `TEXT` | Populated for `skipped` / `publish_failed` |
| `message_id` | `VARCHAR` | Redis stream entry id returned by `xadd` |
| `published_at` | `TIMESTAMPTZ` | Set when `xadd` returns — the retry marker |
| `attempts` | `INTEGER NOT NULL DEFAULT 0` | Incremented per publish attempt |
| `template_ref` | `VARCHAR` | Template id/name/file used |
| `subject` | `VARCHAR` | |
| `created_at` / `updated_at` | `TIMESTAMPTZ DEFAULT NOW()` | |
| `created_by` | `INTEGER` | |

### Status vocabulary (CHECK constraint — spec §2 state machine)

```
pending | publishing | queued | skipped | publish_failed
```

```
  created ──► pending ──(set publishing, THEN xadd)──► publishing
                 │                                          │
                 │                              xadd returns entry id
                 │                                          ▼
                 │                                       queued  ── terminal
                 └── validation failed ──► skipped ── terminal
              xadd raised ──► publish_failed ── safe to retry
```

### Key Constraints
- `CHECK (status IN ('pending','publishing','queued','skipped','publish_failed'))`
- Index on `batch_id`; composite index on `(batch_id, status)` for aggregation.
- Renamed trigger function + `BEFORE UPDATE` trigger for `updated_at`.
- `COMMENT ON COLUMN` for `status` (spelling out the state machine),
  `published_at` (why it exists — the retry marker), and `message_id`.
- Idempotent DDL.

### References in Codebase
- `handlers/models/users_prompts.py` / `users_prompts_creation.sql`
- Spec §2 "Row status state machine"

---

## Acceptance Criteria

- [ ] `from parrot.handlers.models import NotificationBatchRecipient` works
- [ ] `Meta.name == "notification_batch_recipients"`, `driver == "pg"`, `schema == PARROT_SCHEMA`
- [ ] All columns above present; `attempts` defaults to `0`
- [ ] DDL has the 5-value `CHECK`, the `batch_id` index, the `(batch_id, status)`
      composite index, the trigger, and `COMMENT ON` statements
- [ ] **No** second/header batches table is created
- [ ] **No** `delivered` value anywhere in the vocabulary
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_models.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
class TestNotificationBatchRecipient:
    def test_meta_configuration(self):
        assert NotificationBatchRecipient.Meta.name == "notification_batch_recipients"
        assert NotificationBatchRecipient.Meta.driver == "pg"

    def test_defaults(self):
        r = NotificationBatchRecipient(batch_id=uuid.uuid4(), provider="email",
                                       status="pending")
        assert r.attempts == 0
        assert r.published_at is None
        assert r.message_id is None

    def test_ddl_status_vocabulary(self):
        sql = Path("packages/ai-parrot-server/src/parrot/handlers/models/"
                   "notification_batches_creation.sql").read_text()
        for status in ("pending", "publishing", "queued", "skipped", "publish_failed"):
            assert status in sql
        assert "CHECK" in sql
        assert "delivered" not in sql   # not obtainable — see spec §1 Non-Goals

    def test_ddl_indexes_and_trigger(self):
        sql = Path("packages/ai-parrot-server/src/parrot/handlers/models/"
                   "notification_batches_creation.sql").read_text()
        assert "batch_id" in sql
        assert "update_notification_batch_recipients_updated_at" in sql
        assert "BEFORE UPDATE" in sql
```

---

## Agent Instructions

1. **Read the spec** — especially §2 "Row status state machine"
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing code
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2154-batch-tracking-model-ddl.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
