"""Slash command dispatcher and built-in commands for the AI-Parrot agent REPL.

Provides ``SlashCommandDispatcher`` with built-in commands:
``/tools``, ``/info``, ``/clear``, ``/export``, ``/stream``, ``/help``,
``/quit`` (aliased as ``/exit``).

Forward reference note: ``AgentREPL`` is imported under ``TYPE_CHECKING``
only to avoid circular imports — the actual type is resolved at runtime.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List
from uuid import uuid4

if TYPE_CHECKING:
    from parrot.cli.repl import AgentREPL

@dataclass
class SlashCommand:
    """A registered slash command.

    Attributes:
        name: Command trigger string (without leading slash), e.g. ``tools``.
        description: Short description shown in ``/help``.
        handler: Async callable ``handler(repl, args) -> None``.
    """

    name: str
    description: str
    handler: Callable  # async def handler(repl: AgentREPL, args: str) -> None


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

    async def dispatch_async(self, input_text: str, repl: "AgentREPL") -> bool:
        """Parse and execute a slash command asynchronously.

        Preferred over ``dispatch()`` when called from an async context.

        Args:
            input_text: Raw input string from the user.
            repl: The ``AgentREPL`` instance.

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
            repl.renderer.print(
                f"[yellow]Unknown command: /{cmd_name}[/yellow] — "
                f"type [bold]/help[/bold] to see available commands."
            )
            return True
        try:
            await cmd.handler(repl, args)
        except SystemExit:
            raise
        except Exception as exc:
            repl.renderer.render_error(exc)
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


async def _cmd_tools(repl: "AgentREPL", args: str) -> None:  # noqa: ARG001
    """Handle /tools command — list available tools.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Unused arguments.
    """
    tools = repl.bot.get_available_tools()
    count = repl.bot.get_tools_count()
    if not tools:
        repl.renderer.print("[dim]No tools registered for this agent.[/dim]")
        return
    rows = [[tool] for tool in tools]
    repl.renderer.render_table(
        headers=["Tool Name"],
        rows=rows,
        title=f"Available Tools ({count})",
    )


async def _cmd_info(repl: "AgentREPL", args: str) -> None:  # noqa: ARG001
    """Handle /info command — show agent and session info.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Unused arguments.
    """
    bot = repl.bot
    config = repl.config
    bot_class = type(bot).__name__
    # Try to get LLM provider/model info
    provider = getattr(bot, "provider", None) or getattr(bot, "_provider", "unknown")
    model = getattr(bot, "model", None) or getattr(bot, "_model", "unknown")
    tool_count = bot.get_tools_count()
    streaming_state = "enabled" if config.streaming else "disabled"
    repl.renderer.render_info([
        ("Agent name", config.agent_name),
        ("Class", bot_class),
        ("LLM provider", str(provider)),
        ("Model", str(model)),
        ("Session ID", config.session_id),
        ("User ID", config.user_id),
        ("Tools", str(tool_count)),
        ("Streaming", streaming_state),
        ("Server URL", config.server_url or "(standalone)"),
    ])


async def _cmd_clear(repl: "AgentREPL", args: str) -> None:  # noqa: ARG001
    """Handle /clear command — reset session with a new session_id.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Unused arguments.
    """
    old_id = repl.config.session_id
    repl.config.session_id = str(uuid4())
    repl.history.clear()
    repl.renderer.print(
        f"[green]Session cleared.[/green] "
        f"New session ID: [bold]{repl.config.session_id}[/bold] "
        f"(was: [dim]{old_id}[/dim])"
    )


