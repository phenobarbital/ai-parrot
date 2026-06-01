"""Grant subsystem for bounded approval windows (FEAT-211).

This module implements the tool-grant lifecycle:
  request → review → grant → observe → revoke

Key types:
  - Grant: Pydantic record for an approved action window.
  - GrantConfig: Configurable defaults (window duration, timeout, channel).
  - GrantStore: Abstract interface for grant persistence.
  - InMemoryGrantStore: Dict-backed store with TTL expiry and periodic cleanup.
  - GuardDecision: Result returned by GrantGuard.authorize().
  - GrantGuard: The Governor — decides allow / approve / deny for a tool call.

Design notes:
  - Grants are **in-memory only** and lost on restart. Persistence via the
    event ledger (FEAT-212) is a planned future enhancement.
  - Tools called directly via AbstractTool.execute() without going through
    ToolManager are NOT gated. The agent loop always uses ToolManager.
  - The guard is **fail-closed**: requires_grant + no active grant + no HITL
    channel → deny immediately.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext
    from parrot.human.manager import HumanInteractionManager
    from parrot.tools.abstract import AbstractTool


# ── Data Models ───────────────────────────────────────────────────────────────


class Grant(BaseModel):
    """A bounded-window approval record.

    A Grant is created when a human approves a tool call via HITL. It allows
    the same (owner, scope) combination to execute without re-asking until the
    window expires or the grant is explicitly revoked.

    Attributes:
        grant_id: Unique identifier for this grant (auto-generated UUID).
        owner_id: The actor who was granted permission (user_id or agent_id).
        scope: The permission scope, e.g. ``"tool:pulumi_apply"`` or ``"tool:*"``.
        granted_by: Identifier of the human respondent who approved.
        created_at: UTC timestamp when the grant was created.
        expires_at: UTC timestamp when the grant window closes.
        revoked: Whether the grant has been explicitly revoked before expiry.
    """

    grant_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    scope: str
    granted_by: str
    created_at: datetime
    expires_at: datetime
    revoked: bool = False

    def is_active(self, now: Optional[datetime] = None) -> bool:
        """Return True if the grant is still within its window and not revoked.

        Args:
            now: Point in time to evaluate against. Defaults to UTC now.

        Returns:
            True if the grant is active (not revoked, not expired).
        """
        if now is None:
            now = datetime.now(timezone.utc)
        return (not self.revoked) and (now < self.expires_at)

    def covers(self, scope: str) -> bool:
        """Return True if this grant covers the requested scope.

        Supports exact match and the wildcard scope ``"tool:*"``.

        Args:
            scope: The scope to check, e.g. ``"tool:pulumi_apply"``.

        Returns:
            True if this grant covers the requested scope.
        """
        return self.scope == scope or self.scope == "tool:*"


class GrantConfig(BaseModel):
    """Configurable defaults for the grant subsystem.

    Attributes:
        window_seconds: Default approval window in seconds (default 15 min).
        approval_timeout: Seconds to wait for a human response before
            timing out and failing closed (default 120 s).
        default_channel: HITL channel to use for approval requests
            (default ``"telegram"``).
    """

    window_seconds: int = Field(900, gt=0)
    approval_timeout: float = Field(120.0, gt=0)
    default_channel: str = "telegram"


# ── GrantStore ABC ─────────────────────────────────────────────────────────────


class GrantStore(ABC):
    """Abstract interface for grant persistence.

    Implementations must be thread-safe and support concurrent async access.
    The in-memory implementation uses asyncio.Lock; a Redis backend can use
    atomic operations.
    """

    @abstractmethod
    async def grant(
        self,
        owner_id: str,
        scope: str,
        *,
        granted_by: str,
        window_seconds: int,
    ) -> Grant:
        """Create and store a new grant.

        Args:
            owner_id: The actor receiving the grant.
            scope: The permission scope being granted.
            granted_by: Identifier of the approving human.
            window_seconds: Duration of the approval window in seconds.

        Returns:
            The newly created Grant.
        """
        ...

    @abstractmethod
    async def is_allowed(self, owner_id: str, scope: str) -> bool:
        """Check whether there is an active grant covering (owner, scope).

        Args:
            owner_id: The actor whose grants to check.
            scope: The requested scope.

        Returns:
            True if an active, non-revoked, non-expired grant covers the scope.
        """
        ...

    @abstractmethod
    async def revoke(self, grant_id: str) -> bool:
        """Revoke a grant immediately.

        Args:
            grant_id: The unique identifier of the grant to revoke.

        Returns:
            True if the grant was found and revoked; False if not found.
        """
        ...

    @abstractmethod
    async def list_active(self, owner_id: str) -> list[Grant]:
        """List all active (non-expired, non-revoked) grants for an owner.

        Args:
            owner_id: The actor whose active grants to list.

        Returns:
            List of active Grant objects.
        """
        ...


# ── InMemoryGrantStore ─────────────────────────────────────────────────────────


class InMemoryGrantStore(GrantStore):
    """Dict-backed grant store with TTL expiry and periodic cleanup.

    All mutations are protected by an asyncio.Lock to prevent TOCTOU races
    under concurrent tool calls.

    Note:
        Grants are lost on process restart. Persistence is a future concern
        tied to the event ledger (FEAT-212).

    Note:
        ``cleanup()`` removes stale grants but has no built-in scheduler.
        Callers are responsible for invoking it periodically (e.g. on a
        background task or before long-running operations) to bound memory
        growth. A future Redis-backed store will use TTL natively and not
        require explicit cleanup.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory grant store."""
        self._grants: dict[str, Grant] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def grant(
        self,
        owner_id: str,
        scope: str,
        *,
        granted_by: str,
        window_seconds: int,
    ) -> Grant:
        """Create and store a new grant with a fixed expiry window.

        Args:
            owner_id: The actor receiving the grant.
            scope: The permission scope being granted.
            granted_by: Identifier of the approving human.
            window_seconds: Duration of the approval window in seconds.

        Returns:
            The newly created Grant.
        """
        now = datetime.now(timezone.utc)
        new_grant = Grant(
            owner_id=owner_id,
            scope=scope,
            granted_by=granted_by,
            created_at=now,
            expires_at=now + timedelta(seconds=window_seconds),
        )
        async with self._lock:
            self._grants[new_grant.grant_id] = new_grant
            self.logger.debug(
                "Grant created: id=%s owner=%s scope=%s expires=%s",
                new_grant.grant_id,
                owner_id,
                scope,
                new_grant.expires_at.isoformat(),
            )
        return new_grant

    async def is_allowed(self, owner_id: str, scope: str) -> bool:
        """Check whether there is an active grant covering (owner, scope).

        Args:
            owner_id: The actor whose grants to check.
            scope: The requested scope.

        Returns:
            True if at least one active grant covers the scope.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            for g in self._grants.values():
                if g.owner_id == owner_id and g.is_active(now) and g.covers(scope):
                    return True
        return False

    async def revoke(self, grant_id: str) -> bool:
        """Revoke a grant immediately by marking it revoked.

        Args:
            grant_id: The unique identifier of the grant to revoke.

        Returns:
            True if found and revoked; False if not found.
        """
        async with self._lock:
            if grant_id not in self._grants:
                return False
            # Pydantic models are immutable; replace with revoked copy
            g = self._grants[grant_id]
            self._grants[grant_id] = g.model_copy(update={"revoked": True})
            self.logger.debug("Grant revoked: id=%s", grant_id)
        return True

    async def list_active(self, owner_id: str) -> list[Grant]:
        """List all active grants for an owner.

        Args:
            owner_id: The actor whose active grants to list.

        Returns:
            List of active (non-expired, non-revoked) Grant objects.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            return [
                g
                for g in self._grants.values()
                if g.owner_id == owner_id and g.is_active(now)
            ]

    async def cleanup(self) -> int:
        """Remove expired and revoked grants from memory.

        Returns:
            Number of grants removed.
        """
        now = datetime.now(timezone.utc)
        async with self._lock:
            to_remove = [
                gid for gid, g in self._grants.items() if not g.is_active(now)
            ]
            for gid in to_remove:
                del self._grants[gid]
            if to_remove:
                self.logger.debug("Grant cleanup: removed %d stale grants", len(to_remove))
        return len(to_remove)


# ── GuardDecision ──────────────────────────────────────────────────────────────


class GuardDecision(BaseModel):
    """Result of GrantGuard.authorize().

    Attributes:
        allowed: Whether the tool call is permitted.
        reason: Human-readable explanation of the decision.
        grant: The Grant that authorized this call (None if not allowed or
            if the tool did not require a grant).
    """

    allowed: bool
    reason: str
    grant: Optional[Grant] = None


# ── GrantGuard (the Governor) ──────────────────────────────────────────────────


class GrantGuard:
    """The Governor: decides allow / approve / deny for a tool call.

    Integrates with ToolManager via ``set_grant_guard()`` (FEAT-211, TASK-1405).
    The guard is invoked inside ``execute_tool()`` **before** the dispatch to
    ``AbstractTool.execute()``.

    Decision logic:
      1. Tool has no ``requires_grant`` meta → allow immediately.
      2. Active grant covers (owner, scope) → allow.
      3. No grant + human_manager present → request HITL approval.
         - Approved → create bounded window grant → allow.
         - Rejected / timeout → deny (fail-closed).
      4. No grant + no human_manager → deny (fail-closed).

    Args:
        store: The GrantStore to consult and write to.
        human_manager: Optional HITL manager for approval requests.
            If None, the guard operates in fail-closed mode.
        config: Optional configuration overrides.
    """

    def __init__(
        self,
        store: GrantStore,
        human_manager: Optional["HumanInteractionManager"] = None,
        config: Optional[GrantConfig] = None,
    ) -> None:
        """Initialize the GrantGuard.

        Args:
            store: The GrantStore implementation to use.
            human_manager: Optional HumanInteractionManager for HITL approval.
            config: Optional GrantConfig overrides (uses defaults if None).
        """
        self.store = store
        self.human_manager = human_manager
        self.config = config or GrantConfig()
        self.logger = logging.getLogger(__name__)

    async def authorize(
        self,
        *,
        tool: "AbstractTool",
        parameters: dict,
        permission_context: Optional["PermissionContext"] = None,
    ) -> GuardDecision:
        """Decide whether a tool call is allowed.

        Args:
            tool: The tool being called. Must have a ``routing_meta`` dict.
            parameters: The parameters being passed to the tool (reserved for
                future scope parameterization).
            permission_context: The caller's permission context. Provides
                ``user_id`` for grant ownership. Uses ``"anonymous"`` if None.

        Returns:
            A GuardDecision indicating whether the call is allowed.
        """
        # 1. Non-gated tool → allow immediately (no grant needed)
        if not tool.routing_meta.get("requires_grant"):
            return GuardDecision(allowed=True, reason="tool does not require a grant")

        # 2. Resolve scope and owner
        scope: str = tool.routing_meta.get("grant_scope", f"tool:{tool.name}")
        owner: str = permission_context.user_id if permission_context else "anonymous"

        self.logger.debug(
            "Grant check: owner=%s scope=%s tool=%s", owner, scope, tool.name
        )

        # 3. Check existing grant
        if await self.store.is_allowed(owner, scope):
            self.logger.debug("Grant allowed (active grant): owner=%s scope=%s", owner, scope)
            return GuardDecision(allowed=True, reason="active grant covers scope")

        # 4. No active grant — try HITL approval or fail-closed
        if self.human_manager is None:
            self.logger.info(
                "Grant denied (fail-closed, no HITL channel): owner=%s scope=%s",
                owner,
                scope,
            )
            return GuardDecision(
                allowed=False,
                reason="no active grant and no approval channel (fail-closed)",
            )

        # 5. Request HITL approval
        return await self._request_approval(tool, owner, scope, permission_context)

    async def _request_approval(
        self,
        tool: "AbstractTool",
        owner: str,
        scope: str,
        permission_context: Optional["PermissionContext"],
    ) -> GuardDecision:
        """Request human approval and create a grant on success.

        Args:
            tool: The tool awaiting approval.
            owner: The owner_id for the grant.
            scope: The scope being requested.
            permission_context: The caller's permission context (provides channel).

        Returns:
            GuardDecision reflecting the human's decision.
        """
        # Import here to avoid circular imports at module level
        from parrot.human.models import HumanInteraction, InteractionType, Severity

        # Determine HITL channel (prefer context channel, fall back to config)
        channel = (
            permission_context.channel
            if (permission_context and getattr(permission_context, "channel", None))
            else self.config.default_channel
        )

        # Determine window duration (routing_meta override takes precedence).
        # Clamp to at least 1 second: a zero/negative value from routing_meta
        # would produce an already-expired grant, silently defeating the approval.
        raw_window = tool.routing_meta.get("grant_window_seconds", self.config.window_seconds)
        try:
            window_seconds: int = max(1, int(raw_window))
        except (TypeError, ValueError):
            self.logger.warning(
                "Invalid grant_window_seconds %r in routing_meta for tool %r; "
                "falling back to config default (%ds)",
                raw_window,
                tool.name,
                self.config.window_seconds,
            )
            window_seconds = self.config.window_seconds

        window_display = f"{window_seconds / 60:.1f} min"
        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL,
            question=(
                f"⚠️ Tool '{tool.name}' requires approval.\n"
                f"Scope: {scope}\n"
                f"Owner: {owner}\n"
                f"Approval window: {window_display}\n\n"
                "Do you approve this action?"
            ),
            timeout=self.config.approval_timeout,
            default_response=False,  # fail-closed on timeout
            severity=Severity.HIGH,
        )

        self.logger.info(
            "Requesting HITL approval: owner=%s scope=%s tool=%s channel=%s",
            owner,
            scope,
            tool.name,
            channel,
        )

        try:
            result = await self.human_manager.request_human_input(  # type: ignore[union-attr]
                interaction, channel=channel
            )
        except Exception as exc:
            self.logger.warning(
                "HITL approval request failed: %s — denying (fail-closed)", exc
            )
            return GuardDecision(
                allowed=False,
                reason=f"HITL approval request failed: {exc} (fail-closed)",
            )

        # consolidated_value is bool for APPROVAL type
        approved: bool = bool(result.consolidated_value)

        if approved:
            # InteractionResult carries no human-respondent identifier beyond
            # the interaction UUID, so we use it as the granted_by token.
            # This keeps the grant record traceable back to the HITL event.
            new_grant = await self.store.grant(
                owner,
                scope,
                granted_by=str(result.interaction_id),
                window_seconds=window_seconds,
            )
            self.logger.info(
                "Grant approved: owner=%s scope=%s window=%ds grant_id=%s",
                owner,
                scope,
                window_seconds,
                new_grant.grant_id,
            )
            return GuardDecision(
                allowed=True,
                reason="HITL approval granted",
                grant=new_grant,
            )
        else:
            self.logger.info(
                "Grant denied (HITL rejected): owner=%s scope=%s", owner, scope
            )
            return GuardDecision(
                allowed=False,
                reason="HITL approval rejected",
            )
