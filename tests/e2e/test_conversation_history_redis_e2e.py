"""
End-to-end test: Conversation History with Redis (FEAT-524).

Validates the full round-trip:
1. Bot configured with Redis conversation memory
2. Multi-turn conversation with a real LLM (Groq — fast + cheap)
3. Turns persisted in Redis under the segmented key
4. Session resume: new bot instance picks up history from Redis
5. render_history() produces correct alternating messages
6. Multi-bot isolation: two bots, same user/session, independent histories
7. Legacy re-key: un-segmented record migrated to segmented key on first read

Requires: Redis on localhost:6379/3, GROQ_API_KEY via navconfig.
"""

import asyncio
import uuid
import logging
import sys

import pytest
import pytest_asyncio

from parrot.bots import BaseBot
from parrot.memory import RedisConversation, ConversationTurn
from parrot.memory.render import render_history, HistoryMessage

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_PREFIX = f"e2e_test_{uuid.uuid4().hex[:8]}"  # isolate from real data
USER_ID = "e2e_user_alice"
SESSION_ID = f"e2e_session_{uuid.uuid4().hex[:8]}"

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def redis_memory():
    """Create a RedisConversation with a unique prefix and clean up after."""
    redis_url = "redis://localhost:6379/3"
    mem = RedisConversation(
        redis_url=redis_url, use_hash_storage=True, key_prefix=TEST_PREFIX
    )
    assert await mem.ping(), f"Redis is not reachable on {redis_url}"
    yield mem
    # Cleanup: delete all keys created by this test run
    cursor = 0
    while True:
        cursor, keys = await mem.redis.scan(cursor, match=f"{TEST_PREFIX}*", count=200)
        if keys:
            await mem.redis.delete(*keys)
        if cursor == 0:
            break
    await mem.close()


LLM_PROVIDER = "google"
LLM_MODEL = "gemini-2.5-flash"


@pytest_asyncio.fixture
async def bot_alpha(redis_memory):
    """A BaseBot wired to OpenAI gpt-4o-mini with Redis conversation memory."""
    bot = BaseBot(
        name="alpha_bot",
        chatbot_id="alpha_bot",
        llm=LLM_PROVIDER,
        model=LLM_MODEL,
        memory_type="redis",  # will be overridden below
        max_context_turns=20,
    )
    await bot.configure()
    # Override conversation memory with our test-isolated instance
    bot.conversation_memory = redis_memory
    return bot


@pytest_asyncio.fixture
async def bot_beta(redis_memory):
    """A second bot with a different identity, same Redis instance."""
    bot = BaseBot(
        name="beta_bot",
        chatbot_id="beta_bot",
        llm=LLM_PROVIDER,
        model=LLM_MODEL,
        memory_type="redis",
        max_context_turns=20,
    )
    await bot.configure()
    bot.conversation_memory = redis_memory
    return bot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_single_turn_persisted(bot_alpha, redis_memory):
    """A single ask() persists the turn in Redis."""
    response = await bot_alpha.ask(
        question="What is 2 + 2? Reply with just the number.",
        user_id=USER_ID,
        session_id=SESSION_ID,
        use_vector_context=False,
    )

    # 1. Got a real response
    assert response is not None
    assert response.output, "Expected a non-empty LLM response"
    logger.info("Turn 1 response: %s", response.output[:200])

    # 2. Turn was persisted in Redis under the segmented key
    history = await redis_memory.get_history(
        USER_ID, SESSION_ID, chatbot_id="alpha_bot"
    )
    assert history is not None, "History should exist in Redis"
    assert len(history.turns) == 1, f"Expected 1 turn, got {len(history.turns)}"

    turn = history.turns[0]
    assert "2 + 2" in turn.user_message
    assert turn.assistant_response  # non-empty
    assert turn.chatbot_id == "alpha_bot"


