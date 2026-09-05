"""Shared fixtures for FEAT-525 compaction tests.

``make_turn`` generates deterministic, reproducible turns of an
approximate heuristic-token size (4 bytes/token, matching
``HeuristicCounter``) so downstream three-tier-walk tests (TASK-2828) can
reason about cumulative sizes without depending on ``tiktoken`` /
network access.
"""

from __future__ import annotations

import pytest

from parrot.memory.abstract import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import ContextBudget, ToolInvocation, ToolStatus
from parrot.memory.compaction.tokens import HeuristicCounter, TokenCounter


def _sized_text(prefix: str, tokens: int) -> str:
    """Build deterministic filler text sized to ~``tokens`` heuristic tokens.

    ``HeuristicCounter.count`` is ``len(text.encode("utf-8")) // 4``, so
    padding to ``tokens * 4`` characters lands close to the requested size.

    Args:
        prefix: A short, unique tag embedded in every word (helps debugging).
        tokens: Target heuristic token count.

    Returns:
        Deterministic ASCII text of approximately the requested size.
    """
    if tokens <= 0:
        return ""
    n_chars = tokens * 4
    words: list[str] = []
    total = 0
    idx = 0
    while total < n_chars:
        word = f"{prefix}{idx}"
        words.append(word)
        total += len(word) + 1
        idx += 1
    text = " ".join(words)
    return text[:n_chars] if len(text) > n_chars else text


def make_turn(
    i: int,
    *,
    tokens: int = 150,
    tool_output_chars: int = 0,
    chatbot_id: str = "bot",
) -> ConversationTurn:
    """Build a deterministic :class:`ConversationTurn` for compaction tests.

    Args:
        i: Turn index; used to derive the turn id and unique filler text.
        tokens: Approximate combined heuristic-token size of the WHOLE
            turn (user + assistant text + tool output), mirroring a
            realistic round where a big tool result — not the
            conversational text — dominates the size. When a
            ``tool_output_chars`` output is attached, its estimated
            heuristic token cost is subtracted from ``tokens`` first, so
            the user/assistant baseline stays small (a database agent's
            question and one-line answer, not another few thousand
            tokens of prose); the remainder is floored at 10 tokens so
            there is always some text.
        tool_output_chars: When > 0, attaches one ``ToolInvocation`` with an
            output of this many characters (used to model oversized tool
            results).
        chatbot_id: Attribution for the turn.

    Returns:
        A fully populated :class:`ConversationTurn`.
    """
    tool_tokens_estimate = tool_output_chars // 4
    body_tokens = max(10, tokens - tool_tokens_estimate)
    user_tokens = max(1, body_tokens // 3)
    assistant_tokens = max(1, body_tokens - user_tokens)
    user_message = _sized_text(f"u{i}_", user_tokens)
    assistant_response = _sized_text(f"a{i}_", assistant_tokens)

    tool_invocations: list[ToolInvocation] = []
    if tool_output_chars > 0:
        # Prefixed with the turn index so identical-length outputs across
        # turns still hash to distinct content ids (omission dedup keys
        # on content, not on (turn_id, field)).
        output = f"row{i}_" + "d" * tool_output_chars
        tool_invocations = [
            ToolInvocation(
                tool_name="query_database",
                input={"sql": f"SELECT * FROM t WHERE id={i}"},
                output=output,
                status=ToolStatus.COMPLETED,
                elapsed_ms=1200,
                output_chars=len(output),
            )
        ]

    return ConversationTurn(
        turn_id=f"turn-{i}",
        user_id="test-user",
        user_message=user_message,
        assistant_response=assistant_response,
        chatbot_id=chatbot_id,
        tool_invocations=tool_invocations,
    )


@pytest.fixture
def chatty_history() -> ConversationHistory:
    """50 text-only turns of ~150 heuristic tokens each."""
    history = ConversationHistory(session_id="chatty-session", user_id="test-user", chatbot_id="bot")
    for i in range(50):
        history.turns.append(make_turn(i, tokens=150))
    return history


@pytest.fixture
def database_history() -> ConversationHistory:
    """10 turns of ~8k heuristic tokens each, with a 30k-char tool output."""
    history = ConversationHistory(session_id="database-session", user_id="test-user", chatbot_id="bot")
    for i in range(10):
        history.turns.append(make_turn(i, tokens=8_000, tool_output_chars=30_000))
    return history


@pytest.fixture
def counter() -> TokenCounter:
    """Deterministic, offline counter — no tiktoken download in CI."""
    return HeuristicCounter()


@pytest.fixture
def budget() -> ContextBudget:
    """Default budget: available = 19_712, verbatim 15_000, max_turns 30."""
    return ContextBudget(window=32_000)
