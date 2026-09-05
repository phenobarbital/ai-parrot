import asyncio
import json
import os
import signal
import sys
import importlib.util
from importlib import import_module
from pathlib import Path
from typing import Optional
import yaml
import click
from navconfig.logging import logging
from .server import MCPServer, MCPServerConfig
from parrot.tools.abstract import AbstractTool
from parrot.tools.toolkit import AbstractToolkit
from .parrot_server import ParrotMCPServer, TransportConfig


@click.group(invoke_without_command=True)
@click.option('--config', type=click.Path(exists=True), help='Path to YAML configuration file')
@click.pass_context
def mcp(ctx, config):
    """MCP server commands."""
    if ctx.invoked_subcommand is None:
        if config:
            # Run server from config
            from .wrapper import load_server_from_config
            try:
                server = load_server_from_config(config)
                # SimpleMCPServer.run() is blocking and handles the loop internally for http/sse
                # If we need async start for stdio/etc and simple.py run() does it, we assume it works.
                server.run()
            except Exception as e:
                click.echo(f"Error starting server: {e}", err=True)
                sys.exit(1)
        else:
            click.echo(ctx.get_help())


@mcp.command()
@click.argument('config_file', type=click.Path(exists=True))
@click.option(
    '--transport', type=click.Choice(['stdio', 'unix', 'http']), default=None,
        help='Override transport from config')
@click.option(
    '--socket', type=str, default=None,
            help='Unix socket path (for unix transport)')
@click.option(
    '--port', type=int, default=None,
            help='Port (for http transport)')
@click.option(
    '--log-level', type=str, default='INFO',
            help='Logging level')
def serve(
    config_file: str, transport: Optional[str], socket: Optional[str],
        port: Optional[int], log_level: str):
    """
    Start an MCP server from a Python config file or YAML.

    Examples:

        # Python config file
        parrot mcp serve workday_server.py --transport unix --socket /tmp/workday.sock

        # YAML config file
        parrot mcp serve mcp_config.yaml

    Python config file should define 'mcp' variable:

        # workday_server.py
        from parrot.services import ParrotMCPServer
        from parrot.toolkits.workday import WorkdayToolkit

        mcp = ParrotMCPServer(
            name="workday-mcp",
            tools=WorkdayToolkit(redis_url="redis://localhost:6379/4")
        )
    """
    config_path = Path(config_file)

    if config_path.suffix in {'.yaml', '.yml'}:
        mcp_server = _load_from_yaml(config_path)
    elif config_path.suffix == '.py':
        mcp_server = _load_from_python(config_path)
    else:
        click.echo(f"Error: Unsupported config file type: {config_path.suffix}", err=True)
        sys.exit(1)

    # Override settings from CLI
    if transport:
        # Need to update transport config
        mcp_server.transport_configs = {
            transport: _create_transport_config(transport, socket, port)
        }

    # Set log level
    logging.getLogger().setLevel(log_level)

    # Run the server
    asyncio.run(_run_standalone_server(mcp_server))


def _load_from_python(config_path: Path) -> 'ParrotMCPServer':
    """Load ParrotMCPServer from Python file."""


    spec = importlib.util.spec_from_file_location("mcp_config", config_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, 'mcp'):
        raise ValueError(
            f"Config file {config_path} must define 'mcp' variable "
            "containing a ParrotMCPServer instance"
        )

    return module.mcp


