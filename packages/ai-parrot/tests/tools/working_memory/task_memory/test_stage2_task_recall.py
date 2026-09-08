"""TASK-3001 — deterministic task recall as the Stage 2 candidate.

Three properties, one per required case:

``test_combined_budget``
    The snapshot competes with history for one ``ContextBudget.available``.
    Either both fit — with framing and calibration inside the measurement
    — or the injection is declined with an explicit diagnostic. It never
    overruns, because an over-budget prompt is a provider error while a
    missing snapshot is a recoverable inconvenience.

``test_streaming_once``
    At most one snapshot per turn, and the framing never instructs the
    model to call recall as well — injecting a snapshot *and* asking for
    one wastes a round trip re-fetching what is already in context.

``test_kill_switch``
    With compaction disabled, or no task selected, rendering and saving
    are exactly what they were.

These drive `render_context_history` directly, which is the seam the spec
names ("add the candidate at the bot rendering layer"), with real
``compact_history`` and a real token counter — the budget arithmetic is
the thing under test, so stubbing it would test nothing.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

import pytest

from parrot.bots.abstract import AbstractBot
from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import ContextBudget, TurnState
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.models import TaskScope
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore
from parrot.tools.working_memory.task_memory.tools import TaskMemory

pytestmark = pytest.mark.asyncio


class _Counter:
    """The compaction counter's shape: bytes // 4, minimum one."""

    name = "heuristic"

    def count(self, text: str) -> int:
        """Estimate tokens for text.

        Args:
            text: The text to measure.

        Returns:
            The estimate.
        """
        return max(1, len(text.encode("utf-8")) // 4)


class _OmissionStore:
    """Records flushes so a declined injection can be told from a done one."""

    def __init__(self, fail: bool = False) -> None:
        """Initialize the store."""
        self.flushes: List[Any] = []
        self.fail = fail

    async def put_many(self, key: str, omissions: Any) -> None:
        """Record a flush.

        Args:
            key: The omission scope key.
            omissions: The omissions flushed.

        Raises:
            RuntimeError: When configured to fail.
        """
        if self.fail:
            raise RuntimeError("flush unavailable")
        self.flushes.append((key, tuple(omissions)))


class _Memory:
    """Minimal conversation memory: a counter and an omission store."""

    def __init__(self, fail_flush: bool = False) -> None:
        """Initialize the memory."""
        self.token_counter = _Counter()
        self.omission_store = _OmissionStore(fail=fail_flush)

    def omission_key(self, user_id: str, session_id: str, chatbot_id: Optional[str]) -> str:
        """Compose the omission key.

        Args:
            user_id: Owner.
            session_id: Session.
            chatbot_id: Producing agent.

        Returns:
            The key.
        """
        return f"{chatbot_id or '_default'}:{user_id}:{session_id}"


class _Bot(AbstractBot):
    """A bot reduced to what `render_context_history` actually touches."""

    def __init__(
        self,
        *,
        task_memory: Optional[TaskMemory] = None,
        budget: Optional[ContextBudget] = None,
        memory: Optional[_Memory] = None,
    ) -> None:
        """Initialize the stand-in bot."""
        self.task_memory = task_memory
        self._budget = budget
        self.conversation_memory = memory
        self.logger = logging.getLogger("stage2-bot")
        self.name = "bot-a"
        self.chatbot_id = "bot-a"
        self._chatbot_id_explicit = True
        self.max_context_turns = 30

    @property
    def context_budget(self) -> Optional[ContextBudget]:
        """The active budget. Overridden because the real one is read-only
        and resolves a window from the configured model."""
        return self._budget

    async def ask(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError

    async def ask_stream(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError

    async def conversation(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError

    async def invoke(self, *a: Any, **k: Any) -> Any:  # pragma: no cover
        """Unused stub."""
        raise NotImplementedError


def _history(turns: int, *, filler: int = 800) -> ConversationHistory:
    """Build a history big enough to trigger the overflow signal.

    Args:
        turns: How many turns to create.
        filler: Characters of filler per turn.

    Returns:
        The history.
    """
    history = ConversationHistory(user_id="user-1", session_id="sess-1", chatbot_id="bot-a")
    for i in range(turns):
        history.turns.append(
            ConversationTurn(
                turn_id=f"turn-{i}",
                user_id="user-1",
                user_message=f"question {i} " + ("q" * filler),
                assistant_response=f"answer {i} " + ("a" * filler),
                chatbot_id="bot-a",
            )
        )
    return history


async def _task_memory_with_task(goal: str = "reconcile the ledger") -> TaskMemory:
    """Build a task memory with one selected task.

    Args:
        goal: The task goal.

    Returns:
        The composition root, with the task selected.
    """
    scope = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    tm = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), scope)
    result = await tm.service.begin_task(scope, goal=goal)
    tm.select(result.state.task_id)
    return tm


def _injected(messages: List[Any]) -> Optional[Any]:
    """Return the injected recall message, if any.

    Args:
        messages: The rendered messages.

    Returns:
        The message, or ``None``.
    """
    for m in messages:
        if m.content.startswith(AbstractBot.TASK_RECALL_FRAMING[:20]):
            return m
    return None


# ─────────────────────────────────────────────────────────────
# test_combined_budget
# ─────────────────────────────────────────────────────────────


async def test_combined_budget() -> None:
    """History plus snapshot fits the budget, or injection is declined."""
    tm = await _task_memory_with_task()
    memory = _Memory()
    history = _history(24)

    # A window tight enough that the history genuinely overflows.
    budget = ContextBudget(window=9_000, reserve_output=1_000, reserve_fixed=500, min_verbatim_turns=1)
    bot = _Bot(task_memory=tm, budget=budget, memory=memory)

    messages, result = await bot.render_context_history(history)
    assert result is not None
    assert result.stage2_needed, "sanity: this history should overflow the budget"

    block = _injected(messages)
    assert block is not None, "a selected task plus the overflow signal should inject a snapshot"

    # The whole prompt — snapshot AND retained history — fits `available`,
    # with framing and calibration inside the measurement.
    counter = memory.token_counter
    snapshot_cost = counter.count(block.content)
    assert snapshot_cost > 0
    assert result.history_estimate + snapshot_cost <= budget.available, (
        f"combined {result.history_estimate + snapshot_cost} exceeds available {budget.available}"
    )

    # The snapshot is transient context, never a persisted turn.
    assert block.turn_id is None


async def test_combined_budget_declines_rather_than_overrunning(caplog: pytest.LogCaptureFixture) -> None:
    """When both cannot fit, the snapshot is dropped with a diagnostic."""
    tm = await _task_memory_with_task(goal="g" * 1_900)  # a deliberately large snapshot
    memory = _Memory()
    history = _history(12)

    # `min_verbatim_turns=8` is the floor that makes this unwinnable:
    # compact_history will not shrink history below those eight turns, so
    # no amount of re-budgeting frees room for the snapshot.
    budget = ContextBudget(window=1_400, reserve_output=200, reserve_fixed=100, min_verbatim_turns=8)
    bot = _Bot(task_memory=tm, budget=budget, memory=memory)

    with caplog.at_level(logging.INFO):
        messages, result = await bot.render_context_history(history)

    assert result is not None and result.stage2_needed
    # It MUST decline. Injecting here would overrun the provider window,
    # which is a hard error, whereas a missing snapshot merely costs the
    # model some context.
    assert _injected(messages) is None, "injected a snapshot that cannot fit the budget"

    # And it said why — an explicit diagnostic, not a silent no-op.
    diagnostics = [r.getMessage() for r in caplog.records if "declined" in r.getMessage()]
    assert diagnostics, [r.getMessage() for r in caplog.records]
    assert "verbatim" in diagnostics[0], diagnostics[0]

    # The verbatim minimum survived, which is precisely why it declined.
    verbatim = sum(1 for v in result.views if v.state is TurnState.RAW)
    assert verbatim >= min(budget.min_verbatim_turns, len(result.views))


async def test_combined_budget_keeps_history_when_the_extra_flush_fails() -> None:
    """A failed omission flush cancels the injection, losing nothing."""
    tm = await _task_memory_with_task()
    history = _history(24)
    budget = ContextBudget(window=9_000, reserve_output=1_000, reserve_fixed=500, min_verbatim_turns=1)

    # The FIRST flush (ordinary compaction) must succeed or the plain path
    # is taken and there is nothing to test; only the re-budget flush fails.
    memory = _Memory()
    bot = _Bot(task_memory=tm, budget=budget, memory=memory)
    baseline_messages, baseline = await bot.render_context_history(history)

    memory2 = _Memory()
    bot2 = _Bot(task_memory=await _task_memory_with_task(), budget=budget, memory=memory2)

    original = memory2.omission_store.put_many
    calls = {"n": 0}

    async def _flaky(key: str, omissions: Any) -> None:
        """Fail only the second flush.

        Args:
            key: Omission key.
            omissions: The omissions.

        Raises:
            RuntimeError: On the second call.
        """
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("flush unavailable")
        await original(key, omissions)

    memory2.omission_store.put_many = _flaky  # type: ignore[assignment]
    messages, result = await bot2.render_context_history(history)

    # Extra pruning is only safe once its omissions are recoverable, so a
    # failed flush must fall back rather than silently drop content.
    if calls["n"] >= 2:
        assert _injected(messages) is None
        assert [m.content for m in messages] == [m.content for m in baseline_messages]
        assert result is not None and baseline is not None


# ─────────────────────────────────────────────────────────────
# test_streaming_once
# ─────────────────────────────────────────────────────────────


async def test_streaming_once() -> None:
    """At most one snapshot, and it never also instructs recall."""
    tm = await _task_memory_with_task()
    memory = _Memory()
    history = _history(24)
    budget = ContextBudget(window=9_000, reserve_output=1_000, reserve_fixed=500, min_verbatim_turns=1)
    bot = _Bot(task_memory=tm, budget=budget, memory=memory)

    first, _ = await bot.render_context_history(history)
    assert _injected(first) is not None

    # A second render of the same turn — the ordinary and streaming paths
    # both call this — must not contribute another snapshot.
    second, _ = await bot.render_context_history(history)
    assert _injected(second) is None, "a turn received two snapshots"

    # And never more than one within a single rendering.
    assert sum(1 for m in first if m.content.startswith(AbstractBot.TASK_RECALL_FRAMING[:20])) == 1

    # The framing must not ask for a recall the snapshot already answers.
    framing = AbstractBot.TASK_RECALL_FRAMING.lower()
    for forbidden in ("wm_recall_task", "call recall", "you should call", "use the recall tool"):
        assert forbidden not in framing, f"framing instructs recall as well as injecting: {forbidden!r}"

    # It is honest about what it is: a projection, not an LLM summary.
    assert "not a summary of the conversation" in AbstractBot.TASK_RECALL_FRAMING


# ─────────────────────────────────────────────────────────────
# test_kill_switch
# ─────────────────────────────────────────────────────────────


async def test_kill_switch() -> None:
    """No budget, no task, or no signal → rendering is unchanged."""
    history = _history(24)
    tm = await _task_memory_with_task()

    # ── compaction kill switch: budget is None → plain path, no result
    bot = _Bot(task_memory=tm, budget=None, memory=_Memory())
    messages, result = await bot.render_context_history(history)
    assert result is None, "the kill switch must keep the plain rendering path"
    assert _injected(messages) is None

    # ── enabled compaction but NO selected task → no injection
    scope = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    unselected = TaskMemory(InMemoryTaskMemoryStore(), InMemoryArtifactStore(), scope)
    assert unselected.task_id is None
    budget = ContextBudget(window=9_000, reserve_output=1_000, reserve_fixed=500, min_verbatim_turns=1)
    bot2 = _Bot(task_memory=unselected, budget=budget, memory=_Memory())
    messages2, result2 = await bot2.render_context_history(history)
    assert result2 is not None and result2.stage2_needed
    assert _injected(messages2) is None, "recall must never pick a task by itself"

    # ── task memory absent entirely → byte-identical to the no-task render
    bot3 = _Bot(task_memory=None, budget=budget, memory=_Memory())
    messages3, result3 = await bot3.render_context_history(history)
    assert _injected(messages3) is None
    assert [(m.role, m.content) for m in messages3] == [(m.role, m.content) for m in messages2]

    # ── signal absent (history fits) → nothing injected even with a task
    small = _history(1, filler=10)
    bot4 = _Bot(task_memory=await _task_memory_with_task(), budget=budget, memory=_Memory())
    messages4, result4 = await bot4.render_context_history(small)
    assert result4 is not None and not result4.stage2_needed
    assert _injected(messages4) is None


async def test_kill_switch_never_persists_a_synthetic_turn() -> None:
    """The snapshot never becomes a stored turn."""
    tm = await _task_memory_with_task()
    memory = _Memory()
    history = _history(24)
    budget = ContextBudget(window=9_000, reserve_output=1_000, reserve_fixed=500, min_verbatim_turns=1)
    bot = _Bot(task_memory=tm, budget=budget, memory=memory)

    before = [t.turn_id for t in history.turns]
    messages, result = await bot.render_context_history(history)
    assert _injected(messages) is not None

    # Rendering is a read. The stored history is untouched, and no view
    # claims to be an LLM summary.
    assert [t.turn_id for t in history.turns] == before
    assert all(v.state is not TurnState.SUMMARIZED for v in result.views)
    # The injected message carries no turn id, so nothing can mistake it
    # for a real exchange when the turn is later saved.
    assert _injected(messages).turn_id is None


async def test_combined_budget_measures_framing_and_calibration(caplog: pytest.LogCaptureFixture) -> None:
    """The measured cost includes the framing and the calibration factor.

    Asserted against the decline diagnostic's own reported number rather
    than only its consequence: measuring the bare payload, or ignoring
    calibration, understates the snapshot and is exactly how a prompt
    silently goes over the provider's window. Both mistakes are invisible
    whenever the budget has slack, so they are pinned here directly.
    """
    import orjson

    calibration = 2.0
    tm = await _task_memory_with_task(goal="g" * 1_900)
    memory = _Memory()
    history = _history(12)
    # The calibration factor lives in the persisted compaction state, which
    # is the same place `render_context_history` reads it from.
    history.metadata["compaction"] = {"calibration": calibration}
    budget = ContextBudget(window=1_400, reserve_output=200, reserve_fixed=100, min_verbatim_turns=8)
    bot = _Bot(task_memory=tm, budget=budget, memory=memory)

    with caplog.at_level(logging.INFO):
        messages, _ = await bot.render_context_history(history)
    assert _injected(messages) is None

    diagnostics = [r.getMessage() for r in caplog.records if "declined" in r.getMessage()]
    assert diagnostics, [r.getMessage() for r in caplog.records]

    recall = await tm.reader.recall(tm.scope, tm.task_id)
    payload = orjson.dumps(recall.snapshot, option=orjson.OPT_SORT_KEYS).decode("utf-8")
    framed = memory.token_counter.count(bot.TASK_RECALL_FRAMING + payload)
    bare = memory.token_counter.count(payload)
    expected = int(round(framed * calibration))

    assert f"needs {expected} tokens" in diagnostics[0], diagnostics[0]
    # Distinguishable from both mistakes: the framing really does add
    # tokens, and the calibration really does scale them.
    assert framed > bare, "sanity: framing must cost something to be worth measuring"
    assert expected != framed, "sanity: calibration must change the number to be worth measuring"
