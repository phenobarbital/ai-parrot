"""REPL engine for the AI-Parrot agent CLI.

Provides ``AgentREPL`` — a ``prompt_toolkit``-based async read-eval-print loop
that interacts with a registered agent via ``ask()`` / ``ask_stream()``.

Also exports ``REPLConfig`` — a Pydantic v2 model holding session configuration.
"""
import logging
from datetime import datetime
from typing import Any, AsyncIterator, List, Optional
from uuid import uuid4

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from pydantic import BaseModel, Field
from rich.console import Console

from parrot.bots.abstract import AbstractBot
from parrot.cli.commands import ConversationTurn, SlashCommand, SlashCommandDispatcher
from parrot.cli.renderer import ResponseRenderer
from parrot.models.outputs import OutputMode
from parrot.models.responses import AIMessage


class REPLConfig(BaseModel):
    """Configuration for an agent REPL session.

    Attributes:
        agent_name: The name of the agent being conversed with.
        streaming: Whether to use streaming token delivery (default True).
        server_url: Optional server URL for server-mode proxy.
        session_id: Unique session identifier (auto-generated if not provided).
        user_id: User identifier sent with each request.
        permission_context: Optional FEAT-264/266 permission context (a
            ``parrot.auth.permission.PermissionContext``) threaded into
            ``bot.ask``/``bot.ask_stream`` so the credential broker seam
            (``ToolManager`` → ``AbstractTool``) sees ``channel``/``user_id``
            for per-user resolvers like the O365 device-code flow. Typed as
            ``Any`` (not the concrete dataclass) to avoid forcing pydantic
            to resolve ``PermissionContext``'s own TYPE_CHECKING-only
            forward refs at schema-build time. ``None`` by default — agents
            that don't declare broker-backed credentials are completely
            unaffected.
    """

    agent_name: str
    streaming: bool = True
    server_url: Optional[str] = None
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "cli-user"
    permission_context: Optional[Any] = None

    model_config = {"arbitrary_types_allowed": True}


class AgentREPL:
    """Interactive REPL for agent conversation.

    Uses ``prompt_toolkit.PromptSession.prompt_async()`` for async input
    with history, tab completion, and keybindings.  Uses ``ResponseRenderer``
    for Rich-based output.  Dispatches slash commands via
    ``SlashCommandDispatcher`` and forwards remaining input to the agent.

    Attributes:
        bot: The ``AbstractBot`` instance being conversed with.
        config: Session configuration.
        renderer: Rich-based response renderer.
        dispatcher: Slash command dispatcher.
        history: Ordered list of ``ConversationTurn`` objects.
        console: Rich Console for direct output.
    """

    def __init__(
        self,
        bot: AbstractBot,
        config: REPLConfig,
        renderer: ResponseRenderer,
    ) -> None:
        """Initialise the REPL.

        Args:
            bot: The configured ``AbstractBot`` to converse with.
            config: REPL session configuration.
            renderer: Response renderer for terminal output.
        """
        self.bot = bot
        self.config = config
        self.renderer = renderer
        self.dispatcher = SlashCommandDispatcher()
        self.history: List[ConversationTurn] = []
        self.console = Console()
        self.logger = logging.getLogger(__name__)

    async def run(self) -> None:
        """Run the REPL loop until the user exits.

        Creates a ``PromptSession`` with history and slash-command tab
        completion, then loops reading input and dispatching to either the
        slash command handler or the agent.

        ``Ctrl+D`` (EOF) exits cleanly.  ``Ctrl+C`` at the prompt is caught
        and a hint is printed.  ``Ctrl+C`` during an agent response cancels
        the in-progress request and returns to the prompt.

        Raises:
            SystemExit: When the user types ``/quit`` or ``/exit``.
        """
        completions = self.dispatcher.get_completions()
        completer = WordCompleter(completions, sentence=True)
        session: PromptSession = PromptSession(
            history=InMemoryHistory(),
            completer=completer,
        )
        prompt = f"{self.bot.name}> "
        self.logger.info("Starting REPL for agent '%s'", self.bot.name)

        with patch_stdout():
            while True:
                try:
                    text = await session.prompt_async(prompt)
                except EOFError:
                    # Ctrl+D — exit gracefully
                    self.console.print("\n[dim]Goodbye.[/dim]")
                    break
                except KeyboardInterrupt:
                    # Ctrl+C at the prompt — print hint, continue
                    self.console.print(
                        "[dim]Use Ctrl+D or /quit to exit.[/dim]"
                    )
                    continue

                text = text.strip()
                if not text:
                    continue

                # Try slash command first
                is_command = await self.dispatcher.dispatch_async(text, self)
                if is_command:
                    continue

                # Agent query
                try:
                    if self.config.streaming:
                        await self.send_stream(text)
                    else:
                        response = await self.send(text)
                        self.renderer.render(response)
                except KeyboardInterrupt:
                    # Ctrl+C during response — cancel and return to prompt
                    self.console.print()  # newline after ^C
                    self.console.print("[yellow]Request cancelled.[/yellow]")
                except SystemExit:
                    raise
                except Exception as exc:
                    self.logger.exception("Error during agent query")
                    self.renderer.render_error(exc)

    async def send(self, query: str) -> AIMessage:
        """Send a query to the agent and return the full response.

        Records the turn in ``self.history``.

        Args:
            query: The user's input string.

        Returns:
            The ``AIMessage`` response from the agent.
        """
        self.logger.debug("Sending query to agent: %r", query[:80])
        response: AIMessage = await self.bot.ask(
            question=query,
            session_id=self.config.session_id,
            user_id=self.config.user_id,
            output_mode=OutputMode.TERMINAL,
            permission_context=self.config.permission_context,
        )
        self.history.append(
            ConversationTurn(
                query=query,
                response=response,
                timestamp=datetime.now(),
            )
        )
        return response

    async def send_stream(self, query: str) -> None:
        """Send a query to the agent and render the streaming response.

        Calls ``bot.ask_stream()`` and feeds chunks to the renderer's
        streaming API.  Records a summary turn in ``self.history`` after
        the stream completes.

        Args:
            query: The user's input string.
        """
        self.logger.debug("Streaming query to agent: %r", query[:80])
        self.renderer.render_stream_start()
        accumulated = ""
        final_response = None
        try:
            stream: AsyncIterator = self.bot.ask_stream(
                question=query,
                session_id=self.config.session_id,
                user_id=self.config.user_id,
                output_mode=OutputMode.TERMINAL,
                permission_context=self.config.permission_context,
            )
            async for chunk in stream:
                # Chunks may be strings or objects with a text/content attribute
                if isinstance(chunk, str):
                    text = chunk
                elif hasattr(chunk, "text"):
                    text = chunk.text
                elif hasattr(chunk, "content"):
                    text = chunk.content
                elif hasattr(chunk, "output"):
                    # Final AIMessage arrived as last chunk
                    final_response = chunk
                    break
                else:
                    text = str(chunk)
                accumulated += text
                self.renderer.render_stream_chunk(text)
        except KeyboardInterrupt:
            self.renderer.render_stream_end(None)
            raise
        except Exception as exc:
            self.renderer.render_stream_end(None)
            raise exc

        self.renderer.render_stream_end(final_response)

        # Record as a pseudo-AIMessage turn for history
        turn_response = final_response
        if turn_response is None:
            # Create a lightweight proxy for history
            turn_response = _StreamedResponse(query=query, output=accumulated)
        self.history.append(
            ConversationTurn(
                query=query,
                response=turn_response,
                timestamp=datetime.now(),
            )
        )

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
        self.tool_calls = []
        self.usage = None
