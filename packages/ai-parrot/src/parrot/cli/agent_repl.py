"""Click command entry point for the AI-Parrot agent REPL.

Provides the ``parrot agent`` subcommand. Resolves the agent (standalone or
server mode), resolves the presentation mode (``--ui``/TTY state/``TERM``),
builds ``REPLConfig`` and a ``TurnRunner``, and launches either the inline
REPL (interactive or batch) or the full-screen Textual workspace.

The function name must be ``agent`` to match the LazyGroup key:
``cli._lazy_commands = {..., "agent": "parrot.cli.agent_repl"}``.
``LazyGroup.get_command()`` uses ``getattr(mod, cmd_name)`` — i.e.
``getattr(module, "agent")``.
"""

import asyncio
import logging
import os
import sys
from typing import Optional, Set

import click

from parrot.cli.console import get_console  # provided by TASK-3400
from parrot.cli.identity import bot_declares_o365_device_code, build_cli_permission_context
from parrot.cli.loaders import AgentLoadError, ServerAgentProxy, StandaloneAgentLoader
from parrot.cli.modes import (  # provided by TASK-3401
    UIMode,
    UIModeError,
    history_path,
    is_interactive,
    load_session_pointer,
    resolve_ui_mode,
)
from parrot.cli.renderer import ResponseRenderer
from parrot.cli.repl import AgentREPL, REPLConfig
from parrot.cli.session import TurnRunner  # provided by TASK-3404

# NOTE: no `from rich.console import Console` and no `parrot.cli.tui` import at module level (AC12, AC22)

logger = logging.getLogger(__name__)
console = get_console()


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
@click.option(
    "--ui",
    type=click.Choice(["auto", "inline", "tui"]),
    default="auto",
    show_default=True,
    help="Interface: full-screen workspace (tui), classic inline console (inline), or detect (auto).",
)
@click.option(
    "--session",
    "session",
    default=None,
    metavar="ID|last",
    help="Resume a prior conversation session.",
)
@click.option(
    "--user",
    "user_id",
    default=None,
    metavar="USER_ID",
    help="Identity sent with each request (standalone only; refused with --server).",
)
@click.option(
    "--token",
    envvar="PARROT_SERVER_TOKEN",
    default=None,
    help="Bearer token for --server mode.",
)
@click.option(
    "--no-history",
    is_flag=True,
    default=False,
    help="Do not persist composer history.",
)
def agent(
    name: Optional[str],
    list_agents: bool,
    server: Optional[str],
    no_stream: bool,
    ui: str,
    session: Optional[str],
    user_id: Optional[str],
    token: Optional[str],
    no_history: bool,
) -> None:
    """Interactive workspace / console for AI-Parrot agents.

    Loads the named agent (or prompts for selection) and drops into either
    the full-screen Textual workspace or the classic inline console.
    Supports both standalone mode (default) and server-proxy mode
    (``--server URL``).

    Args:
        name: Optional agent name.  If omitted, an interactive picker is shown.
        list_agents: If True, list registered agents and exit.
        server: Optional server URL for server-proxy mode.
        no_stream: If True, disable streaming and use batch rendering.
        ui: Requested presentation mode (``auto``/``inline``/``tui``).
        session: Optional session id to resume, or ``last`` for the most recent one.
        user_id: Optional identity sent with each request (standalone only).
        token: Optional bearer token for ``--server`` mode (``PARROT_SERVER_TOKEN``).
        no_history: If True, do not persist composer history to disk.
    """
    try:
        asyncio.run(_run(name, list_agents, server, no_stream, ui, session, user_id, token, no_history))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")


