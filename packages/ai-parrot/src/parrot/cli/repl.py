"""REPL engine for the AI-Parrot agent CLI.

Provides ``AgentREPL`` — a ``prompt_toolkit``-based async read-eval-print loop
that consumes ``TurnRunner`` events (``parrot.cli.session``) and renders them
through ``ResponseRenderer``. The REPL never calls the bot's ask methods
directly — the ``TurnRunner`` is the sole turn-execution boundary (spec §3 M5).

Also exports ``REPLConfig`` — a Pydantic v2 model holding session configuration.
"""

import asyncio
import logging
import os
import signal
from typing import Any, ContextManager, Iterable, List, Optional
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from pydantic import BaseModel, Field

from parrot.cli.commands import ConversationTurn, SlashCommand, SlashCommandDispatcher
from parrot.cli.console import get_console
from parrot.cli.events import PostTurnHook, TextDelta, TurnCompleted, TurnFailed, TurnStarted
from parrot.cli.modes import UIMode, history_path
from parrot.cli.renderer import ResponseRenderer
from parrot.cli.session import TurnRunner
from parrot.models.basic import ToolCall
from parrot.models.responses import AIMessage


class REPLConfig(BaseModel):
    """Configuration for an agent REPL session.

    Attributes:
        agent_name: The name of the agent being conversed with.
        streaming: Whether to use streaming token delivery (default True).
        server_url: Optional server URL for server-mode proxy.
        session_id: Unique session identifier (auto-generated if not provided).
        user_id: User identifier sent with each request. ``None`` in server mode
            when the caller does not wish to thread an identity (spec Q8).
        permission_context: Optional FEAT-264/266 permission context (a
            ``parrot.auth.permission.PermissionContext``) threaded into the
            bot's ask methods (via ``TurnRunner``) so the credential broker seam
            (``ToolManager`` → ``AbstractTool``) sees ``channel``/``user_id``
            for per-user resolvers like the O365 device-code flow. Typed as
            ``Any`` (not the concrete dataclass) to avoid forcing pydantic
            to resolve ``PermissionContext``'s own TYPE_CHECKING-only
            forward refs at schema-build time. ``None`` by default — agents
            that don't declare broker-backed credentials are completely
            unaffected.
        ui_mode: Requested presentation mode (``AUTO``/``INLINE``/``TUI``).
        resume_session_id: Optional session id to resume history from at start.
        server_token: Optional bearer token for server-proxy mode.
        history_enabled: Whether composer input persists via ``FileHistory``.
    """

    agent_name: str
    streaming: bool = True
    server_url: Optional[str] = None
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: Optional[str] = "cli-user"
    permission_context: Optional[Any] = None
    ui_mode: UIMode = UIMode.AUTO
    resume_session_id: Optional[str] = None
    server_token: Optional[str] = None
    history_enabled: bool = True

    model_config = {"arbitrary_types_allowed": True}


