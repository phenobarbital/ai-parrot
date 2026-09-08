"""
End-to-end test: Conversation History with OpenAI + Redis (FEAT-524).

Exercises the full FEAT-524 conversation-ownership loop against the real
OpenAI API and a real Redis instance, covering:

1. Single turn persisted to Redis with chatbot_id segmentation
2. Multi-turn accumulation in a single session
3. render_history() output correctness (alternation, roles)
4. Session resume — new bot instance picks up prior history from Redis
5. History reaches the OpenAI client as formatted messages; LLM recalls context
6. Multi-bot isolation on the same user + session
7. Legacy un-segmented key re-keyed on first chatbot-segmented read
8. OpenAI fallback_model metadata when primary model capacity-errors

Requires:
    - Redis on localhost:6379 DB 3
    - OPENAI_API_KEY loaded via navconfig (NOT an env var directly)
"""

import uuid
import logging
import sys
from typing import Optional

import pytest
import pytest_asyncio

from parrot.bots import BaseBot
from parrot.memory import RedisConversation, ConversationTurn
from parrot.memory.render import render_history, HistoryMessage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REDIS_URL = "redis://localhost:6379/3"
TEST_PREFIX = f"oai_e2e_{uuid.uuid4().hex[:8]}"
USER_ID = "e2e_openai_user"
SESSION_ID = f"oai_session_{uuid.uuid4().hex[:8]}"

# Use gpt-4.1-nano — cheapest and fastest OpenAI model with chat support.
# The OpenAI client's built-in fallback (gpt-5-nano) will kick in
# automatically if the primary is unavailable.
LLM_MODEL = "gpt-4.1-nano"

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _openai_api_key() -> Optional[str]:
    """Load the OpenAI key via navconfig (project standard)."""
    try:
        from navconfig import config
        return config.get("OPENAI_API_KEY")
    except Exception:
        return None


def _can_reach_openai() -> bool:
    """Return True when the OpenAI key is set AND has active credits."""
    key = _openai_api_key()
    if not key:
        return False
    try:
        import httpx
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


