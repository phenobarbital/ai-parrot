"""Confirmation subsystem for per-call HITL tool-call review (FEAT-235).

This module implements the confirm-before-execute lifecycle:
  routing_meta gate → window check → briefing render → HITL ask → result mapping

Key types:
  - ConfirmationConfig: Configurable defaults (window, timeout, channel, retries).
  - ConfirmationDecision: Result returned by ConfirmationGuard.confirm().
  - ConfirmationWindowStore: Abstract window persistence (keyed by owner/tool/args).
  - InMemoryConfirmationWindowStore: asyncio.Lock-guarded dict with TTL expiry.
  - ConfirmationGuard: The Governor — asks HITL before each confirmed tool call.
  - compute_args_hash: Stable hash over normalized parameters for window keying.

Design notes:
  - Structurally mirrors ``parrot/auth/grants.py`` (GrantGuard) so the two guards
    stay symmetric and wiring patterns are identical.
  - Fail-closed: ``requires_confirmation`` + no HITL channel → cancelled immediately.
  - Dispatch order in ToolManager: grant → confirm (authorization before review).
  - ``window_seconds=0`` (default) means always re-ask — the safe default.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Type

from pydantic import BaseModel, Field, ValidationError

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext
    from parrot.human.manager import HumanInteractionManager
    from parrot.human.models import WaitStrategy
    from parrot.tools.abstract import AbstractTool

from parrot.tools.abstract import AbstractToolArgsSchema


# ── Helpers ───────────────────────────────────────────────────────────────────


def compute_args_hash(parameters: dict) -> str:
    """Produce a stable SHA-256 hash over normalized parameters.

    The hash is deterministic across runs: keys are sorted and values are
    serialized with ``json.dumps(..., sort_keys=True, default=str)`` to handle
    non-JSON-serialisable values gracefully.

    Args:
        parameters: Tool call parameters to hash.

    Returns:
        Hex-encoded SHA-256 digest of the canonical parameter serialization.
    """
    canonical = json.dumps(parameters, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


# ── Data Models ───────────────────────────────────────────────────────────────


class ConfirmationConfig(BaseModel):
    """Configurable defaults for the confirmation subsystem.

    Mirrors :class:`GrantConfig` (grants.py:95).

    Attributes:
        window_seconds: Default approval window in seconds.
            ``0`` (default) means "always re-ask" — the safe, per-call default.
        approval_timeout: Seconds to wait for a human response before
            timing out and failing closed (default 120 s).
        default_channel: HITL channel to use when the permission context
            does not specify one (default ``"telegram"``).
        max_edit_retries: Maximum number of times the guard re-asks after
            invalid edited values before auto-cancelling (default 1).
    """

    window_seconds: int = Field(0, ge=0)
    approval_timeout: float = Field(120.0, gt=0)
    default_channel: str = "telegram"
    max_edit_retries: int = Field(1, ge=0)


class ConfirmationDecision(BaseModel):
    """Result of ConfirmationGuard.confirm().

    Mirrors :class:`GuardDecision` (grants.py:320).

    Attributes:
        allowed: Whether the tool call is permitted to proceed.
        status: Outcome token — one of ``confirmed``, ``cancelled``,
            ``timeout``, ``not_required``.
        reason: Human-readable explanation of the decision.
        parameters: (Possibly edited and re-validated) parameters to pass to
            ``tool.execute()``. ``None`` means use the original parameters.
    """

    allowed: bool
    status: Literal["confirmed", "cancelled", "timeout", "not_required"] = "confirmed"
    reason: str
    parameters: Optional[Dict[str, Any]] = None


# ── ConfirmationWindowStore ABC ───────────────────────────────────────────────


class ConfirmationWindowStore(ABC):
    """Abstract window persistence for the confirmation subsystem.

    Mirrors :class:`GrantStore` (grants.py:114).

    Key = (owner_id, tool_name, args_hash).  Implementations must be
    thread-safe and support concurrent async access.
    """

    @abstractmethod
    async def is_confirmed(
        self,
        owner_id: str,
        tool_name: str,
        args_hash: str,
    ) -> bool:
        """Return True if a non-expired confirmation window covers this call.

        Args:
            owner_id: The actor who confirmed the tool call.
            tool_name: Name of the tool.
            args_hash: Stable hash of the call parameters.

        Returns:
            True if a live window exists; False otherwise.
        """
        ...

    @abstractmethod
    async def record(
        self,
        owner_id: str,
        tool_name: str,
        args_hash: str,
        *,
        window_seconds: int,
    ) -> None:
        """Record a confirmed call in the window store.

        When ``window_seconds == 0`` the implementation MUST store nothing
        so that subsequent ``is_confirmed`` calls always return False (always
        re-ask behaviour).

        Args:
            owner_id: The actor who confirmed the tool call.
            tool_name: Name of the tool.
            args_hash: Stable hash of the call parameters.
            window_seconds: Duration of the window in seconds.  ``0`` means
                do not store.
        """
        ...


# ── InMemoryConfirmationWindowStore ──────────────────────────────────────────


class InMemoryConfirmationWindowStore(ConfirmationWindowStore):
    """asyncio.Lock-guarded dict-backed window store with TTL expiry.

    All mutations are protected by an :class:`asyncio.Lock` to prevent
    TOCTOU races under concurrent tool calls.  Mirrors
    :class:`InMemoryGrantStore` (grants.py:185).

    Note:
        Windows are lost on process restart.  A Redis backend may follow
        (mirroring a future ``RedisGrantStore``).
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory window store."""
        # Maps (owner_id, tool_name, args_hash) → expiry UTC timestamp (float)
        self._windows: Dict[tuple, float] = {}
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def is_confirmed(
        self,
        owner_id: str,
        tool_name: str,
        args_hash: str,
    ) -> bool:
        """Return True only if a non-expired window exists for this call.

        Args:
            owner_id: The actor who confirmed the tool call.
            tool_name: Name of the tool.
            args_hash: Stable hash of the call parameters.

        Returns:
            True if an active (non-expired) window covers the key.
        """
        key = (owner_id, tool_name, args_hash)
        now = datetime.now(timezone.utc).timestamp()
        async with self._lock:
            expiry = self._windows.get(key)
            if expiry is None:
                return False
            if now >= expiry:
                # Expired — clean up lazily
                del self._windows[key]
                self.logger.debug(
                    "Confirmation window expired: owner=%s tool=%s", owner_id, tool_name
                )
                return False
            return True

    async def record(
        self,
        owner_id: str,
        tool_name: str,
        args_hash: str,
        *,
        window_seconds: int,
    ) -> None:
        """Record a confirmed call; noop when ``window_seconds == 0``.

        Args:
            owner_id: The actor who confirmed the tool call.
            tool_name: Name of the tool.
            args_hash: Stable hash of the call parameters.
            window_seconds: Window duration.  ``0`` means do not store.
        """
        if window_seconds <= 0:
            # Default per-call behaviour — never cache
            return
        key = (owner_id, tool_name, args_hash)
        expiry = datetime.now(timezone.utc).timestamp() + window_seconds
        async with self._lock:
            self._windows[key] = expiry
            self.logger.debug(
                "Confirmation window recorded: owner=%s tool=%s window=%ds",
                owner_id,
                tool_name,
                window_seconds,
            )


# ── Briefing Helpers ──────────────────────────────────────────────────────────


def render_briefing(tool: "AbstractTool", parameters: dict) -> str:
    """Render a confirmation briefing string for the tool call.

    Tries to format ``tool.routing_meta.get("confirm_template")`` against a
    context dict ``{tool, params, **parameters}`` using safe string
    formatting.  Falls back to a raw ``"<tool.name> with: k=v, …"``
    listing on any template error (missing key, bad format, etc.).

    Never uses ``eval`` or ``format_map`` with untrusted attribute access.

    Args:
        tool: The tool being confirmed.
        parameters: The call parameters.

    Returns:
        A human-readable briefing string.
    """
    logger = logging.getLogger(__name__)
    template: Optional[str] = (tool.routing_meta or {}).get("confirm_template")

    if template:
        param_str = ", ".join(f"{k}={v!r}" for k, v in parameters.items())
        ctx = {"tool": tool.name, "params": param_str, **parameters}
        try:
            return template.format(**ctx)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "confirm_template formatting failed for tool %r (%s); "
                "falling back to raw listing",
                tool.name,
                exc,
            )

    # Raw fallback listing
    if parameters:
        pairs = ", ".join(f"{k}={v!r}" for k, v in parameters.items())
        return f"{tool.name} with: {pairs}"
    return f"{tool.name} (no parameters)"


def build_form_schema(tool: "AbstractTool", parameters: dict) -> dict:
    """Build a FORM interaction schema from the tool's args_schema.

    Derives a ``form_schema`` dict for a ``HumanInteraction(type=FORM)``
    interaction, pre-filled with the current ``parameters`` so the human
    sees the intended values and can edit them.

    The produced schema passes the ``HumanInteraction`` model_validator
    (non-empty dict requirement).

    Args:
        tool: The tool being confirmed.
        parameters: Current call parameters (used as default values).

    Returns:
        A non-empty form_schema dict suitable for ``HumanInteraction.form_schema``.
    """
    schema: dict = {"fields": {}, "current_values": parameters}

    args_schema: Optional[Type] = getattr(tool, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_fields"):
        # Pydantic v2: model_fields is a dict of field_name → FieldInfo
        for field_name, field_info in args_schema.model_fields.items():
            if field_name.startswith("_"):
                continue
            field_def: dict = {
                "type": "string",  # safe default
                "title": field_name,
            }
            if field_info.description:
                field_def["description"] = field_info.description
            if field_name in parameters:
                field_def["default"] = parameters[field_name]
            schema["fields"][field_name] = field_def
    elif args_schema is not None and hasattr(args_schema, "schema"):
        # Fallback: use JSON schema
        try:
            json_schema = args_schema.schema()
            props = json_schema.get("properties", {})
            for field_name, prop in props.items():
                field_def = dict(prop)
                if field_name in parameters:
                    field_def["default"] = parameters[field_name]
                schema["fields"][field_name] = field_def
        except Exception as exc:
            logging.getLogger(__name__).debug(
                "JSON schema extraction failed for tool %r: %s", tool.name, exc
            )

    if not schema["fields"] and parameters:
        # Last resort: plain key listing so form_schema is non-empty
        for k, v in parameters.items():
            schema["fields"][k] = {"type": "string", "default": v}

    if not schema:
        # Guarantee non-empty for model_validator
        schema["_placeholder"] = True

    return schema


def revalidate_edit(tool: "AbstractTool", edited: dict) -> dict:
    """Validate edited values against the tool's args_schema.

    Args:
        tool: The tool being confirmed (provides ``args_schema``).
        edited: The edited parameter dict returned by the human.

    Returns:
        Validated (and possibly coerced) parameter dict.

    Raises:
        ValidationError: If the edited values do not pass schema validation.
    """
    args_schema: Optional[Type] = getattr(tool, "args_schema", None)
    if args_schema is None or args_schema is AbstractToolArgsSchema:
        # No schema to validate against — pass through
        return edited

    # Pydantic v2 model validation
    validated = args_schema.model_validate(edited)
    return validated.model_dump(exclude_unset=False)


# ── ConfirmationGuard ─────────────────────────────────────────────────────────


class ConfirmationGuard:
    """The Governor: asks a human to confirm each marked tool call.

    Mirrors :class:`GrantGuard` (grants.py:338) in structure.  Wired into
    ``ToolManager`` via ``set_confirmation_guard()`` and invoked in
    ``execute_tool()`` **after** the grant check and **before**
    ``tool.execute()``.

    Lifecycle for each call:
      1. Non-confirmation tool → allow immediately (``not_required``).
      2. Within ``confirm_window_seconds`` for same args_hash → allow (window hit).
      3. No ``human_manager`` → deny (fail-closed, ``cancelled``).
      4. Build briefing → ask HITL (APPROVAL or FORM × BLOCK or SUSPEND).
      5. Map result → decision (confirm/cancel/timeout).

    Args:
        store: Window store to consult and write confirmed calls.
        human_manager: Optional HITL manager.  ``None`` → fail-closed mode.
        config: Optional configuration overrides (uses defaults if None).
    """

    def __init__(
        self,
        store: ConfirmationWindowStore,
        human_manager: Optional["HumanInteractionManager"] = None,
        config: Optional[ConfirmationConfig] = None,
    ) -> None:
        """Initialize the ConfirmationGuard.

        Args:
            store: The ConfirmationWindowStore implementation to use.
            human_manager: Optional HumanInteractionManager for HITL asks.
            config: Optional ConfirmationConfig overrides.
        """
        self.store = store
        self.human_manager = human_manager
        self.config = config or ConfirmationConfig()
        self.logger = logging.getLogger(__name__)

    async def confirm(
        self,
        *,
        tool: "AbstractTool",
        parameters: dict,
        permission_context: Optional["PermissionContext"] = None,
    ) -> ConfirmationDecision:
        """Decide whether this specific tool call may proceed.

        Args:
            tool: The tool being called.  Must have a ``routing_meta`` dict.
            parameters: The parameters for this call.
            permission_context: Caller's permission context.  Provides
                ``user_id`` for window keying.  Uses ``"anonymous"`` if None.

        Returns:
            A :class:`ConfirmationDecision` indicating whether the call is allowed.
        """
        # 1. Non-confirmation tool → allow immediately
        if not (tool.routing_meta or {}).get("requires_confirmation"):
            return ConfirmationDecision(
                allowed=True,
                status="not_required",
                reason="tool does not require confirmation",
                parameters=parameters,
            )

        # 2. Resolve owner and args_hash; check window
        owner: str = (
            permission_context.user_id if permission_context else "anonymous"
        )
        args_hash = compute_args_hash(parameters)
        raw_window = (tool.routing_meta or {}).get(
            "confirm_window_seconds", self.config.window_seconds
        )
        try:
            window_seconds: int = max(0, int(raw_window))
        except (TypeError, ValueError):
            self.logger.warning(
                "Invalid confirm_window_seconds %r in routing_meta for tool %r; "
                "falling back to config default (%ds)",
                raw_window,
                tool.name,
                self.config.window_seconds,
            )
            window_seconds = self.config.window_seconds

        self.logger.debug(
            "Confirmation check: owner=%s tool=%s window=%ds",
            owner,
            tool.name,
            window_seconds,
        )

        if window_seconds > 0 and await self.store.is_confirmed(
            owner, tool.name, args_hash
        ):
            self.logger.debug(
                "Confirmation window hit: owner=%s tool=%s", owner, tool.name
            )
            return ConfirmationDecision(
                allowed=True,
                status="confirmed",
                reason="within confirmation window",
                parameters=parameters,
            )

        # 3. Fail-closed: no human manager
        if self.human_manager is None:
            self.logger.info(
                "Confirmation denied (fail-closed, no HITL channel): owner=%s tool=%s",
                owner,
                tool.name,
            )
            return ConfirmationDecision(
                allowed=False,
                status="cancelled",
                reason="confirmation required but no human manager configured (fail-closed)",
                parameters=None,
            )

        # 4. Ask the human
        return await self._request_confirmation(
            tool=tool,
            parameters=parameters,
            owner=owner,
            args_hash=args_hash,
            window_seconds=window_seconds,
            permission_context=permission_context,
        )

    async def _request_confirmation(
        self,
        *,
        tool: "AbstractTool",
        parameters: dict,
        owner: str,
        args_hash: str,
        window_seconds: int,
        permission_context: Optional["PermissionContext"],
    ) -> ConfirmationDecision:
        """Ask the human to confirm (or edit) the tool call.

        Handles both BLOCK and SUSPEND wait strategies, and both APPROVAL
        (approve/cancel) and FORM (edit-before-execute) interaction types.

        Args:
            tool: The tool being confirmed.
            parameters: Current call parameters.
            owner: Resolved owner_id.
            args_hash: Stable hash of parameters.
            window_seconds: Window duration (0 = always re-ask).
            permission_context: Caller's permission context.

        Returns:
            A :class:`ConfirmationDecision`.
        """
        # Import inside method to avoid circular imports at module level
        from parrot.human.models import WaitStrategy

        # Determine channel
        channel: str = (
            permission_context.channel
            if (permission_context and getattr(permission_context, "channel", None))
            else self.config.default_channel
        )

        # Determine wait strategy
        raw_strategy = (tool.routing_meta or {}).get("wait_strategy")
        if raw_strategy == WaitStrategy.SUSPEND or raw_strategy == "suspend":
            wait_strategy = WaitStrategy.SUSPEND
        else:
            if raw_strategy not in (WaitStrategy.BLOCK, "block", None):
                self.logger.warning(
                    "Unrecognized wait_strategy %r for tool %r; defaulting to BLOCK",
                    raw_strategy, tool.name,
                )
            wait_strategy = WaitStrategy.BLOCK

        # Determine interaction type: FORM when allow_edit is set
        allow_edit: bool = bool((tool.routing_meta or {}).get("allow_edit", False))

        # Render briefing
        briefing = render_briefing(tool, parameters)

        self.logger.info(
            "Requesting HITL confirmation: owner=%s tool=%s channel=%s strategy=%s allow_edit=%s",
            owner,
            tool.name,
            channel,
            wait_strategy.value,
            allow_edit,
        )

        if allow_edit:
            return await self._ask_form(
                tool=tool,
                parameters=parameters,
                briefing=briefing,
                owner=owner,
                args_hash=args_hash,
                window_seconds=window_seconds,
                channel=channel,
                wait_strategy=wait_strategy,
            )
        else:
            return await self._ask_approval(
                tool=tool,
                parameters=parameters,
                briefing=briefing,
                owner=owner,
                args_hash=args_hash,
                window_seconds=window_seconds,
                channel=channel,
                wait_strategy=wait_strategy,
            )

    async def _ask_approval(
        self,
        *,
        tool: "AbstractTool",
        parameters: dict,
        briefing: str,
        owner: str,
        args_hash: str,
        window_seconds: int,
        channel: str,
        wait_strategy: "WaitStrategy",
    ) -> ConfirmationDecision:
        """Ask the human for Yes/No approval.

        Args:
            tool: The tool being confirmed.
            parameters: Current call parameters.
            briefing: Rendered briefing string.
            owner: Resolved owner_id.
            args_hash: Stable hash of parameters.
            window_seconds: Window duration.
            channel: HITL channel name.
            wait_strategy: BLOCK or SUSPEND.

        Returns:
            A :class:`ConfirmationDecision`.
        """
        from parrot.core.exceptions import HumanInteractionInterrupt
        from parrot.human.models import HumanInteraction, InteractionType, WaitStrategy

        interaction = HumanInteraction(
            interaction_type=InteractionType.APPROVAL,
            question=briefing,
            timeout=self.config.approval_timeout,
            default_response=False,  # fail-closed on timeout
        )

        if wait_strategy == WaitStrategy.SUSPEND:
            # Non-blocking SUSPEND path
            interaction_id = await self.human_manager.request_human_input_async(  # type: ignore[union-attr]
                interaction,
                channel=channel,
                schedule_timeout=False,
            )
            raise HumanInteractionInterrupt(
                prompt=briefing,
                interaction_id=interaction_id,
            )

        # BLOCK path
        try:
            result = await self.human_manager.request_human_input(  # type: ignore[union-attr]
                interaction,
                channel=channel,
            )
        except asyncio.TimeoutError:
            self.logger.warning("Confirmation timed out for tool %r", tool.name)
            return ConfirmationDecision(
                allowed=False,
                status="timeout",
                reason="Confirmation request timed out",
                parameters=None,
            )
        except Exception as exc:
            self.logger.warning(
                "HITL confirmation request failed for tool %r: %s — cancelling (fail-closed)",
                tool.name,
                exc,
            )
            return ConfirmationDecision(
                allowed=False,
                status="cancelled",
                reason=f"HITL confirmation request failed: {exc} (fail-closed)",
                parameters=None,
            )

        if result.timed_out:
            self.logger.info(
                "Confirmation timed out: owner=%s tool=%s", owner, tool.name
            )
            return ConfirmationDecision(
                allowed=False,
                status="timeout",
                reason="confirmation timed out (fail-closed)",
                parameters=None,
            )

        approved: bool = bool(result.consolidated_value)
        if approved:
            if window_seconds > 0:
                await self.store.record(owner, tool.name, args_hash, window_seconds=window_seconds)
            self.logger.info(
                "Confirmation approved: owner=%s tool=%s window=%ds",
                owner,
                tool.name,
                window_seconds,
            )
            return ConfirmationDecision(
                allowed=True,
                status="confirmed",
                reason="HITL approval granted",
                parameters=parameters,
            )
        else:
            self.logger.info(
                "Confirmation rejected: owner=%s tool=%s", owner, tool.name
            )
            return ConfirmationDecision(
                allowed=False,
                status="cancelled",
                reason="HITL approval rejected",
                parameters=None,
            )

    async def _ask_form(
        self,
        *,
        tool: "AbstractTool",
        parameters: dict,
        briefing: str,
        owner: str,
        args_hash: str,
        window_seconds: int,
        channel: str,
        wait_strategy: "WaitStrategy",
    ) -> ConfirmationDecision:
        """Ask the human to edit parameters via a FORM interaction.

        Loops up to ``config.max_edit_retries`` times on validation failure,
        then auto-cancels.

        Args:
            tool: The tool being confirmed.
            parameters: Current call parameters.
            briefing: Rendered briefing string.
            owner: Resolved owner_id.
            args_hash: Stable hash of parameters.
            window_seconds: Window duration.
            channel: HITL channel name.
            wait_strategy: BLOCK or SUSPEND.

        Returns:
            A :class:`ConfirmationDecision`.
        """
        from parrot.core.exceptions import HumanInteractionInterrupt
        from parrot.human.models import HumanInteraction, InteractionType, WaitStrategy

        form_schema = build_form_schema(tool, parameters)
        retries_left = self.config.max_edit_retries + 1  # first attempt + retries

        # Note: SUSPEND exits via HumanInteractionInterrupt on the first iteration;
        # the retry loop only applies to the BLOCK path.
        while retries_left > 0:
            retries_left -= 1
            interaction = HumanInteraction(
                interaction_type=InteractionType.FORM,
                question=briefing,
                form_schema=form_schema,
                timeout=self.config.approval_timeout,
                default_response=False,
            )

            if wait_strategy == WaitStrategy.SUSPEND:
                interaction_id = await self.human_manager.request_human_input_async(  # type: ignore[union-attr]
                    interaction,
                    channel=channel,
                    schedule_timeout=False,
                )
                raise HumanInteractionInterrupt(
                    prompt=briefing,
                    interaction_id=interaction_id,
                )

            # BLOCK path
            try:
                result = await self.human_manager.request_human_input(  # type: ignore[union-attr]
                    interaction,
                    channel=channel,
                )
            except asyncio.TimeoutError:
                self.logger.warning("Confirmation timed out for tool %r", tool.name)
                return ConfirmationDecision(
                    allowed=False,
                    status="timeout",
                    reason="Confirmation request timed out",
                    parameters=None,
                )
            except Exception as exc:
                self.logger.warning(
                    "HITL form confirmation request failed for tool %r: %s — cancelling",
                    tool.name,
                    exc,
                )
                return ConfirmationDecision(
                    allowed=False,
                    status="cancelled",
                    reason=f"HITL form request failed: {exc} (fail-closed)",
                    parameters=None,
                )

            if result.timed_out:
                return ConfirmationDecision(
                    allowed=False,
                    status="timeout",
                    reason="confirmation (form) timed out (fail-closed)",
                    parameters=None,
                )

            # FORM result: consolidated_value is the edited dict, or None/False = cancel
            edited = result.consolidated_value
            if edited is None or edited is False:
                return ConfirmationDecision(
                    allowed=False,
                    status="cancelled",
                    reason="HITL form cancelled by user",
                    parameters=None,
                )

            if isinstance(edited, dict):
                try:
                    validated_params = revalidate_edit(tool, edited)
                    # Valid — re-hash in case window is > 0
                    new_hash = compute_args_hash(validated_params)
                    if window_seconds > 0:
                        await self.store.record(
                            owner, tool.name, new_hash, window_seconds=window_seconds
                        )
                    self.logger.info(
                        "Confirmation approved (edited): owner=%s tool=%s", owner, tool.name
                    )
                    return ConfirmationDecision(
                        allowed=True,
                        status="confirmed",
                        reason="HITL form approved with edits",
                        parameters=validated_params,
                    )
                except (ValidationError, Exception) as exc:
                    self.logger.warning(
                        "Edited parameters failed validation for tool %r (retries_left=%d): %s",
                        tool.name,
                        retries_left,
                        exc,
                    )
                    if retries_left > 0:
                        # Update form_schema with the invalid values as current for re-ask
                        form_schema = build_form_schema(tool, edited)
                        briefing = (
                            f"Validation failed: {exc}\n\nPlease correct and resubmit:\n{briefing}"
                        )
                        continue
                    else:
                        return ConfirmationDecision(
                            allowed=False,
                            status="cancelled",
                            reason=f"Edited values failed validation after max retries: {exc}",
                            parameters=None,
                        )
            else:
                # Non-dict response from FORM — treat as cancel
                return ConfirmationDecision(
                    allowed=False,
                    status="cancelled",
                    reason="HITL form returned unexpected response type",
                    parameters=None,
                )

        # Exhausted retries
        return ConfirmationDecision(
            allowed=False,
            status="cancelled",
            reason="Confirmation cancelled after exhausting max_edit_retries",
            parameters=None,
        )
