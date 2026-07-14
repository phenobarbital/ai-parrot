---
type: Wiki Summary
title: parrot.auth.audit
id: mod:parrot.auth.audit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'DEPRECATED: Use ``parrot.security.audit_ledger`` instead.'
relates_to:
- concept: class:parrot.auth.audit.AuditEntry
  rel: defines
- concept: class:parrot.auth.audit.AuditLedger
  rel: defines
---

# `parrot.auth.audit`

DEPRECATED: Use ``parrot.security.audit_ledger`` instead.

This module is superseded by the canonical
:class:`parrot.security.audit_ledger.AuditLedger` (FEAT-264 / TASK-1675),
which provides KMS-signed entries and a unified single-ledger design.

Migration
---------
Old (deprecated)::

    from parrot.auth.audit import AuditLedger, AuditEntry
    ledger = AuditLedger()
    ledger.record(AuditEntry(timestamp=..., user_id=..., ...))

New (canonical)::

    from parrot.security.audit_ledger import AuditLedger
    ledger = AuditLedger()
    await ledger.append(user_id=..., channel=..., tool=...,
                        provider=..., credential_material=token)

This file is kept for backward-compatibility; both ``AuditLedger`` and
``AuditEntry`` will emit :class:`DeprecationWarning` on use in a future
release and will be removed in the version after that.

## Classes

- **`AuditEntry`** — Single credential invocation record.
- **`AuditLedger`** — DEPRECATED log-based audit ledger.
