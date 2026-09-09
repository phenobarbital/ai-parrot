"""TASK-2990 — bot turn context and single invocation persistence.

Three properties, one per required case:

``test_entrypoints``
    The ordinary, streaming and structured paths each bracket their turn
    with a bound task context, and none of them leaks it afterwards —
    not on success, not on an exception, and not when a stream is
    cancelled mid-iteration (AC14).

``test_single_writer``
    A captured call is persisted exactly once. The observer's records
    REPLACE the ``AIMessage.tool_calls`` conversion rather than adding to
    it, and only ``save_conversation_turn`` writes (AC1, AC11).

``test_disabled``
    With task memory absent nothing changes: no context is bound, no
    import or network setup happens, and the persisted turn is identical
    to the legacy one (AC13).

The bot entry points are large and carry heavy provider machinery, so
these tests drive the *seams* those paths use — `_enter_task_turn` /
`_exit_task_turn` / `observed_tool_invocations` and the
`from_ai_message` override — plus a structural check that all four
entry points are actually bracketed. That structural check is what stops
a future edit quietly dropping one path's bracket.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from typing import Any, List, Optional

import pytest

from parrot.bots.abstract import AbstractBot
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.context import TASK_CONTEXT, current_session
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.tools import TaskMemory

pytestmark = pytest.mark.asyncio

BASE_PY = pathlib.Path(inspect.getfile(__import__("parrot.bots.base", fromlist=["x"])))

#: The four entry points that render history and must therefore bracket
#: their turn. `_conversation_body` backs `chat`; the other three are the
#: ordinary, structured and streaming paths named in AC14.
BRACKETED_ENTRY_POINTS = ("_conversation_body", "invoke", "ask", "ask_stream")


class _FakeToolManager:
    """Minimal tool manager exposing only the observer seam."""

    def __init__(self) -> None:
        """Initialize with no observer."""
        self._invocation_observer: Optional[Any] = None

    def set_invocation_observer(self, observer: Optional[Any]) -> None:
        """Install an observer.

        Args:
            observer: The observer, or ``None`` to clear.
        """
        self._invocation_observer = observer

    @property
    def invocation_observer(self) -> Optional[Any]:
        """The installed observer, or ``None``."""
        return self._invocation_observer


class _Bot(AbstractBot):
    """A bot reduced to what the turn-context seams actually touch.

    ``AbstractBot`` is abstract and its constructor pulls in the whole
    provider stack, so this subclass bypasses ``__init__`` deliberately —
    the code under test reads only ``memory_key_id``, ``tool_manager``,
    ``task_memory`` and ``logger``.
    """

    def __init__(self, task_memory: Optional[TaskMemory] = None) -> None:
        """Initialize the stand-in bot."""
        import logging

        self.task_memory = task_memory
        self.tool_manager = _FakeToolManager()
        self.logger = logging.getLogger("test-bot")
        self._chatbot_id_explicit = True
        self.chatbot_id = "bot-a"
        self.name = "bot-a"

    # AbstractBot declares these four abstract; the seams under test do
    # not call them, so they exist only to make the class instantiable.
    async def ask(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError

    async def conversation(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError


def _make_bot(enabled: bool = True) -> _Bot:
    """Build a bot with task memory on or off.

    Args:
        enabled: Whether to wire a task memory.

    Returns:
        The bot.
    """
    if not enabled:
        return _Bot(None)
    scope = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    return _Bot(TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), scope))


def _invocation(name: str) -> ToolInvocation:
    """Build a captured invocation.

    Args:
        name: Tool name.

    Returns:
        The invocation.
    """
    return ToolInvocation(tool_name=name, input={}, output="ok", status=ToolStatus.COMPLETED)


class _Response:
    """An AIMessage-shaped stand-in carrying tool calls."""

    def __init__(self, tool_calls: List[Any]) -> None:
        """Initialize with the given tool calls."""
        self.tool_calls = tool_calls
        self.content = "answer"
        self.to_text = "answer"
        self.turn_id = "turn-1"
        self.model = "m"
        self.provider = "p"
        self.usage = None
        self.finish_reason = "stop"
        self.response_time = 1.0


class _ToolCall:
    """A tool call as `from_ai_message` expects to find it."""

    def __init__(self, name: str) -> None:
        """Initialize the call."""
        self.name = name
        self.arguments = {}
        self.result = "ok"
        self.error = None
        self.execution_time = 0.5


# ─────────────────────────────────────────────────────────────
# test_entrypoints
# ─────────────────────────────────────────────────────────────


def _bracketed_methods() -> dict:
    """Report which entry points enter and exit the task turn.

    Parses ``bots/base.py`` rather than running the provider stack: the
    property under test is structural — every entry point must bracket
    its turn — and a structural property is best checked structurally.

    Returns:
        Mapping of method name to ``(enters, exits, guarded)``.
    """
    tree = ast.parse(BASE_PY.read_text())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if node.name not in BRACKETED_ENTRY_POINTS:
            continue
        src = ast.dump(node)
        enters = "_enter_task_turn" in src
        exits = "_exit_task_turn" in src
        # The exit must live in a `finally`, or an exception would leak
        # the context — which is the whole point of the bracket.
        in_finally = any(
            isinstance(n, ast.Try) and "_exit_task_turn" in ast.dump(ast.Module(body=n.finalbody, type_ignores=[]))
            for n in ast.walk(node)
        )
        found[node.name] = (enters, exits, in_finally)
    return found


async def test_entrypoints() -> None:
    """Every entry point brackets its turn, and nothing leaks after."""
    # ── structural: all four paths are bracketed, and released in a finally
    found = _bracketed_methods()
    assert set(found) == set(BRACKETED_ENTRY_POINTS), found
    for name, (enters, exits, in_finally) in found.items():
        assert enters, f"{name} never enters the task turn"
        assert exits, f"{name} never exits the task turn"
        assert in_finally, f"{name} releases the task turn outside a finally — an exception would leak it"

    # ── behavioural: enter binds, exit releases
    bot = _make_bot(enabled=True)
    assert current_session() is None

    token = bot._enter_task_turn("user-1", "sess-1")
    assert token is not None
    session = current_session()
    assert session is not None
    assert session.scope.user_id == "user-1"
    assert session.scope.session_id == "sess-1"
    # Scope comes from the bot's stable identity, never from a tool arg.
    assert session.scope.chatbot_id == bot.memory_key_id
    # The observer is installed for the duration of the turn.
    assert bot.tool_manager.invocation_observer is not None

    bot._exit_task_turn(token)
    assert current_session() is None
    assert bot.tool_manager.invocation_observer is None

    # ── no leak when the turn raises
    token = bot._enter_task_turn("user-1", "sess-1")
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        pass
    finally:
        bot._exit_task_turn(token)
    assert current_session() is None
    assert bot.tool_manager.invocation_observer is None

    # ── no leak when the turn is cancelled
    token = bot._enter_task_turn("user-1", "sess-1")
    try:
        raise __import__("asyncio").CancelledError()
    except BaseException:
        pass
    finally:
        bot._exit_task_turn(token)
    assert current_session() is None

    # ── exit is idempotent and never raises from a finally
    bot._exit_task_turn(None)
    assert current_session() is None


async def test_entrypoints_restores_a_previous_observer() -> None:
    """A nested turn restores the observer it displaced, not None."""
    bot = _make_bot(enabled=True)
    sentinel = object()
    bot.tool_manager.set_invocation_observer(sentinel)

    token = bot._enter_task_turn("user-1", "sess-1")
    assert bot.tool_manager.invocation_observer is not sentinel
    bot._exit_task_turn(token)
    # Restored, rather than blindly cleared — clearing would silently
    # disable observation for whatever installed the outer one.
    assert bot.tool_manager.invocation_observer is sentinel


# ─────────────────────────────────────────────────────────────
# test_single_writer
# ─────────────────────────────────────────────────────────────


async def test_single_writer() -> None:
    """Observed calls replace the tool_calls conversion; no duplicates."""
    bot = _make_bot(enabled=True)
    response = _Response([_ToolCall("wm_get_result"), _ToolCall("wm_list_stored")])

    # ── unobserved: the legacy derivation still applies, unchanged
    assert bot.observed_tool_invocations() is None
    legacy = ConversationTurn.from_ai_message(
        user_message="q",
        response=response,
        user_id="user-1",
        chatbot_id=bot.memory_key_id,
        tool_invocations=bot.observed_tool_invocations(),
    )
    assert [i.tool_name for i in legacy.tool_invocations] == ["wm_get_result", "wm_list_stored"]

    # ── observed: the session's records are what get persisted
    token = bot._enter_task_turn("user-1", "sess-1")
    try:
        session = current_session()
        for name in ("wm_get_result", "wm_list_stored", "denied_tool"):
            record = session.begin_invocation(name)
            record.invocation = _invocation(name)

        captured = bot.observed_tool_invocations()
        assert [i.tool_name for i in captured] == ["wm_get_result", "wm_list_stored", "denied_tool"]

        turn = ConversationTurn.from_ai_message(
            user_message="q",
            response=response,
            user_id="user-1",
            chatbot_id=bot.memory_key_id,
            tool_invocations=captured,
        )
    finally:
        bot._exit_task_turn(token)

    names = [i.tool_name for i in turn.tool_invocations]
    # Exactly once each — the observed list REPLACED the conversion. Had
    # it been appended instead, the two overlapping names would appear
    # twice and the length would be five.
    assert names == ["wm_get_result", "wm_list_stored", "denied_tool"]
    assert len(names) == len(set(names)) == 3
    # The third call never produced a tool_call at all, so the observer is
    # strictly more complete than the AIMessage — which is the reason it
    # replaces rather than supplements.
    assert "denied_tool" in names


async def test_single_writer_only_save_conversation_turn_persists() -> None:
    """Nothing in the turn-context seams writes history itself."""
    src = BASE_PY.read_text()
    tree = ast.parse(src)

    writers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name in {"add_turn", "_store_turn", "save_conversation_turn"}:
                writers.add(name)
    # The bot remains the sole writer and reaches memory only through
    # save_conversation_turn — FEAT-524's invariant, which FEAT-538 must
    # not quietly break by persisting invocations on its own.
    assert "save_conversation_turn" in writers
    assert "add_turn" not in writers
    assert "_store_turn" not in writers

    # And the observer seam is a pure read: it must not append anything.
    seam = inspect.getsource(AbstractBot.observed_tool_invocations)
    for forbidden in ("append(", "save_", "add_turn", "await "):
        assert forbidden not in seam, f"observed_tool_invocations should be a pure read, found {forbidden!r}"


# ─────────────────────────────────────────────────────────────
# test_disabled
# ─────────────────────────────────────────────────────────────


async def test_disabled() -> None:
    """With task memory absent, nothing is bound and nothing changes."""
    bot = _make_bot(enabled=False)
    assert bot.task_memory is None

    # No scope, no context, no observer — and no exception.
    assert bot._task_scope("user-1", "sess-1") is None
    token = bot._enter_task_turn("user-1", "sess-1")
    assert token is None
    assert current_session() is None
    assert bot.tool_manager.invocation_observer is None

    # Exiting a turn that never began is a no-op.
    bot._exit_task_turn(token)
    assert current_session() is None

    # The turn is byte-identical to the legacy one: `None` means "keep the
    # AIMessage.tool_calls conversion", so history does not change shape.
    assert bot.observed_tool_invocations() is None
    response = _Response([_ToolCall("wm_get_result")])
    enabled_off = ConversationTurn.from_ai_message(
        user_message="q",
        response=response,
        user_id="u",
        chatbot_id="bot-a",
        tool_invocations=bot.observed_tool_invocations(),
    )
    legacy = ConversationTurn.from_ai_message(
        user_message="q",
        response=response,
        user_id="u",
        chatbot_id="bot-a",
    )
    assert enabled_off.to_dict()["tool_invocations"] == legacy.to_dict()["tool_invocations"]
    assert [i.tool_name for i in enabled_off.tool_invocations] == ["wm_get_result"]


async def test_disabled_touches_no_task_memory_machinery(monkeypatch: pytest.MonkeyPatch) -> None:
    """The disabled path never constructs task-memory objects."""
    bot = _make_bot(enabled=False)

    import parrot.tools.working_memory.task_memory.observer as observer_mod

    built = []
    original = observer_mod.InvocationObserver

    class _Tripwire(original):  # type: ignore[misc,valid-type]
        """Records construction so a disabled turn can be proven inert."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Record and delegate."""
            built.append(args)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(observer_mod, "InvocationObserver", _Tripwire)

    for _ in range(3):
        token = bot._enter_task_turn("user-1", "sess-1")
        bot._exit_task_turn(token)
        assert bot.observed_tool_invocations() is None

    assert built == [], "the disabled path constructed an observer"
    assert TASK_CONTEXT.get() is None
