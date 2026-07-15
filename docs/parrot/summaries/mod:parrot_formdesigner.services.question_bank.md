---
type: Wiki Summary
title: parrot_formdesigner.services.question_bank
id: mod:parrot_formdesigner.services.question_bank
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: QuestionBankService — tenant-scoped library of reusable field definitions.
relates_to:
- concept: class:parrot_formdesigner.services.question_bank.QuestionBankService
  rel: defines
- concept: class:parrot_formdesigner.services.question_bank.ReusableField
  rel: defines
- concept: class:parrot_formdesigner.services.question_bank.ReusableFieldRef
  rel: defines
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.services._identifiers
  rel: references
- concept: mod:parrot_formdesigner.services.registry
  rel: references
---

# `parrot_formdesigner.services.question_bank`

QuestionBankService — tenant-scoped library of reusable field definitions.

Provides CRUD operations on ``ReusableField`` entries stored in a dedicated
``field_bank`` table (JSONB-backed), mirroring the ``form_schemas`` DDL
pattern from ``services/storage.py``.  Unit tests use the built-in in-memory
store; the ``db=`` constructor kwarg plugs in an asyncdb/asyncpg connection
for production use.

FEAT-300 — Module 3.

## Classes

- **`ReusableField(BaseModel)`** — A single entry in the tenant's QuestionBank.
- **`ReusableFieldRef(BaseModel)`** — A reference to a ``ReusableField`` with optional field-level overrides.
- **`QuestionBankService`** — Tenant-scoped service for managing reusable field definitions.
