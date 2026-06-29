"""Per-user credential resolver for the Microsoft 365 Agents SDK integration.

Provides :class:`BFTokenServiceResolver`, a :class:`CredentialResolver`
subclass that acquires per-user tokens from the Bot Framework Token Service
(part of the Azure Bot infrastructure). The resolver:

1. Maps a tool name to an Azure Bot OAuth connection name (from config).
2. Fetches the current per-user token from the SDK token client.
3. Optionally performs an on-behalf-of (OBO) exchange for Microsoft-cluster
   APIs that need specific scopes.
4. Records a ``key_fingerprint`` (SHA-256 of the first 8 token bytes) to an
   :class:`~parrot.auth.audit.AuditLedger` for compliance.

When the token service has no token for the user (sign-in not yet completed),
:meth:`BFTokenServiceResolver.resolve` raises :class:`CredentialRequired` so
the caller can emit a native OAuthCard sign-in activity.

Raw tokens are never returned in a way that exposes them to the model context
or the conversational transcript.

All ``microsoft_agents.*`` imports are kept **inside methods** (lazy) so this
module can be imported without the SDK installed.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from parrot.auth.credentials import CredentialResolver

if TYPE_CHECKING:
    from parrot.security.audit_ledger import AuditLedger

# ContextVar that holds a (resolver, turn_context) tuple so tools running
# inside _handle_message can reach the resolver without passing it explicitly.
_resolver_var: ContextVar = ContextVar("msagentsdk_resolver", default=None)


class CredentialRequired(Exception):
    """Raised when per-user credentials are needed but not yet authorized.

    The caller should surface an OAuth sign-in card when this exception is
    caught, rather than returning an error to the user.

    Attributes:
        tool: Name of the tool that requires credentials.
        connection_name: Azure Bot OAuth connection name to use for sign-in.
    """

    def __init__(self, tool: str, connection_name: str) -> None:
        """Initialise the exception.

        Args:
            tool: Name of the tool requesting credentials (e.g. ``"o365"``).
            connection_name: Azure Bot OAuth connection name (e.g.
                ``"graph_sso"``).
        """
        self.tool = tool
        self.connection_name = connection_name
        super().__init__(
            f"User authorization required for tool '{tool}' "
            f"(connection: '{connection_name}')"
        )


class BFTokenServiceResolver(CredentialResolver):
    """Resolves per-user tokens from the Bot Framework Token Service.

    Subclasses :class:`~parrot.auth.credentials.CredentialResolver` and adds
    support for the ``turn_context`` keyword argument that is required to
    access the SDK token client.

    The resolver accepts extra keyword arguments on :meth:`resolve` so it can
    coexist with the abstract interface::

        token = await resolver.resolve(
            channel, user_id,
            tool="o365",
            turn_context=turn_context,
        )

    Attributes:
        _connections: Maps tool name → Azure Bot OAuth connection name.
        _obo_scopes: Maps tool name → list of OBO target scopes.
        _ledger: Optional audit ledger.
        logger: Logger scoped to this resolver.
    """

    def __init__(
        self,
        oauth_connections: Dict[str, str],
        obo_scopes: Dict[str, List[str]],
        audit_ledger: Optional["AuditLedger"] = None,
    ) -> None:
        """Initialise the resolver.

        Args:
            oauth_connections: Maps tool name to Azure Bot OAuth connection
                name. Example: ``{"o365": "graph_sso", "jira": "jira_oauth"}``.
            obo_scopes: Maps tool name to list of OBO target scopes for
                Microsoft-cluster APIs. Example:
                ``{"o365": ["https://graph.microsoft.com/.default"]}``.
            audit_ledger: Optional :class:`~parrot.auth.audit.AuditLedger`
                for recording per-invocation credential usage.
        """
        self._connections = oauth_connections
        self._obo_scopes = obo_scopes
        self._ledger = audit_ledger
        self.logger = logging.getLogger(__name__)

    async def resolve(
        self,
        channel: str,
        user_id: str,
        **kwargs: Any,
    ) -> Optional[Any]:
        """Resolve per-user credentials from the Bot Framework Token Service.

        Looks up the OAuth connection name for the requested tool, fetches
        the current user token from the SDK token client, optionally performs
        an OBO exchange, and records a key fingerprint to the audit ledger.

        Args:
            channel: Integration channel identifier (e.g. ``"msagentsdk"``).
            user_id: Canonical user identity (``aad_object_id`` or channel id).
            **kwargs: Recognised optional keyword arguments:

                - ``tool`` (``str``): Name of the tool requesting credentials.
                  Required for connection lookup.
                - ``turn_context``: The current ``TurnContext`` from the MS
                  Agents SDK. Required to access the token service client.

        Returns:
            The resolved token string, or ``None`` if no connection is
            configured for the requested tool.

        Raises:
            :exc:`CredentialRequired`: When the token service has no token for
                the user (sign-in not yet completed). The caller should emit
                an OAuthCard sign-in activity.
        """
        tool: str = kwargs.get("tool", "")
        turn_context = kwargs.get("turn_context")

        connection_name = self._connections.get(tool)
        if not connection_name:
            self.logger.debug(
                "No OAuth connection configured for tool=%s", tool
            )
            return None

        token = await self._fetch_token(turn_context, user_id, connection_name)
        if token is None:
            raise CredentialRequired(tool=tool, connection_name=connection_name)

        # Optional OBO exchange for Microsoft-cluster scopes
        target_token = token
        if tool in self._obo_scopes and self._obo_scopes[tool]:
            target_token = await self._obo_exchange(
                turn_context,
                token,
                self._obo_scopes[tool],
                connection_name,
            )

        # Record audit entry with key fingerprint (never the raw token)
        if self._ledger is not None:
            await self._record_audit(
                channel=channel,
                user_id=user_id,
                tool=tool,
                connection=connection_name,
                token=target_token,
                action="resolve",
            )

        return target_token

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Not supported — the BF Token Service uses OAuthCard sign-in.

        Args:
            channel: Integration channel identifier.
            user_id: Canonical user identity.

        Raises:
            NotImplementedError: Always. Sign-in is initiated by emitting an
                OAuthCard activity, not by redirecting to a URL.
        """
        raise NotImplementedError(
            "BFTokenServiceResolver uses OAuthCard sign-in activities; "
            "URL-based redirect is not supported."
        )

    async def is_connected(self, channel: str, user_id: str) -> bool:
        """Not supported — use resolve() with tool= and turn_context= kwargs.

        Args:
            channel: Integration channel identifier.
            user_id: Canonical user identity.

        Raises:
            NotImplementedError: Always. :meth:`resolve` requires ``tool`` and
                ``turn_context`` keyword arguments that this method signature
                does not carry.
        """
        raise NotImplementedError(
            "BFTokenServiceResolver.is_connected() requires 'tool' and "
            "'turn_context' kwargs — call resolve() directly."
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_token(
        self,
        turn_context: Any,
        user_id: str,
        connection_name: str,
    ) -> Optional[str]:
        """Fetch the per-user token from the Bot Framework Token Service.

        Tries ``UserTokenClient`` (available in newer SDK versions) first,
        then falls back to ``adapter.get_user_token``.

        Args:
            turn_context: The current SDK ``TurnContext``.
            user_id: Canonical user identity.
            connection_name: Azure Bot OAuth connection name.

        Returns:
            The token string, or ``None`` when unavailable.
        """
        if turn_context is None:
            self.logger.warning(
                "No turn_context — cannot fetch token for connection=%s",
                connection_name,
            )
            return None

        try:
            # Newer SDK: use UserTokenClient from turn_state
            token_client = None
            turn_state = getattr(turn_context, "turn_state", None)
            if turn_state is not None:
                try:
                    from microsoft_agents.hosting.core import UserTokenClient

                    token_client = turn_state.get(UserTokenClient)
                except (ImportError, AttributeError, KeyError):
                    pass

            if token_client is not None:
                channel_id = getattr(
                    getattr(turn_context, "activity", None), "channel_id", "msteams"
                )
                result = await token_client.get_user_token(
                    user_id,
                    connection_name,
                    channel_id,
                    None,  # magic_code — only needed for verifyState flow
                )
            elif hasattr(turn_context, "adapter") and hasattr(
                turn_context.adapter, "get_user_token"
            ):
                # Older / alternative SDK path
                result = await turn_context.adapter.get_user_token(
                    turn_context, connection_name, None
                )
            else:
                self.logger.warning(
                    "Cannot fetch token: no UserTokenClient or "
                    "adapter.get_user_token available"
                )
                return None

            if result is not None:
                token = getattr(result, "token", None)
                if token:
                    return token
            return None

        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Token fetch failed for connection=%s: %s", connection_name, exc
            )
            return None

    async def _obo_exchange(
        self,
        turn_context: Any,
        token: str,
        scopes: List[str],
        connection_name: str,
    ) -> str:
        """Perform an on-behalf-of token exchange (best-effort).

        The OBO exchange allows one Entra sign-in to serve multiple tools with
        different scopes (e.g. ``o365`` and ``work-iq`` both using
        ``graph_sso`` but targeting different Graph scopes).

        In the MS Agents SDK for Python (v0.9), the OBO exchange is typically
        handled transparently by the token service when the Azure Bot OAuth
        connection is configured with the correct OBO policy. If the exchange
        fails, the original token is returned (graceful degradation).

        Args:
            turn_context: The current SDK ``TurnContext``.
            token: The initial user token to exchange.
            scopes: Target OBO scopes.
            connection_name: OAuth connection name (for logging).

        Returns:
            The OBO-exchanged token, or the original token on failure.
        """
        # OQ#4 from spec: the exact Python SDK API for OBO exchange is
        # unresolved. The token service may handle OBO internally via the
        # Azure Bot OAuth connection configuration. Return original token
        # until the SDK API is verified.
        if self._obo_scopes:
            self.logger.warning(
                "OBO exchange is not yet implemented — returning original token for "
                "connection=%s scopes=%s. Operator action required: OBO via SDK not verified.",
                connection_name,
                scopes,
            )
        else:
            self.logger.debug(
                "OBO exchange skipped (no scopes configured) for connection=%s",
                connection_name,
            )
        return token

    async def _record_audit(
        self,
        channel: str,
        user_id: str,
        tool: str,
        connection: str,
        token: str,
        action: str,
    ) -> None:
        """Record a credential invocation to the canonical audit ledger.

        Delegates to :meth:`parrot.security.audit_ledger.AuditLedger.append`
        which computes the ``key_fingerprint`` internally (SHA-256 of the
        credential material).  The raw token is never stored.

        Args:
            channel: Integration channel.
            user_id: Canonical user identity.
            tool: Tool name.
            connection: OAuth connection name (used as ``provider`` label).
            token: The resolved token (used only to derive the fingerprint).
            action: ``"resolve"`` or ``"obo_exchange"`` (appended to tool label).
        """
        await self._ledger.append(
            user_id=user_id,
            channel=channel,
            tool=f"{tool}:{action}",
            provider=connection,
            credential_material=token,
        )
