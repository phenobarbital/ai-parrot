"""Click commands for the Agent CLI Daemon (agentd) — Module 9.

Lazily registered into the existing core ``parrot`` `LazyGroup` (see
``packages/ai-parrot/src/parrot/cli/__init__.py``) under the keys
``serve``, ``attach``, ``ask``, ``status``, ``install-service``,
``mcp-serve``. Function names MUST match those keys (with ``-`` -> ``_``)
since ``LazyGroup.get_command()`` resolves them via
``getattr(mod, cmd_name.replace("-", "_"))``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import click
from parrot.cli.renderer import ResponseRenderer
from parrot.cli.repl import AgentREPL, REPLConfig
from rich.console import Console
from rich.markdown import Markdown

from .client import AgentDaemonClient, DaemonNotRunning, RpcRemoteError, resolve_socket
from .config import AgentServiceConfig
from .mcp_server import run_mcp_proxy
from .proxy import DaemonAgentProxy, register_daemon_commands
from .service import AgentDaemon

console = Console()

__all__ = [
    "ask",
    "attach",
    "install_service",
    "mcp_serve",
    "serve",
    "status",
]


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------


@click.command("serve")
@click.argument("config_or_target")
@click.option(
    "--name", default=None, help="Service name (required for a module:attr target)."
)
@click.option(
    "--socket", "socket_path", default=None, type=click.Path(), help="Explicit UDS socket path."
)
@click.option("--dsn", default=None, help="Postgres DSN for schedule persistence.")
@click.option(
    "--redis/--no-redis",
    "use_redis",
    default=None,
    help="Attach a Redis-backed jobstore.",
)
@click.option("--log-level", default=None, help="Logging level (e.g. INFO, DEBUG).")
def serve(
    config_or_target: str,
    name: str | None,
    socket_path: str | None,
    dsn: str | None,
    use_redis: bool | None,
    log_level: str | None,
) -> None:
    """Run a per-agent daemon in the foreground.

    CONFIG_OR_TARGET is either a path to a YAML config file (``.yaml``/
    ``.yml``) or a Python ``module:attr`` target (class, instance, or
    sync/async factory).
    """
    try:
        cfg = _build_serve_config(config_or_target, name, socket_path, dsn, use_redis, log_level)
    except click.ClickException:
        raise
    except Exception as exc:
        click.echo(f"Error building agentd config: {exc}", err=True)
        raise SystemExit(1) from exc

    try:
        asyncio.run(AgentDaemon(cfg).run())
    except KeyboardInterrupt:
        pass


def _build_serve_config(
    config_or_target: str,
    name: str | None,
    socket_path: str | None,
    dsn: str | None,
    use_redis: bool | None,
    log_level: str | None,
) -> AgentServiceConfig:
    """Build an `AgentServiceConfig` from CLI args (YAML file or target)."""
    path = Path(config_or_target)
    if path.is_file() and path.suffix.lower() in (".yaml", ".yml"):
        cfg = AgentServiceConfig.from_yaml(path)
        if name:
            cfg = cfg.model_copy(update={"name": name})
    else:
        if not name:
            raise click.UsageError(
                "--name is required when serving directly from a module:attr target."
            )
        cfg = AgentServiceConfig.from_target(config_or_target, name=name)

    overrides: dict[str, Any] = {}
    if socket_path:
        overrides["socket"] = Path(socket_path)
    if log_level:
        overrides["log_level"] = log_level
    if overrides:
        cfg = cfg.model_copy(update=overrides)

    scheduler_overrides: dict[str, Any] = {}
    if dsn is not None:
        scheduler_overrides["dsn"] = dsn
    if use_redis is not None:
        scheduler_overrides["redis"] = use_redis
    if scheduler_overrides:
        cfg = cfg.model_copy(
            update={"scheduler": cfg.scheduler.model_copy(update=scheduler_overrides)}
        )

    return cfg


# --------------------------------------------------------------------------
# attach
# --------------------------------------------------------------------------


@click.command("attach")
@click.argument("name_or_socket")
@click.option(
    "--no-stream",
    is_flag=True,
    default=False,
    help="Disable streaming; wait for the full response before rendering.",
)
def attach(name_or_socket: str, no_stream: bool) -> None:
    """Attach the interactive Rich console to a running agentd daemon."""
    try:
        asyncio.run(_run_attach(name_or_socket, no_stream))
    except SystemExit:
        raise
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")


async def _run_attach(name_or_socket: str, no_stream: bool) -> None:
    """Async implementation of the `attach` command."""
    renderer = ResponseRenderer()
    proxy = DaemonAgentProxy(name_or_socket)

    try:
        bot = await proxy.load(name_or_socket)
    except DaemonNotRunning as exc:
        console.print(f"[bold red]Cannot attach:[/bold red] {exc}")
        console.print(
            "[dim]Check 'systemctl --user status parrot-<name>' or start it "
            "with 'parrot serve <config.yaml|module:attr>'.[/dim]"
        )
        raise SystemExit(1) from exc

    display_name = bot.name
    try:
        agents = await proxy.list_agents()
        if agents:
            display_name = agents[0].get("name", display_name)
            bot.name = display_name
    except RpcRemoteError:
        pass  # Cosmetic only -- keep going with the fallback name.

    config = REPLConfig(agent_name=display_name, streaming=not no_stream)
    repl = AgentREPL(bot=bot, config=config, renderer=renderer)
    register_daemon_commands(repl, proxy)
    _wrap_with_event_drain(repl, proxy)

    console.print(
        f"\n[bold green]Attached to daemon:[/bold green] [bold]{display_name}[/bold]"
    )
    console.print(
        "[dim]Type your message to chat.  Use /help for slash commands "
        "(including /status, /schedules, /invoke).  Ctrl+D or /quit to "
        "exit.[/dim]\n"
    )

    try:
        await repl.run()
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[bold red]REPL error:[/bold red] {exc}")
        raise SystemExit(1) from exc
    finally:
        await proxy.close()


def _wrap_with_event_drain(repl: AgentREPL, proxy: DaemonAgentProxy) -> None:
    """Flush queued job-event lines after each turn, never mid-stream.

    `AgentREPL.run()`'s loop is a monolithic method with no exposed
    post-turn hook, and modifying `parrot.cli.repl` is out of scope for
    this feature. Instead, this wraps `repl.send`/`repl.send_stream` at
    the INSTANCE level (shadowing the class methods `run()` calls) so
    queued events print right after a turn completes and before the next
    prompt is shown -- the same seam the spec calls for, achieved without
    touching core.
    """
    original_send = repl.send
    original_send_stream = repl.send_stream

    async def _send_with_drain(query: str):
        result = await original_send(query)
        _print_drained_events(proxy)
        return result

    async def _send_stream_with_drain(query: str) -> None:
        await original_send_stream(query)
        _print_drained_events(proxy)

    repl.send = _send_with_drain
    repl.send_stream = _send_stream_with_drain


def _print_drained_events(proxy: DaemonAgentProxy) -> None:
    """Print every queued job-event line, then clear the queue."""
    for line in proxy.drain_events():
        console.print(f"[dim]{line}[/dim]")


# --------------------------------------------------------------------------
# ask
# --------------------------------------------------------------------------


@click.command("ask")
@click.argument("name_or_socket")
@click.argument("question")
def ask(name_or_socket: str, question: str) -> None:
    """One-shot, pipe-friendly question to a running agentd daemon.

    Renders Markdown when stdout is a TTY, plain text otherwise (no ANSI
    in pipes/CI). Exits 0 on success, 1 on error.
    """
    asyncio.run(_run_ask(name_or_socket, question))


async def _run_ask(name_or_socket: str, question: str) -> None:
    """Async implementation of the `ask` command."""
    socket_path = resolve_socket(name_or_socket)
    try:
        client = await AgentDaemonClient.connect(socket_path)
    except DaemonNotRunning as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc

    try:
        try:
            result = await client.call(
                "chat.send", prompt=question, stream=False, metadata={}
            )
        except RpcRemoteError as exc:
            click.echo(f"Error: {exc}", err=True)
            raise SystemExit(1) from exc
    finally:
        await client.close()

    output = result.get("output", "")
    if sys.stdout.isatty():
        console.print(Markdown(output))
    else:
        click.echo(output)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


@click.command("status")
@click.argument("name_or_socket")
def status(name_or_socket: str) -> None:
    """Pretty-print a running agentd daemon's status."""
    asyncio.run(_run_status(name_or_socket))


