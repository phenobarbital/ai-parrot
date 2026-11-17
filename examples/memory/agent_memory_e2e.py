"""Demonstrate durable user and episodic recall across two fresh agent sessions."""

from __future__ import annotations

import argparse
import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

from parrot.bots.agent import BasicAgent
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.tools.working_memory import WorkingMemoryToolkit

logger = logging.getLogger(__name__)

AGENT_NAME = "memory-demo-agent"
TENANT_ID = "default"
CAPITAL_QUESTION = "¿Cuál es la capital de Australia?"
SESSION_B_QUESTION = "¿Qué sabes sobre mí y sobre cómo prefiero que me respondas?"
#: Wordings a model uses for the stored short-answer preference ("cortas", "breves", the literal bound).
PREFERENCE_MARKERS = ("cort", "brev", "una o dos frases")
SYSTEM_PROMPT = (
    "Eres un asistente de cultura general. Responde en español y respeta las preferencias duraderas "
    "que recuerdes sobre el usuario."
)


def _build_agent(
    *,
    llm: str,
    storage_path: Path,
    key_prefix: str,
    working_memory: WorkingMemoryToolkit,
) -> BasicAgent:
    """Create an agent with conversation, user, episodic and working memory enabled.

    Args:
        llm: Provider and model specification.
        storage_path: SQLite file shared by both fresh agents.
        key_prefix: Run-owned Redis conversation prefix.
        working_memory: In-process working-memory toolkit for this agent.

    Returns:
        An unconfigured four-plane memory agent.
    """
    return BasicAgent(
        name=AGENT_NAME,
        llm=llm,
        system_prompt=SYSTEM_PROMPT,
        temperature=0.2,
        tools=working_memory.get_tools(),
        memory_type="redis",
        memory_config={"key_prefix": key_prefix, "history_ttl": 600},
        enable_user_memory=True,
        enable_episodic_memory=True,
        agent_memory_config={
            "storage_path": str(storage_path),
            "max_episodic_warnings": 0,
            "max_episodic_recall": 3,
        },
    )


async def _delete_owned_history(agent: BasicAgent, user_id: str, session_id: str) -> None:
    """Delete one run-owned Redis history and close its connection.

    Args:
        agent: Agent that owns the conversation-memory connection.
        user_id: Demo user identity.
        session_id: Demo session identity.
    """
    memory = agent.conversation_memory
    if memory is None:
        return
    try:
        await memory.delete_history(user_id, session_id, chatbot_id=agent.memory_key_id)
    finally:
        await memory.close()


async def main(llm: str, storage_path: Path, user_id: str) -> None:
    """Teach in session A, close its agent, then show both recall planes in fresh session B.

    Args:
        llm: Provider and model specification.
        storage_path: SQLite file used by both fresh agents.
        user_id: Stable user identity shared by both sessions.
    """
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    key_prefix = f"agent-memory-example:{run_id}"
    session_a = f"session-a-{run_id}"
    session_b = f"session-b-{run_id}"
    agent_a: BasicAgent | None = None
    agent_b: BasicAgent | None = None
    agent_a_cleaned = False
    agent_b_cleaned = False

    logger.info("Starting memory example model=%s storage=%s user=%s", llm, storage_path, user_id)
    try:
        working_memory_a = WorkingMemoryToolkit(session_id=session_a)
        agent_a = _build_agent(
            llm=llm,
            storage_path=storage_path,
            key_prefix=key_prefix,
            working_memory=working_memory_a,
        )
        await agent_a.configure()

        session_a_questions = (
            "Me gustan las respuestas cortas, de una o dos frases como máximo.",
            CAPITAL_QUESTION,
        )
        for question in session_a_questions:
            response = await agent_a.ask(
                question,
                user_id=user_id,
                session_id=session_a,
                use_vector_context=False,
                return_sources=False,
            )
            logger.info("Session A user=%s", question)
            logger.info("Session A agent=%s", response.to_text)

        await working_memory_a.store_result(
            "temas_pendientes",
            ["Imperio Romano", "ríos de Sudamérica"],
            description="Temas que el usuario quiere consultar más adelante.",
        )
        logger.info("Working memory=%s", await working_memory_a.list_stored())

        conversation_memory = agent_a.conversation_memory
        if conversation_memory is None:
            raise RuntimeError("conversation memory was not configured")
        history = await conversation_memory.get_history(
            user_id,
            session_a,
            chatbot_id=agent_a.memory_key_id,
        )
        turn_count = len(history.turns) if history is not None else 0
        logger.info("Redis conversation history contains %d completed turns", turn_count)

        await agent_a.cleanup()
        agent_a_cleaned = True

        working_memory_b = WorkingMemoryToolkit(session_id=session_b)
        agent_b = _build_agent(
            llm=llm,
            storage_path=storage_path,
            key_prefix=key_prefix,
            working_memory=working_memory_b,
        )
        await agent_b.configure()

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
        logger.info("Recalled user profile=%s", context.user_knowledge or "(empty)")
        logger.info("Recalled earlier interaction=%s", context.episodic_recall or "(empty)")
        if not context.user_knowledge:
            raise RuntimeError("user profile extraction produced no durable record; inspect provider logs")
        if CAPITAL_QUESTION not in context.episodic_recall:
            raise RuntimeError("the earlier capital interaction was not recalled")

        response = await agent_b.ask(
            SESSION_B_QUESTION,
            user_id=user_id,
            session_id=session_b,
            use_vector_context=False,
            return_sources=False,
        )
        logger.info("Session B user=%s", SESSION_B_QUESTION)
        logger.info("Session B preference-aware answer=%s", response.to_text)
        answer = response.to_text.casefold()
        if not any(marker in answer for marker in PREFERENCE_MARKERS):
            raise RuntimeError("the fresh-session answer did not reflect the stored short-response preference")

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
                if agent_b is not None:
                    await _delete_owned_history(agent_b, user_id, session_b)
                if agent_a is not None:
                    await _delete_owned_history(agent_a, user_id, session_a)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", default="google:gemini-3-flash-preview")
    parser.add_argument(
        "--storage",
        type=Path,
        default=Path(tempfile.gettempdir()) / f"agent-memory-{uuid.uuid4().hex}.sqlite3",
    )
    parser.add_argument("--user-id", default="memory-demo-user")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(args.llm, args.storage, args.user_id))
