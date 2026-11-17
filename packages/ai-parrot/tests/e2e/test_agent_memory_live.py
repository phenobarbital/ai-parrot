"""Opt-in host proof of durable user and episodic recall across fresh agent sessions."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiosqlite
import pytest
from redis.asyncio import Redis

from parrot.bots.agent import BasicAgent
from parrot.conf import REDIS_HISTORY_URL
from parrot.e2e.errors import E2EPrerequisiteError
from parrot.e2e.live import (
    build_live_client,
    build_live_generation_budget,
    require_live_opt_in,
    resolve_plan_budget,
)
from parrot.memory.agent_memory.models import ChatStorageEvidenceRef, MemoryRequestScope
from parrot.storage import ChatStorage

pytestmark = [pytest.mark.real_llm, pytest.mark.live]

AGENT_NAME = "memory-live-agent"
TENANT_ID = "default"
CAPITAL_QUESTION = "¿Cuál es la capital de Australia?"
SESSION_A_QUESTIONS = (
    "Me gustan las respuestas cortas, de una o dos frases como máximo.",
    CAPITAL_QUESTION,
)
SESSION_B_QUESTION = "¿Qué sabes sobre mí y sobre cómo prefiero que me respondas?"
#: Wordings a model uses for the stored short-answer preference ("cortas", "breves", the literal bound).
PREFERENCE_MARKERS = ("cort", "brev", "una o dos frases")


def _redis_database_url(url: str, database: int) -> str:
    """Return a Redis URL pinned to one database while preserving credentials and options.

    Args:
        url: Configured Redis history URL.
        database: Redis logical database number.

    Returns:
        The URL with its path replaced by the requested logical database.

    Raises:
        ValueError: If the configured URL is not a TCP Redis URL.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.netloc:
        raise ValueError("REDIS_HISTORY_URL must be a redis:// or rediss:// URL for the live proof")
    return urlunsplit((parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment))


def _build_agent(
    *,
    client: Any,
    storage_path: Path,
    redis_url: str,
    key_prefix: str,
    extraction_client_factory: Callable[[], Any],
    evidence_tenant_resolver: Callable[[ChatStorageEvidenceRef], Awaitable[str | None]],
) -> BasicAgent:
    """Construct one live agent without resetting the run-scoped provider budget.

    Args:
        client: Dedicated answer client for this agent session.
        storage_path: SQLite file shared by both fresh agents.
        redis_url: Redis database-15 URL checked before provider construction.
        key_prefix: Run-owned Redis key prefix.
        extraction_client_factory: Factory for independent extraction clients.
        evidence_tenant_resolver: Trusted ChatStorage metadata resolver.

    Returns:
        An unconfigured agent with durable memory enabled.
    """
    agent = BasicAgent(
        name=AGENT_NAME,
        llm=client,
        system_prompt=(
            "Responde en español. Conserva y respeta las preferencias duraderas del usuario. "
            "Cuando el usuario pregunte qué sabes sobre él, menciona esas preferencias de forma directa."
        ),
        temperature=0.0,
        use_tools=False,
        memory_type="redis",
        memory_config={"redis_url": redis_url, "key_prefix": key_prefix, "history_ttl": 600},
        enable_user_memory=True,
        enable_episodic_memory=True,
        agent_memory_config={
            "storage_path": str(storage_path),
            "max_episodic_warnings": 0,
            "max_episodic_recall": 3,
        },
    )
    agent.memory_extraction_client_factory = extraction_client_factory
    agent.memory_evidence_tenant_resolver = evidence_tenant_resolver
    return agent


