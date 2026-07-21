---
type: Wiki Entity
title: DuplicateAccountingCodeError
id: class:parrot_formdesigner.services.project_service.DuplicateAccountingCodeError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when ``(client_id, accounting_code)`` already exists.
---

# DuplicateAccountingCodeError

Defined in [`parrot_formdesigner.services.project_service`](../summaries/mod:parrot_formdesigner.services.project_service.md).

```python
class DuplicateAccountingCodeError(Exception)
```

Raised when ``(client_id, accounting_code)`` already exists.

Attributes:
    client_id: Client the conflict belongs to.
    accounting_code: The duplicate code.
