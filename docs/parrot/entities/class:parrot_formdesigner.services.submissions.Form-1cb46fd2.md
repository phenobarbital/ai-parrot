---
type: Wiki Entity
title: FormSubmissionStorage
id: class:parrot_formdesigner.services.submissions.FormSubmissionStorage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Persist form submissions in a PostgreSQL table.
---

# FormSubmissionStorage

Defined in [`parrot_formdesigner.services.submissions`](../summaries/mod:parrot_formdesigner.services.submissions.md).

```python
class FormSubmissionStorage
```

Persist form submissions in a PostgreSQL table.

Follows the same pattern as ``PostgresFormStorage``: identifier-validated
SQL, ``asyncpg`` pool management, and an explicit ``initialize()`` step
that creates the table when the application starts. The target schema
must already exist.

Args:
    pool: An active ``asyncpg`` connection pool.
    schema: Postgres schema where the table lives. Default
        ``"navigator"``. Used when no per-call tenant overrides it.
    table_name: Table name within ``schema``. Default ``"form_data"``.
    tenant: Optional default tenant slug. When set, every operation
        without an explicit ``tenant=`` kwarg targets
        ``<tenant>.<table_name>`` instead of ``<schema>.<table_name>``.

## Methods

- `async def initialize(self, *, tenant: str | None=None) -> None` — Create the configured submission table if it does not exist.
- `async def store(self, submission: FormSubmission, *, tenant: str | None=None) -> str` — Persist a ``FormSubmission`` record and return its ``submission_id``.
