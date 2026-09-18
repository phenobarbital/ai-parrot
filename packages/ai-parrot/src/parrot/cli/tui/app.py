"""Full-screen Textual workspace for ``parrot agent`` (spec §3 Module 11)."""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from prompt_toolkit.history import History  # verified: prompt_toolkit 3.0.47
from textual import events, work  # verified: textual 8.2.8 probe
from textual.app import App, ComposeResult  # verified: textual 8.2.8 probe
from textual.binding import Binding  # verified: textual 8.2.8 probe
from textual.widgets import Footer, Header  # verified: textual 8.2.8 probe

from parrot.cli.commands import ConversationTurn, SlashCommandDispatcher  # verified: commands.py:38, :70
from parrot.cli.events import TurnCancelled, TurnCompleted, TurnFailed  # provided by TASK-3403
from parrot.cli.repl import REPLConfig  # verified: repl.py:61
from parrot.cli.session import TurnRunner  # provided by TASK-3404
from parrot.cli.tui.adapter import DrawerLogHandler, TUICommandContext, TUIRenderer  # provided by TASK-3411
from parrot.cli.tui.widgets import Composer, LogDrawer, StatusBar, ToolActivity, TranscriptView  # provided by TASK-3410

NARROW_WIDTH = 60
QUIT_DOUBLE_PRESS_S = 2.0


