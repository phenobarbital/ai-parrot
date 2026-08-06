# TASK-2153: NotificationTemplate model + DDL

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. Templates today only exist as files under `TEMPLATE_DIR`;
non-developers cannot author or edit one. This task creates the persistence
layer for Jinja2 template **strings** in Postgres.

Leaf task — no dependencies. The CRUD endpoints that consume this model are
TASK-2160.

---

## Scope

- Implement the `NotificationTemplate` asyncdb `Model` at
  `handlers/models/notification_templates.py`.
- Author the full DDL at `handlers/models/notification_templates_creation.sql`.
- Export the model from `handlers/models/__init__.py`.
- Write unit tests for field defaults, `Meta` config, and `tags` handling.

**NOT in scope**:
- CRUD endpoints (TASK-2160).
- Batch/tracking table (TASK-2154).
- **Executing** the DDL against a live database — spec §1 Non-Goals states this
  is an operator/deployment step. Author the file only.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_templates.py` | CREATE | `NotificationTemplate(Model)` |
| `packages/ai-parrot-server/src/parrot/handlers/models/notification_templates_creation.sql` | CREATE | Table + unique + index + trigger + comments |
| `packages/ai-parrot-server/src/parrot/handlers/models/__init__.py` | MODIFY | Export `NotificationTemplate` |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06 by import + signature introspection in `.venv`.

### Verified Imports

```python
import uuid
from datetime import datetime
from typing import Optional

from datamodel import Field                  # verified: core dep
from asyncdb.models import Model             # verified: models/users_prompts.py:16
from parrot.conf import PARROT_SCHEMA        # verified live → "navigator"
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py:19-64
# ← COPY THIS SHAPE EXACTLY
class UserPrompts(Model):
    prompt_id: uuid.UUID = Field(primary_key=True, required=False,
                                 default_factory=uuid.uuid4)   # line 27
    user_id: int = Field(primary_key=True, required=True)
    title: str = Field(required=True)
    prompt_tags: list = Field(required=False, default_factory=list)
    is_public: bool = Field(required=False, default=False)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)

    class Meta:                                                # line 55
        driver = "pg"
        name = "users_prompts"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
```

```sql
-- packages/ai-parrot-server/src/parrot/handlers/models/users_prompts_creation.sql:42-56
-- ← COPY THIS TRIGGER SHAPE, renaming for this table
CREATE OR REPLACE FUNCTION update_users_prompts_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_users_prompts_updated_at ON navigator.users_prompts;
CREATE TRIGGER trigger_users_prompts_updated_at
    BEFORE UPDATE ON navigator.users_prompts
    FOR EACH ROW
    EXECUTE FUNCTION update_users_prompts_updated_at();
```

### Does NOT Exist

- ~~`packages/ai-parrot/src/parrot/handlers/models/`~~ — **this directory does
  not exist.** Models live in `packages/ai-parrot-server/src/parrot/handlers/models/`.
  Older SDD tasks (e.g. TASK-1136) cite the pre-package-split path — do not follow them.
- ~~`navigator.notification_templates`~~ — the table does not exist yet; this task creates its DDL.
- ~~`parrot.handlers.models.NotificationTemplate`~~ — does not exist yet.
- ~~A `user_id` column on this table~~ — templates are **global** by explicit
  decision (spec §8, brainstorm). Do NOT add `user_id`; only `created_by` /
  `updated_by` audit columns.
- ~~`Model.Meta.table`~~ — the attribute is `name`, not `table`.

---

## Implementation Notes

### Required columns (spec §2 Data Models)

| Column | Type | Notes |
|---|---|---|
| `template_id` | `UUID` PK | `DEFAULT uuid_generate_v4()` |
| `name` | `VARCHAR NOT NULL` | **UNIQUE** — used to reference a template by name |
| `template_string` | `TEXT NOT NULL` | The Jinja2 body |
| `subject` | `VARCHAR` | Default email subject |
| `provider` | `VARCHAR` | Default provider |
| `description` | `TEXT` | |
| `tags` | `VARCHAR[] DEFAULT '{}'::VARCHAR[]` | |
| `is_active` | `BOOLEAN NOT NULL DEFAULT TRUE` | Sender rejects inactive templates |
| `created_at` / `updated_at` | `TIMESTAMPTZ DEFAULT NOW()` | |
| `created_by` / `updated_by` | `INTEGER` | Audit; no FK required |

### Key Constraints
- `UNIQUE (name)` — the CRUD endpoint maps its violation to `409`.
- Index on `name` and on `is_active`.
- `update_notification_templates_updated_at()` + `BEFORE UPDATE` trigger —
  `updated_at` is maintained by the DB, **never** by application code.
- `COMMENT ON TABLE` + `COMMENT ON COLUMN` for `template_string`, `is_active`,
  and `provider` (explaining it is a *default*, overridable per request).
- Google-style docstrings and full type hints.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/models/users_prompts.py` — model shape
- `packages/ai-parrot-server/src/parrot/handlers/models/users_prompts_creation.sql` — DDL + trigger
- `packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql` — second DDL reference

