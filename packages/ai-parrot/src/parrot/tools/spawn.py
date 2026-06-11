"""SpawnSubAgentTool — ephemeral sub-agent spawner (FEAT-208).

Provides a first-class tool that an agent can invoke to:
1. Spawn an ephemeral sub-agent with a restricted tool subset.
2. Execute a single task with a configurable timeout.
3. Tear down the sub-agent unconditionally (success, error, or timeout).

The tool orchestrates the existing ``BotManager`` lifecycle methods
(generalized for typed ownership by TASK-1387/TASK-1388):
  create_ephemeral_user_bot → poll phase=="ready" → invoke(timeout) → discard.

Usage::

    tool = SpawnSubAgentTool(
        bot_manager=app["bot_manager"],
        owner_id="agent:my-orchestrator",
        allowed_tools=["search_docs", "get_weather"],
    )
    result = await tool.execute(
        task="Summarize the latest market news.",
        tools=["search_docs"],
        timeout=60,
    )
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from parrot.tools.abstract import AbstractTool

# ---------------------------------------------------------------------------
# Args schema
# ---------------------------------------------------------------------------


class SpawnSubAgentInput(BaseModel):
    """Input schema for SpawnSubAgentTool.

    Attributes:
        task: The question / task for the ephemeral sub-agent.
        tools: Allowed tool names for the sub-agent.  Intersected with the
            parent's ``allowed_tools`` allowlist for defense in depth.
        model: LLM model override.  Inherits parent default when not set.
        system_prompt: System prompt injected into the sub-agent.
        timeout: Max seconds the sub-agent is allowed to run before the call
            is cancelled.  Defaults to 120 s.
        ttl_seconds: Ephemeral registry TTL.  Keep short (default 300 s /
            5 min) for sub-agents — they should be discarded well before this.
    """

    task: str = Field(..., description="The task/question for the ephemeral sub-agent.")
    tools: List[str] = Field(
        default_factory=list,
        description="Allowed tool names for the sub-agent (intersected with parent allowlist).",
    )
    model: Optional[str] = Field(
        default=None,
        description="LLM model override for the sub-agent.",
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="System prompt for the sub-agent.",
    )
    timeout: int = Field(
        default=120,
        ge=1,
        le=900,
        description="Max seconds for the sub-agent task execution.",
    )
    ttl_seconds: int = Field(
        default=300,
        ge=10,
        description="Ephemeral registry TTL in seconds (short — minutes, not hours).",
    )


# ---------------------------------------------------------------------------
# SpawnSubAgentTool
# ---------------------------------------------------------------------------

_POLL_INTERVAL: float = 0.1   # seconds between get_ephemeral_status polls
_POLL_TIMEOUT: float = 30.0   # max seconds to wait for phase=="ready"


class SpawnSubAgentTool(AbstractTool):
    """Spawn an ephemeral sub-agent to execute a single task.

    Creates a short-lived sub-agent owned by the calling agent, executes
    one task with a restricted tool subset and a timeout, then discards the
    sub-agent — regardless of success, error, or timeout.

    The tool **never** calls ``promote_user_bot``; all sub-agents are
    ephemeral and discarded after their task completes.

    Args:
        bot_manager: The ``BotManager`` instance (injected via constructor —
            testable without an aiohttp app).
        owner_id: Canonical string ID of the parent agent that owns the
            sub-agent (e.g. ``"agent:orchestrator-001"``).
        allowed_tools: Allowlist of tool names the parent authorises for
            sub-agents.  The sub-agent receives only the intersection of
            this list and the ``tools`` requested in the call.
        name: Tool name (default: ``"spawn_sub_agent"``).
        description: Tool description override.
        routing_meta: Routing hints for the CapabilityRegistry.  The key
            ``"requires_grant"`` is reserved for future HITL grant
            enforcement (FEAT-grants); set but not enforced here.
    """

    # Class-level name/description (overridable in __init__)
    name: str = "spawn_sub_agent"
    description: str = (
        "Spawn an ephemeral sub-agent to execute a single isolated task, "
        "then tear it down. Use this to delegate bounded work to a "
        "sub-agent with a restricted tool subset."
    )
    args_schema = SpawnSubAgentInput

    def __init__(
        self,
        bot_manager: Any,
        owner_id: str,
        *,
        allowed_tools: Optional[List[str]] = None,
        name: str = "spawn_sub_agent",
        description: Optional[str] = None,
        routing_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize SpawnSubAgentTool.

        Args:
            bot_manager: ``BotManager`` instance — injected, not taken from
                ``app["bot_manager"]``, so the tool is testable standalone.
            owner_id: Canonical owner ID of the parent agent.
            allowed_tools: Parent-defined allowlist of tool names.  Sub-agents
                may only use tools in this list.  Empty list means no tools.
            name: Tool name (default: ``"spawn_sub_agent"``).
            description: Override description for the LLM tool descriptor.
            routing_meta: Optional routing hints.  The ``"requires_grant"``
                key is set to ``False`` by default (no enforcement yet).
        """
        # Build routing_meta with requires_grant and requires_confirmation placeholders.
        effective_routing = dict(routing_meta or {})
        effective_routing.setdefault("requires_grant", False)
        effective_routing.setdefault("requires_confirmation", False)  # FEAT-235

        super().__init__(
            name=name,
            description=description or self.description,
            routing_meta=effective_routing,
        )

        self._bot_manager = bot_manager
        self._owner_id = owner_id
        self._allowed_tools: List[str] = list(allowed_tools or [])

    # ------------------------------------------------------------------
    # Subset enforcement helpers
    # ------------------------------------------------------------------

    def _compute_effective_tools(self, requested: List[str]) -> List[str]:
        """Compute the intersection of *requested* tools with the parent allowlist.

        If ``allowed_tools`` is empty (no allowlist configured), the
        intersection is the empty list — no tools are passed to the sub-agent.
        If ``allowed_tools`` is non-empty, only tools present in it are allowed.

        Args:
            requested: Tool names requested by the LLM in this call.

        Returns:
            Sorted list of tool names the sub-agent is authorised to use.
        """
        if not self._allowed_tools:
            if requested:
                self.logger.warning(
                    "SpawnSubAgentTool: no allowed_tools configured; "
                    "sub-agent will have no tools (requested: %s)",
                    requested,
                )
            return []

        allowed_set = set(self._allowed_tools)
        effective = [t for t in requested if t in allowed_set]

        excluded = set(requested) - allowed_set
        if excluded:
            self.logger.warning(
                "SpawnSubAgentTool: tools excluded (not in allowlist): %s",
                sorted(excluded),
            )
        return sorted(effective)

    @staticmethod
    def _tools_to_config(tool_names: List[str]) -> List[Dict[str, Any]]:
        """Convert tool name strings to minimal tools_config_plain dicts.

        This is a best-effort mapping: each tool receives a minimal config
        dict with only its name.  In a production deployment with a full
        ToolManager, this could be enriched with parameters and credentials.

        Args:
            tool_names: List of tool name strings.

        Returns:
            ``[{"name": name} for name in tool_names]``
        """
        return [{"name": name} for name in tool_names]

    # ------------------------------------------------------------------
    # Core lifecycle
    # ------------------------------------------------------------------

    async def _execute(self, **kwargs: Any) -> Any:
        """Execute the sub-agent lifecycle: create → poll ready → invoke → discard.

        Steps:
        1. Compute effective tool subset (intersect with allowlist).
        2. Build config dict and call ``create_ephemeral_user_bot``.
        3. Poll ``get_ephemeral_status`` until ``phase == "ready"`` (sync).
        4. Retrieve sub-agent from ``get_bots()[chatbot_id]``.
        5. ``asyncio.wait_for(sub.invoke(question=task), timeout)``.
        6. (finally) ``discard_ephemeral_user_bot`` — always, even on error.

        Args:
            **kwargs: Validated against ``SpawnSubAgentInput`` by the
                ``AbstractTool.execute`` wrapper (args_schema).

        Returns:
            Response content string from the sub-agent.

        Raises:
            asyncio.TimeoutError: Re-raised as a ``TimeoutError`` with a
                descriptive message when the sub-agent exceeds ``timeout``.
            RuntimeError: When the sub-agent cannot reach ``phase == "ready"``
                within ``_POLL_TIMEOUT`` seconds, or when the ``chatbot_id``
                is not found in ``get_bots()`` after creation.
        """
        # --- Extract validated inputs ---
        task: str = kwargs["task"]
        requested_tools: List[str] = kwargs.get("tools") or []
        model: Optional[str] = kwargs.get("model")
        system_prompt: Optional[str] = kwargs.get("system_prompt")
        timeout: int = kwargs.get("timeout", 120)
        ttl_seconds: int = kwargs.get("ttl_seconds", 300)

        # --- Tool subset enforcement ---
        effective_tools = self._compute_effective_tools(requested_tools)
        tools_config = self._tools_to_config(effective_tools)

        # --- Build ephemeral bot config ---
        # ``name`` is a required field on UserBotModel (no default).
        # Use a deterministic slug derived from the owner_id + task prefix.
        config: Dict[str, Any] = {
            "name": f"ephemeral-sub-{self._owner_id.replace(':', '-')[:40]}",
        }
        # Use ``system_prompt_template`` — the actual UserBotModel field name.
        # (Not ``system_prompt``, which is not a valid field and would cause
        # a ValidationError in strict mode.)
        if system_prompt:
            config["system_prompt_template"] = system_prompt
        if model:
            config["llm"] = model
        if tools_config:
            config["tools_config_plain"] = tools_config

        # --- Create ephemeral sub-agent ---
        self.logger.info(
            "SpawnSubAgentTool: spawning sub-agent (owner=%s, tools=%s, timeout=%ds)",
            self._owner_id,
            effective_tools,
            timeout,
        )
        status = await self._bot_manager.create_ephemeral_user_bot(
            owner_id=self._owner_id,
            owner_kind="agent",
            config=config,
            uploaded_paths=[],
            ttl_seconds=ttl_seconds,
        )
        chatbot_id: str = status.chatbot_id

        try:
            # --- Poll until ready (or app=None → already ready) ---
            await self._wait_for_ready(chatbot_id)

            # --- Resolve sub-agent from BotManager ---
            bots = self._bot_manager.get_bots()
            sub = bots.get(chatbot_id)
            if sub is None:
                raise RuntimeError(
                    f"SpawnSubAgentTool: sub-agent {chatbot_id!r} not found in "
                    "BotManager._bots after creation."
                )

            # --- Invoke with timeout ---
            self.logger.debug(
                "SpawnSubAgentTool: invoking sub-agent %s (task=%r, timeout=%ds)",
                chatbot_id,
                task[:80],
                timeout,
            )
            try:
                response = await asyncio.wait_for(
                    sub.invoke(question=task),
                    timeout=float(timeout),
                )
            except asyncio.TimeoutError as exc:
                self.logger.error(
                    "SpawnSubAgentTool: sub-agent %s timed out after %ds",
                    chatbot_id,
                    timeout,
                )
                raise TimeoutError(
                    f"Sub-agent task timed out after {timeout} seconds."
                ) from exc

            # --- Extract result ---
            if hasattr(response, "content"):
                return response.content
            return str(response)

        finally:
            # --- Guaranteed teardown (success, error, timeout) ---
            try:
                await self._bot_manager.discard_ephemeral_user_bot(
                    chatbot_id,
                    owner_id=self._owner_id,
                )
                self.logger.debug(
                    "SpawnSubAgentTool: discarded sub-agent %s", chatbot_id
                )
            except Exception as discard_exc:  # noqa: BLE001
                self.logger.warning(
                    "SpawnSubAgentTool: failed to discard sub-agent %s: %s",
                    chatbot_id,
                    discard_exc,
                )

    async def _wait_for_ready(self, chatbot_id: str) -> None:
        """Poll ``get_ephemeral_status`` until ``phase == "ready"`` or error.

        ``get_ephemeral_status`` is synchronous so we poll with
        ``asyncio.sleep`` to yield control to other coroutines.

        Args:
            chatbot_id: The sub-agent's canonical UUID string.

        Raises:
            RuntimeError: If the bot's phase becomes ``"error"`` or if the
                ready state is not reached within ``_POLL_TIMEOUT`` seconds.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _POLL_TIMEOUT
        while True:
            status = self._bot_manager.get_ephemeral_status(
                chatbot_id,
                owner_id=self._owner_id,
            )
            if status is None:
                raise RuntimeError(
                    f"SpawnSubAgentTool: ephemeral status for {chatbot_id!r} "
                    "disappeared during warm-up."
                )
            if status.phase == "ready":
                return
            if status.phase == "error":
                raise RuntimeError(
                    f"SpawnSubAgentTool: sub-agent {chatbot_id!r} warm-up failed: "
                    f"{status.error}"
                )
            if loop.time() >= deadline:
                raise RuntimeError(
                    f"SpawnSubAgentTool: sub-agent {chatbot_id!r} did not reach "
                    f"phase='ready' within {_POLL_TIMEOUT:.0f}s."
                )
            await asyncio.sleep(_POLL_INTERVAL)