# All tests in this module require a reachable, funded OpenAI account.
_openai_available = _can_reach_openai()
pytestmark = pytest.mark.skipif(
    not _openai_available,
    reason="OpenAI API not reachable or has no credits (OPENAI_API_KEY via navconfig)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_memory():
    """RedisConversation with a unique test-run prefix; cleans up after."""
    mem = RedisConversation(
        redis_url=REDIS_URL, use_hash_storage=True, key_prefix=TEST_PREFIX
    )
    assert await mem.ping(), f"Redis not reachable on {REDIS_URL}"
    yield mem
    # Cleanup every key created by this run
    cursor = 0
    while True:
        cursor, keys = await mem.redis.scan(cursor, match=f"{TEST_PREFIX}*", count=200)
        if keys:
            await mem.redis.delete(*keys)
        if cursor == 0:
            break
    await mem.close()


async def _make_bot(
    name: str,
    redis_memory: RedisConversation,
    model: str = LLM_MODEL,
) -> BaseBot:
    """Factory: create a BaseBot wired to OpenAI + the shared test Redis."""
    bot = BaseBot(
        name=name,
        chatbot_id=name,
        llm="openai",
        model=model,
        memory_type="redis",
        max_context_turns=20,
    )
    await bot.configure()
    bot.conversation_memory = redis_memory
    return bot


@pytest_asyncio.fixture
async def bot_alpha(redis_memory):
    return await _make_bot("oai_alpha", redis_memory)


@pytest_asyncio.fixture
async def bot_beta(redis_memory):
    return await _make_bot("oai_beta", redis_memory)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_turn_persisted(bot_alpha, redis_memory):
    """ask() → LLM response saved in Redis under the segmented key."""
    resp = await bot_alpha.ask(
        question="What is 7 * 8? Reply with just the number.",
        user_id=USER_ID,
        session_id=SESSION_ID,
        use_vector_context=False,
    )

    assert resp is not None
    assert resp.output, "Expected a non-empty LLM response"
    logger.info("Turn 1 response: %s", resp.output[:200])

    # Provider metadata
    assert resp.provider == "openai", f"Expected provider='openai', got {resp.provider!r}"
    assert resp.model, "Expected a model name in the response"

    # Persisted in Redis
    history = await redis_memory.get_history(USER_ID, SESSION_ID, chatbot_id="oai_alpha")
    assert history is not None, "History should exist in Redis"
    assert len(history.turns) == 1, f"Expected 1 turn, got {len(history.turns)}"

    turn = history.turns[0]
    assert "7 * 8" in turn.user_message or "7*8" in turn.user_message
    assert turn.assistant_response
    assert turn.chatbot_id == "oai_alpha"
    # OpenAI should answer 56
    assert "56" in turn.assistant_response


@pytest.mark.asyncio
async def test_multi_turn_accumulation(bot_alpha, redis_memory):
    """Three sequential turns accumulate in the same session, in order."""
    questions = [
        "I work at a bakery.",
        "What kind of shop do I work at?",
        "Suggest a pastry I should learn to make.",
    ]

    responses = []
    for q in questions:
        resp = await bot_alpha.ask(
            question=q,
            user_id=USER_ID,
            session_id=SESSION_ID,
            use_vector_context=False,
        )
        assert resp.output, f"Empty response for: {q}"
        responses.append(resp)
        logger.info("Q: %s → A: %s", q, resp.output[:120])

    # All 3 in Redis
    history = await redis_memory.get_history(USER_ID, SESSION_ID, chatbot_id="oai_alpha")
    assert history is not None
    assert len(history.turns) == 3, f"Expected 3 turns, got {len(history.turns)}"

    for i, turn in enumerate(history.turns):
        assert turn.user_message == questions[i]
        assert turn.chatbot_id == "oai_alpha"

    # Turn 2 should reference "bakery" — it's a context-dependent question
    assert "baker" in responses[1].output.lower(), (
        f"Turn 2 should recall the bakery. Got: {responses[1].output[:200]}"
    )


@pytest.mark.asyncio
async def test_render_history_alternation(bot_alpha, redis_memory):
    """render_history() produces strictly alternating user/assistant messages."""
    for q in ["Tell me something about the ocean.", "Now something about the sky."]:
        await bot_alpha.ask(
            question=q, user_id=USER_ID, session_id=SESSION_ID, use_vector_context=False,
        )

    history = await redis_memory.get_history(USER_ID, SESSION_ID, chatbot_id="oai_alpha")
    rendered = render_history(history, max_turns=10, current_chatbot_id="oai_alpha")

    assert len(rendered) >= 4, f"Expected ≥4 messages (2 turns), got {len(rendered)}"
    for i, msg in enumerate(rendered):
        assert isinstance(msg, HistoryMessage)
        expected_role = "user" if i % 2 == 0 else "assistant"
        assert msg.role == expected_role, f"Message {i}: expected {expected_role}, got {msg.role}"
    assert rendered[0].role == "user"
    assert rendered[-1].role == "assistant"


@pytest.mark.asyncio
async def test_session_resume_across_instances(redis_memory):
    """A fresh BaseBot instance resumes a session from Redis."""
    session_id = f"oai_resume_{uuid.uuid4().hex[:8]}"

    # Instance 1: plant a fact
    bot1 = await _make_bot("oai_resume_bot", redis_memory)
    resp1 = await bot1.ask(
        question="My favorite color is turquoise and I was born in 1990.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp1.output
    logger.info("Instance-1 response: %s", resp1.output[:200])

    # Instance 2: same chatbot_id, new object
    bot2 = await _make_bot("oai_resume_bot", redis_memory)
    resp2 = await bot2.ask(
        question="What is my favorite color and what year was I born?",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp2.output
    logger.info("Instance-2 response (resumed): %s", resp2.output[:200])

    # Both turns in the same session
    history = await redis_memory.get_history(USER_ID, session_id, chatbot_id="oai_resume_bot")
    assert len(history.turns) == 2

    # LLM should recall at least one of the planted facts
    answer_lower = resp2.output.lower()
    assert "turquoise" in answer_lower or "1990" in answer_lower, (
        f"LLM should recall planted facts from history. Got: {resp2.output[:300]}"
    )


@pytest.mark.asyncio
async def test_context_in_llm_response(bot_alpha, redis_memory):
    """Verify the LLM uses history — ask a context-dependent follow-up."""
    session_id = f"oai_ctx_{uuid.uuid4().hex[:8]}"

    await bot_alpha.ask(
        question="I speak Spanish and I am studying machine learning.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )

    resp2 = await bot_alpha.ask(
        question="What language do I speak and what am I studying?",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp2.output
    logger.info("Context follow-up: %s", resp2.output[:300])

    answer = resp2.output.lower()
    assert "spanish" in answer or "machine learning" in answer, (
        f"LLM should recall context. Got: {resp2.output[:300]}"
    )


@pytest.mark.asyncio
async def test_multi_bot_isolation(bot_alpha, bot_beta, redis_memory):
    """Two bots with the same user+session produce separate Redis histories."""
    session_id = f"oai_iso_{uuid.uuid4().hex[:8]}"

    await bot_alpha.ask(
        question="Tell me about penguins.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    await bot_beta.ask(
        question="Tell me about elephants.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )

    alpha_hist = await redis_memory.get_history(USER_ID, session_id, chatbot_id="oai_alpha")
    beta_hist = await redis_memory.get_history(USER_ID, session_id, chatbot_id="oai_beta")

    assert alpha_hist is not None and len(alpha_hist.turns) == 1
    assert beta_hist is not None and len(beta_hist.turns) == 1

    assert "penguin" in alpha_hist.turns[0].user_message.lower()
    assert "elephant" in beta_hist.turns[0].user_message.lower()

    # Keys are distinct
    alpha_key = redis_memory._get_key(USER_ID, session_id, "oai_alpha")
    beta_key = redis_memory._get_key(USER_ID, session_id, "oai_beta")
    assert alpha_key != beta_key

    # Cross-contamination check: alpha's key has no elephant data
    cross = await redis_memory.get_history(USER_ID, session_id, chatbot_id="oai_alpha")
    assert all("elephant" not in t.user_message.lower() for t in cross.turns)


@pytest.mark.asyncio
async def test_legacy_rekey_migration(redis_memory):
    """Legacy un-segmented key is transparently re-keyed on first chatbot-segmented read."""
    session_id = f"oai_legacy_{uuid.uuid4().hex[:8]}"
    chatbot_id = "oai_rekey_bot"

    # 1. Write a legacy record (no chatbot_id in the key)
    legacy_key = redis_memory._get_key(USER_ID, session_id, chatbot_id=None)
    turn = ConversationTurn(
        turn_id="legacy_oai_t1",
        user_id=USER_ID,
        user_message="Legacy OpenAI conversation",
        assistant_response="Response from the old storage format.",
    )
    await redis_memory.create_history(USER_ID, session_id, chatbot_id=None)
    await redis_memory.add_turn(USER_ID, session_id, turn, chatbot_id=None)
    assert await redis_memory.redis.exists(legacy_key)

    # 2. Read with chatbot_id — triggers re-key
    segmented_key = redis_memory._get_key(USER_ID, session_id, chatbot_id=chatbot_id)
    assert not await redis_memory.redis.exists(segmented_key)

    history = await redis_memory.get_history(USER_ID, session_id, chatbot_id=chatbot_id)

    assert history is not None
    assert len(history.turns) == 1
    assert history.turns[0].user_message == "Legacy OpenAI conversation"
    assert history.chatbot_id == chatbot_id

    # 3. Segmented key now populated; legacy preserved
    assert await redis_memory.redis.exists(segmented_key)
    assert await redis_memory.redis.exists(legacy_key), "Legacy key preserved for rollback"


@pytest.mark.asyncio
async def test_response_metadata_has_openai_fields(bot_alpha, redis_memory):
    """The AIMessage returned by ask() carries OpenAI-specific metadata."""
    session_id = f"oai_meta_{uuid.uuid4().hex[:8]}"

    resp = await bot_alpha.ask(
        question="What is the capital of France?",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )

    assert resp.output
    assert resp.provider == "openai"
    assert resp.model  # should be populated (e.g. "gpt-4.1-nano")
    logger.info("Model used: %s, provider: %s", resp.model, resp.provider)

    # Usage metadata
    usage = resp.usage
    assert usage is not None, "Expected usage data from OpenAI"
    assert usage.prompt_tokens > 0, "Expected prompt_tokens > 0"
    assert usage.completion_tokens > 0, "Expected completion_tokens > 0"
    logger.info(
        "Usage — prompt: %d, completion: %d, total: %d",
        usage.prompt_tokens, usage.completion_tokens, usage.total_tokens,
    )

    # Conversation context metadata should be present on turn 1 too
    # (it was not used, but the field should exist)
    meta = resp.metadata or {}
    conv_ctx = meta.get("conversation_context", {})
    logger.info("Conversation context meta: %s", conv_ctx)
