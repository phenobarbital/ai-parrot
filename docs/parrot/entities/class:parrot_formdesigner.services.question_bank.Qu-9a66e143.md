---
type: Wiki Entity
title: QuestionBankService
id: class:parrot_formdesigner.services.question_bank.QuestionBankService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tenant-scoped service for managing reusable field definitions.
---

# QuestionBankService

Defined in [`parrot_formdesigner.services.question_bank`](../summaries/mod:parrot_formdesigner.services.question_bank.md).

```python
class QuestionBankService
```

Tenant-scoped service for managing reusable field definitions.

Backs a ``field_bank`` table (one per tenant schema) that stores
``FormField`` definitions as JSONB, with usage counters.  In tests
the in-memory fallback (internal dict) is used automatically when no
``db=`` connection is provided.

Example::

    svc = QuestionBankService(storage, tenant="navigator")
    created = await svc.create_field(my_field)
    await svc.increment_usage(created.field_id, forms=1)
    ref = ReusableFieldRef(bank_field_id=created.field_id,
                           overrides={"label": "Custom"})
    field = await svc.resolve_ref(ref)

Args:
    storage: ``FormStorage`` instance (used for tenant-schema resolution
        in production).  The service uses ``storage`` for context but
        manages the ``field_bank`` table itself.
    tenant: Tenant slug scoping all operations.
    db: Optional asyncdb/asyncpg DB connection.  When ``None``, the
        service operates in-memory (suitable for tests and development).
    table: Table name inside the tenant schema. Defaults to
        ``"field_bank"``.

## Methods

- `async def create_field(self, field: FormField) -> ReusableField` — Add a field definition to the bank.
- `async def get_field(self, field_id: str) -> ReusableField | None` — Retrieve a ``ReusableField`` by its bank ID.
- `async def list_fields(self) -> list[ReusableField]` — List all bank entries for the current tenant.
- `async def increment_usage(self, field_id: str, *, forms: int=0, responses: int=0) -> None` — Atomically increment usage counters.
- `async def resolve_ref(self, ref: ReusableFieldRef) -> FormField` — Resolve a ``ReusableFieldRef`` to a ``FormField``.