class AgentREPL:
    """Interactive REPL for agent conversation, driven by a ``TurnRunner``.

    Uses ``prompt_toolkit.PromptSession.prompt_async()`` for async input
    with history, tab completion, and keybindings, bracketed by the shared
    ``LiveRegion.modal()`` so the composer never collides with in-progress
    streaming output.  Uses ``ResponseRenderer`` for Rich-based output.
    Dispatches slash commands via ``SlashCommandDispatcher`` and forwards
    remaining input to the ``TurnRunner``. Implements the structural
    ``CommandContext`` protocol (``parrot.cli.commands.CommandContext``).

    Attributes:
        bot: The ``AbstractBot`` instance being conversed with.
        config: Session configuration.
        renderer: Rich-based response renderer.
        dispatcher: Slash command dispatcher.
        runner: The ``TurnRunner`` that owns turn execution and history.
        console: Shared, process-wide Rich Console for direct output.
    """

    def __init__(
        self,
        bot: Any,
        config: REPLConfig,
        renderer: ResponseRenderer,
        *,
        runner: Optional[TurnRunner] = None,
    ) -> None:
        """Initialise the REPL.

        Args:
            bot: The configured ``AbstractBot`` to converse with, or a duck-typed
                proxy (``_ServerBotProxy``, ``loaders.py``) exposing the same
                ``ask``/``ask_stream``/``get_conversation_history`` surface --
                typed ``Any`` to match ``TurnRunner``'s own ``bot: Any`` (session.py),
                which this REPL always forwards ``bot`` to.
            config: REPL session configuration.
            renderer: Response renderer for terminal output.
            runner: Turn execution boundary. Defaults to ``TurnRunner(bot, config)``.
        """
        self.bot = bot
        self.config = config
        self.renderer = renderer
        self.dispatcher = SlashCommandDispatcher()
        self.runner: TurnRunner = runner or TurnRunner(bot, config)
        self.console = get_console()
        self.logger = logging.getLogger(__name__)

    @property
    def history(self) -> List[ConversationTurn]:
        """Display/export history — owned by the runner (read-only alias)."""
        return self.runner.history

    def add_post_turn_hook(self, hook: PostTurnHook) -> None:
        """Register a coroutine awaited after each completed turn (agentd uses this; AC15).

        ``TurnRunner.add_post_turn_hook`` awaits registered hooks as
        ``hook(runner, turn)`` (``session.py`` — the runner has no presenter
        reference of its own). Wrap here so hooks registered through the REPL
        observe the richer ``CommandContext`` surface (``self``) instead of
        the bare ``TurnRunner``.

        Args:
            hook: Coroutine function called as ``hook(ctx, turn)``.
        """

        async def _wrapped(_runner: TurnRunner, turn: ConversationTurn) -> None:
            await hook(self, turn)

        self.runner.add_post_turn_hook(_wrapped)

    def suspend(self) -> ContextManager[None]:
        """Release the terminal to a foreign prompt (HITL/device code) — ``LiveRegion.modal()``."""
        return self.renderer.region.modal()

    async def run(self) -> None:
        """Run the REPL loop until the user exits.

        Creates a ``PromptSession`` with history and slash-command tab
        completion, then loops reading input and dispatching to either the
        slash command handler or the agent. Every prompt is bracketed by
        ``self.renderer.region.modal()`` so streaming output pauses cleanly
        while the user types.

        ``Ctrl+D`` (EOF) exits cleanly.  ``Ctrl+C`` at the prompt is caught
        and a hint is printed.  ``Ctrl+C`` during an agent turn cancels the
        in-progress turn via ``self.runner.cancel()`` and returns to the
        prompt (spec AC18).

        Raises:
            SystemExit: When the user types ``/quit`` or ``/exit``.
        """
        completions = self.dispatcher.get_completions()
        completer = WordCompleter(completions, sentence=True)
        history: Any = InMemoryHistory()
        if self.config.history_enabled:
            path = history_path(self.config.agent_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            os.chmod(path, 0o600)
            history = FileHistory(str(path))
        session: PromptSession = PromptSession(
            history=history,
            completer=completer,
        )
        prompt = f"{self.bot.name}> "
        self.logger.info("Starting REPL for agent '%s'", self.bot.name)

        if self.config.resume_session_id:
            turns = await self.runner.load_history(self.config.resume_session_id)
            self.renderer.render_history(turns, session_id=self.config.session_id)

        with patch_stdout():
            while True:
                try:
                    with self.renderer.region.modal():
                        text = await session.prompt_async(prompt)
                except EOFError:
                    # Ctrl+D — exit gracefully
                    self.console.print("\n[dim]Goodbye.[/dim]")
                    break
                except KeyboardInterrupt:
                    # Ctrl+C at the prompt — print hint, continue
                    self.console.print("[dim]Use Ctrl+D or /quit to exit.[/dim]")
                    continue

                text = text.strip()
                if not text:
                    continue

                # Intercept bare quit/exit (common UX trap)
                if text.lower() in ("quit", "exit"):
                    self.console.print("[dim]Goodbye.[/dim]")
                    break

                # Try slash command first
                is_command = await self.dispatcher.dispatch_async(text, self)
                if is_command:
                    continue

                # Agent turn — TurnRunner never raises (exceptions become TurnFailed
                # events, AC19); only SystemExit from a slash command escapes here.
                await self._turn_with_cancel(text)

    async def _turn_with_cancel(self, text: str) -> None:
        """Run one agent turn as a task; SIGINT while it runs cancels it instead of killing the REPL (AC18)."""
        loop = asyncio.get_running_loop()
        task = loop.create_task(self.send_stream(text) if self.config.streaming else self._send_and_render(text))
        previous = signal.getsignal(signal.SIGINT)
        installed = False
        try:
            loop.add_signal_handler(signal.SIGINT, self.runner.cancel)
            installed = True
        except NotImplementedError:
            # Some event loops (e.g. Windows' ProactorEventLoop) don't support
            # add_signal_handler; fall back to default KeyboardInterrupt behaviour.
            pass
        try:
            try:
                await task
            except KeyboardInterrupt:
                self.runner.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            if installed:
                loop.remove_signal_handler(signal.SIGINT)
                signal.signal(signal.SIGINT, previous)

    async def _send_and_render(self, text: str) -> None:
        """Batch-mode turn helper for ``_turn_with_cancel``."""
        self.renderer.render(await self.send(text))

    async def _consume(self, query: str, *, streaming: bool) -> Any:
        """Drive the runner and render each event; returns the final message (or None).

        ``TurnRunner.run_turn`` reads ``self.config.streaming`` to decide which bot
        ask method to call (spec M5); ``send``/``send_stream`` are batch/streaming
        regardless of the persisted config, so this shim saves and restores
        ``config.streaming`` around the runner call.

        Args:
            query: The user's input string.
            streaming: Whether this call should stream (``send_stream``) or not (``send``).

        Returns:
            The final ``AIMessage``-like response, or ``None`` if the turn failed
            or was cancelled before completing.
        """
        previous, self.config.streaming = self.config.streaming, streaming
        final: Any = None
        try:
            async for event in self.runner.run_turn(query):
                if isinstance(event, TurnStarted) and streaming:
                    self.renderer.render_stream_start()
                elif isinstance(event, TextDelta):
                    self.renderer.render_stream_chunk(event.text)
                elif isinstance(event, TurnCompleted):
                    final = event.message
                    if streaming:
                        self.renderer.render_stream_end(final)
                else:
                    self.renderer.render_turn_event(event)  # Tool*, TurnFailed, TurnCancelled
        finally:
            self.config.streaming = previous
        return final

    async def send(self, query: str) -> AIMessage:
        """Send a query (batch) and return the full response; history is recorded by the runner.

        Args:
            query: The user's input string.

        Returns:
            The ``AIMessage`` response from the agent.
        """
        return await self._consume(query, streaming=False)

    async def send_stream(self, query: str) -> None:
        """Send a query and render the streamed response (start/chunk/end on the renderer).

        Args:
            query: The user's input string.
        """
        await self._consume(query, streaming=True)

    async def run_batch(self, lines: Iterable[str]) -> int:
        """Non-TTY mode: one turn per non-empty line, slash commands allowed, plain output.

        Args:
            lines: Input lines (e.g. from stdin when piped).

        Returns:
            ``0`` on success, ``1`` if any turn ended in ``TurnFailed``.
        """
        exit_code = 0
        if self.config.resume_session_id:
            turns = await self.runner.load_history(self.config.resume_session_id)
            self.renderer.render_history(turns, session_id=self.config.session_id)
        for line in lines:
            text = line.strip()
            if not text:
                continue
            if text.lower() in ("quit", "exit"):
                break
            if await self.dispatcher.dispatch_async(text, self):
                continue
            async for event in self.runner.run_turn(text):
                if isinstance(event, TurnFailed):
                    exit_code = 1
                self.renderer.render_turn_event(event)
        return exit_code

    def register_command(self, cmd: SlashCommand) -> None:
        """Register a custom slash command with the dispatcher.

        Args:
            cmd: A ``SlashCommand`` instance to register.
        """
        self.dispatcher.register(cmd)


class _StreamedResponse:
    """Lightweight response placeholder for streamed responses.

    Used when the streaming loop did not yield a final ``AIMessage`` object,
    so we still record the accumulated text in the conversation history.

    Attributes:
        output: Accumulated streamed text.
        tool_calls: Empty list (streaming doesn't track tool calls in v1).
        usage: None.
    """

    def __init__(self, query: str, output: str) -> None:
        """Initialise with query and accumulated output.

        Args:
            query: The original user query.
            output: The accumulated streamed text.
        """
        self.query = query
        self.output = output
        self.response = output
        self.tool_calls: List[ToolCall] = []
        self.usage = None
