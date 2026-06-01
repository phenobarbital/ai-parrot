"""
Operator-only Telegram commands for the autonomous harness (FEAT-210).

This module defines ``OperatorCommandsMixin`` — a mixin class that adds 7
operator-restricted command handlers to ``TelegramAgentWrapper``.  The mixin
is mixed in by TASK-1398 (wrapper.py) and its commands are registered via
``_register_operator_commands()``.

Commands implemented here:
- /context  — show the conversation's system-prompt / shaping context (read-only)
- /memory   — show recent conversation turns (read-only, limited to N)
- /model    — show the agent's model name and LLM provider (read-only)
- /mission  — show the heartbeat mission string (read-only; degrades if absent)
- /health   — project heartbeat liveness (degrades if FEAT-209 not wired)
- /status   — composite view: heartbeat + ephemeral sub-agents (each section degrades independently)
- /thread   — fork work to an ephemeral sub-agent (FEAT-208; degrades if absent)

All external feature imports (FEAT-208, FEAT-209) are guarded with
try/except ImportError so the wrapper starts cleanly even when those
features have not been merged or installed.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Optional

from aiogram.filters import Command
from aiogram.types import Message

# ---------------------------------------------------------------------------
# Guarded imports for FEAT-209 (HeartbeatManager) — not yet merged
# ---------------------------------------------------------------------------
try:
    from parrot.autonomous.heartbeat import HeartbeatManager, HeartbeatState  # type: ignore[import]
except ImportError:
    HeartbeatManager = None  # type: ignore[assignment,misc]
    HeartbeatState = None  # type: ignore[assignment]


if TYPE_CHECKING:
    from parrot.memory.abstract import ConversationMemory

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Module-level tunables (readable by tests via oc_module._X)
# ---------------------------------------------------------------------------
_MEMORY_TURN_LIMIT = 10
_THREAD_TIMEOUT = 120.0  # seconds — hard ceiling for /thread sub-agent spawns


def _format_memory(conv: "ConversationMemory", limit: int = _MEMORY_TURN_LIMIT) -> str:
    """Format recent conversation turns for operator display.

    Iterates through all sessions stored in the ConversationMemory and
    collects the most recent ``limit`` turns across all histories.

    Args:
        conv: A ConversationMemory instance (e.g. InMemoryConversation).
        limit: Maximum number of turns to display.

    Returns:
        Human-readable string with the most recent turns or a placeholder
        when the memory is empty.
    """
    lines: List[str] = []
    try:
        # InMemoryConversation stores histories in _histories dict.
        # We iterate all histories to collect recent turns.
        histories_store = getattr(conv, '_histories', {})
        all_turns = []
        for user_histories in histories_store.values():
            for chatbot_histories in user_histories.values():
                for history in chatbot_histories.values():
                    all_turns.extend(history.turns)
        # Sort by timestamp descending, take the most recent `limit` turns
        all_turns.sort(key=lambda t: t.timestamp, reverse=True)
        recent = list(reversed(all_turns[:limit]))
        if not recent:
            return "Memory: no turns recorded yet."
        lines.append(f"Memory ({len(recent)} recent turns):\n")
        for turn in recent:
            ts = turn.timestamp.strftime("%H:%M:%S") if hasattr(turn.timestamp, 'strftime') else str(turn.timestamp)
            user_snippet = (turn.user_message or "")[:120]
            asst_snippet = (turn.assistant_response or "")[:120]
            lines.append(f"[{ts}] U: {user_snippet}")
            lines.append(f"       A: {asst_snippet}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Memory: (error reading turns — {exc})"


def _format_context(conv: "ConversationMemory") -> str:
    """Format the conversation's stored context / shaping info.

    For InMemoryConversation the metadata dict on the most recent history
    is used. If no history exists, reports empty.

    Args:
        conv: A ConversationMemory instance.

    Returns:
        Human-readable string with context metadata.
    """
    try:
        histories_store = getattr(conv, '_histories', {})
        all_metadata = []
        for user_histories in histories_store.values():
            for chatbot_histories in user_histories.values():
                for history in chatbot_histories.values():
                    if history.metadata:
                        all_metadata.append(history.metadata)
        if not all_metadata:
            return "Context: no shaping context stored yet."
        lines = ["Conversation context:\n"]
        for meta in all_metadata:
            for key, val in meta.items():
                val_str = str(val)[:200]
                lines.append(f"  {key}: {val_str}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Context: (error reading context — {exc})"


def _format_heartbeat_health(states: list) -> str:
    """Format HeartbeatManager states for /health display.

    Args:
        states: List of HeartbeatState objects returned by
                ``HeartbeatManager.get_all_states()``.

    Returns:
        Human-readable health summary string.
    """
    if not states:
        return "Heartbeat: no agents registered."
    lines = [f"Heartbeat health ({len(states)} agent(s)):\n"]
    for state in states:
        name = getattr(state, 'agent_name', 'unknown')
        ticks = getattr(state, 'tick_count', '?')
        last_tick = getattr(state, 'last_tick', None)
        ts = last_tick.strftime("%H:%M:%S") if last_tick and hasattr(last_tick, 'strftime') else str(last_tick or 'n/a')
        lines.append(f"  [{name}] ticks={ticks} last_tick={ts}")
    return "\n".join(lines)


def _format_status(heartbeat_states: Optional[list], ephemeral_info: Optional[str]) -> str:
    """Format composite /status view.

    Args:
        heartbeat_states: Output from HeartbeatManager.get_all_states(), or
                          None when the heartbeat is not configured.
        ephemeral_info: Pre-formatted string about active ephemeral sub-agents,
                        or None when FEAT-208 is not wired.

    Returns:
        Composite status string with two independently-degradable sections.
    """
    lines = ["Harness status:\n"]

    # Heartbeat section
    if heartbeat_states is None:
        lines.append("Heartbeat: not configured.")
    elif len(heartbeat_states) == 0:
        lines.append("Heartbeat: no agents registered.")
    else:
        lines.append(_format_heartbeat_health(heartbeat_states))

    lines.append("")

    # Sub-agents section
    if ephemeral_info is None:
        lines.append("Sub-agents: not available.")
    else:
        lines.append(f"Sub-agents: {ephemeral_info}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class OperatorCommandsMixin:
    """Operator-only Telegram commands for the autonomous harness.

    This mixin adds 7 command handlers and the ``_register_operator_commands``
    registration helper.  It is designed to be mixed into ``TelegramAgentWrapper``
    via multiple-inheritance.

    The mixin relies on the following attributes being present on ``self``:
    - ``self.config``          — TelegramAgentConfig (with operator_chat_ids,
                                 enable_operator_commands from TASK-1394)
    - ``self.agent``           — AbstractBot instance
    - ``self.conversations``   — Dict[int, ConversationMemory]
    - ``self.app``             — aiohttp web.Application (may be None or dict)
    - ``self.router``          — aiogram Router
    - ``self.logger``          — standard Python logger
    - ``_is_operator()``       — gate method added by TASK-1394
    - ``_send_safe_message()`` — safe reply helper from wrapper.py
    - ``_typing_indicator()``  — optional; used by /thread for Telegram UX.
                                 When absent, /thread still works without indicator.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_from_app(self, key: str):
        """Safely retrieve a value from ``self.app`` by key.

        Handles both ``aiohttp.web.Application`` (a ``MutableMapping``) and
        plain ``dict``-like objects.  Returns ``None`` when ``self.app`` is
        absent, has no ``.get`` method, or the key is not present.

        Args:
            key: The application-state key to look up.

        Returns:
            The stored value, or ``None``.
        """
        app = getattr(self, 'app', None)
        if app is None:
            return None
        get = getattr(app, 'get', None)
        if callable(get):
            return get(key)
        return None

    def _register_operator_commands(self) -> None:
        """Register all 7 operator command handlers on the router.

        Called from ``_register_handlers()`` in wrapper.py when
        ``config.enable_operator_commands`` is True.  All 7 commands
        are registered even when FEAT-208/FEAT-209 are not merged —
        the individual handlers degrade gracefully in that case.
        """
        self.logger.debug("Registering operator commands")
        self.router.message.register(self.handle_health, Command("health"))
        self.router.message.register(self.handle_status, Command("status"))
        self.router.message.register(self.handle_context, Command("context"))
        self.router.message.register(self.handle_memory, Command("memory"))
        self.router.message.register(self.handle_mission, Command("mission"))
        self.router.message.register(self.handle_model, Command("model"))
        self.router.message.register(self.handle_thread, Command("thread"))

    # ------------------------------------------------------------------
    # Read-only commands (TASK-1395)
    # ------------------------------------------------------------------

    async def handle_context(self, message: Message) -> None:
        """Handle /context — show the conversation shaping context (read-only).

        Projects metadata stored in the conversation history for the
        operator's chat.  Does NOT mutate any state.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return
        conv = self.conversations.get(chat_id)
        if conv is None:
            await self._send_safe_message(
                message, "Context: no conversation started yet for this chat."
            )
            return
        text = _format_context(conv)
        await self._send_safe_message(message, text)

    async def handle_memory(self, message: Message) -> None:
        """Handle /memory — show recent conversation turns (read-only).

        Displays the ``_MEMORY_TURN_LIMIT`` most recent turns for the chat.
        Output is truncated to avoid Telegram's 4096-character message limit.
        Does NOT mutate any state.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return
        conv = self.conversations.get(chat_id)
        if conv is None:
            await self._send_safe_message(
                message, "Memory: no conversation started yet for this chat."
            )
            return
        text = _format_memory(conv, limit=_MEMORY_TURN_LIMIT)
        await self._send_safe_message(message, text)

    async def handle_model(self, message: Message) -> None:
        """Handle /model — show the agent's model name and LLM provider (read-only).

        Reads ``self.agent.model`` and ``self.agent.use_llm`` via ``getattr``
        for safety.  Does NOT change the agent's model.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return
        model = getattr(self.agent, 'model', None) or getattr(self.agent, '_model', 'unknown')
        use_llm = getattr(self.agent, 'use_llm', None) or getattr(self.agent, '_use_llm', 'unknown')
        agent_name = getattr(self.agent, 'name', getattr(self.agent, '__class__', type(self.agent)).__name__)
        text = (
            f"Agent model info:\n"
            f"  Agent: {agent_name}\n"
            f"  Model: {model}\n"
            f"  Provider: {use_llm}"
        )
        await self._send_safe_message(message, text)

    async def handle_mission(self, message: Message) -> None:
        """Handle /mission — show the heartbeat mission string (read-only).

        Consumes HeartbeatManager (FEAT-209).  Degrades gracefully when
        the heartbeat is not configured or FEAT-209 is not installed.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return
        if HeartbeatManager is None:
            await self._send_safe_message(
                message, "Mission: heartbeat not configured (FEAT-209 not available)."
            )
            return
        hb = self._get_from_app('heartbeat_manager')
        if hb is None:
            await self._send_safe_message(
                message, "Mission: heartbeat not configured."
            )
            return
        try:
            # Prefer a dedicated attribute; fall back to a callable accessor.
            if hasattr(hb, 'mission'):
                mission = hb.mission
            elif hasattr(hb, 'get_mission'):
                get_fn = hb.get_mission
                if asyncio.iscoroutinefunction(get_fn):
                    mission = await get_fn()
                else:
                    mission = get_fn()
            else:
                mission = None
            if mission:
                text = f"Mission:\n{mission}"
            else:
                text = "Mission: (no mission set on heartbeat manager)."
            await self._send_safe_message(message, text)
        except Exception as exc:
            self.logger.warning("handle_mission error: %s", exc, exc_info=True)
            await self._send_safe_message(message, "Mission: (error reading mission).")

    # ------------------------------------------------------------------
    # Harness-state commands (TASK-1396)
    # ------------------------------------------------------------------

    async def handle_health(self, message: Message) -> None:
        """Handle /health — project heartbeat liveness.

        Consumes ``HeartbeatManager.get_all_states()`` (FEAT-209).
        Degrades to "heartbeat not configured" when HeartbeatManager is
        absent or not wired in the aiohttp application.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return
        if HeartbeatManager is None:
            await self._send_safe_message(
                message, "Health: heartbeat not configured (FEAT-209 not available)."
            )
            return
        hb = self._get_from_app('heartbeat_manager')
        if hb is None:
            await self._send_safe_message(
                message, "Health: heartbeat not configured."
            )
            return
        try:
            get_states = hb.get_all_states
            if asyncio.iscoroutinefunction(get_states):
                states = await get_states()
            else:
                states = get_states()
            text = _format_heartbeat_health(states)
            await self._send_safe_message(message, text)
        except Exception as exc:
            self.logger.warning("handle_health error: %s", exc, exc_info=True)
            await self._send_safe_message(message, "Health: (error reading heartbeat state).")

    async def handle_status(self, message: Message) -> None:
        """Handle /status — composite view of heartbeat and ephemeral sub-agents.

        Combines HeartbeatManager state (FEAT-209) and active ephemeral
        sub-agent info (FEAT-208).  Each section degrades independently
        when its source is not configured.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return

        # Heartbeat section — degrades independently if FEAT-209 absent or not wired
        heartbeat_states: Optional[list] = None
        if HeartbeatManager is not None:
            hb = self._get_from_app('heartbeat_manager')
            if hb is not None:
                try:
                    get_states = hb.get_all_states
                    if asyncio.iscoroutinefunction(get_states):
                        heartbeat_states = await get_states()
                    else:
                        heartbeat_states = get_states()
                except Exception as exc:
                    self.logger.warning("handle_status heartbeat error: %s", exc)

        # Sub-agent section — degrades independently if FEAT-208 absent or not wired
        ephemeral_info: Optional[str] = None
        try:
            bot_manager = self._get_from_app('bot_manager')
            if bot_manager is not None:
                status_method = getattr(bot_manager, 'get_ephemeral_status', None)
                if status_method is not None:
                    if asyncio.iscoroutinefunction(status_method):
                        info = await status_method()
                    else:
                        info = status_method()
                    ephemeral_info = str(info) if info is not None else "no active sub-agents."
                else:
                    ephemeral_info = "(status method unavailable)"
        except Exception as exc:
            self.logger.warning("handle_status sub-agent error: %s", exc)

        text = _format_status(heartbeat_states, ephemeral_info)
        await self._send_safe_message(message, text)

    # ------------------------------------------------------------------
    # Fork command (TASK-1397)
    # ------------------------------------------------------------------

    async def handle_thread(self, message: Message) -> None:
        """Handle /thread <task> — fork work to an ephemeral sub-agent (FEAT-208).

        Parses the task description from the message text, spawns an ephemeral
        sub-agent via the ``bot_manager`` in ``self.app``, awaits the result
        with a timeout, and delivers the response.  Degrades to "sub-agents
        not available" when FEAT-208 is not wired.

        Args:
            message: Incoming aiogram Message.
        """
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("Access denied. Operator-only command.")
            return

        # Parse task text
        text = message.text or ""
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await self._send_safe_message(
                message,
                "Usage: /thread <task description>\n\nExample: /thread Summarise the last 5 news articles."
            )
            return

        task = parts[1].strip()

        # Resolve bot_manager from app
        bot_manager = self._get_from_app('bot_manager')

        if bot_manager is None:
            await self._send_safe_message(message, "Sub-agents not available.")
            return

        # Start typing indicator while the sub-agent runs (may take up to _THREAD_TIMEOUT s).
        # _typing_indicator is defined on TelegramAgentWrapper; gracefully absent in unit tests.
        typing_task = None
        _ti = getattr(self, '_typing_indicator', None)
        if _ti is not None:
            typing_task = asyncio.create_task(_ti(chat_id))

        try:
            spawn_method = getattr(bot_manager, 'create_ephemeral_user_bot', None)
            if spawn_method is None:
                await self._send_safe_message(
                    message, "Sub-agent spawn method not available on bot_manager."
                )
                return

            # Spawn the sub-agent with a timeout guard
            try:
                result = await asyncio.wait_for(
                    _invoke_spawn(spawn_method, task),
                    timeout=_THREAD_TIMEOUT,
                )
                result_text = str(result)[:4000] if result else "(no result returned)"
                await self._send_safe_message(
                    message, f"Sub-agent result:\n{result_text}"
                )
            except asyncio.TimeoutError:
                await self._send_safe_message(
                    message,
                    f"Sub-agent timed out after {int(_THREAD_TIMEOUT)}s. "
                    "The task may still be running in the background."
                )
        except Exception as exc:
            self.logger.warning("handle_thread error: %s", exc, exc_info=True)
            await self._send_safe_message(message, f"Sub-agent error: {exc}")
        finally:
            if typing_task is not None:
                typing_task.cancel()


async def _invoke_spawn(spawn_method, task: str):
    """Invoke spawn_method with the task string.

    Handles both coroutine and regular functions.

    Args:
        spawn_method: Callable to invoke (sync or async).
        task: The task description string.

    Returns:
        The result from spawn_method.
    """
    if asyncio.iscoroutinefunction(spawn_method):
        return await spawn_method(task)
    return spawn_method(task)
