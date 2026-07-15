---
type: Wiki Summary
title: parrot.tools.stub_credentialed_tool
id: mod:parrot.tools.stub_credentialed_tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Stub credentialed tool for FEAT-260 v1 acceptance testing.
relates_to:
- concept: class:parrot.tools.stub_credentialed_tool.StubCredentialedTool
  rel: defines
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.stub_credentialed_tool`

Stub credentialed tool for FEAT-260 v1 acceptance testing.

:class:`StubCredentialedTool` is a minimal echo tool that declares a
per-user credential requirement (``credential_provider = "stub"``).  It
exists solely to validate the A2A credential bridge end-to-end
(suspend → consent link → OAuth callback → resume → result → audit)
without a real IdP.

The tool is intentionally trivial: it echoes its ``message`` argument back
as the result.  Credential secrets MUST NOT appear in the output — the
bridge applies standard output scrubbing; the stub relies on that seam and
does not perform additional sanitisation.

Usage in tests::

    from parrot.tools.stub_credentialed_tool import StubCredentialedTool
    from parrot.a2a.server import A2AServer
    from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner

    tool = StubCredentialedTool()
    ledger = AuditLedger(signer=LocalHMACSigner())
    server = A2AServer(
        agent,
        credential_resolvers={"stub": my_resolver},
        audit_ledger=ledger,
    )
    # agent.tools = [tool]

## Classes

- **`StubCredentialedTool(AbstractTool)`** — Minimal credentialed echo tool for A2A bridge integration tests.
