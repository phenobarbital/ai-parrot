"""Slash command dispatcher and built-in commands for the AI-Parrot agent REPL.

Provides ``SlashCommandDispatcher`` with built-in commands:
``/tools``, ``/info``, ``/clear``, ``/export``, ``/stream``, ``/help``,
``/resume``, ``/quit`` (aliased as ``/exit``).

Protocol note: handlers take a structural ``CommandContext`` (a
``typing.Protocol``), not a concrete presenter class — both the inline REPL
(TASK-3407) and ``TUICommandContext`` (Textual workspace, TASK-3411) satisfy
it without inheritance, which keeps this module free of any runtime import
of ``parrot.cli.repl`` (avoiding the circular import at ``repl.py:22``).
"""

import asyncio
import json
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ContextManager, Dict, List, Optional, Protocol

from parrot.cli.modes import load_session_pointer  # provided by TASK-3401

if TYPE_CHECKING:
    from parrot.cli.repl import REPLConfig  # verified: repl.py:61
    from parrot.cli.session import TurnRunner  # provided by TASK-3404


class RendererProtocol(Protocol):
    """What a slash-command handler may call on ``ctx.renderer`` (inline ``ResponseRenderer`` or the TUI adapter)."""

    def print(self, *args: Any, **kwargs: Any) -> None: ...
    def render(self, response: Any) -> None: ...
    def render_error(self, error: Exception) -> None: ...
    def render_table(self, headers: List[str], rows: List[List[str]], title: Optional[str] = None) -> None: ...
    def render_info(self, lines: List[tuple[str, str]]) -> None: ...
    def render_history(self, turns: List["ConversationTurn"], *, session_id: str) -> None: ...


class CommandContext(Protocol):
    """Host surface a handler may touch. Implemented by the inline REPL (TASK-3407) and ``TUICommandContext`` (tui/adapter.py, TASK-3411).

    ``renderer`` is declared as a read-only property (never reassigned by any
    handler or presenter) rather than a plain attribute, so mypy checks it
    covariantly: a presenter's ``ResponseRenderer``/``TUIRenderer`` -- both
    supersets of ``RendererProtocol`` -- correctly satisfy this Protocol
    without widening either concrete class's own ``self.renderer`` type.
    """

    bot: Any
    config: "REPLConfig"
    dispatcher: "SlashCommandDispatcher"
    runner: "TurnRunner"

    @property
    def renderer(self) -> RendererProtocol: ...

    @property
    def history(self) -> List["ConversationTurn"]: ...

    def suspend(self) -> ContextManager[None]:
        """Yield the terminal to a foreign prompt (HITL, device code): inline → ``LiveRegion.modal()``; TUI → ``App.suspend()``."""
        ...


@dataclass
class SlashCommand:
    """A registered slash command.

    Attributes:
        name: Command trigger string (without leading slash), e.g. ``tools``.
        description: Short description shown in ``/help``.
        handler: Async callable ``handler(ctx, args) -> None``.
    """

    name: str
    description: str
    handler: Callable  # async def handler(ctx: CommandContext, args: str) -> None


