---
type: Wiki Overview
title: MS Teams Agent Commands — Implementation Plan
id: doc:docs-superpowers-plans-2026-07-08-msteams-agent-commands-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Create `packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py`:'
relates_to:
- concept: mod:parrot.integrations.msteams.commands
  rel: mentions
- concept: mod:parrot.integrations.msteams.commands.agent_commands
  rel: mentions
- concept: mod:parrot.integrations.utils
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
---

# MS Teams Agent Commands — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port core agent commands (`/function`, `/tool`, `/skill`, `/commands`, `/help`, `/clear`, `/whoami`, `/question`, `/call`) from Telegram to MS Teams, activate the dead `config.commands` field, and extract `parse_kwargs` into a shared module.

**Architecture:** New `AgentCommandHandler` class in `msteams/commands/agent_commands.py` receives `agent` + `wrapper`, registers 9 handlers + custom config commands on the existing `MSTeamsCommandRouter`. Shared `parse_kwargs` utility in `parrot/integrations/utils.py`. Wrapper always creates the router (no longer gated on `oauth_manager`).

**Tech Stack:** Python 3.12, botbuilder-core (TurnContext, Activity), shlex, pytest + pytest-asyncio, unittest.mock.

## Global Constraints

- All async handlers follow signature `async (turn_context: TurnContext) -> None`.
- Responses use the wrapper's existing `_parse_response` + `_send_parsed_response` pipeline (Adaptive Cards).
- Agent access is via `self.agent` — always use `hasattr`/`getattr` guards for optional attributes (`_skill_file_registry`, `_skill_registry`, `tool_manager`).
- No new dependencies — `shlex` is stdlib, `botbuilder-core` already required.

---

### Task 1: Shared `parse_kwargs` utility

**Files:**
- Create: `packages/ai-parrot-integrations/src/parrot/integrations/utils.py`
- Modify: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:1043-1058`
- Test: `packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py`

**Interfaces:**
- Produces: `parse_kwargs(text: str) -> dict` — imported by Task 2 (`agent_commands.py`) and by Telegram wrapper.

- [ ] **Step 1: Write the failing test**

Create `packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py`:

```python
"""Tests for the shared parse_kwargs utility."""
import pytest

from parrot.integrations.utils import parse_kwargs


class TestParseKwargs:
    def test_empty_string(self):
        assert parse_kwargs("") == {}

    def test_whitespace_only(self):
        assert parse_kwargs("   ") == {}

    def test_none_input(self):
        assert parse_kwargs(None) == {}

    def test_simple_key_value(self):
        result = parse_kwargs("key=val")
        assert result == {"key": "val"}

    def test_multiple_key_values(self):
        result = parse_kwargs("name=Alice age=30")
        assert result == {"name": "Alice", "age": "30"}

    def test_quoted_value(self):
        result = parse_kwargs('report="Read this loudly"')
        assert result == {"report": "Read this loudly"}

    def test_quoted_value_with_nested_single_quotes(self):
        result = parse_kwargs("""report="In a place of 'La-Mancha'" max_lines=2""")
        assert result == {"report": "In a place of 'La-Mancha'", "max_lines": "2"}

    def test_single_quoted_value(self):
        result = parse_kwargs("report='Hello world' num=1")
        assert result == {"report": "Hello world", "num": "1"}

    def test_positional_args(self):
        result = parse_kwargs("hello world")
        assert result == {"arg0": "hello", "arg1": "world"}

    def test_mixed_kwargs_and_positional(self):
        result = parse_kwargs('name=Alice hello key="big value"')
        assert result == {"name": "Alice", "arg0": "hello", "key": "big value"}

    def test_malformed_quotes_fallback(self):
        """Unmatched quotes should fall back to simple split."""
        result = parse_kwargs('key="unclosed value')
        assert "key" in result or "arg0" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parrot.integrations.utils'`

- [ ] **Step 3: Create the shared utils module**

