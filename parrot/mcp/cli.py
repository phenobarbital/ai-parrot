import asyncio
import sys
import importlib.util
from importlib import import_module
from pathlib import Path
from typing import Optional
import yaml
import click
from navconfig.logging import logging
from .server import MCPServer, MCPServerConfig
from ..tools.abstract import AbstractTool
from ..tools.toolkit import AbstractToolkit
from ..services.mcp.server import ParrotMCPServer, TransportConfig


@click.group()
def mcp():
    """MCP server commands."""
    pass


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

    logger.info(f"Loaded {len(tools)} tools")

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
        logger.info(f"Starting MCP server in {transport_config.transport} mode...")
        await server.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        await server.stop()