async def _run_status(name_or_socket: str) -> None:
    """Async implementation of the `status` command."""
    socket_path = resolve_socket(name_or_socket)
    try:
        client = await AgentDaemonClient.connect(socket_path)
    except DaemonNotRunning as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1) from exc

    try:
        result = await client.call("daemon.status")
    finally:
        await client.close()

    scheduler = result.get("scheduler", {})
    ResponseRenderer().render_info(
        [
            ("PID", str(result.get("pid"))),
            ("Uptime (s)", f"{result.get('uptime_s', 0):.1f}"),
            ("Version", str(result.get("version"))),
            ("Scheduler available", str(scheduler.get("available"))),
            ("Scheduler running", str(scheduler.get("running"))),
            ("Scheduled jobs", str(scheduler.get("jobs"))),
            ("Active connections", str(result.get("active_connections"))),
        ]
    )


# --------------------------------------------------------------------------
# install-service
# --------------------------------------------------------------------------


@click.command("install-service")
@click.argument("config_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--system",
    "system_mode",
    is_flag=True,
    default=False,
    help="Print a system-wide unit instead of writing a user unit (never writes to /etc, never sudo).",
)
def install_service(config_path: str, system_mode: bool) -> None:
    """Generate a systemd unit file for an agentd daemon."""
    cfg_path = Path(config_path).resolve()
    try:
        cfg = AgentServiceConfig.from_yaml(cfg_path)
    except Exception as exc:
        click.echo(f"Error reading config: {exc}", err=True)
        raise SystemExit(1) from exc

    unit_text = _render_unit(cfg.name, cfg_path)

    if system_mode:
        click.echo(unit_text)
        click.echo(
            "\n# --system prints ONLY -- this command never writes to /etc "
            "or escalates privileges. To install system-wide, save the unit "
            f"above as /etc/systemd/system/parrot-{cfg.name}.service as root, "
            "then run:\n"
            "#   sudo systemctl daemon-reload\n"
            f"#   sudo systemctl enable --now parrot-{cfg.name}",
            err=True,
        )
        return

    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / f"parrot-{cfg.name}.service"
    unit_path.write_text(unit_text, encoding="utf-8")

    click.echo(f"Wrote {unit_path}")
    click.echo("Next steps:")
    click.echo("  systemctl --user daemon-reload")
    click.echo(f"  systemctl --user enable --now parrot-{cfg.name}")


def _render_unit(name: str, config_path: Path) -> str:
    """Render the systemd unit file content for one agentd service."""
    parrot_bin = Path(sys.executable).parent / "parrot"
    return (
        "[Unit]\n"
        f"Description=AI-Parrot Agent Daemon: {name}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=notify\n"
        f"ExecStart={parrot_bin} serve {config_path}\n"
        "Restart=on-failure\n"
        "Environment=PYTHONUNBUFFERED=1\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


# --------------------------------------------------------------------------
# mcp-serve
# --------------------------------------------------------------------------


@click.command("mcp-serve")
@click.argument("name_or_socket")
def mcp_serve(name_or_socket: str) -> None:
    """Run an MCP stdio proxy exposing an agentd daemon to external LLMs."""
    try:
        asyncio.run(run_mcp_proxy(name_or_socket))
    except KeyboardInterrupt:
        pass
