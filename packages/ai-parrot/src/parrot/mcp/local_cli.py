"""`parrot mcp-local` — serve an ``AbstractToolkit`` as a local stdio MCP server.

FEAT-485. Top-level lazy Click command registered in
``parrot.cli._lazy_commands["mcp-local"]``. The ``parrot mcp`` group is
owned by ai-parrot-server's ``parrot.mcp.cli`` module (merged PEP 420
namespace) — core cannot attach a subcommand to it, hence a sibling
top-level command instead (precedent: ``mcp-serve`` for agentd).

stdout is reserved for the JSON-RPC channel once the serve loop starts, so
all logging is redirected to stderr before the toolkit is resolved, and the
heavy imports (``toolkit_server`` -> toolkit classes) happen inside the
command function rather than at module import time.
"""

import asyncio
import logging
import sys
from pathlib import Path

import click


def _configure_stderr_logging() -> None:
    """Route root logging to stderr only — stdout is the JSON-RPC channel."""
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.WARNING)


def _print_toolkit_list(root: Path, config_path: Path | None = None) -> None:
    """Print resolvable toolkit names, enabled state, and class path.

    Deliberately does NOT import any toolkit class — only the config
    models (dotted-path strings) are loaded, keeping ``--list`` fast and
    side-effect free.

    Args:
        root: Project root to resolve ``.parrot/mcp-toolkits.yaml`` from.
        config_path: Optional explicit config file (``--config`` override).
    """
    from parrot.mcp.toolkit_config import load_toolkits_config

    cfg = load_toolkits_config(root, config_path=config_path)
    if not cfg.toolkits:
        click.echo("No toolkits resolvable.")
        return

    for name in sorted(cfg.toolkits):
        section = cfg.toolkits[name]
        state = "enabled" if section.enabled else "disabled"
        click.echo(f"{name}\t{state}\t{section.class_path}")


@click.command("mcp-local")
@click.argument("name", required=False, default=None)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(path_type=Path),
    help="Override .parrot/mcp-toolkits.yaml path.",
)
@click.option(
    "--include",
    "include",
    multiple=True,
    help="Whitelist a tool name for exposure (repeatable). Wins over --exclude.",
)
@click.option(
    "--exclude",
    "exclude",
    multiple=True,
    help="Blacklist a tool name from exposure (repeatable).",
)
@click.option(
    "--list",
    "list_toolkits",
    is_flag=True,
    default=False,
    help="List resolvable toolkit names (built-ins + config sections) and exit.",
)
def mcp_local(
    name: str | None,
    config_path: Path | None,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    list_toolkits: bool,
) -> None:
    """Serve NAME as a local stdio MCP server.

    The project root is the current working directory — the MCP host
    (Claude Code, Codex, ...) starts this process inside the project
    directory, and ``.parrot/mcp-toolkits.yaml`` is resolved relative to it.

    \b
    Examples:
      parrot mcp-local memory
      parrot mcp-local scraping --include scrape_url --include list_plans
      parrot mcp-local --list
    """
    root = Path.cwd()

    if list_toolkits:
        _print_toolkit_list(root, config_path)
        return

    if not name:
        click.echo("Error: NAME is required unless --list is given.", err=True)
        sys.exit(2)

    _configure_stderr_logging()

    # Heavy import (pulls in toolkit_config + eventually toolkit classes)
    # deferred to here so `parrot --help` / module import stay fast and
    # cannot pollute stdout.
    from parrot.mcp.toolkit_server import create_toolkit_mcp_server

    overrides: dict[str, object] = {}
    if config_path is not None:
        overrides["config_path"] = config_path
    if include:
        overrides["include"] = list(include)
    if exclude:
        overrides["exclude"] = list(exclude)

    try:
        server = create_toolkit_mcp_server(name, root, **overrides)
    except (ValueError, ImportError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        sys.exit(0)