def _load_from_yaml(config_path: Path) -> ParrotMCPServer:
    """Load ParrotMCPServer from YAML file."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Parse tools from YAML
    tools_config = {
        tool_entry['class']: tool_entry['module']
        for tool_entry in config.get('tools', [])
    }

    # Parse transports
    transports = config.get('transport', 'stdio')

    return ParrotMCPServer(
        name=config.get('name', 'ai-parrot-mcp'),
        description=config.get('description', 'AI-Parrot MCP Server'),
        transports=transports,
        tools=tools_config,
        **config.get('server_config', {})
    )


def _create_transport_config(transport: str, socket: Optional[str], port: Optional[int]):
    """Create TransportConfig from CLI args."""
    return TransportConfig(
        transport=transport,
        host="127.0.0.1" if transport == "http" else None,
        port=port if transport == "http" else None,
    )


async def _run_standalone_server(mcp_server: ParrotMCPServer):
    """Run MCP server in standalone mode (no aiohttp app)."""
    logger = logging.getLogger("parrot.mcp.serve")

    # Load tools
    tools = await mcp_server._load_configured_tools()
    if not tools:
        logger.error("No tools configured")
        sys.exit(1)

    logger.info("Loaded %s tools", len(tools))

    # Get transport config (should be single transport in CLI mode)
    if len(mcp_server.transport_configs) != 1:
        logger.error("CLI mode requires exactly one transport")
        sys.exit(1)

    transport_key, transport_config = list(mcp_server.transport_configs.items())[0]

    # Create MCP server
    config = MCPServerConfig(
        name=mcp_server.name,
        description=mcp_server.description,
        transport=transport_config.transport,
        host=transport_config.host,
        port=transport_config.port,
        socket_path=transport_config.socket_path if hasattr(transport_config, 'socket_path') else None,
        log_level=mcp_server.log_level,
    )

    server = MCPServer(config)
    server.register_tools(tools)

    # Start and run
    try:
        logger.info("Starting MCP server in %s mode...", transport_config.transport)
        await server.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await server.stop()


# ── Obscura lifecycle commands (FEAT-530) ────────────────────────
#
# `ObscuraProcessManager` (parrot.mcp.obscura) tracks process ownership
# only in-process (`_owns_process`), which is correct for an embedded,
# long-lived caller (an agent process) but cannot survive across two
# separate CLI invocations (`start` in one process, `stop`/`status` in
# another). These commands therefore delegate lifecycle *decisions* to
# `ObscuraProcessManager` (start/readiness, CDP status probing) but use
# a small PID-file adapter (`default_pid_file`/`write_pid_file`/
# `read_pid_file`/`remove_pid_file`, also in `parrot.mcp.obscura`) to
# find the process again on `stop`. Never launches Chrome/Selenium as a
# fallback.


@mcp.group("obscura")
def obscura_group():
    """Supervised Obscura process lifecycle commands (FEAT-530)."""


@obscura_group.command("start")
@click.option(
    "--binary", "binary_path", required=True,
    help="Path to (or PATH-resolvable name of) the Obscura binary.",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="CDP bind host.")
@click.option("--port", default=9222, show_default=True, type=int, help="CDP port.")
@click.option(
    "--stealth", is_flag=True, default=False,
    help="Enable Obscura's stealth mode.",
)
@click.option(
    "--allow-private-network", is_flag=True, default=False,
    help=(
        "Enable --allow-private-network. Required for local fixtures; "
        "do not enable by default in general deployments."
    ),
)
@click.option(
    "--attach-only", is_flag=True, default=False,
    help="Adopt an already-running endpoint instead of spawning a new process.",
)
@click.option(
    "--startup-timeout", default=10.0, show_default=True, type=float,
    help="Seconds to wait for the CDP endpoint to become ready.",
)
def obscura_start(
    binary_path, host, port, stealth, allow_private_network, attach_only,
    startup_timeout,
):
    """Start (or adopt) the supervised Obscura process."""
    asyncio.run(
        _obscura_start(
            binary_path, host, port, stealth, allow_private_network,
            attach_only, startup_timeout,
        )
    )


async def _obscura_start(
    binary_path, host, port, stealth, allow_private_network, attach_only,
    startup_timeout,
):
    from .obscura import (
        ObscuraProcessConfig,
        ObscuraProcessManager,
        default_pid_file,
        write_pid_file,
    )

    config = ObscuraProcessConfig(
        binary_path=binary_path,
        host=host,
        port=port,
        stealth=stealth,
        allow_private_network=allow_private_network,
        attach_only=attach_only,
        startup_timeout=startup_timeout,
    )
    manager = ObscuraProcessManager(config)
    try:
        endpoint = await manager.start()
    except RuntimeError as exc:
        click.echo(f"Error starting Obscura: {exc}", err=True)
        sys.exit(1)
        return

    if manager.process is not None:
        write_pid_file(default_pid_file(port), manager.process.pid)
    click.echo(f"Obscura ready at {endpoint}")


@obscura_group.command("stop")
@click.option(
    "--port", default=9222, show_default=True, type=int,
    help="CDP port of the supervised process to stop.",
)
def obscura_stop(port):
    """Stop a previously started supervised Obscura process."""
    asyncio.run(_obscura_stop(port))


async def _obscura_stop(port):
    from .obscura import default_pid_file, read_pid_file, remove_pid_file

    pid_file = default_pid_file(port)
    pid = read_pid_file(pid_file)
    if pid is None:
        click.echo(
            f"No supervised Obscura process found for port {port} "
            f"(no PID file at {pid_file}).",
            err=True,
        )
        sys.exit(1)
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        click.echo(f"Obscura process {pid} was already gone.", err=True)
        remove_pid_file(pid_file)
        return
    except OSError as exc:
        click.echo(f"Error stopping Obscura process {pid}: {exc}", err=True)
        sys.exit(1)
        return

    remove_pid_file(pid_file)
    click.echo(f"Stopped Obscura process {pid} on port {port}.")


@obscura_group.command("status")
@click.option("--host", default="127.0.0.1", show_default=True, help="CDP host to probe.")
@click.option("--port", default=9222, show_default=True, type=int, help="CDP port to probe.")
def obscura_status(host, port):
    """Report whether a supervised Obscura CDP endpoint is responsive."""
    asyncio.run(_obscura_status(host, port))


async def _obscura_status(host, port):
    from .obscura import (
        ObscuraProcessConfig,
        ObscuraProcessManager,
        default_pid_file,
        read_pid_file,
    )

    # attach_only=True: a status probe must never spawn a process — it
    # only reports what's currently observable (CDP readiness + any
    # known PID file), regardless of who started it.
    config = ObscuraProcessConfig(
        binary_path="obscura", host=host, port=port, attach_only=True,
    )
    manager = ObscuraProcessManager(config)
    status = await manager.status()
    status["pid"] = read_pid_file(default_pid_file(port))
    click.echo(json.dumps(status))


@obscura_group.command("mcp-config")
@click.option(
    "--binary", "binary_path", default=None,
    help="Path to (or PATH-resolvable name of) the Obscura binary.",
)
@click.option("--name", default="obscura", show_default=True, help="MCP server name.")
@click.option(
    "--port", default=9222, show_default=True, type=int,
    help="CDP port Obscura's native MCP mode should use internally.",
)
@click.option("--stealth", is_flag=True, default=False, help="Enable Obscura's stealth mode.")
@click.option(
    "--allow-private-network", is_flag=True, default=False,
    help="Enable --allow-private-network.",
)
def obscura_mcp_config(binary_path, name, port, stealth, allow_private_network):
    """Print the native `obscura mcp` stdio config (for Codex/MCP hosts).

    This is the documented command/config path for native Obscura MCP:
    paste the printed ``command``/``args`` into any MCP host's stdio
    server configuration (Codex, Claude Code, etc.), or use
    ``parrot.mcp.integration.create_obscura_mcp_server()`` /
    ``MCPEnabledMixin.add_obscura_mcp_server()`` directly from Python.
    """
    from parrot.mcp.integration import create_obscura_mcp_server

    config = create_obscura_mcp_server(
        binary_path=binary_path,
        name=name,
        port=port,
        stealth=stealth,
        allow_private_network=allow_private_network,
    )
    click.echo(
        json.dumps(
            {
                "name": config.name,
                "command": config.command,
                "args": config.args,
                "transport": config.transport,
            },
            indent=2,
        )
    )
