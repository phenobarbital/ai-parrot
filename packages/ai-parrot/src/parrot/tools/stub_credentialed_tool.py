"""Stub credentialed tool for FEAT-260 v1 acceptance testing.

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
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import Field

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema


logger = logging.getLogger(__name__)


class _StubCredentialedArgs(AbstractToolArgsSchema):
    """Input schema for :class:`StubCredentialedTool`."""

    message: str = Field(
        default="ping",
        description="Message to echo back in the tool result.",
    )
    metadata: Optional[str] = Field(
        default=None,
        description="Optional metadata string passed through in the result.",
    )


class StubCredentialedTool(AbstractTool):
    """Minimal credentialed echo tool for A2A bridge integration tests.

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
    """

    name = "stub_credentialed"
    description = (
        "Echo tool that requires a per-user stub credential. "
        "Used for A2A credential bridge acceptance testing (FEAT-260)."
    )
    credential_provider: str = "stub"
    args_schema = _StubCredentialedArgs

    async def _execute(self, message: str = "ping", metadata: Optional[str] = None, **kwargs: Any) -> str:
        """Echo the input message as the tool result.

        The resolved credential is injected via ``kwargs`` by the bridge
        when available (the bridge calls ``_execute(**params)`` after
        ``CredentialResolver.resolve()`` succeeds).  We do NOT log or
        return the credential value — only its fingerprint is recorded by
        the :class:`~parrot.security.audit_ledger.AuditLedger`.

        Args:
            message: Text to echo back.
            metadata: Optional metadata string.
            **kwargs: Absorbed; may contain bridge-internal keys.

        Returns:
            A string of the form ``"stub-echo: <message>"`` (optionally
            with metadata appended).
        """
        self.logger.info("StubCredentialedTool._execute: message=%r", message)
        result = f"stub-echo: {message}"
        if metadata:
            result += f" [{metadata}]"
        return result