class AgentWorkspaceApp(App[int]):
    """Full-screen agent workspace. The return value is the process exit code."""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("pageup", "scroll_transcript(-1)", "Scroll up", show=False),
        Binding("pagedown", "scroll_transcript(1)", "Scroll down", show=False),
        Binding("end", "resume_follow", "Follow"),
        Binding("ctrl+c", "cancel_turn", "Cancel / quit", priority=True),
        Binding("ctrl+d", "quit_app", "Quit", priority=True),
        Binding("f2", "toggle_tools", "Tools"),
        Binding("f3", "toggle_logs", "Logs"),
        Binding("ctrl+l", "clear_session", "Clear", priority=True),
    ]

    def __init__(
        self,
        *,
        bot: Any,
        config: REPLConfig,
        runner: TurnRunner,
        dispatcher: SlashCommandDispatcher,
        history: History,
        resume_turns: Optional[List[ConversationTurn]] = None,
    ) -> None:
        """Initialise the workspace with its already-constructed collaborators.

        Args:
            bot: The bot-like backend, threaded through only to build the
                ``TUICommandContext`` (spec: the app itself never calls it, AC5).
            config: The session's ``REPLConfig``.
            runner: The ``TurnRunner`` driving turn execution (spec §3 M5).
            dispatcher: The shared ``SlashCommandDispatcher``.
            history: ``prompt_toolkit`` history backing the composer.
            resume_turns: Optional resumed turns rendered on mount.
        """
        super().__init__()
        self.bot = bot
        self.config = config
        self.runner = runner
        self.dispatcher = dispatcher
        self._history = history
        self._resume_turns = resume_turns or []
        self._log_handler: Optional[DrawerLogHandler] = None
        self._last_ctrl_c = 0.0
        self.logger = logging.getLogger(__name__)
        self.command_context: Optional[TUICommandContext] = None

    def compose(self) -> ComposeResult:
        """Build the fixed widget tree whose ids ``app.tcss`` (TASK-3410) targets."""
        yield Header(show_clock=False)
        yield TranscriptView(id="transcript")
        yield LogDrawer(id="logs")
        yield Composer(history=self._history, completions=self.dispatcher.get_completions, id="composer")
        yield StatusBar(id="status")
        yield Footer()

    async def on_mount(self) -> None:
        """Render any resumed turns, install the drawer log handler, and focus the composer."""
        self.title = f"parrot agent · {self.config.agent_name}"
        self.sub_title = f"tui · session {self.config.session_id[:8]}"
        transcript = self.query_one("#transcript", TranscriptView)
        renderer = TUIRenderer(transcript)
        self.command_context = TUICommandContext(self, self.bot, self.config, self.runner, self.dispatcher, renderer)
        if self._resume_turns:
            renderer.render_history(self._resume_turns, session_id=self.config.session_id)
        self._log_handler = DrawerLogHandler(self, self.query_one("#logs", LogDrawer))
        logging.getLogger().addHandler(self._log_handler)  # AC14: add a handler, never change levels
        self.query_one("#composer", Composer).focus()

    def on_unmount(self) -> None:
        """Remove the drawer log handler so it never outlives this screen."""
        if self._log_handler is not None:
            logging.getLogger().removeHandler(self._log_handler)
            self._log_handler = None

    async def on_composer_submitted(self, message: Composer.Submitted) -> None:
        """Forward a composer submission to :meth:`submit`."""
        await self.submit(message.text)

    async def submit(self, text: str) -> None:
        """Slash command → dispatcher; otherwise start the turn worker (one at a time, AC4)."""
        text = text.strip()
        if not text:
            return
        if text.lower() in ("quit", "exit"):
            self.exit(0)
            return
        if text.startswith("/"):
            try:
                await self.dispatcher.dispatch_async(text, self.command_context)  # type: ignore[arg-type]
            except SystemExit as exc:  # /quit — commands.py:319
                self.exit(int(exc.code or 0))
            return
        if self.runner.is_active:
            self.notify("A request is running — Ctrl+C cancels", severity="warning")
            self.query_one("#composer", Composer).load_text(text)  # keep the typed text (AC4)
            return
        self.query_one("#transcript", TranscriptView).resume_follow()
        self._run_turn(text)

    @work(exclusive=True, group="turn")
    async def _run_turn(self, query: str) -> None:
        """Drive one turn through the runner, applying every event to the transcript and status bar."""
        transcript = self.query_one("#transcript", TranscriptView)
        status = self.query_one("#status", StatusBar)
        async for event in self.runner.run_turn(query):
            await transcript.apply(event)
            status.apply(event)
            # A concurrent /clear (dispatched independent of runner.is_active, see submit()) may have
            # rotated the session id while this turn was in flight — refresh the sub_title to match (AC20).
            if isinstance(event, (TurnCompleted, TurnFailed, TurnCancelled)):
                self.sub_title = f"tui · session {self.config.session_id[:8]}"

    def action_cancel_turn(self) -> None:
        """Ctrl+C: cancel an active turn via the runner; idle double-press within 2s quits (AC18)."""
        if self.runner.is_active:
            self.query_one("#status", StatusBar).set_cancelling()
            self.runner.cancel()
            return
        now = time.monotonic()
        if now - self._last_ctrl_c < QUIT_DOUBLE_PRESS_S:
            self.exit(0)
        else:
            self._last_ctrl_c = now
            self.notify("Press Ctrl+C again to quit (Ctrl+D also quits)")

    def action_quit_app(self) -> None:
        """Ctrl+D: quit unconditionally."""
        self.exit(0)

    def action_toggle_tools(self) -> None:
        """F2: flip ``collapsed`` on every ``ToolActivity`` panel in the transcript."""
        for panel in self.query(ToolActivity):
            panel.collapsed = not panel.collapsed

    def action_toggle_logs(self) -> None:
        """F3: show/hide the log drawer."""
        drawer = self.query_one("#logs", LogDrawer)
        drawer.display = not drawer.display

    def action_resume_follow(self) -> None:
        """End: re-enable auto-follow on the transcript."""
        self.query_one("#transcript", TranscriptView).resume_follow()

    def action_scroll_transcript(self, direction: int) -> None:
        """PageUp/PageDown: page the transcript; paging up also disengages auto-follow (AC3)."""
        transcript = self.query_one("#transcript", TranscriptView)
        if direction < 0:
            transcript.action_page_up()
        else:
            transcript.action_page_down()

    async def action_clear_session(self) -> None:
        """Ctrl+L: alias for ``/clear`` so both paths go through the shared handler (AC20)."""
        await self.submit("/clear")

    def on_resize(self, event: events.Resize) -> None:
        """Narrow terminals (< 60 cols): collapse tool panels and mark the status bar compact."""
        narrow = event.size.width < NARROW_WIDTH
        for panel in self.query(ToolActivity):
            if narrow:
                panel.collapsed = True
        self.query_one("#status", StatusBar).set_class(narrow, "compact")
