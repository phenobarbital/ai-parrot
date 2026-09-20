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
import contextlib
import logging
import os
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from parrot.mcp.local_server import StdioMCPServer

logger = logging.getLogger(__name__)


async def _serve_with_shutdown(server: "StdioMCPServer") -> None:
    """Run `server.start()`, handling SIGTERM without hanging the process.

    `StdioMCPServer.start()` reads stdin via
    `loop.run_in_executor(None, sys.stdin.readline)`. Once that blocking
    read is in flight, its task cannot be cancelled — a
    `concurrent.futures.Future` refuses cancellation once it is already
    running — so a SIGTERM handler that merely cancels the running task
    (or relies on `asyncio.run()`'s own teardown, which joins the default
    executor) would hang the process for as long as the MCP host keeps
    stdin open (FEAT-580 M4). `loop.add_signal_handler` instead delivers
    the signal through the loop's self-pipe, which the loop can service
    even while that read is still pending, so this shutdown path never
    waits on it: on SIGTERM it restores the prior handler, drives the
    server's own bounded `stop()` (which releases any owned toolkit
    resources), and then forces the process to exit directly with
    `os._exit()` — which also reaps the still-blocked reader thread,
    covering the actual process exit path a graceful `asyncio.run()`
    teardown cannot.

    Args:
        server: The server whose `start()` should run, and whose `stop()`
            releases owned resources on shutdown.
    """
    loop = asyncio.get_running_loop()
    prior_handler = signal.getsignal(signal.SIGTERM)
    installed = False

    def _restore_handler() -> None:
        nonlocal installed
        if not installed:
            return
        installed = False
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.remove_signal_handler(signal.SIGTERM)
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal.SIGTERM, prior_handler)

    async def _on_sigterm() -> None:
        # Restore first: whether or not the bounded stop() below succeeds,
        # a second SIGTERM must fall through to the platform's default
        # disposition rather than re-entering this handler.
        _restore_handler()
        try:
            await server.stop()
        except Exception:  # noqa: BLE001 -- best-effort; we exit regardless
            logger.exception("Error while shutting down mcp-local on SIGTERM")
        finally:
            os._exit(0)

    def _sigterm_callback() -> None:
        asyncio.ensure_future(_on_sigterm())

    try:
        loop.add_signal_handler(signal.SIGTERM, _sigterm_callback)
        installed = True
    except NotImplementedError:
        # Event loops without POSIX signal support (e.g. Windows'
        # ProactorEventLoop) fall back to default SIGTERM handling.
        pass

    try:
        await server.start()
    finally:
        _restore_handler()


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

    Every name comes from a section declared in
    ``.parrot/mcp-toolkits.yaml`` — nothing resolves implicitly (FEAT-570).
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
    help="List resolvable toolkit names (sections declared in .parrot/mcp-toolkits.yaml) and exit.",
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
        # An unknown name (not a configured section) is the hard cut's only
        # migration aid — name the exact fix. An ImportError (the class path
        # resolves to a missing distribution) needs a different fix, so it
        # is left to its own message rather than advised to reinstall the
        # toolkit config, which cannot help it.
        if isinstance(exc, ValueError) and str(exc).startswith("Unknown toolkit name:"):
            click.echo(
                f"No toolkit named {name!r} is configured. Install it with: " f"parrot toolkits install {name}",
                err=True,
            )
        sys.exit(1)

    try:
        asyncio.run(_serve_with_shutdown(server))
    except KeyboardInterrupt:
        sys.exit(0)