async def _cmd_export(repl: "AgentREPL", args: str) -> None:
    """Handle /export [path] command — save conversation history to JSON.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Optional file path. Defaults to ``conversation_<session_id>.json``.
    """
    path = args.strip() if args.strip() else f"conversation_{repl.config.session_id}.json"
    if not repl.history:
        repl.renderer.print("[yellow]No conversation history to export.[/yellow]")
        return
    # Path traversal guard — only applies to relative paths to prevent ../escape
    raw = Path(path)
    if not raw.is_absolute():
        resolved = raw.resolve()
        cwd = Path.cwd().resolve()
        if not str(resolved).startswith(str(cwd)):
            repl.renderer.print("[red]Export path must be within the current directory.[/red]")
            return
    turns = [turn.to_dict() for turn in repl.history]
    export_data = {
        "session_id": repl.config.session_id,
        "agent_name": repl.config.agent_name,
        "user_id": repl.config.user_id,
        "exported_at": datetime.now().isoformat(),
        "turns": turns,
    }
    try:
        def _write() -> None:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(export_data, fh, indent=2, ensure_ascii=False)

        await asyncio.to_thread(_write)
        repl.renderer.print(
            f"[green]Conversation exported to:[/green] [bold]{path}[/bold] "
            f"({len(turns)} turn(s))"
        )
    except OSError as exc:
        repl.renderer.render_error(exc)


async def _cmd_stream(repl: "AgentREPL", args: str) -> None:  # noqa: ARG001
    """Handle /stream command — toggle streaming on/off.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Unused arguments.
    """
    repl.config.streaming = not repl.config.streaming
    state = "enabled" if repl.config.streaming else "disabled"
    repl.renderer.print(f"[cyan]Streaming {state}.[/cyan]")


async def _cmd_help(repl: "AgentREPL", args: str) -> None:  # noqa: ARG001
    """Handle /help command — list all available slash commands.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Unused arguments.
    """
    commands = sorted(repl.dispatcher._commands.values(), key=lambda c: c.name)
    rows = [[f"/{cmd.name}", cmd.description] for cmd in commands]
    repl.renderer.render_table(
        headers=["Command", "Description"],
        rows=rows,
        title="Available Slash Commands",
    )
    repl.renderer.print("[dim]/exit is an alias for /quit[/dim]")


async def _cmd_quit(repl: "AgentREPL", args: str) -> None:  # noqa: ARG001
    """Handle /quit command — exit the REPL.

    Args:
        repl: The active ``AgentREPL`` instance.
        args: Unused arguments.

    Raises:
        SystemExit: Always raised to signal REPL exit.
    """
    repl.renderer.print("[dim]Goodbye.[/dim]")
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


async def _cmd_create_agent(repl: "AgentREPL", args: str) -> None:
    """Handle /create_agent — drive the AgentFactoryOrchestrator from the REPL.

    Builds a CLI-channel HumanInteractionManager on the fly, runs the
    orchestrator, and prints the FactoryResult. Both HITL checkpoints are
    delivered through the same CLI prompt the REPL already uses.
    """
    parsed = _parse_create_agent_args(args)
    if not parsed["description"]:
        repl.renderer.print(
            "[yellow]Usage:[/yellow] /create_agent <description> "
            "[--clone-from <name>] [--category <dir>]"
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

    channel = CLIHumanChannel(console=getattr(repl.renderer, "console", None))
    manager = HumanInteractionManager(channels={"cli": channel})
    await manager.startup()

    use_llm = getattr(repl.bot, "_use_llm", None) or "google"
    orchestrator = AgentFactoryOrchestrator(
        human_manager=manager,
        human_channel="cli",
        human_targets=[repl.config.user_id or "cli_user"],
        use_llm=use_llm,
        category=parsed["category"],
    )

    request = FactoryRequest(
        description=parsed["description"],
        clone_from=parsed["clone_from"],
    )

    repl.renderer.print("[cyan]Routing your request to the factory…[/cyan]")
    result = await orchestrator.run(request)

    if result.status == FactoryStatus.SUCCESS:
        repl.renderer.print(
            f"[green]Agent created:[/green] "
            f"[bold]{result.definition.name}[/bold] → {result.yaml_path}"
        )
    elif result.status == FactoryStatus.CANCELLED_BY_USER:
        repl.renderer.print(
            f"[yellow]Cancelled at {result.cancelled_at.value}.[/yellow]"
        )
    elif result.status == FactoryStatus.TIMEOUT:
        repl.renderer.print(
            f"[yellow]Timed out at {result.cancelled_at.value}.[/yellow]"
        )
    else:
        repl.renderer.print(f"[red]Factory failed:[/red] {result.error or 'unknown'}")
