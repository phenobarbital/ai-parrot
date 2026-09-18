"""Turn execution boundary for the ``parrot agent`` presenters (FEAT-573, spec §3 M5).

Only this module calls ``bot.ask`` / ``bot.ask_stream``. Both the inline REPL and
the Textual workspace consume the ``TurnEvent`` stream produced here.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, List, Optional
from uuid import uuid4

from parrot.cli.commands import ConversationTurn  # verified: commands.py:38
from parrot.cli.events import (  # provided by TASK-3403
    BackendCapabilities,
    TextDelta,
    ToolFailed,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnEvent,
    TurnFailed,
    TurnStarted,
    summarize_message_text,
)
from parrot.cli.modes import save_session_pointer  # provided by TASK-3401
from parrot.core.events.lifecycle import (  # verified: lifecycle/__init__.py:21-22, :39-41
    AfterToolCallEvent,
    BeforeToolCallEvent,
    ToolCallFailedEvent,
    get_global_registry,
)
from parrot.core.events.lifecycle.turn_scope import in_turn_scope, turn_scope  # provided by TASK-3402
from parrot.models.basic import ToolCall  # verified: models/basic.py:23
from parrot.models.outputs import OutputMode  # verified: repl.py:24

#: Hook signature as ``TurnRunner`` itself actually calls it: ``hook(runner, turn)``.
#: Distinct from ``parrot.cli.events.PostTurnHook`` (which types the presenter-facing
#: ``ctx: CommandContext`` parameter) because ``TurnRunner`` has no presenter reference
#: and passes itself as the first argument -- see ``add_post_turn_hook``'s docstring.
_RunnerPostTurnHook = Callable[["TurnRunner", ConversationTurn], Awaitable[None]]


class TurnInProgressError(RuntimeError):
    """Raised by :meth:`TurnRunner.run_turn` while another turn is active (one turn per session)."""


class _ResumedResponse:
    """AIMessage-compatible view of a stored memory turn (``output``/``response``/``tool_calls``/``usage``)."""

    def __init__(self, output: str, tool_calls: List[ToolCall], error: Optional[str] = None) -> None:
        self.output = output
        self.response = output
        self.tool_calls = tool_calls
        self.usage = None
        self.error = error


class TurnRunner:
    """Run conversation turns against a bot-like backend and yield ``TurnEvent``s.

    Identity kwargs are exactly those ``AgentREPL`` passes today (repl.py:212-218, :249-255):
    ``session_id``, ``user_id``, ``output_mode=OutputMode.TERMINAL``, ``permission_context``.
    ``user_id=None`` is omitted from the call.
    """

    def __init__(self, bot: Any, config: Any, *, capabilities: Optional[BackendCapabilities] = None) -> None:
        self.bot = bot
        self.config = config
        self.history: List[ConversationTurn] = []
        self.logger = logging.getLogger(__name__)
        self._hooks: List[_RunnerPostTurnHook] = []
        self._active_task: Optional[asyncio.Task] = None
        self._capabilities = capabilities or self._default_capabilities(bot)

    @staticmethod
    def _default_capabilities(bot: Any) -> BackendCapabilities:
        """``bot.capabilities`` when it IS a BackendCapabilities (AsyncMock attrs are not), else standalone defaults."""
        caps = getattr(bot, "capabilities", None)
        if isinstance(caps, BackendCapabilities):
            return caps
        return BackendCapabilities(
            streaming=True,
            live_tool_events=True,
            usage=True,
            resume=callable(getattr(bot, "get_conversation_history", None)),
        )

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    @property
    def is_active(self) -> bool:
        return self._active_task is not None and not self._active_task.done()

    def _identity_kwargs(self) -> dict[str, Any]:
        """The exact kwargs AgentREPL passes today (repl.py:212-218); ``user_id`` omitted when None."""
        kwargs: dict[str, Any] = {
            "session_id": self.config.session_id,
            "output_mode": OutputMode.TERMINAL,
            "permission_context": self.config.permission_context,
        }
        if self.config.user_id is not None:
            kwargs["user_id"] = self.config.user_id
        return kwargs

    async def run_turn(self, query: str) -> AsyncIterator[TurnEvent]:
        """Yield TurnStarted, then TextDelta/Tool* events, then exactly one terminal event."""
        if self.is_active:
            raise TurnInProgressError("a turn is already running")
        turn_id = str(uuid4())
        seq = 0
        queue: "asyncio.Queue[TurnEvent]" = asyncio.Queue()
        registry = get_global_registry()
        sub_ids: List[str] = []
        partial = ""
        message: Any = None
        self._active_task = asyncio.current_task()

        def _drain_pending() -> List[TurnEvent]:
            """Pop every queued tool event, assigning the next monotonic ``seq`` to each."""
            nonlocal seq
            drained: List[TurnEvent] = []
            while not queue.empty():
                evt = queue.get_nowait()
                seq += 1
                evt.seq = seq
                drained.append(evt)
            return drained

        async def _flush_pending() -> List[TurnEvent]:
            """Drain the queue after giving forwarded tool events a chance to land.

            ``BeforeToolCallEvent`` reaches our subscription through TWO nested
            ``loop.create_task`` hops (``EventRegistry.emit_nowait`` schedules the
            tool's own registry ``emit()``, whose forward-to-global step schedules a
            second task), while ``AfterToolCallEvent``/``ToolCallFailedEvent`` need
            only one (a direct ``await emit()`` whose forward step schedules a single
            task). A tool whose ``_execute()`` has no real ``await`` of its own never
            gives the loop a natural turn between Before/After, so without this a
            ``ToolStarted`` can still be in flight when we drain right before
            ``TurnCompleted`` — breaking AC6 ("both before TurnCompleted"). A few
            no-op scheduler turns are cheap insurance against that race.
            """
            for _ in range(3):
                await asyncio.sleep(0)
            return _drain_pending()

        yield TurnStarted(turn_id=turn_id, seq=seq, query=query, streaming=self.config.streaming)
        try:
            if self.capabilities.live_tool_events:

                async def _on_tool_started(event: BeforeToolCallEvent) -> None:
                    queue.put_nowait(
                        ToolStarted(
                            turn_id=turn_id,
                            seq=0,
                            call_id=event.trace_context.span_id,
                            tool_name=event.tool_name,
                            args_summary=event.args_summary,
                        )
                    )

                async def _on_tool_finished(event: AfterToolCallEvent) -> None:
                    queue.put_nowait(
                        ToolFinished(
                            turn_id=turn_id,
                            seq=0,
                            call_id=event.trace_context.span_id,
                            tool_name=event.tool_name,
                            duration_ms=event.duration_ms,
                            result_status=event.result_status,
                            result_size_bytes=event.result_size_bytes,
                        )
                    )

                async def _on_tool_failed(event: ToolCallFailedEvent) -> None:
                    queue.put_nowait(
                        ToolFailed(
                            turn_id=turn_id,
                            seq=0,
                            call_id=event.trace_context.span_id,
                            tool_name=event.tool_name,
                            duration_ms=event.duration_ms,
                            error_type=event.error_type,
                            error_message=event.error_message,
                        )
                    )

                sub_ids.append(registry.subscribe(BeforeToolCallEvent, _on_tool_started, where=in_turn_scope(turn_id)))
                sub_ids.append(registry.subscribe(AfterToolCallEvent, _on_tool_finished, where=in_turn_scope(turn_id)))
                sub_ids.append(registry.subscribe(ToolCallFailedEvent, _on_tool_failed, where=in_turn_scope(turn_id)))
            with turn_scope(turn_id):
                if self.config.streaming:
                    stream = self.bot.ask_stream(question=query, **self._identity_kwargs())
                    try:
                        async for chunk in stream:
                            for evt in _drain_pending():
                                yield evt
                            if isinstance(chunk, str):
                                text = chunk
                            elif hasattr(chunk, "output"):
                                # Final AIMessage arrived as last chunk. Checked before the
                                # generic .text/.content duck-typing below: a real AIMessage
                                # has no .text/.content attribute, but a duck-typed/mock final
                                # message (e.g. MagicMock in tests) auto-vivifies EVERY
                                # attribute access as truthy, so hasattr(chunk, "text") would
                                # otherwise match first and silently pick the wrong branch.
                                message = chunk
                                break
                            elif hasattr(chunk, "text"):
                                text = chunk.text
                            elif hasattr(chunk, "content"):
                                text = chunk.content
                            else:
                                text = str(chunk)
                            partial += text
                            seq += 1
                            yield TextDelta(turn_id=turn_id, seq=seq, text=text)
                    except asyncio.CancelledError:
                        await stream.aclose()
                        raise
                else:
                    message = await self.bot.ask(question=query, **self._identity_kwargs())
                    partial = summarize_message_text(message)
            for evt in await _flush_pending():
                yield evt
            seq += 1
            response = message if message is not None else _ResumedResponse(partial, [])
            yield TurnCompleted(turn_id=turn_id, seq=seq, text=partial, message=response)
            turn = ConversationTurn(query=query, response=response, timestamp=datetime.now())
            self.history.append(turn)
            # save_session_pointer() does real, synchronous filesystem I/O
            # (mkdir/chmod/NamedTemporaryFile/os.replace) — never block the
            # event loop on every completed turn.
            await asyncio.to_thread(save_session_pointer, self.config.agent_name, self.config.session_id)
            for hook in self._hooks:
                await hook(self, turn)
        except asyncio.CancelledError:
            yield TurnCancelled(turn_id=turn_id, seq=seq + 1, partial_text=partial)
        except Exception as exc:  # noqa: BLE001 — presenters must never see a raw exception (AC19)
            self.logger.exception("turn %s failed", turn_id)
            yield TurnFailed(
                turn_id=turn_id,
                seq=seq + 1,
                error_type=type(exc).__name__,
                error_message=str(exc),
                partial_text=partial,
            )
        finally:
            for sid in sub_ids:
                registry.unsubscribe(sid)
            self._active_task = None

    def cancel(self) -> bool:
        """Cancel the active turn's task; True if one was active.

        Relies on ``self._active_task`` -- the caller's own task, captured by
        ``run_turn()`` via ``asyncio.current_task()`` -- so this only cancels
        anything when the caller wraps turn-consumption in a dedicated task
        (as the inline REPL's ``_turn_with_cancel`` and the TUI's
        ``action_cancel_turn`` both do). A caller that drives ``run_turn()``
        directly on its own task (no wrapper) has nothing for this to cancel.
        """
        if not self.is_active:
            return False
        self._active_task.cancel()  # type: ignore[union-attr]
        return True

    async def load_history(self, session_id: str) -> List[ConversationTurn]:
        """Resume: map ``bot.get_conversation_history(user_id, session_id)`` turns to CLI turns."""
        if not self.capabilities.resume:
            return []
        history = await self.bot.get_conversation_history(self.config.user_id or "cli-user", session_id)
        if history is None:
            return []
        turns: List[ConversationTurn] = []
        for mem_turn in history.turns:
            tool_calls = [
                ToolCall(
                    id=str(uuid4()),
                    name=inv.tool_name,
                    arguments=inv.input,
                    result=inv.output,
                    error=inv.error,
                )
                for inv in mem_turn.tool_invocations
            ]
            turns.append(
                ConversationTurn(
                    query=mem_turn.user_message,
                    response=_ResumedResponse(mem_turn.assistant_response, tool_calls, mem_turn.error),
                    timestamp=mem_turn.timestamp,
                )
            )
        self.config.session_id = session_id
        self.history = turns
        return self.history

    def reset_session(self) -> str:
        """New session id (``/clear`` semantics, commands.py:228-230); clears history."""
        self.config.session_id = str(uuid4())
        self.history.clear()
        return self.config.session_id

    def add_post_turn_hook(self, hook: _RunnerPostTurnHook) -> None:
        """Register a coroutine awaited after each COMPLETED turn.

        The hook is awaited as ``hook(self, turn)`` — the ``TurnRunner`` itself
        stands in for ``CommandContext`` here, since this module has no
        presenter reference. A presenter implementing the richer
        ``CommandContext`` protocol (e.g. ``AgentREPL``, TASK-3407) should wrap
        the hook to close over its own ``ctx`` before delegating registration
        to :meth:`add_post_turn_hook`.
        """
        self._hooks.append(hook)