Create `packages/ai-parrot-integrations/src/parrot/integrations/utils.py`:

```python
"""Shared utilities for integration wrappers (Telegram, MS Teams, etc.)."""
import shlex


def parse_kwargs(text: str) -> dict:
    """Parse 'key=val key2="quoted val"' into a kwargs dict.

    Supports quoted values so multi-word strings survive as a single value:
        report="Read this loudly" max_lines=5

    Non key=val tokens become positional: arg0, arg1, etc.

    Args:
        text: The argument string to parse.

    Returns:
        Dict of parsed keyword arguments.
    """
    if not text or not text.strip():
        return {}
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    kwargs: dict = {}
    positional_idx = 0
    for part in parts:
        if "=" in part:
            key, _, val = part.partition("=")
            kwargs[key.strip()] = val.strip()
        else:
            kwargs[f"arg{positional_idx}"] = part
            positional_idx += 1
    return kwargs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py -v`
Expected: All tests PASS

- [ ] **Step 5: Refactor Telegram wrapper to delegate to shared util**

In `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`:

Add import after line 18 (`import json`):
```python
from parrot.integrations.utils import parse_kwargs as _shared_parse_kwargs
```

Replace the `_parse_kwargs` static method body (lines 1043-1058) with:

```python
    @staticmethod
    def _parse_kwargs(text: str) -> dict:
        """Parse 'key=val key2="quoted val"' into a kwargs dict."""
        return _shared_parse_kwargs(text)
```

Remove the `import shlex` line added earlier in this session (line 18) — the import now lives in `utils.py`.

- [ ] **Step 6: Run existing Telegram tests to verify no regression**

Run: `source .venv/bin/activate && pytest packages/ai-parrot-integrations/tests/ -k "telegram" --timeout=30 -x -q`
Expected: Existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add packages/ai-parrot-integrations/src/parrot/integrations/utils.py \
       packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py \
       packages/ai-parrot-integrations/tests/integrations/test_parse_kwargs.py
git commit -m "refactor: extract parse_kwargs to shared integrations.utils module"
```

---

### Task 2: `AgentCommandHandler` — core class and `/function`, `/call`, `/question` handlers

**Files:**
- Create: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py`
- Test: `packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py`

**Interfaces:**
- Consumes: `parse_kwargs(text) -> dict` from `parrot.integrations.utils` (Task 1).
- Produces: `AgentCommandHandler(agent, wrapper)` with `.register(router)` — imported by Task 4 (`wrapper.py` changes).

- [ ] **Step 1: Write the failing tests**

Create `packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py`:

```python
"""Tests for AgentCommandHandler — core handlers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch


def _make_turn_context(text: str = ""):
    """Build a minimal mock TurnContext for agent command tests."""
    ctx = MagicMock()
    ctx.activity.text = text
    ctx.activity.from_property.id = "user-123"
    ctx.activity.from_property.name = "Test User"
    ctx.activity.conversation.id = "conv-456"
    ctx.activity.recipient.id = "bot-789"
    ctx.activity.recipient.name = "TestBot"
    ctx.activity.entities = []
    ctx.send_activity = AsyncMock()
    return ctx


def _make_agent(**overrides):
    """Build a mock agent with standard attributes."""
    agent = MagicMock()
    agent.agent_id = "test-agent"
    agent.name = "Test Agent"
    agent.description = "A test agent"
    agent.model = "gpt-4"
    agent.tool_manager = MagicMock()
    agent.tool_manager.get_tool.return_value = None
    agent.tool_manager.list_tools.return_value = []
    agent.tool_manager._tools = {}
    for key, val in overrides.items():
        setattr(agent, key, val)
    return agent


def _make_wrapper(agent=None):
    """Build a mock wrapper with standard response helpers."""
    wrapper = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.commands = {}
    wrapper._remove_mentions = MagicMock(side_effect=lambda act, text: text)
    wrapper._parse_response = MagicMock(return_value=MagicMock(text="result", documents=[], media=[]))
    wrapper._send_parsed_response = AsyncMock()
    wrapper.send_text = AsyncMock()
    wrapper.send_card = AsyncMock()
    wrapper.send_typing = AsyncMock()
    wrapper.conversation_state = MagicMock()
    wrapper.conversation_state.clear_state = AsyncMock()
    wrapper.conversation_state.save_changes = AsyncMock()
    return wrapper


class TestHandleFunction:
    @pytest.mark.asyncio
    async def test_usage_message_when_no_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        ctx = _make_turn_context("/function")
        await handler.handle_function(ctx)
        handler.wrapper.send_text.assert_called_once()
        call_text = handler.wrapper.send_text.call_args[0][1]
        assert "Usage" in call_text

    @pytest.mark.asyncio
    async def test_method_not_found(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        del agent.nonexistent_method  # ensure it doesn't exist
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function nonexistent_method")
        await handler.handle_function(ctx)
        call_text = handler.wrapper.send_text.call_args[0][1]
        assert "not found" in call_text

    @pytest.mark.asyncio
    async def test_calls_async_method_with_kwargs(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.speech_report = AsyncMock(return_value={"result": "ok"})
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context('/function speech_report report="hello world" max_lines=2')
        await handler.handle_function(ctx)
        agent.speech_report.assert_called_once_with(report="hello world", max_lines="2")

    @pytest.mark.asyncio
    async def test_calls_sync_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.get_info = MagicMock(return_value="info")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function get_info")
        await handler.handle_function(ctx)
        agent.get_info.assert_called_once()


class TestHandleCall:
    @pytest.mark.asyncio
    async def test_calls_method_with_positional_args(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.greet = AsyncMock(return_value="hi")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/call greet Alice")
        await handler.handle_call(ctx)
        agent.greet.assert_called_once_with("Alice")


class TestHandleQuestion:
    @pytest.mark.asyncio
    async def test_calls_agent_ask_without_tools(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.ask = AsyncMock(return_value="42")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/question What is the answer?")
        await handler.handle_question(ctx)
        agent.ask.assert_called_once()
        call_kwargs = agent.ask.call_args
        assert call_kwargs.kwargs.get("use_tools") is False


class TestRegister:
    def test_registers_all_core_commands(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        router = MSTeamsCommandRouter()
        handler.register(router)

        expected = {
            "function", "call", "tool", "skill", "commands",
            "help", "clear", "whoami", "question",
        }
        assert expected.issubset(set(router.registered_commands))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parrot.integrations.msteams.commands.agent_commands'`

- [ ] **Step 3: Implement AgentCommandHandler**

Create `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/agent_commands.py`:

```python
"""Core agent commands for MS Teams (FEAT-XXX).

Provides ``AgentCommandHandler``, which registers /function, /tool, /skill,
/commands, /help, /clear, /whoami, /question, and /call on the
``MSTeamsCommandRouter``, plus custom commands from ``config.commands``.

Usage::

    from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

    handler = AgentCommandHandler(agent, wrapper)
    handler.register(router)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, TYPE_CHECKING

from parrot.integrations.utils import parse_kwargs

if TYPE_CHECKING:
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter


class AgentCommandHandler:
    """Core agent commands for MS Teams.

    Registers /function, /tool, /skill, /commands, /help, /clear, /whoami,
    /question, /call, and custom config-mapped commands on the router.

    Args:
        agent: The AI-Parrot agent instance.
        wrapper: The ``MSTeamsAgentWrapper`` instance (used for response
            helpers and config access).
    """

    def __init__(self, agent: Any, wrapper: Any) -> None:
        self.agent = agent
        self.wrapper = wrapper
        self.logger = logging.getLogger(f"msteams.commands.{getattr(agent, 'agent_id', 'unknown')}")

    def register(self, router: "MSTeamsCommandRouter") -> None:
        """Register all core and custom commands on the router."""
        router.register("function", self.handle_function)
        router.register("call", self.handle_call)
        router.register("tool", self.handle_tool)
        router.register("skill", self.handle_skill)
        router.register("commands", self.handle_commands)
        router.register("help", self.handle_help)
        router.register("clear", self.handle_clear)
        router.register("whoami", self.handle_whoami)
        router.register("question", self.handle_question)
        self._register_custom_commands(router)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_text(self, turn_context) -> str:
        """Get clean text from activity, stripping bot mentions."""
        text = turn_context.activity.text or ""
        return self.wrapper._remove_mentions(turn_context.activity, text).strip()

    async def _send_result(self, turn_context, result: Any, prefix: str = "") -> None:
        """Parse an agent result and send as Adaptive Card or text."""
        parsed = self.wrapper._parse_response(result)
        if isinstance(parsed, dict):
            await self.wrapper.send_card(parsed, turn_context)
        else:
            await self.wrapper._send_parsed_response(parsed, turn_context)

    async def _send_text(self, turn_context, text: str) -> None:
        await self.wrapper.send_text(text, turn_context)

    def _list_tools(self) -> str:
        tool_manager = getattr(self.agent, "tool_manager", None)
        if tool_manager is None:
            return "(no tools available)"
        tools = getattr(tool_manager, "_tools", {})
        if not tools:
            return "(no tools available)"
        lines = []
        for name in sorted(tools)[:20]:
            tool = tools[name]
            desc = getattr(tool, "description", "") or ""
            short = (desc[:60] + "...") if len(desc) > 60 else desc
            lines.append(f"- **{name}** -- {short}" if short else f"- **{name}**")
        if len(tools) > 20:
            lines.append(f"_...and {len(tools) - 20} more_")
        return "\n".join(lines)

    def _list_skills(self) -> str:
        skills: list[str] = []
        file_registry = getattr(self.agent, "_skill_file_registry", None)
        if file_registry is not None and hasattr(file_registry, "list_skills"):
            try:
                for sd in file_registry.list_skills():
                    triggers = ", ".join(getattr(sd, "triggers", []) or [])
                    suffix = f" ({triggers})" if triggers else ""
                    desc = (getattr(sd, "description", "") or "")[:50]
                    skills.append(f"- **{sd.name}**{suffix} -- {desc}")
            except Exception:
                pass
        registry = getattr(self.agent, "_skill_registry", None)
        cached = getattr(registry, "_skills", None) if registry else None
        if isinstance(cached, dict):
            for entry in cached.values():
                meta = getattr(entry, "metadata", None)
                name = getattr(meta, "name", None) if meta else None
                if not name:
                    continue
                desc = (getattr(meta, "description", "") or "")[:50]
                skills.append(f"- **{name}** -- {desc}")
        if not skills:
            return "(no skills available)"
        return "\n".join(skills[:15])

    def _list_callable_methods(self) -> str:
        skip = {"ask", "completion", "stream", "embed", "run", "start", "stop",
                "configure", "close", "shutdown"}
        methods = []
        for name in sorted(dir(self.agent)):
            if name.startswith("_") or name in skip:
                continue
            attr = getattr(self.agent, name, None)
            if callable(attr) and not isinstance(attr, type):
                methods.append(f"- {name}")
        if not methods:
            return ""
        if len(methods) > 15:
            return "\n".join(methods[:15]) + f"\n_...and {len(methods) - 15} more_"
        return "\n".join(methods)

    async def _resolve_skill(self, name: str):
        file_registry = getattr(self.agent, "_skill_file_registry", None)
        if file_registry is None:
            return None
        skill = None
        if hasattr(file_registry, "get_by_name"):
            skill = file_registry.get_by_name(name)
        if skill is None and hasattr(file_registry, "get"):
            trigger = name if name.startswith("/") else f"/{name}"
            skill = file_registry.get(trigger)
        return skill

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def handle_function(self, turn_context) -> None:
        """Handle /function <method> [key=val ...] -- invoke agent method with kwargs."""
        text = self._extract_text(turn_context)
        parts = text.split(maxsplit=2)

        if len(parts) < 2:
            await self._send_text(
                turn_context,
                "Usage: /function <method_name> [key=val ...]\n\n"
                "Example: /function speech_report report=\"Hello world\" max_lines=2",
            )
            return

        method_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        if not hasattr(self.agent, method_name) or not callable(
            getattr(self.agent, method_name)
        ):
            await self._send_text(turn_context, f"Method '{method_name}' not found on agent.")
            return

        await self.wrapper.send_typing(turn_context)
        method = getattr(self.agent, method_name)
        kwargs = parse_kwargs(args_text)
        self.logger.info("/function %s(%s)", method_name, kwargs)

        if asyncio.iscoroutinefunction(method):
            result = await method(**kwargs) if kwargs else await method()
        else:
            result = method(**kwargs) if kwargs else method()

        await self._send_result(turn_context, result, prefix=f"**{method_name}** result:\n\n")

    async def handle_call(self, turn_context) -> None:
        """Handle /call <method> [args ...] -- invoke agent method with positional args."""
        text = self._extract_text(turn_context)
        parts = text.split(maxsplit=2)

        if len(parts) < 2:
            await self._send_text(turn_context, "Usage: /call <method_name> [arg1 arg2 ...]")
            return

        method_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        if not hasattr(self.agent, method_name) or not callable(
            getattr(self.agent, method_name)
        ):
            await self._send_text(turn_context, f"Method '{method_name}' not found on agent.")
            return

        await self.wrapper.send_typing(turn_context)
        method = getattr(self.agent, method_name)
        args = args_text.split() if args_text else []
        self.logger.info("/call %s(%s)", method_name, args)

        if asyncio.iscoroutinefunction(method):
            result = await method(*args) if args else await method()
        else:
            result = method(*args) if args else method()

        await self._send_result(turn_context, result, prefix=f"**{method_name}** result:\n\n")

    async def handle_tool(self, turn_context) -> None:
        """Handle /tool <name> [input] -- use a specific tool via LLM."""
        text = self._extract_text(turn_context)
        parts = text.split(maxsplit=2)

        if len(parts) < 2:
            tools = self._list_tools()
            await self._send_text(
                turn_context, f"Available tools:\n{tools}\n\nUsage: /tool <name> [input]"
            )
            return

        tool_name = parts[1]
        tool_input = parts[2] if len(parts) > 2 else ""

        tool_manager = getattr(self.agent, "tool_manager", None)
        if tool_manager is None or tool_manager.get_tool(tool_name) is None:
            await self._send_text(turn_context, f"Tool '{tool_name}' not found.")
            return

        await self.wrapper.send_typing(turn_context)
        prompt = (
            f"Use the tool {tool_name} with the following input: {tool_input}"
            if tool_input
            else f"Use the tool {tool_name}"
        )
        conversation_id = turn_context.activity.conversation.id
        self.logger.info("/tool %s — prompt: %s", tool_name, prompt[:100])
        from parrot.models.outputs import OutputMode

        response = await self.agent.ask(
            prompt, session_id=conversation_id, output_mode=OutputMode.MSTEAMS
        )
        await self._send_result(turn_context, response)

    async def handle_skill(self, turn_context) -> None:
        """Handle /skill <name> [input] -- activate a skill and query the agent."""
        text = self._extract_text(turn_context)
        parts = text.split(maxsplit=2)

        if len(parts) < 2:
            skills = self._list_skills()
            await self._send_text(
                turn_context, f"Available skills:\n{skills}\n\nUsage: /skill <name> [input]"
            )
            return

        skill_name = parts[1]
        skill_input = parts[2] if len(parts) > 2 else ""

        skill_def = await self._resolve_skill(skill_name)

…(truncated)…
