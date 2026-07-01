"""Click command entry point for the AI-Parrot agent REPL.

Provides the ``parrot agent`` subcommand. Resolves the agent (standalone or
server mode), builds ``REPLConfig``, and launches ``AgentREPL.run()``.

The function name must be ``agent`` to match the LazyGroup key:
``cli._lazy_commands = {..., "agent": "parrot.cli.agent_repl"}``.
``LazyGroup.get_command()`` uses ``getattr(mod, cmd_name)`` — i.e.
``getattr(module, "agent")``.
"""
import asyncio
import logging
from typing import Optional

import click
from rich.console import Console

from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context
from parrot.cli.loaders import AgentLoadError, ServerAgentProxy, StandaloneAgentLoader
from parrot.cli.repl import AgentREPL, REPLConfig
from parrot.cli.renderer import ResponseRenderer

logger = logging.getLogger(__name__)
console = Console()


@click.command("agent")
@click.argument("name", required=False, default=None)
@click.option(
    "--list",
    "list_agents",
    is_flag=True,
    default=False,
    help="List all registered agents and exit.",
)
@click.option(
    "--server",
    default=None,
    metavar="URL",
    help="Connect to a running AI-Parrot server at URL.",
)
@click.option(
    "--no-stream",
    is_flag=True,
    default=False,
    help="Disable streaming; wait for the full response before rendering.",
)
def agent(
    name: Optional[str],
    list_agents: bool,
    server: Optional[str],
    no_stream: bool,
) -> None:
    """Interactive REPL for AI-Parrot agents.

    Loads the named agent (or prompts for selection) and drops into an
    interactive console session.  Supports both standalone mode (default)
    and server-proxy mode (``--server URL``).

    Args:
        name: Optional agent name.  If omitted, an interactive picker is shown.
        list_agents: If True, list registered agents and exit.
        server: Optional server URL for server-proxy mode.
        no_stream: If True, disable streaming and use batch rendering.
    """
    try:
        asyncio.run(_run(name, list_agents, server, no_stream))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")


async def _run(
    name: Optional[str],
    list_agents: bool,
    server: Optional[str],
    no_stream: bool,
) -> None:
    """Async implementation of the ``agent`` Click command.

    Args:
        name: Optional agent name.
        list_agents: Whether to list agents and exit.
        server: Optional server URL.
        no_stream: Whether to disable streaming.
    """
    renderer = ResponseRenderer()
    loader: ServerAgentProxy | StandaloneAgentLoader

    if server:
        loader = ServerAgentProxy(server)
    else:
        loader = StandaloneAgentLoader()

    # --list: show agent table and exit
    if list_agents:
        await _handle_list(loader, renderer, server)
        return

    # Resolve agent name (prompt if omitted)
    if name is None:
        try:
            name = await loader.select_agent()
        except AgentLoadError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from exc

    # Load the agent
    try:
        bot = await loader.load(name)
    except AgentLoadError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1) from exc
    except Exception as exc:
        console.print(f"[bold red]Unexpected error loading agent:[/bold red] {exc}")
        logger.exception("Agent load failure")
        raise SystemExit(1) from exc

    # Print welcome banner
    _print_banner(bot, name, server)

    # FEAT-266: bootstrap the device-code permission context ONLY when this
    # agent actually declares the o365 device_code provider — agents that
    # don't are completely unaffected (no O365_PRINCIPAL requirement).
    permission_context = None
    if not server and bot_declares_o365_device_code(bot):
        try:
            permission_context = build_cli_permission_context()
        except RuntimeError as exc:
            console.print(f"[bold red]O365 device-code identity error:[/bold red] {exc}")
            raise SystemExit(1) from exc

    # Build config and run the REPL
    config = REPLConfig(
        agent_name=name,
        streaming=not no_stream,
        server_url=server,
        permission_context=permission_context,
    )
    repl = AgentREPL(bot=bot, config=config, renderer=renderer)

    try:
        await repl.run()
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[bold red]REPL error:[/bold red] {exc}")
        logger.exception("REPL loop failure")
        raise SystemExit(1) from exc
    finally:
        if server and isinstance(loader, ServerAgentProxy):
            await loader.close()


async def _handle_list(
    loader: "ServerAgentProxy | StandaloneAgentLoader",
    renderer: ResponseRenderer,
    server: Optional[str],
) -> None:
    """List registered agents and display them in a Rich table.

    Args:
        loader: The agent loader (standalone or server proxy).
        renderer: The response renderer for table output.
        server: Whether server mode is active (for display purposes).
    """
    try:
        agents = await loader.list_agents()
    except AgentLoadError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    if not agents:
        console.print("[yellow]No agents registered.[/yellow]")
        return

    headers = ["Name", "Class", "Tags", "Source"]
    rows = []
    for agent_item in agents:
        if isinstance(agent_item, dict):
            # Server mode: dict from JSON
            name_val = agent_item.get("name", "?")
            class_val = agent_item.get("class", "?")
            tags_val = ", ".join(agent_item.get("tags", []))
            source_val = server or "server"
        else:
            # Standalone mode: BotMetadata dataclass
            name_val = getattr(agent_item, "name", "?")
            factory = getattr(agent_item, "factory", None)
            class_val = factory.__name__ if factory and hasattr(factory, "__name__") else str(factory)
            tags = getattr(agent_item, "tags", set()) or set()
            tags_val = ", ".join(sorted(tags))
            source_val = "standalone"
        rows.append([name_val, class_val, tags_val, source_val])

    title = "Registered Agents" if not server else f"Agents on {server}"
    renderer.render_table(headers=headers, rows=rows, title=title)


def _print_banner(bot: object, name: str, server: Optional[str]) -> None:
    """Print a welcome banner after the agent loads.

    Args:
        bot: The loaded bot instance.
        name: Agent name.
        server: Server URL (or None for standalone).
    """
    bot_class = type(bot).__name__
    tool_count = 0
    has_tools = False
    try:
        tool_count = bot.get_tools_count()  # type: ignore[attr-defined]
        has_tools = bot.has_tools()  # type: ignore[attr-defined]
    except AttributeError:
        pass

    mode = f"server ({server})" if server else "standalone"
    console.print(
        f"\n[bold green]Agent loaded:[/bold green] [bold]{name}[/bold] "
        f"([dim]{bot_class}[/dim]) • mode=[cyan]{mode}[/cyan]"
        + (f" • tools=[magenta]{tool_count}[/magenta]" if has_tools else "")
    )
    console.print(
        "[dim]Type your message to chat.  "
        "Use /help for slash commands.  Ctrl+D or /quit to exit.[/dim]\n"
    )
