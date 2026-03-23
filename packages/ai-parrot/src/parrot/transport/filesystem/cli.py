"""CLI overlay for FilesystemTransport — human-in-the-loop observation and messaging."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List

from .config import FilesystemTransportConfig
from .feed import ActivityFeed
from .registry import AgentRegistry

logger = logging.getLogger(__name__)

try:
    import click

    _HAS_CLICK = True
except ImportError:
    _HAS_CLICK = False

try:
    from rich.console import Console
    from rich.table import Table

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False


class CrewCLI:
    """Read-only CLI view into the FilesystemTransport state.

    Reads directly from the filesystem — no running transport process
    is required.

    Args:
        root_dir: Root directory of the FilesystemTransport data.
    """

    def __init__(self, root_dir: Path) -> None:
        self._root = Path(root_dir)
        config = FilesystemTransportConfig(root_dir=self._root)
        self._registry = AgentRegistry(self._root / "registry", config)
        self._feed = ActivityFeed(self._root / "feed.jsonl", config)

    async def get_state(self) -> Dict[str, Any]:
        """Read current system state from the filesystem.

        Returns:
            Dict with ``agents`` (list of agent dicts) and ``feed``
            (list of recent event dicts).
        """
        agents = await self._registry.list_active()
        feed = await self._feed.tail(50)
        return {"agents": agents, "feed": feed}

    def render_text(self, state: Dict[str, Any]) -> str:
        """Render state as plain text.

        Args:
            state: State dict from ``get_state()``.

        Returns:
            Human-readable text representation.
        """
        lines: List[str] = []
        agents = state.get("agents", [])
        feed = state.get("feed", [])

        lines.append("=" * 60)
        lines.append("  FilesystemTransport — Agent Status")
        lines.append("=" * 60)
        lines.append(f"  {len(agents)} agentes activos")
        lines.append("")

        if agents:
            for a in agents:
                name = a.get("name", "?")
                status = a.get("status", "unknown")
                role = a.get("role", "agent")
                pid = a.get("pid", "?")
                icon = "o" if status == "idle" else "*"
                lines.append(f"  [{icon}] {name}  ({role}, PID {pid})  status={status}")
        else:
            lines.append("  (no agents registered)")

        lines.append("")
        lines.append("-" * 60)
        lines.append("  Recent Activity Feed")
        lines.append("-" * 60)

        if feed:
            for entry in feed[-20:]:
                ts = entry.get("ts", "")
                event = entry.get("event", "?")
                # Shorten timestamp for display.
                short_ts = ts[11:19] if len(ts) > 19 else ts
                detail = ""
                if "agent_id" in entry:
                    detail = f" agent={entry['agent_id']}"
                elif "from" in entry:
                    detail = f" from={entry['from']}"
                lines.append(f"  {short_ts}  {event}{detail}")
        else:
            lines.append("  (no events)")

        lines.append("=" * 60)
        return "\n".join(lines)

    def render_rich(self, state: Dict[str, Any]) -> None:
        """Render state using ``rich`` for formatted terminal output.

        Args:
            state: State dict from ``get_state()``.
        """
        console = Console()
        agents = state.get("agents", [])
        feed = state.get("feed", [])

        console.rule("[bold]FilesystemTransport — Agent Status[/bold]")
        console.print(f"  {len(agents)} agentes activos\n")

        if agents:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Name")
            table.add_column("Role")
            table.add_column("PID")
            table.add_column("Status")
            for a in agents:
                table.add_row(
                    a.get("name", "?"),
                    a.get("role", "agent"),
                    str(a.get("pid", "?")),
                    a.get("status", "unknown"),
                )
            console.print(table)
        else:
            console.print("  [dim](no agents registered)[/dim]")

        console.rule("[bold]Recent Activity Feed[/bold]")
        if feed:
            for entry in feed[-20:]:
                ts = entry.get("ts", "")
                event = entry.get("event", "?")
                short_ts = ts[11:19] if len(ts) > 19 else ts
                console.print(f"  [dim]{short_ts}[/dim]  {event}")
        else:
            console.print("  [dim](no events)[/dim]")


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from synchronous context."""
    return asyncio.get_event_loop().run_until_complete(coro)


if _HAS_CLICK:

    @click.command("parrot-crew")
    @click.option(
        "--root",
        type=click.Path(exists=False),
        default=".parrot",
        help="Root directory for transport data.",
    )
    @click.option("--watch", is_flag=True, help="Live watch mode (refresh every second).")
    @click.option("--send", nargs=2, type=str, default=None, help="Send a message: --send AGENT MESSAGE")
    @click.option("--feed", "feed_count", type=int, default=None, help="Show last N feed events.")
    def main(
        root: str,
        watch: bool,
        send: tuple[str, str] | None,
        feed_count: int | None,
    ) -> None:
        """FilesystemTransport CLI overlay — observe agents and send messages."""
        root_path = Path(root)
        cli = CrewCLI(root_path)

        if send is not None:
            agent_name, message = send
            _run_send(root_path, agent_name, message)
            return

        if feed_count is not None:
            state = _run_async(cli.get_state())
            feed_entries = state.get("feed", [])[-feed_count:]
            state["feed"] = feed_entries
            _display(cli, state)
            return

        if watch:
            _run_watch(cli)
            return

        # Default: snapshot.
        state = _run_async(cli.get_state())
        _display(cli, state)

    def _display(cli: CrewCLI, state: Dict[str, Any]) -> None:
        """Display state using rich if available, else plain text."""
        if _HAS_RICH:
            cli.render_rich(state)
        else:
            click.echo(cli.render_text(state))

    def _run_send(root_path: Path, agent_name: str, message: str) -> None:
        """Send a message to an agent via a temporary transport."""
        from .transport import FilesystemTransport

        async def _do_send() -> None:
            config = FilesystemTransportConfig(root_dir=root_path)
            async with FilesystemTransport(
                agent_name="human-cli", config=config
            ) as t:
                msg_id = await t.send(agent_name, message)
                click.echo(f"Sent {msg_id} to {agent_name}")

        _run_async(_do_send())

    def _run_watch(cli: CrewCLI) -> None:
        """Watch mode: refresh state every second."""

        async def _loop() -> None:
            try:
                while True:
                    click.clear()
                    state = await cli.get_state()
                    if _HAS_RICH:
                        cli.render_rich(state)
                    else:
                        click.echo(cli.render_text(state))
                    await asyncio.sleep(1.0)
            except KeyboardInterrupt:
                pass

        _run_async(_loop())

else:
    # click not installed — provide a no-op main.
    def main() -> None:  # type: ignore[misc]
        """CLI requires click. Install with: uv pip install click"""
        print("Error: click is required for the CLI overlay. Install with: uv pip install click")