@dataclass
class ConversationTurn:
    """A single turn in the conversation history (used by ``/export``).

    Attributes:
        query: The user's input.
        response: The agent's ``AIMessage`` response.
        timestamp: When this turn occurred.
    """

    query: str
    response: Any  # AIMessage (typed loosely to avoid heavy import at module level)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the turn to a JSON-safe dictionary.

        Returns:
            Dictionary with ``query``, ``response``, and ``timestamp`` keys.
        """
        response_output = ""
        if self.response is not None:
            try:
                response_output = self.response.output or self.response.response or ""
            except AttributeError:
                response_output = str(self.response)
        return {
            "query": self.query,
            "response": str(response_output) if not isinstance(response_output, str) else response_output,
            "timestamp": self.timestamp.isoformat(),
        }


class SlashCommandDispatcher:
    """Dispatches slash commands in the agent REPL.

    Parses ``/command [args]`` strings and routes them to registered
    async handler functions. Unknown commands print the help listing.

    Attributes:
        logger: Module-level logger.
    """

    def __init__(self) -> None:
        """Initialise dispatcher and register built-in commands."""
        self.logger = logging.getLogger(__name__)
        self._commands: Dict[str, SlashCommand] = {}
        self._register_builtins()

    def register(self, cmd: SlashCommand) -> None:
        """Register a slash command.

        Args:
            cmd: The ``SlashCommand`` to register.
        """
        self._commands[cmd.name] = cmd
        self.logger.debug("Registered slash command: /%s", cmd.name)

    async def dispatch_async(self, input_text: str, ctx: "CommandContext") -> bool:
        """Parse and execute a slash command asynchronously.

        Preferred over ``dispatch()`` when called from an async context.

        Args:
            input_text: Raw input string from the user.
            ctx: The ``CommandContext`` instance.

        Returns:
            ``True`` if the input was a slash command, ``False`` otherwise.
        """
        if not input_text.startswith("/"):
            return False
        parts = input_text[1:].split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        # Resolve aliases
        if cmd_name == "exit":
            cmd_name = "quit"
        cmd = self._commands.get(cmd_name)
        if cmd is None:
            ctx.renderer.print(
                f"[yellow]Unknown command: /{cmd_name}[/yellow] — "
                f"type [bold]/help[/bold] to see available commands."
            )
            return True
        try:
            await cmd.handler(ctx, args)
        except SystemExit:
            raise
        except Exception as exc:
            ctx.renderer.render_error(exc)
        return True

    def get_completions(self) -> List[str]:
        """Return slash command names for tab completion.

        Returns:
            List of strings like ``["/tools", "/info", ...]``.
        """
        return [f"/{name}" for name in sorted(self._commands.keys())]

    # ------------------------------------------------------------------
    # Built-in command handlers
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        """Register all built-in slash commands."""
        builtins = [
            SlashCommand("tools", "List the agent's available tools.", _cmd_tools),
            SlashCommand("info", "Show agent and session information.", _cmd_info),
            SlashCommand("clear", "Reset conversation session (new session_id).", _cmd_clear),
            SlashCommand("resume", "Resume a prior conversation. Usage: /resume <session_id|last>", _cmd_resume),
            SlashCommand(
                "export",
                "Export conversation history to a JSON file. Usage: /export [path]",
                _cmd_export,
            ),
            SlashCommand("stream", "Toggle streaming mode on/off.", _cmd_stream),
            SlashCommand(
                "create_agent",
                "Run the AgentFactory to create a new agent. "
                "Usage: /create_agent <natural-language description> "
                "[--clone-from <name>] [--category <dir>]",
                _cmd_create_agent,
            ),
            SlashCommand("help", "List all available slash commands.", _cmd_help),
            SlashCommand("quit", "Exit the REPL.", _cmd_quit),
        ]
        for cmd in builtins:
            self.register(cmd)


# ------------------------------------------------------------------
# Built-in handler functions (module-level async functions)
# ------------------------------------------------------------------


async def _cmd_tools(ctx: "CommandContext", args: str) -> None:  # noqa: ARG001
    """Handle /tools command — list available tools.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Unused arguments.
    """
    tools = ctx.bot.get_available_tools()
    count = ctx.bot.get_tools_count()
    if not tools:
        ctx.renderer.print("[dim]No tools registered for this agent.[/dim]")
        return
    rows = [[tool] for tool in tools]
    ctx.renderer.render_table(
        headers=["Tool Name"],
        rows=rows,
        title=f"Available Tools ({count})",
    )


async def _cmd_info(ctx: "CommandContext", args: str) -> None:  # noqa: ARG001
    """Handle /info command — show agent and session info.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Unused arguments.
    """
    bot = ctx.bot
    config = ctx.config
    bot_class = type(bot).__name__
    # Try to get LLM provider/model info
    provider = getattr(bot, "provider", None) or getattr(bot, "_provider", "unknown")
    model = getattr(bot, "model", None) or getattr(bot, "_model", "unknown")
    tool_count = bot.get_tools_count()
    streaming_state = "enabled" if config.streaming else "disabled"
    ctx.renderer.render_info(
        [
            ("Agent name", config.agent_name),
            ("Class", bot_class),
            ("LLM provider", str(provider)),
            ("Model", str(model)),
            ("Session ID", config.session_id),
            ("User ID", str(config.user_id)),
            ("Tools", str(tool_count)),
            ("Streaming", streaming_state),
            ("Server URL", config.server_url or "(standalone)"),
        ]
    )


async def _cmd_clear(ctx: "CommandContext", args: str) -> None:  # noqa: ARG001
    """Handle /clear command — reset session with a new session_id.

    Session identity and history are owned by the ``TurnRunner`` (spec M5)
    so both the inline REPL and the Textual workspace observe the same reset.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Unused arguments.
    """
    old_id = ctx.config.session_id
    new_id = ctx.runner.reset_session()  # owns session identity + history (TASK-3404)
    ctx.renderer.print(
        f"[green]Session cleared.[/green] " f"New session ID: [bold]{new_id}[/bold] " f"(was: [dim]{old_id}[/dim])"
    )


async def _cmd_resume(ctx: "CommandContext", args: str) -> None:
    """Handle ``/resume <session_id|last>`` — re-render a prior session from bot-owned memory (spec G5/AC9).

    Args:
        ctx: The command context.
        args: Session id, or ``last`` to use the per-agent pointer written after each completed turn.
    """
    target = args.strip()
    if not target:
        ctx.renderer.print("[yellow]Usage:[/yellow] /resume <session_id|last>")
        return
    if not ctx.runner.capabilities.resume:
        ctx.renderer.print("[red]This backend cannot resume conversations (no history read path).[/red]")
        return
    if target == "last":
        pointer = await asyncio.to_thread(load_session_pointer, ctx.config.agent_name)
        if pointer is None:
            ctx.renderer.print("[yellow]No previous session recorded for this agent.[/yellow]")
            return
        target = pointer.last_session_id
    turns = await ctx.runner.load_history(target)
    if not turns:
        ctx.renderer.print(f"[yellow]No stored turns for session {target}[/yellow]")
        return
    ctx.renderer.render_history(turns, session_id=target)


async def _cmd_export(ctx: "CommandContext", args: str) -> None:
    """Handle /export [path] command — save conversation history to JSON.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Optional file path. Defaults to ``conversation_<session_id>.json``.
    """
    path = args.strip() if args.strip() else f"conversation_{ctx.config.session_id}.json"
    if not ctx.history:
        ctx.renderer.print("[yellow]No conversation history to export.[/yellow]")
        return
    # Path traversal guard — only applies to relative paths to prevent ../escape
    raw = Path(path)
    if not raw.is_absolute():
        resolved = os.path.realpath(raw)  # noqa: ASYNC240
        cwd = os.path.realpath(os.getcwd())  # noqa: ASYNC240
        if not resolved.startswith(cwd):
            ctx.renderer.print("[red]Export path must be within the current directory.[/red]")
            return
    turns = [turn.to_dict() for turn in ctx.history]
    export_data = {
        "session_id": ctx.config.session_id,
        "agent_name": ctx.config.agent_name,
        "user_id": ctx.config.user_id,
        "exported_at": datetime.now().isoformat(),
        "turns": turns,
    }
    try:

        def _write() -> None:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(export_data, fh, indent=2, ensure_ascii=False)

        await asyncio.to_thread(_write)
        ctx.renderer.print(f"[green]Conversation exported to:[/green] [bold]{path}[/bold] " f"({len(turns)} turn(s))")
    except OSError as exc:
        ctx.renderer.render_error(exc)


async def _cmd_stream(ctx: "CommandContext", args: str) -> None:  # noqa: ARG001
    """Handle /stream command — toggle streaming on/off.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Unused arguments.
    """
    ctx.config.streaming = not ctx.config.streaming
    state = "enabled" if ctx.config.streaming else "disabled"
    ctx.renderer.print(f"[cyan]Streaming {state}.[/cyan]")


async def _cmd_help(ctx: "CommandContext", args: str) -> None:  # noqa: ARG001
    """Handle /help command — list all available slash commands.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Unused arguments.
    """
    commands = sorted(ctx.dispatcher._commands.values(), key=lambda c: c.name)
    rows = [[f"/{cmd.name}", cmd.description] for cmd in commands]
    ctx.renderer.render_table(
        headers=["Command", "Description"],
        rows=rows,
        title="Available Slash Commands",
    )
    ctx.renderer.print("[dim]/exit is an alias for /quit[/dim]")


async def _cmd_quit(ctx: "CommandContext", args: str) -> None:  # noqa: ARG001
    """Handle /quit command — exit the REPL.

    Args:
        ctx: The active ``CommandContext`` instance.
        args: Unused arguments.

    Raises:
        SystemExit: Always raised to signal REPL exit.
    """
    ctx.renderer.print("[dim]Goodbye.[/dim]")
    raise SystemExit(0)


def _parse_create_agent_args(args: str) -> Dict[str, Any]:
    """Parse ``--clone-from X`` and ``--category Y`` flags out of ``args``.

    The remaining text is the natural-language description.
    """
    tokens = args.strip().split()
    parsed: Dict[str, Any] = {"description": "", "clone_from": None, "category": "general"}
    description: List[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--clone-from" and i + 1 < len(tokens):
            parsed["clone_from"] = tokens[i + 1]
            i += 2
            continue
        if tok == "--category" and i + 1 < len(tokens):
            parsed["category"] = tokens[i + 1]
            i += 2
            continue
        description.append(tok)
        i += 1
    parsed["description"] = " ".join(description)
    return parsed


async def _cmd_create_agent(ctx: "CommandContext", args: str) -> None:
    """Handle /create_agent — drive the AgentFactoryOrchestrator from the REPL.

    Builds a CLI-channel HumanInteractionManager on the fly, runs the
    orchestrator, and prints the FactoryResult. Both HITL checkpoints are
    delivered through the same CLI prompt the REPL already uses. The whole
    body runs inside ``ctx.suspend()`` so the HITL prompts get the screen
    (spec §7 "One writer at a time"): a no-op-ish ``LiveRegion.modal()``
    inline, ``App.suspend()`` in the TUI.
    """
    with ctx.suspend():
        parsed = _parse_create_agent_args(args)
        if not parsed["description"]:
            ctx.renderer.print(
                "[yellow]Usage:[/yellow] /create_agent <description> " "[--clone-from <name>] [--category <dir>]"
            )
            return

        # Local imports keep REPL startup snappy — factory pulls in pydantic +
        # the registry graph, which we do not want to pay for unless the user
        # actually invokes this command.
        from parrot.bots.factory import (
            AgentFactoryOrchestrator,
            FactoryRequest,
            FactoryStatus,
        )
        from parrot.human.channels import CLIHumanChannel
        from parrot.human.manager import HumanInteractionManager

        channel = CLIHumanChannel(console=getattr(ctx.renderer, "console", None))
        manager = HumanInteractionManager(channels={"cli": channel})
        await manager.startup()

        use_llm = getattr(ctx.bot, "_use_llm", None) or "google"
        orchestrator = AgentFactoryOrchestrator(
            human_manager=manager,
            human_channel="cli",
            human_targets=[ctx.config.user_id or "cli_user"],
            use_llm=use_llm,
            category=parsed["category"],
        )

        request = FactoryRequest(
            description=parsed["description"],
            clone_from=parsed["clone_from"],
        )

        ctx.renderer.print("[cyan]Routing your request to the factory…[/cyan]")
        result = await orchestrator.run(request)

        if result.status == FactoryStatus.SUCCESS:
            # FactoryResult.definition is populated only on SUCCESS (contracts.py docstring);
            # the None-guard is defensive narrowing for mypy, not an expected runtime path.
            agent_name = result.definition.name if result.definition is not None else "(unknown)"
            ctx.renderer.print(f"[green]Agent created:[/green] [bold]{agent_name}[/bold] → {result.yaml_path}")
        elif result.status == FactoryStatus.CANCELLED_BY_USER:
            checkpoint = result.cancelled_at.value if result.cancelled_at is not None else "unknown checkpoint"
            ctx.renderer.print(f"[yellow]Cancelled at {checkpoint}.[/yellow]")
        elif result.status == FactoryStatus.TIMEOUT:
            checkpoint = result.cancelled_at.value if result.cancelled_at is not None else "unknown checkpoint"
            ctx.renderer.print(f"[yellow]Timed out at {checkpoint}.[/yellow]")
        else:
            ctx.renderer.print(f"[red]Factory failed:[/red] {result.error or 'unknown'}")