@pytest.mark.asyncio
async def test_multi_turn_conversation(bot_alpha, redis_memory):
    """Multiple turns accumulate in the same session."""
    questions = [
        "My name is Alice. Remember it.",
        "What is my name?",
        "Now spell my name backwards.",
    ]

    for q in questions:
        resp = await bot_alpha.ask(
            question=q,
            user_id=USER_ID,
            session_id=SESSION_ID,
            use_vector_context=False,
        )
        assert resp.output, f"Empty response for: {q}"
        logger.info("Q: %s → A: %s", q, resp.output[:120])

    # All 3 turns in Redis
    history = await redis_memory.get_history(
        USER_ID, SESSION_ID, chatbot_id="alpha_bot"
    )
    assert history is not None
    assert len(history.turns) == 3, f"Expected 3 turns, got {len(history.turns)}"

    # Verify chronological order
    for i, turn in enumerate(history.turns):
        assert turn.user_message == questions[i]
        assert turn.chatbot_id == "alpha_bot"


@pytest.mark.asyncio
async def test_render_history_correct(bot_alpha, redis_memory):
    """render_history produces alternating user/assistant HistoryMessages."""
    # Seed two turns
    for q in ["Hello, how are you?", "Tell me a joke."]:
        await bot_alpha.ask(
            question=q,
            user_id=USER_ID,
            session_id=SESSION_ID,
            use_vector_context=False,
        )

    history = await redis_memory.get_history(
        USER_ID, SESSION_ID, chatbot_id="alpha_bot"
    )
    rendered = render_history(
        history, max_turns=10, current_chatbot_id="alpha_bot"
    )

    assert len(rendered) >= 2, "Should render at least 2 messages (1 full turn)"
    # Must alternate user → assistant
    for i, msg in enumerate(rendered):
        assert isinstance(msg, HistoryMessage)
        expected_role = "user" if i % 2 == 0 else "assistant"
        assert msg.role == expected_role, (
            f"Message {i} should be {expected_role}, got {msg.role}"
        )
    # First message is user, last is assistant
    assert rendered[0].role == "user"
    assert rendered[-1].role == "assistant"


