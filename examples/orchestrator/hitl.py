"""Lightweight Human-in-the-Loop tool for the orchestrator example.

Production deployments should use ``parrot.human.HumanInteractionManager``
with a Redis-backed channel (CLI, Telegram, Web). For a self-contained,
runnable example we keep the round-trip in-process: the tool reads from
stdin via ``run_in_executor`` so the asyncio loop stays unblocked, or
returns a pre-baked answer when running a scripted scenario.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Optional

from parrot.tools import tool


_LOG = logging.getLogger("orchestrator.hitl")

# Scenario mode: when set, the orchestrator runs unattended and the
# question/answers are scripted via this module-level dict — see main.py
# for how scenarios populate it.
SCRIPTED_ANSWERS: dict[str, str] = {}


def _scripted_answer_for(question: str) -> Optional[str]:
    """Return a scripted answer when the question contains a known key."""
    lowered = question.lower()
    for key, answer in SCRIPTED_ANSWERS.items():
        if key.lower() in lowered:
            return answer
    return None


async def _ask_via_stdin(question: str, context: Optional[str]) -> str:
    """Render the question to stderr and read one line from stdin."""
    loop = asyncio.get_running_loop()

    def _prompt() -> str:
        if context:
            print(f"\n📋 Context: {context}", file=sys.stderr)
        print(f"\n🧑 Question for you: {question}", file=sys.stderr)
        print("→ ", end="", file=sys.stderr, flush=True)
        return sys.stdin.readline().strip()

    return await loop.run_in_executor(None, _prompt)


@tool
async def ask_user_question(
    question: str,
    context: Optional[str] = None,
) -> str:
    """Ask the human user a clarifying question and wait for the reply.

    Use this whenever you need information you do not have — employee
    id, severity confirmation, missing receipt status, impact details.
    Prefer one focused question per call.

    Args:
        question: A concise, specific question for the user.
        context: Optional short context shown above the question.

    Returns:
        The user's free-text response, stripped of surrounding whitespace.
    """
    scripted = _scripted_answer_for(question)
    if scripted is not None:
        _LOG.info("HITL scripted answer for '%s': %s", question, scripted)
        return scripted

    if os.getenv("ORCHESTRATOR_HITL", "interactive") == "noninteractive":
        # CI / non-tty fallback — the orchestrator should be running a
        # scripted scenario in this mode.
        return "(no human available — proceed with best assumption)"

    return await _ask_via_stdin(question, context)
