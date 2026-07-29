---
type: Wiki Entity
title: StubCredentialedTool
id: class:parrot.tools.stub_credentialed_tool.StubCredentialedTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Minimal credentialed echo tool for A2A bridge integration tests.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# StubCredentialedTool

Defined in [`parrot.tools.stub_credentialed_tool`](../summaries/mod:parrot.tools.stub_credentialed_tool.md).

```python
class StubCredentialedTool(AbstractTool)
```

Minimal credentialed echo tool for A2A bridge integration tests.

Declares ``credential_provider = "stub"`` so that the A2A credential
gate (FEAT-260 / TASK-1644) suspends the task and issues a consent link
when the per-user stub credential has not yet been resolved.

When the credential IS resolved, the tool simply echoes the ``message``
argument back.  The ``key_fingerprint`` of the resolved credential is
written to the :class:`~parrot.security.audit_ledger.AuditLedger`.

Attributes:
    name: Tool identifier used by the A2A gateway.
    description: Human-readable description sent to the LLM.
    credential_provider: Declares that this tool requires a per-user
        credential from the ``"stub"`` provider.
    args_schema: Pydantic v2 model for tool input validation.
