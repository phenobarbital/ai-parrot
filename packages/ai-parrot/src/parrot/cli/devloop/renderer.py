"""Run renderer — Rich Live envelope painter for ``parrot devloop``.

Polls ``SessionHost.replay_since(last_seq)`` on a ticker and maps action
types to Rich renderables in a scrolling Live region. Read-only
relationship with the host — never calls ``apply`` or ``resolve_gate``.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Type

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.15  # seconds between replay_since polls
_MAX_DELTA_LINES = 40  # cap streaming text tail


class RunView:
    """Renders a single dev-loop run's action stream in the terminal."""

    def __init__(
        self,
        host: Any,  # SessionHost
        console: Optional[Console] = None,
        *,
        run_id: str = "",
    ) -> None:
        self.host = host
        self.console = console or Console()
        self.run_id = run_id or getattr(host, "state", None) and host.state.run_id or "?"
        self._last_seq = 0
        self._live: Optional[Live] = None
        self._paused = False
        self._stop = False
        self._renderables: List[Any] = []
        self._current_node: str = ""
        self._delta_buffer: str = ""
        self._delta_lines = 0
        self._tool_uses: List[str] = []
        self.logger = logging.getLogger(__name__)

    def poll_once(self) -> List[Any]:
        """Poll for new envelopes since last seen sequence."""
        envelopes = self.host.replay_since(self._last_seq)
        for env in envelopes:
            if env.server_seq > self._last_seq:
                self._last_seq = env.server_seq
            self._render_envelope(env)
        return envelopes

    def _render_envelope(self, envelope: Any) -> None:
        """Map an ActionEnvelope to a Rich renderable via dispatch table."""
        action = envelope.action
        action_type = getattr(action, "type", "")
        handler = _ACTION_HANDLERS.get(action_type)
        if handler:
            handler(self, action)
        else:
            self._add_line(Text(f"  [{action_type}]", style="dim"))

    def _add_line(self, renderable: Any) -> None:
        self._renderables.append(renderable)
        if len(self._renderables) > 200:
            self._renderables = self._renderables[-150:]

    def pending_gates(self) -> Dict[str, Any]:
        """Return currently pending gates from host state."""
        gates = getattr(self.host.state, "gates", {})
        return {
            gid: gate for gid, gate in gates.items()
            if getattr(gate, "status", "") == "pending"
        }

    def pause(self) -> None:
        """Pause the live display (for modal prompts)."""
        self._paused = True
        if self._live:
            self._live.stop()

    def resume(self) -> None:
        """Resume the live display after a modal prompt."""
        self._paused = False
        if self._live:
            self._live.start()

    def stop(self) -> None:
        """Signal the run_live loop to stop."""
        self._stop = True

    async def run_live(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Run the Rich Live display loop, polling for new envelopes."""
        self._stop = False
        stop = stop_event or asyncio.Event()

        with Live(
            self._build_display(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        ) as live:
            self._live = live
            while not self._stop and not stop.is_set():
                if not self._paused:
                    self.poll_once()
                    live.update(self._build_display())
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_POLL_INTERVAL)
                    break
                except asyncio.TimeoutError:
                    pass
            self._live = None

    def _build_display(self) -> Group:
        """Build the current display from accumulated renderables."""
        header = self._build_header()
        items = [header] + list(self._renderables[-80:])
        return Group(*items)

    def _build_header(self) -> Panel:
        """Build a header panel with run status."""
        state = self.host.state
        phase = getattr(state, "phase", "unknown")
        summary = getattr(state, "summary", "")
        jira = getattr(state, "jira_issue_key", "")
        pr = getattr(state, "pr_url", "")

        parts = [f"[bold]Run:[/bold] {self.run_id}  [bold]Phase:[/bold] {phase}"]
        if summary:
            parts.append(f"  [dim]{summary}[/dim]")
        if jira:
            parts.append(f"  [cyan]Jira:[/cyan] {jira}")
        if pr:
            parts.append(f"  [green]PR:[/green] {pr}")

        return Panel(
            Text.from_markup("".join(parts)),
            border_style="blue",
            padding=(0, 1),
        )

    # ── Action handlers ─────────────────────────────────────────────────

    def _handle_run_created(self, action: Any) -> None:
        kind = getattr(action, "work_kind", "")
        summary = getattr(action, "summary", "")
        self._add_line(Text(f"  Run created ({kind}: {summary})", style="bold green"))

    def _handle_run_cancelled(self, action: Any) -> None:
        by = getattr(action, "requested_by", "")
        self._add_line(Text(f"  Run cancelled by {by}", style="bold red"))

    def _handle_run_closed(self, action: Any) -> None:
        outcome = getattr(action, "outcome", "")
        style = "bold green" if outcome == "succeeded" else "bold red"
        self._add_line(Text(f"  Run closed: {outcome}", style=style))

    def _handle_node_started(self, action: Any) -> None:
        node_id = getattr(action, "node_id", "")
        self._current_node = node_id
        self._delta_buffer = ""
        self._delta_lines = 0
        self._tool_uses = []
        self._add_line(Text.from_markup(f"  [bold cyan][{node_id}][/bold cyan] started..."))

    def _handle_node_completed(self, action: Any) -> None:
        node_id = getattr(action, "node_id", "")
        self._add_line(Text(f"  [{node_id}] completed", style="green"))
        self._current_node = ""

    def _handle_node_failed(self, action: Any) -> None:
        node_id = getattr(action, "node_id", "")
        error = getattr(action, "error", "")
        self._add_line(Text(f"  [{node_id}] FAILED: {error}", style="bold red"))
        self._current_node = ""

    def _handle_node_skipped(self, action: Any) -> None:
        node_id = getattr(action, "node_id", "")
        self._add_line(Text(f"  [{node_id}] skipped", style="dim"))

    def _handle_dispatch_queued(self, action: Any) -> None:
        node_id = getattr(action, "node_id", "")
        dispatcher = getattr(action, "dispatcher", "")
        self._add_line(Text(f"    dispatch queued ({dispatcher})", style="dim"))

    def _handle_dispatch_started(self, action: Any) -> None:
        self._add_line(Text("    dispatch started", style="dim cyan"))

    def _handle_dispatch_delta(self, action: Any) -> None:
        # DispatchDelta has no text field — just bump counter
        self._delta_lines += 1

    def _handle_dispatch_tool_use(self, action: Any) -> None:
        tool = getattr(action, "tool_name", "")
        self._tool_uses.append(tool)
        self._add_line(Text(f"    tool: {tool}", style="yellow"))

    def _handle_dispatch_tool_result(self, action: Any) -> None:
        pass  # no-op for display

    def _handle_dispatch_output_invalid(self, action: Any) -> None:
        error = getattr(action, "error", "")
        self._add_line(Text(f"    output invalid: {error}", style="red"))

    def _handle_dispatch_failed(self, action: Any) -> None:
        error = getattr(action, "error", "")
        self._add_line(Text(f"    dispatch FAILED: {error}", style="bold red"))

    def _handle_dispatch_completed(self, action: Any) -> None:
        self._add_line(Text("    dispatch completed", style="green"))

    def _handle_gate_opened(self, action: Any) -> None:
        gate = getattr(action, "gate", None)
        if gate:
            kind = getattr(gate, "kind", "")
            title = getattr(gate, "title", "")
            gate_id = getattr(gate, "gate_id", "")
            self._add_line(
                Panel(
                    f"[bold yellow]GATE[/bold yellow] {kind}: {title}\n"
                    f"ID: {gate_id}",
                    border_style="yellow",
                    title="Approval Required",
                )
            )

    def _handle_gate_resolved(self, action: Any) -> None:
        gate_id = getattr(action, "gate_id", "")
        resolution = getattr(action, "resolution", "")
        by = getattr(action, "resolved_by", "")
        style = "green" if resolution == "approved" else "red"
        self._add_line(Text(f"  Gate {gate_id} {resolution} by {by}", style=style))

    def _handle_gate_expired(self, action: Any) -> None:
        gate_id = getattr(action, "gate_id", "")
        self._add_line(Text(f"  Gate {gate_id} expired", style="dim red"))

    def _handle_jira_linked(self, action: Any) -> None:
        key = getattr(action, "issue_key", "")
        self._add_line(Text(f"  Jira: {key}", style="cyan"))

    def _handle_pr_linked(self, action: Any) -> None:
        url = getattr(action, "pr_url", "")
        self._add_line(Text(f"  PR: {url}", style="green"))


# ── Dispatch table ──────────────────────────────────────────────────────────

_ACTION_HANDLERS: Dict[str, Any] = {
    "run/created": RunView._handle_run_created,
    "run/cancelled": RunView._handle_run_cancelled,
    "run/closed": RunView._handle_run_closed,
    "node/started": RunView._handle_node_started,
    "node/completed": RunView._handle_node_completed,
    "node/failed": RunView._handle_node_failed,
    "node/skipped": RunView._handle_node_skipped,
    "dispatch/queued": RunView._handle_dispatch_queued,
    "dispatch/started": RunView._handle_dispatch_started,
    "dispatch/delta": RunView._handle_dispatch_delta,
    "dispatch/tool_use": RunView._handle_dispatch_tool_use,
    "dispatch/tool_result": RunView._handle_dispatch_tool_result,
    "dispatch/output_invalid": RunView._handle_dispatch_output_invalid,
    "dispatch/failed": RunView._handle_dispatch_failed,
    "dispatch/completed": RunView._handle_dispatch_completed,
    "gate/opened": RunView._handle_gate_opened,
    "gate/resolved": RunView._handle_gate_resolved,
    "gate/expired": RunView._handle_gate_expired,
    "jira/linked": RunView._handle_jira_linked,
    "pr/linked": RunView._handle_pr_linked,
}