async def _run(
    name: Optional[str],
    list_agents: bool,
    server: Optional[str],
    no_stream: bool,
    ui: str = "auto",
    session: Optional[str] = None,
    user_id: Optional[str] = None,
    token: Optional[str] = None,
    no_history: bool = False,
) -> None:
    """Async implementation of ``parrot agent`` (spec §3 Module 13 sequence).

    Args:
        name: Optional agent name.
        list_agents: Whether to list agents and exit.
        server: Optional server URL.
        no_stream: Whether to disable streaming.
        ui: Requested presentation mode (``auto``/``inline``/``tui``).
        session: Optional session id to resume, or ``last``.
        user_id: Optional identity for standalone mode.
        token: Optional bearer token for server mode.
        no_history: Whether to disable composer history persistence.
    """
    renderer = ResponseRenderer()
    loader: ServerAgentProxy | StandaloneAgentLoader

    if server:
        loader = ServerAgentProxy(server, token=token)
    else:
        loader = StandaloneAgentLoader()

    # --list: show agent table and exit
    if list_agents:
        await _handle_list(loader, renderer, server)
        return

    stdin_tty, stdout_tty = sys.stdin.isatty(), sys.stdout.isatty()
    interactive = is_interactive(stdin_isatty=stdin_tty, stdout_isatty=stdout_tty)

    try:
        mode = resolve_ui_mode(
            UIMode(ui), stdin_isatty=stdin_tty, stdout_isatty=stdout_tty, term=os.environ.get("TERM")
        )
    except UIModeError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        raise SystemExit(2) from exc

    if not interactive and name is None:
        console.print("[bold red]Error:[/bold red] agent name required when stdin is not a terminal.")
        raise SystemExit(2)

    if server and user_id:  # Q8 / AC27
        console.print(
            "[bold red]Error:[/bold red] --user is not allowed with --server; identity comes from the bearer "
            "token (--token / PARROT_SERVER_TOKEN)."
        )
        raise SystemExit(2)

    # Resolve agent name (prompt if omitted) — only reached when interactive
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

    resume_id = session
    if session == "last":
        pointer = await asyncio.to_thread(load_session_pointer, name)
        if pointer is None:
            console.print(f"[yellow]No previous session for {name}[/yellow]")
            resume_id = None
        else:
            resume_id = pointer.last_session_id

    streaming = not no_stream

    # Build config and runner
    config = REPLConfig(
        agent_name=name,
        streaming=streaming,
        server_url=server,
        permission_context=permission_context,
        ui_mode=mode,
        resume_session_id=resume_id,
        server_token=token,
        history_enabled=not no_history,
        user_id=None if server else (user_id or "cli-user"),
    )
    if resume_id:
        config.session_id = resume_id

    runner = TurnRunner(bot, config, capabilities=getattr(bot, "capabilities", None))

    exit_code = 0
    try:
        if mode is UIMode.TUI:
            from parrot.cli.commands import SlashCommandDispatcher  # noqa: PLC0415 — lazy on purpose (AC22)
            from parrot.cli.tui.app import AgentWorkspaceApp  # noqa: PLC0415 — lazy on purpose (AC22)
            from prompt_toolkit.history import FileHistory, InMemoryHistory  # noqa: PLC0415

            history = FileHistory(str(history_path(name))) if config.history_enabled else InMemoryHistory()
            resume_turns = await runner.load_history(resume_id) if resume_id else None
            app = AgentWorkspaceApp(
                bot=bot,
                config=config,
                runner=runner,
                dispatcher=SlashCommandDispatcher(),
                history=history,
                resume_turns=resume_turns,
            )
            exit_code = int(await app.run_async() or 0)
        else:
            repl = AgentREPL(bot=bot, config=config, renderer=renderer, runner=runner)
            if not interactive:
                exit_code = await repl.run_batch(sys.stdin)
            else:
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
        # Clean up bot resources (aiohttp sessions, DB connections, etc.)
        # to avoid "Unclosed client session" warnings on exit.
        if hasattr(bot, "cleanup") and callable(bot.cleanup):
            try:
                await bot.cleanup()
            except Exception:
                logger.debug("Bot cleanup error (ignored on exit)", exc_info=True)

    if exit_code:
        raise SystemExit(exit_code)


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
            tags: Set[str] = getattr(agent_item, "tags", set()) or set()
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
    console.print("[dim]Type your message to chat.  " "Use /help for slash commands.  Ctrl+D or /quit to exit.[/dim]\n")