---

## Acceptance Criteria

- [ ] `NotificationTemplate` importable: `from parrot.handlers.models import NotificationTemplate`
- [ ] `Meta.driver == "pg"`, `Meta.name == "notification_templates"`, `Meta.schema == PARROT_SCHEMA`
- [ ] All columns from the table above present with correct defaults
- [ ] **No `user_id` field** (templates are global)
- [ ] DDL contains `UNIQUE (name)`, both indexes, the renamed trigger function,
      the `BEFORE UPDATE` trigger, and `COMMENT ON` statements
- [ ] DDL is idempotent (`CREATE TABLE IF NOT EXISTS`, `DROP TRIGGER IF EXISTS`)
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_models.py -v`
- [ ] `ruff check` clean on changed files

---

## Test Specification

```python
# packages/ai-parrot-server/tests/handlers/test_comm_center_models.py
import uuid
from pathlib import Path

import pytest

from parrot.handlers.models import NotificationTemplate
from parrot.conf import PARROT_SCHEMA


class TestNotificationTemplate:
    def test_meta_configuration(self):
        assert NotificationTemplate.Meta.driver == "pg"
        assert NotificationTemplate.Meta.name == "notification_templates"
        assert NotificationTemplate.Meta.schema == PARROT_SCHEMA

    def test_defaults(self):
        t = NotificationTemplate(name="welcome", template_string="Hola {{ name }}")
        assert isinstance(t.template_id, uuid.UUID)
        assert t.is_active is True
        assert t.tags == []

    def test_templates_are_global_no_user_id(self):
        """Templates are global by explicit spec decision."""
        assert "user_id" not in NotificationTemplate.__annotations__

    def test_ddl_has_trigger_and_unique(self):
        sql = Path(
            "packages/ai-parrot-server/src/parrot/handlers/models/"
            "notification_templates_creation.sql"
        ).read_text()
        assert "update_notification_templates_updated_at" in sql
        assert "BEFORE UPDATE" in sql
        assert "UNIQUE" in sql and "name" in sql
        assert "CREATE TABLE IF NOT EXISTS" in sql
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm `users_prompts.py` and its `.sql`
   still match the quoted shapes before copying them
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** following the scope and contract above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2153-notification-templates-model-ddl.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-06
**Notes**:
Implemented `NotificationTemplate` model + DDL exactly per contract, copying
the `UserPrompts`/`users_prompts_creation.sql` shape. Verified with
`py_compile` and `uvx ruff check` (clean). `pytest` could not be executed
successfully: importing `parrot.handlers.models` (via the pre-existing
`users_bots.py` -> `_encrypted_field.py` -> `parrot.handlers.credentials_utils`
-> `parrot.security` -> `parrot.security.vault_utils` -> `parrot.security.
credentials_utils` chain) unconditionally imports `navigator_session.vault.
crypto`, which does not exist in this sandbox's installed `navigator_session`
package (confirmed: the installed package only ships `conf.py`, `data.py`,
`middleware.py`, `session.py`, `storages`, `version.py` — no `vault`
subpackage). This is a pre-existing environment/dependency-version mismatch
entirely unrelated to this task's files (it reproduces on the unmodified
`users_bots.py` import chain) and out of this task's scope to fix.

**Deviations from spec**: none. Test execution blocked by the pre-existing
`navigator_session.vault` environment issue described above — flagging for
maintainer attention; code and tests are otherwise complete and lint-clean.
