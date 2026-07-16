---
type: Wiki Overview
title: 'TASK-1655: AuditLedger — credential invocation audit log'
id: doc:sdd-tasks-completed-task-1655-auditledger-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **6**. The `AuditLedger` records per-invocation
---

# TASK-1655: AuditLedger — credential invocation audit log

**Feature**: FEAT-261 — Per-User Auth & OBO for MS Agents SDK Integration
**Spec**: `sdd/specs/auth-obo-msagentsdk.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module **6**. The `AuditLedger` records per-invocation
credential usage for compliance. Initially log-based (structured JSON);
can be extended to a persistent store. This is a standalone module with no
dependencies on other FEAT-261 modules.

## Scope

Create a new file `packages/ai-parrot/src/parrot/auth/audit.py` with:
- `AuditEntry` dataclass
- `AuditLedger` class

## Files to Create/Modify

- `packages/ai-parrot/src/parrot/auth/audit.py` — CREATE

## Implementation Notes

```python
"""Credential invocation audit ledger."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class AuditEntry:
    """Single credential invocation record.

    Attributes:
        timestamp: ISO-8601 UTC timestamp of the invocation.
        user_id: Canonical user identity (aad_object_id or channel id).
        channel: Integration channel (e.g. "msagentsdk").
        tool: Tool name that requested credentials (e.g. "o365").
        connection: OAuth connection name (e.g. "graph_sso").
        key_fingerprint: SHA-256 hex of first 8 bytes of the token.
        action: "resolve" or "obo_exchange".
    """
    timestamp: str
    user_id: str
    channel: str
    tool: str
    connection: str
    key_fingerprint: str
    action: str


class AuditLedger:
    """Records per-invocation credential usage for compliance.

    Initially log-based (structured JSON lines). Can be extended to
    persist to a database or external audit service.

    Attributes:
        logger: Logger instance for structured JSON output.
        _entries: In-memory list of recorded entries (for testing/inspection).
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger(__name__)
        self._entries: List[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        """Record a credential invocation entry.

        Logs as structured JSON and appends to in-memory list.

        Args:
            entry: The audit entry to record.
        """
        self._entries.append(entry)
        self.logger.info(
            "AUDIT %s",
            json.dumps(asdict(entry), separators=(",", ":")),
        )

    async def flush(self) -> None:
        """Flush any buffered entries (no-op for log-based implementation)."""
        # Log-based backend writes synchronously in record(); nothing to flush.
        pass

    def entries(self) -> List[AuditEntry]:
        """Return a copy of all recorded entries (for testing)."""
        return list(self._entries)
```

## Codebase Contract

### Verified Imports
```python
# No external dependencies — pure stdlib
import json       # stdlib
import logging    # stdlib
from dataclasses import dataclass, asdict  # stdlib
from typing import List, Optional          # stdlib
```

### Does NOT Exist
- `AuditLedger` — does not exist yet; being created
- `AuditEntry` — does not exist yet; being created

## Acceptance Criteria

- [ ] `AuditEntry` dataclass with fields: `timestamp`, `user_id`, `channel`,
      `tool`, `connection`, `key_fingerprint`, `action`.
- [ ] `AuditLedger.record(entry)` logs structured JSON via `self.logger.info()`.
- [ ] `AuditLedger.record(entry)` appends entry to `_entries` list.
- [ ] `AuditLedger.flush()` is a coroutine (async def) and completes without
      error.
- [ ] `AuditLedger.entries()` returns a copy of all recorded entries.
- [ ] SHA-256 of first 8 bytes of a known token produces expected fingerprint.

## Test Specification

```python
def test_audit_ledger_records_entry():
    ledger = AuditLedger()
    entry = AuditEntry(
        timestamp="2026-06-26T00:00:00Z",
        user_id="00000000-0000-0000-0000-000000000001",
        channel="msagentsdk",
        tool="o365",
        connection="graph_sso",
        key_fingerprint="abc123",
        action="resolve",
    )
    ledger.record(entry)
    assert len(ledger.entries()) == 1


def test_key_fingerprint_computation():
    import hashlib
    token = "my-secret-token"
    raw = token.encode("utf-8")[:8]
    expected = hashlib.sha256(raw).hexdigest()
    # BFTokenServiceResolver computes this; verify formula here
    assert len(expected) == 64
```

### Completion Note

Created `packages/ai-parrot/src/parrot/auth/audit.py` with `AuditEntry`
dataclass (timestamp, user_id, channel, tool, connection, key_fingerprint,
action) and `AuditLedger` class. `record()` appends to `_entries` and logs
structured JSON via `self.logger.info()`. `flush()` is async no-op.
`entries()` returns a copy for testing. No external dependencies — pure stdlib.
