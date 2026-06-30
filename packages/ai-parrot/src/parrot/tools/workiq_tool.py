"""Work IQ MCP credential adapter tool for the A2A per-user credential bridge.

OQ#5 resolved (2026-06-27 — FEAT-263 / TASK-1649):
Work IQ (``github.com/microsoft/work-iq``) is an **MCP server**, not a native
toolkit.  Auth: Entra On-Behalf-Of (OBO), scope
``api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask``.  Admin consent required.
App-only access is NOT supported.

This module contains :class:`WorkIQTool`, which acts as a credential adapter:
- Declares ``credential_provider = "workiq"`` so the A2A bridge routes through
  :class:`~parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver`.
- After the bridge resolves the per-user OBO token, the tool proxies the query
  to the Work IQ MCP server.

Work IQ enforces M365 permissions, sensitivity labels, and compliance policies
automatically — no additional filtering is required on this adapter side.

Usage::

    from parrot.tools.workiq_tool import WorkIQTool
    from parrot.auth.oauth2.workiq_provider import WorkIQOAuth2Provider

    tool = WorkIQTool()
    provider = WorkIQOAuth2Provider(
        o365_interface=o365,
        o365_oauth_manager=o365_manager,
        vault_token_sync=vault,
    )
    a2a_server.wire_workiq_resolver(provider.credential_resolver())
    # agent.tools = [tool]
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import Field

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema

logger = logging.getLogger(__name__)


class _WorkIQArgs(AbstractToolArgsSchema):
    """Input schema for :class:`WorkIQTool`."""

    query: str = Field(
        ...,
        description=(
            "The question or task to send to Work IQ (Microsoft enterprise "
            "assistant powered by M365 data)."
        ),
    )
    context: Optional[str] = Field(
        default=None,
        description="Optional conversation context or additional instructions.",
    )


class WorkIQTool(AbstractTool):
    """Work IQ MCP credential adapter — queries the Work IQ MCP server via OBO auth.

    Work IQ (``github.com/microsoft/work-iq``) is a Microsoft enterprise
    assistant delivered as an MCP server.  It answers natural-language queries
    about enterprise M365 data (Teams, SharePoint, email, calendar) while
    applying the user's M365 permissions, sensitivity labels, and compliance
    policies automatically.

    This tool is a **credential adapter**: it declares the OBO credential
    requirement (``credential_provider = "workiq"``) so the A2A bridge
    (FEAT-263 / TASK-1644) resolves the delegated Entra OBO token via
    :class:`~parrot.auth.oauth2.workiq_provider.WorkIQOBOCredentialResolver`
    before invocation.  After credential resolution, the tool proxies the query
    to the Work IQ MCP server endpoint.

    Attributes:
        name: ``"workiq_ask"`` — stable identifier used in A2A ``"tool"``
            payloads.
        credential_provider: ``"workiq"`` — signals OBO-gated resolver.
        args_schema: :class:`_WorkIQArgs` Pydantic v2 model.
        mcp_server_url: Work IQ MCP server endpoint (configurable per
            deployment; default: ``"https://workiq.svc.cloud.microsoft/mcp"``).
    """

    name = "workiq_ask"
    description = (
        "Query Work IQ (Microsoft enterprise assistant) about M365 data "
        "(Teams, SharePoint, email, calendar) using your delegated Entra access. "
        "Work IQ enforces M365 permissions, sensitivity labels, and compliance "
        "policies automatically.  Requires Entra sign-in with admin consent "
        "(WorkIQAgent.Ask delegated permission)."
    )
    credential_provider: str = "workiq"
    args_schema = _WorkIQArgs

    def __init__(
        self,
        mcp_server_url: str = "https://workiq.svc.cloud.microsoft/mcp",
        **kwargs: Any,
    ) -> None:
        """Initialise the Work IQ credential adapter.

        Args:
            mcp_server_url: URL of the Work IQ MCP server endpoint.  Override
                at deployment time if the tenant uses a custom endpoint.
            **kwargs: Forwarded to :class:`~parrot.tools.abstract.AbstractTool`.
        """
        super().__init__(**kwargs)
        self.mcp_server_url = mcp_server_url

    async def _execute(
        self,
        query: str = "",
        context: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Proxy the query to the Work IQ MCP server using the OBO token.

        The OBO access token is resolved by the A2A bridge before this method
        is called; the resolved credential is available in ``kwargs`` but is
        NOT logged or included in the output — only its fingerprint is recorded
        by the :class:`~parrot.security.audit_ledger.AuditLedger`.

        Operators should replace the stub body with the real MCP client call,
        for example::

            obo_token = kwargs.get("credential") or kwargs.get("access_token")
            result = await mcp_client.call_tool(
                "ask", {"query": query}, token=obo_token
            )

        Args:
            query: The question or task to send to Work IQ.
            context: Optional conversation context or additional instructions.
            **kwargs: Absorbed; may contain bridge-internal keys (e.g.
                ``credential``, ``user_id``).

        Returns:
            The Work IQ MCP server response as a string.
        """
        self.logger.info(
            "WorkIQTool._execute: query=%r mcp_url=%s", query, self.mcp_server_url
        )

        # NOTE: The MCP transport layer is wired by the operator at deployment.
        # The A2A bridge resolves the OBO token via WorkIQOBOCredentialResolver
        # and passes it in kwargs; the actual MCP call is out of scope here.
        # Replace this stub with the real MCP client when deploying:
        #
        #   token = kwargs.get("credential")
        #   async with aiohttp.ClientSession() as session:
        #       async with session.post(
        #           f"{self.mcp_server_url}/tools/ask",
        #           json={"query": query},
        #           headers={"Authorization": f"Bearer {token}"},
        #       ) as resp:
        #           return (await resp.json())["result"]

        result = f"Work IQ (via MCP): query received — {query!r}"
        if context:
            result += f" [context: {context!r}]"
        return result