@pytest.mark.asyncio
async def test_session_resume(redis_memory):
    """A new bot instance resumes the conversation from Redis."""
    session_id = f"resume_{uuid.uuid4().hex[:8]}"

    # --- Bot instance 1: first turn ---
    bot1 = BaseBot(
        name="resume_bot",
        chatbot_id="resume_bot",
        llm=LLM_PROVIDER,
        model=LLM_MODEL,
        memory_type="redis",
        max_context_turns=20,
    )
    await bot1.configure()
    bot1.conversation_memory = redis_memory

    resp1 = await bot1.ask(
        question="My favorite city is Buenos Aires and my favorite number is 42.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp1.output
    logger.info("Bot1 turn 1: %s", resp1.output[:200])

    # --- Bot instance 2: same chatbot_id, fresh object ---
    bot2 = BaseBot(
        name="resume_bot",
        chatbot_id="resume_bot",
        llm=LLM_PROVIDER,
        model=LLM_MODEL,
        memory_type="redis",
        max_context_turns=20,
    )
    await bot2.configure()
    bot2.conversation_memory = redis_memory

    resp2 = await bot2.ask(
        question="What is my favorite city and my favorite number?",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp2.output
    logger.info("Bot2 turn 2 (resumed): %s", resp2.output[:200])

    # The response SHOULD reference the city and number, proving history was loaded
    history = await redis_memory.get_history(
        USER_ID, session_id, chatbot_id="resume_bot"
    )
    assert len(history.turns) == 2, "Both turns should be in the same session"
    # Check that the second call had rendered history from turn 1
    answer_lower = resp2.output.lower()
    assert "buenos aires" in answer_lower or "42" in answer_lower, (
        f"Expected LLM to recall the city or number from history. Got: {resp2.output[:300]}"
    )


@pytest.mark.asyncio
async def test_multi_bot_isolation(bot_alpha, bot_beta, redis_memory):
    """Two different bots sharing the same user+session have separate histories."""
    session_id = f"isolation_{uuid.uuid4().hex[:8]}"

    # Alpha talks about cats
    await bot_alpha.ask(
        question="Tell me a fact about cats.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    # Beta talks about dogs
    await bot_beta.ask(
        question="Tell me a fact about dogs.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )

    # Each bot's history is isolated
    alpha_hist = await redis_memory.get_history(
        USER_ID, session_id, chatbot_id="alpha_bot"
    )
    beta_hist = await redis_memory.get_history(
        USER_ID, session_id, chatbot_id="beta_bot"
    )

    assert alpha_hist is not None and len(alpha_hist.turns) == 1
    assert beta_hist is not None and len(beta_hist.turns) == 1

    # No cross-contamination
    assert "cats" in alpha_hist.turns[0].user_message.lower()
    assert "dogs" in beta_hist.turns[0].user_message.lower()

    # Verify Redis keys are different
    alpha_key = redis_memory._get_key(USER_ID, session_id, "alpha_bot")
    beta_key = redis_memory._get_key(USER_ID, session_id, "beta_bot")
    assert alpha_key != beta_key
    logger.info("Alpha key: %s  |  Beta key: %s", alpha_key, beta_key)


@pytest.mark.asyncio
async def test_legacy_rekey(redis_memory):
    """Legacy un-segmented history is migrated to segmented key on first read."""
    session_id = f"legacy_{uuid.uuid4().hex[:8]}"
    chatbot_id = "rekey_bot"

    # 1. Write a legacy record (no chatbot_id in key)
    legacy_key = redis_memory._get_key(USER_ID, session_id, chatbot_id=None)
    turn = ConversationTurn(
        turn_id="legacy_t1",
        user_id=USER_ID,
        user_message="Hello from the old world",
        assistant_response="Greetings from legacy storage.",
    )
    await redis_memory.create_history(USER_ID, session_id, chatbot_id=None)
    await redis_memory.add_turn(USER_ID, session_id, turn, chatbot_id=None)

    # Verify legacy key exists
    assert await redis_memory.redis.exists(legacy_key)

    # 2. Read with chatbot_id → should trigger re-key
    segmented_key = redis_memory._get_key(USER_ID, session_id, chatbot_id=chatbot_id)
    assert not await redis_memory.redis.exists(segmented_key), "Segmented key should not exist yet"

    history = await redis_memory.get_history(USER_ID, session_id, chatbot_id=chatbot_id)

    assert history is not None, "Should have migrated the legacy record"
    assert len(history.turns) == 1
    assert history.turns[0].user_message == "Hello from the old world"
    assert history.chatbot_id == chatbot_id

    # 3. Segmented key now exists
    assert await redis_memory.redis.exists(segmented_key), "Segmented key should exist after re-key"
    # Legacy key is preserved for rollback safety
    assert await redis_memory.redis.exists(legacy_key), "Legacy key should still exist"


@pytest.mark.asyncio
async def test_history_passed_to_client(bot_alpha, redis_memory):
    """Verify the LLM receives prior history — response metadata confirms it."""
    session_id = f"ctx_{uuid.uuid4().hex[:8]}"

    # Turn 1: seed with a distinctive fact
    resp1 = await bot_alpha.ask(
        question="I am learning Portuguese and I live in Buenos Aires.",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp1.output

    # Turn 2: depends on context
    resp2 = await bot_alpha.ask(
        question="What city do I live in and what language am I learning?",
        user_id=USER_ID,
        session_id=session_id,
        use_vector_context=False,
    )
    assert resp2.output
    logger.info("History-context response: %s", resp2.output[:300])

    # The AIMessage metadata should indicate conversation context was used
    meta = resp2.metadata or {}
    conv_ctx = meta.get("conversation_context", {})
    logger.info("Conversation context metadata: %s", conv_ctx)

    # Best-effort LLM check — it should recall at least one fact
    answer_lower = resp2.output.lower()
    assert "buenos aires" in answer_lower or "portuguese" in answer_lower, (
        f"LLM should recall facts from history. Got: {resp2.output[:300]}"
    )
