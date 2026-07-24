"""Console engine — session, slash commands, gates for ``parrot devloop``.

``DevLoopConsole`` orchestrates: wizard → dispatch → Rich Live rendering →
interactive gate resolution → slash commands. Modal terminal discipline:
one writer at a time (pause/resume Live around prompts).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from parrot.cli.devloop.renderer import RunView

logger = logging.getLogger(__name__)

_GATE_POLL_INTERVAL = 0.25  # seconds


class DevLoopConsole:
    """Interactive console session for dev-loop flows."""

    def __init__(
        self,
        *,
        console: Optional[Console] = None,
        session: Optional[PromptSession] = None,
    ) -> None:
        self.console = console or Console()
        self._session = session or PromptSession()
        self._runtime: Any = None  # DevLoopRuntime
        self._runs: Dict[str, asyncio.Task] = {}
        self._views: Dict[str, RunView] = {}
        self._active_view: Optional[RunView] = None
        self._active_run_id: Optional[str] = None
        self._stop = False
        self.logger = logging.getLogger(__name__)

    async def start(
        self,
        *,
        brief_file: Optional[str] = None,
        revision: bool = False,
    ) -> int:
        """Run the interactive console session.

        Returns:
            Exit code (0 = success, 1 = preflight failure).
        """
        self.console.print(
            Panel(
                "[bold]parrot devloop[/bold] — Interactive Dev-Loop Console\n"
                "Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit.",
                border_style="blue",
            )
        )

        # Bootstrap runtime
        try:
            from parrot.cli.devloop.bootstrap import build_runtime  # noqa: PLC0415
            self._runtime = await build_runtime(console=self.console)
        except SystemExit:
            return 1

        # Load or collect brief, then dispatch
        try:
            await self._dispatch_initial(brief_file=brief_file, revision=revision)
        except (EOFError, KeyboardInterrupt):
            self.console.print("\n[dim]Cancelled.[/dim]")
            return 0

        # Main command loop
        return await self._command_loop()

    async def _dispatch_initial(
        self,
        *,
        brief_file: Optional[str] = None,
        revision: bool = False,
    ) -> None:
        """Collect a brief and dispatch the first run."""
        if revision:
            brief = await self._collect_revision_brief(brief_file)
            await self._dispatch_revision(brief)
        else:
            brief = await self._collect_work_brief(brief_file)
            await self._dispatch_run(brief)

    async def _collect_work_brief(self, brief_file: Optional[str] = None) -> Any:
        """Collect a WorkBrief via wizard or file."""
        from parrot.flows.dev_loop.models import WorkBrief  # noqa: PLC0415
        from parrot.cli.wizard import PydanticWizard, WizardConfig, WizardFieldOverride  # noqa: PLC0415

        if brief_file:
            return self._load_brief_file(brief_file, WorkBrief)

        config = WizardConfig(
            overrides={
                "description": WizardFieldOverride(file_loadable=True),
                "reporter": WizardFieldOverride(
                    prompt="Reporter (Jira accountId or email)",
                ),
                "escalation_assignee": WizardFieldOverride(
                    prompt="Escalation assignee (Jira accountId or email)",
                ),
            }
        )

        defaults: Dict[str, Any] = {}
        if self._runtime:
            if self._runtime.reporter:
                defaults["reporter"] = self._runtime.reporter
            if self._runtime.escalation_assignee:
                defaults["escalation_assignee"] = self._runtime.escalation_assignee

        wizard = PydanticWizard(
            WorkBrief, config=config, console=self.console, session=self._session
        )
        return await wizard.collect(initial=defaults)

    async def _collect_revision_brief(self, brief_file: Optional[str] = None) -> Any:
        """Collect a RevisionBrief via wizard or file."""
        from parrot.flows.dev_loop.models import RevisionBrief  # noqa: PLC0415
        from parrot.cli.wizard import PydanticWizard  # noqa: PLC0415

        if brief_file:
            return self._load_brief_file(brief_file, RevisionBrief)

        wizard = PydanticWizard(
            RevisionBrief, console=self.console, session=self._session
        )
        return await wizard.collect()

    def _load_brief_file(self, path_str: str, model_type: type) -> Any:
        """Load a brief from a YAML or JSON file."""
        path = Path(path_str).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Brief file not found: {path}")
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # noqa: PLC0415
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)
        return model_type(**data)

    async def _dispatch_run(self, brief: Any) -> str:
        """Dispatch a new dev-loop run and attach a RunView."""
        import uuid  # noqa: PLC0415
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        runner = self._runtime.runner

        task = asyncio.create_task(
            runner.run(brief, run_id=run_id),
            name=f"devloop-run-{run_id}",
        )
        self._runs[run_id] = task

        # Wait briefly for the host to be created
        await asyncio.sleep(0.1)
        host = runner.get_host(run_id)
        if host:
            view = RunView(host, self.console, run_id=run_id)
            self._views[run_id] = view
            self._active_view = view
            self._active_run_id = run_id

        self.console.print(f"[green]Dispatched run {run_id}[/green]")
        return run_id

    async def _dispatch_revision(self, brief: Any) -> str:
        """Dispatch a revision-mode run."""
        import uuid  # noqa: PLC0415
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        runner = self._runtime.runner

        task = asyncio.create_task(
            runner.run_revision(brief, run_id=run_id),
            name=f"devloop-revision-{run_id}",
        )
        self._runs[run_id] = task

        await asyncio.sleep(0.1)
        host = runner.get_host(run_id)
        if host:
            view = RunView(host, self.console, run_id=run_id)
            self._views[run_id] = view
            self._active_view = view
            self._active_run_id = run_id

        self.console.print(f"[green]Dispatched revision run {run_id}[/green]")
        return run_id

    async def _command_loop(self) -> int:
        """Main interactive loop: render + poll gates + accept commands."""
        stop_event = asyncio.Event()

        with patch_stdout():
            while not self._stop:
                # Render active view if any
                if self._active_view:
                    render_task = asyncio.create_task(
                        self._active_view.run_live(stop_event)
                    )
                else:
                    render_task = None

                try:
                    # Poll for gates + accept user input
                    await self._interactive_loop(stop_event)
                except (EOFError, KeyboardInterrupt):
                    await self._handle_ctrl_c()
                finally:
                    stop_event.set()
                    if render_task and not render_task.done():
                        render_task.cancel()
                        try:
                            await render_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    stop_event.clear()

        # Wait for all runs to complete
        for run_id, task in list(self._runs.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        return 0

    async def _interactive_loop(self, stop_event: asyncio.Event) -> None:
        """Accept commands and watch for gates."""
        while not self._stop:
            # Check for pending gates
            if self._active_view:
                pending = self._active_view.pending_gates()
                if pending:
                    await self._handle_gates(pending)
                    continue

            # Check if active run finished
            if self._active_run_id and self._active_run_id in self._runs:
                task = self._runs[self._active_run_id]
                if task.done():
                    # Final poll to get remaining envelopes
                    if self._active_view:
                        self._active_view.poll_once()
                    try:
                        result = task.result()
                        status = getattr(result, "status", "unknown")
                        self.console.print(
                            f"\n[bold]Run {self._active_run_id} finished: {status}[/bold]"
                        )
                    except Exception as exc:
                        self.console.print(
                            f"\n[bold red]Run {self._active_run_id} errored: {exc}[/bold red]"
                        )
                    self._active_view = None
                    stop_event.set()

            # Accept user input
            try:
                raw = await asyncio.wait_for(
                    self._session.prompt_async("devloop> "),
                    timeout=_GATE_POLL_INTERVAL,
                )
            except asyncio.TimeoutError:
                continue
            except EOFError:
                self._stop = True
                break

            raw = raw.strip()
            if not raw:
                continue

            if raw.startswith("/"):
                await self._dispatch_command(raw)
            else:
                self.console.print("[dim]Type /help for commands.[/dim]")

    async def _handle_gates(self, gates: Dict[str, Any]) -> None:
        """Prompt user for each pending gate."""
        for gate_id, gate in gates.items():
            if self._active_view:
                self._active_view.pause()

            kind = getattr(gate, "kind", "")
            title = getattr(gate, "title", "")
            instructions = getattr(gate, "instructions", "")
            expires_at = getattr(gate, "expires_at", None)

            panel_content = f"[bold yellow]{kind}[/bold yellow]: {title}"
            if instructions:
                panel_content += f"\n{instructions}"
            if expires_at:
                import time  # noqa: PLC0415
                remaining = max(0, expires_at - time.time())
                panel_content += f"\n[dim]Expires in {int(remaining)}s[/dim]"

            self.console.print(Panel(
                panel_content,
                title=f"Gate: {gate_id}",
                border_style="yellow",
            ))

            try:
                resolution = await self._session.prompt_async(
                    "  Approve or reject? [a/r]: "
                )
                resolution = resolution.strip().lower()
                if resolution in ("a", "approve", "approved", "y", "yes"):
                    resolution_str = "approved"
                elif resolution in ("r", "reject", "rejected", "n", "no"):
                    resolution_str = "rejected"
                else:
                    self.console.print("[yellow]Skipping gate (enter 'a' or 'r').[/yellow]")
                    if self._active_view:
                        self._active_view.resume()
                    continue

                comment = await self._session.prompt_async("  Comment (optional): ")
                comment = comment.strip()

                identity = os.environ.get("USER", "cli-user")
                runner = self._runtime.runner

                try:
                    await runner.resolve_gate(
                        self._active_run_id,
                        gate_id,
                        resolution=resolution_str,
                        resolved_by=identity,
                        comment=comment,
                    )
                    self.console.print(
                        f"[green]Gate {gate_id} {resolution_str}.[/green]"
                    )
                except Exception as exc:
                    self.console.print(
                        f"[red]Gate resolution failed: {exc}[/red]"
                    )

            except (EOFError, KeyboardInterrupt):
                self.console.print("[dim]Gate skipped.[/dim]")

            if self._active_view:
                self._active_view.resume()

    async def _handle_ctrl_c(self) -> None:
        """Handle Ctrl-C: confirm cancellation."""
        if not self._active_run_id:
            self._stop = True
            return

        self.console.print("\n[yellow]Ctrl-C detected.[/yellow]")
        try:
            confirm = await self._session.prompt_async(
                "Cancel active run? [y/N]: "
            )
            if confirm.strip().lower() in ("y", "yes"):
                identity = os.environ.get("USER", "cli-user")
                runner = self._runtime.runner
                try:
                    await runner.cancel_run(
                        self._active_run_id,
                        requested_by=identity,
                    )
                    self.console.print(
                        f"[red]Run {self._active_run_id} cancelled.[/red]"
                    )
                except Exception as exc:
                    self.console.print(f"[red]Cancel failed: {exc}[/red]")
                self._stop = True
            else:
                self.console.print("[dim]Continuing...[/dim]")
        except (EOFError, KeyboardInterrupt):
            self._stop = True

    # ── Slash commands ──────────────────────────────────────────────────

    async def _dispatch_command(self, raw: str) -> None:
        """Parse and dispatch a slash command."""
        parts = raw[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "runs": self._cmd_runs,
            "attach": self._cmd_attach,
            "cancel": self._cmd_cancel,
            "new": self._cmd_new,
            "revise": self._cmd_revise,
            "help": self._cmd_help,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(args)
            except Exception as exc:
                self.console.print(f"[red]Error: {exc}[/red]")
        else:
            self.console.print(
                f"[yellow]Unknown command: /{cmd}[/yellow] — type /help"
            )

    async def _cmd_runs(self, args: str) -> None:
        """List all runs in this session."""
        if not self._runs:
            self.console.print("[dim]No runs.[/dim]")
            return

        table = Table(title="Runs")
        table.add_column("Run ID", style="cyan")
        table.add_column("Status")
        table.add_column("Active View")

        runner = self._runtime.runner
        active_set = runner.active_runs()

        for run_id, task in self._runs.items():
            if task.done():
                try:
                    result = task.result()
                    status = f"[green]finished ({getattr(result, 'status', '?')})[/green]"
                except Exception:
                    status = "[red]errored[/red]"
            elif run_id in active_set:
                status = "[yellow]running[/yellow]"
            else:
                status = "[dim]queued (cap)[/dim]"

            is_active = "*" if run_id == self._active_run_id else ""
            table.add_row(run_id, status, is_active)

        self.console.print(table)

    async def _cmd_attach(self, args: str) -> None:
        """Switch the active view to a different run."""
        run_id = args.strip()
        if not run_id:
            self.console.print("[yellow]Usage: /attach <run-id>[/yellow]")
            return
        if run_id not in self._views:
            self.console.print(f"[red]Run {run_id} not found or no view.[/red]")
            return
        if self._active_view:
            self._active_view.stop()
        self._active_view = self._views[run_id]
        self._active_run_id = run_id
        self.console.print(f"[green]Attached to {run_id}[/green]")

    async def _cmd_cancel(self, args: str) -> None:
        """Cancel a run."""
        run_id = args.strip() or self._active_run_id
        if not run_id:
            self.console.print("[yellow]No active run to cancel.[/yellow]")
            return
        identity = os.environ.get("USER", "cli-user")
        runner = self._runtime.runner
        try:
            await runner.cancel_run(run_id, requested_by=identity)
            self.console.print(f"[red]Run {run_id} cancelled.[/red]")
        except Exception as exc:
            self.console.print(f"[red]Cancel failed: {exc}[/red]")

    async def _cmd_new(self, args: str) -> None:
        """Start a new run with the wizard."""
        if self._active_view:
            self._active_view.pause()
        try:
            brief = await self._collect_work_brief()
            await self._dispatch_run(brief)
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]Cancelled.[/dim]")
        if self._active_view:
            self._active_view.resume()

    async def _cmd_revise(self, args: str) -> None:
        """Start a revision-mode run."""
        if self._active_view:
            self._active_view.pause()
        try:
            brief_file = args.strip() or None
            brief = await self._collect_revision_brief(brief_file)
            await self._dispatch_revision(brief)
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]Cancelled.[/dim]")
        if self._active_view:
            self._active_view.resume()

    async def _cmd_help(self, args: str) -> None:
        """Show help."""
        help_text = (
            "[bold]Commands:[/bold]\n"
            "  /new           Start a new run (wizard)\n"
            "  /runs          List all runs in this session\n"
            "  /attach <id>   Switch view to a different run\n"
            "  /cancel [id]   Cancel a run (default: active)\n"
            "  /revise [file] Start a revision-mode run\n"
            "  /help          Show this help\n"
            "  /quit          Exit the console\n"
            "\n"
            "  Ctrl-C         Cancel active run (with confirmation)"
        )
        self.console.print(Panel(help_text, title="Help", border_style="blue"))

    async def _cmd_quit(self, args: str) -> None:
        """Exit the console."""
        self._stop = True