async def _sqlite_count(database_path: Path, statement: str, parameters: tuple[str, ...]) -> int:
    """Return one scoped SQLite count.

    Args:
        database_path: Durable memory database.
        statement: Parameterized count query.
        parameters: Values bound to the query.

    Returns:
        The integer count returned by SQLite.
    """
    async with aiosqlite.connect(database_path) as database:
        async with database.execute(statement, parameters) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_agent_memory_cross_session_live(tmp_path: Path) -> None:
    """Persist session A, reopen a fresh BasicAgent/session B and prove both recall planes."""
    plan_budget = resolve_plan_budget()
    try:
        opt_in = require_live_opt_in(budget=plan_budget)
    except E2EPrerequisiteError as exc:
        pytest.skip(str(exc))

    try:
        redis_url = _redis_database_url(REDIS_HISTORY_URL, 15)
    except ValueError as exc:
        pytest.skip(str(exc))

    key_prefix = f"agent-memory-e2e:{uuid.uuid4().hex}"
    redis_client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    redis_ready = False
    agent_a: BasicAgent | None = None
    agent_b: BasicAgent | None = None
    agent_a_cleaned = False
    agent_b_cleaned = False
    conversation_memories: list[Any] = []
    chat_storages: list[ChatStorage] = []

    async def resolve_evidence_tenant(reference: ChatStorageEvidenceRef) -> str | None:
        """Resolve only a same-tenant turn that authoritative ChatStorage can still read."""
        if reference.tenant_id != TENANT_ID or reference.agent_name != AGENT_NAME:
            return None
        for chat_storage in chat_storages:
            messages = await chat_storage.load_conversation(
                reference.user_id,
                reference.session_id,
                agent_id=reference.agent_name,
            )
            if any(message.get("turn_id") == reference.turn_id for message in messages):
                return TENANT_ID
        return None

    try:
        try:
            await redis_client.ping()
        except Exception as exc:  # noqa: BLE001 - unavailable infrastructure is an honest prerequisite skip
            pytest.skip(f"Redis database 15 is unavailable: {type(exc).__name__}")
        redis_ready = True

        shared_budget = build_live_generation_budget(opt_in, budget=plan_budget)

        def extraction_client_factory() -> Any:
            """Build a fresh extraction client against the same run-scoped budget."""
            return build_live_client(opt_in, shared_budget)

        database_path = tmp_path / "agent-memory-live.sqlite3"
        user_id = f"memory-live-user-{uuid.uuid4().hex}"
        session_a = f"session-a-{uuid.uuid4().hex}"
        session_b = f"session-b-{uuid.uuid4().hex}"

        agent_a = _build_agent(
            client=build_live_client(opt_in, shared_budget),
            storage_path=database_path,
            redis_url=redis_url,
            key_prefix=key_prefix,
            extraction_client_factory=extraction_client_factory,
            evidence_tenant_resolver=resolve_evidence_tenant,
        )
        await agent_a.configure()
        assert agent_a.conversation_memory is not None
        conversation_memories.append(agent_a.conversation_memory)
        chat_storages.append(ChatStorage(redis_conversation=agent_a.conversation_memory))

        for question in SESSION_A_QUESTIONS:
            await agent_a.ask(
                question,
                user_id=user_id,
                session_id=session_a,
                use_vector_context=False,
                return_sources=False,
                use_tools=False,
                max_tokens=256,
            )

        history = await agent_a.conversation_memory.get_history(
            user_id,
            session_a,
            chatbot_id=agent_a.memory_key_id,
        )
        assert history is not None
        assert len(history.turns) == len(SESSION_A_QUESTIONS)

        await agent_a.cleanup()
        agent_a_cleaned = True

        active_knowledge = await _sqlite_count(
            database_path,
            """
            SELECT COUNT(*)
            FROM user_knowledge
            WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND status = 'active'
            """,
            (TENANT_ID, AGENT_NAME, user_id),
        )
        recorded_episodes = await _sqlite_count(
            database_path,
            """
            SELECT COUNT(*)
            FROM episodes
            WHERE tenant_id = ? AND agent_id = ? AND user_id = ? AND session_id = ?
            """,
            (TENANT_ID, AGENT_NAME, user_id, session_a),
        )
        assert active_knowledge >= 1
        assert recorded_episodes == len(SESSION_A_QUESTIONS)

        agent_b = _build_agent(
            client=build_live_client(opt_in, shared_budget),
            storage_path=database_path,
            redis_url=redis_url,
            key_prefix=key_prefix,
            extraction_client_factory=extraction_client_factory,
            evidence_tenant_resolver=resolve_evidence_tenant,
        )
        await agent_b.configure()
        assert agent_b.conversation_memory is not None
        conversation_memories.append(agent_b.conversation_memory)
        chat_storages.append(ChatStorage(redis_conversation=agent_b.conversation_memory))

        context = await agent_b.prepare_memory(
            CAPITAL_QUESTION,
            scope=MemoryRequestScope(
                tenant_id=TENANT_ID,
                agent_id=AGENT_NAME,
                user_id=user_id,
                session_id=session_b,
                turn_id=uuid.uuid4().hex,
                identity_provenance="runtime_derived",
            ),
        )
        assert context.user_knowledge.strip()
        assert CAPITAL_QUESTION in context.episodic_recall

        response = await agent_b.ask(
            SESSION_B_QUESTION,
            user_id=user_id,
            session_id=session_b,
            use_vector_context=False,
            return_sources=False,
            use_tools=False,
            max_tokens=256,
        )
        answer = response.to_text.casefold()
        assert any(marker in answer for marker in PREFERENCE_MARKERS), answer

        await agent_b.cleanup()
        agent_b_cleaned = True
    finally:
        try:
            if agent_b is not None and not agent_b_cleaned:
                await agent_b.cleanup()
        finally:
            try:
                if agent_a is not None and not agent_a_cleaned:
                    await agent_a.cleanup()
            finally:
                for memory in reversed(conversation_memories):
                    await memory.close()
                if redis_ready:
                    owned_keys = [key async for key in redis_client.scan_iter(match=f"{key_prefix}*")]
                    if owned_keys:
                        await redis_client.delete(*owned_keys)
                await redis_client.close()
