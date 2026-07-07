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

        db_skill_body: Optional[str] = None
        if skill_def is None:
            registry = getattr(self.agent, "_skill_registry", None)
            if registry is not None:
                try:
                    listed = await registry.list_skills()
                    match = next(
                        (s for s in listed if s.get("name", "").lower() == skill_name.lower()),
                        None,
                    )
                    if match:
                        db_skill_body = await registry.read_skill(match["skill_id"])
                except Exception as exc:
                    self.logger.debug("DB skill lookup failed: %s", exc)

        if skill_def is None and db_skill_body is None:
            await self._send_text(
                turn_context,
                f"Skill '{skill_name}' not found. Use /skill to see available skills.",
            )
            return

        await self.wrapper.send_typing(turn_context)
        question = skill_input or f"Apply the '{skill_name}' skill."
        conversation_id = turn_context.activity.conversation.id
        self.logger.info("/skill %s — question: %s", skill_name, question[:100])

        from parrot.models.outputs import OutputMode

        if skill_def is not None:
            setattr(self.agent, "_active_skill", skill_def)
            try:
                response = await self.agent.ask(
                    question,
                    session_id=conversation_id,
                    output_mode=OutputMode.MSTEAMS,
                )
            finally:
                self.agent._active_skill = None
        else:
            framed = (
                f"Follow these skill instructions:\n\n{db_skill_body}\n\n"
                f"User request: {question}"
            )
            response = await self.agent.ask(
                framed,
                session_id=conversation_id,
                output_mode=OutputMode.MSTEAMS,
            )

        await self._send_result(turn_context, response)

    async def handle_question(self, turn_context) -> None:
        """Handle /question <text> -- ask the LLM without tools."""
        text = self._extract_text(turn_context)
        parts = text.split(maxsplit=1)

        if len(parts) < 2:
            await self._send_text(turn_context, "Usage: /question <your question>")
            return

        question = parts[1]
        await self.wrapper.send_typing(turn_context)
        conversation_id = turn_context.activity.conversation.id
        self.logger.info("/question: %s", question[:100])

        from parrot.models.outputs import OutputMode

        response = await self.agent.ask(
            question,
            use_tools=False,
            session_id=conversation_id,
            output_mode=OutputMode.MSTEAMS,
        )
        await self._send_result(turn_context, response)

    async def handle_commands(self, turn_context) -> None:
        """Handle /commands -- list all commands, tools, skills, agent methods."""
        lines = ["**Available Commands:**\n"]
        router = getattr(self.wrapper, "_command_router", None)
        if router is not None:
            for cmd in sorted(router.registered_commands):
                lines.append(f"- /{cmd}")

        methods = self._list_callable_methods()
        if methods:
            lines.append(f"\n**Agent Methods** (use /function):\n{methods}")

        tools = self._list_tools()
        if tools and tools != "(no tools available)":
            lines.append(f"\n**Tools** (use /tool):\n{tools}")

        skills = self._list_skills()
        if skills and skills != "(no skills available)":
            lines.append(f"\n**Skills** (use /skill):\n{skills}")

        await self._send_text(turn_context, "\n".join(lines))

    async def handle_help(self, turn_context) -> None:
        """Handle /help -- show help text."""
        agent_name = getattr(self.agent, "name", getattr(self.agent, "agent_id", "Agent"))
        description = getattr(self.agent, "description", "AI Agent")

        help_text = (
            f"**{agent_name}**\n{description}\n\n"
            "**Commands:**\n"
            "- /help -- Show this help\n"
            "- /commands -- List all commands, tools, skills\n"
            "- /function <method> [key=val] -- Call agent method\n"
            "- /call <method> [args] -- Call method (positional args)\n"
            "- /tool <name> [input] -- Use a specific tool\n"
            "- /skill <name> [input] -- Activate a skill\n"
            "- /question <text> -- Ask without tools\n"
            "- /whoami -- Show agent and user info\n"
            "- /clear -- Clear conversation history\n"
        )
        await self._send_text(turn_context, help_text)

    async def handle_whoami(self, turn_context) -> None:
        """Handle /whoami -- show agent info and user identity."""
        agent_name = getattr(self.agent, "name", getattr(self.agent, "agent_id", "Agent"))
        model = getattr(self.agent, "model", "unknown")
        tool_manager = getattr(self.agent, "tool_manager", None)
        tool_count = len(getattr(tool_manager, "_tools", {})) if tool_manager else 0
        user = turn_context.activity.from_property

        info = (
            f"**Agent:** {agent_name}\n"
            f"**Model:** {model}\n"
            f"**Tools:** {tool_count}\n\n"
            f"**User:** {getattr(user, 'name', 'unknown')}\n"
            f"**User ID:** {getattr(user, 'id', 'unknown')}\n"
        )
        await self._send_text(turn_context, info)

    async def handle_clear(self, turn_context) -> None:
        """Handle /clear -- clear conversation history."""
        await self.wrapper.conversation_state.clear_state(turn_context)
        await self.wrapper.conversation_state.save_changes(turn_context, force=True)
        await self._send_text(turn_context, "Conversation cleared.")

    # ------------------------------------------------------------------
    # Custom commands from config.commands
    # ------------------------------------------------------------------

    def _register_custom_commands(self, router: "MSTeamsCommandRouter") -> None:
        """Register custom commands from ``config.commands`` dict."""
        commands = getattr(self.wrapper.config, "commands", {}) or {}
        for cmd_name, method_name in commands.items():
            if not hasattr(self.agent, method_name) or not callable(
                getattr(self.agent, method_name)
            ):
                self.logger.warning(
                    "Custom command /%s -> %s: method not found, skipping",
                    cmd_name,
                    method_name,
                )
                continue
            router.register(cmd_name, self._make_custom_handler(cmd_name, method_name))
            self.logger.info("Registered custom command: /%s -> %s", cmd_name, method_name)

    def _make_custom_handler(self, cmd_name: str, method_name: str):
        """Create a closure handler for a custom config command."""
        async def handler(turn_context) -> None:
            text = self._extract_text(turn_context)
            parts = text.split(maxsplit=1)
            args_text = parts[1] if len(parts) > 1 else ""

            await self.wrapper.send_typing(turn_context)
            method = getattr(self.agent, method_name)
            kwargs = parse_kwargs(args_text)
            self.logger.info("/%s -> %s(%s)", cmd_name, method_name, kwargs)

            if asyncio.iscoroutinefunction(method):
                result = await method(**kwargs) if kwargs else await method()
            else:
                result = method(**kwargs) if kwargs else method()

            await self._send_result(
                turn_context, result, prefix=f"**{method_name}** result:\n\n"
            )

        return handler
