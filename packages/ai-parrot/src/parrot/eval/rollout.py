"""Rollout strategies and user simulators for the Generic Agent Evaluation Harness.

FEAT-217 — Module 5.

Rollout strategies drive an agent against a task inside a sandbox and
return a ``Trajectory``.  User simulators generate user-side turns for
conversational (τ-bench style) evaluations.

Provided implementations:
- ``SingleTurnRollout`` — one ``bot.ask()`` call; suitable for
  single-shot toolkit agents.
- ``ConversationalRollout`` — iterative ``bot.conversation()`` loop driven
  by a ``UserSimulator``; suitable for multi-turn agents.
- ``LLMUserSimulator`` — calls ``client.ask()`` to generate synthetic user
  turns (τ-bench style, temperature = 0 for reproducibility).
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from parrot.eval.models import (
    EvalTask,
    Trajectory,
    TurnRecord,
)
from parrot.eval.sandbox.base import Sandbox

if TYPE_CHECKING:
    from parrot.bots.abstract import AbstractBot
    from parrot.clients.base import AbstractClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UserSimulator ABC
# ---------------------------------------------------------------------------


class UserSimulator(ABC):
    """Abstract user-side simulator for conversational rollouts.

    Generates the next user message given the current conversation history.
    Returns ``None`` to signal that the task is complete or that the
    simulator gives up.
    """

    @abstractmethod
    async def respond(
        self,
        conversation: list[TurnRecord],
        scenario: str,
    ) -> str | None:
        """Generate the next user utterance.

        Args:
            conversation: Current conversation history (turns so far).
            scenario: Natural language description of the user's goal
                (from ``EvalTask.user_scenario``).

        Returns:
            The next user message, or ``None`` to end the conversation.
        """
        ...


# ---------------------------------------------------------------------------
# LLMUserSimulator
# ---------------------------------------------------------------------------


class LLMUserSimulator(UserSimulator):
    """User simulator backed by an LLM (``AbstractClient.ask()``).

    Sends the scenario + conversation history to the model and asks it to
    generate the next user turn.  Uses ``temperature=0`` for reproducibility
    (spec D6).

    A ``None`` return from the model (or any response that looks like an
    end-of-task signal) stops the conversational rollout.

    Args:
        client: ``AbstractClient`` instance to use for turn generation.
            Must NOT be the same model-under-test.
        system_prompt: Optional system prompt.  Defaults to a sensible
            user-simulation instruction.
    """

    _DEFAULT_SYSTEM_PROMPT = (
        "You are simulating a user in a customer-support scenario. "
        "Your job is to interact with an AI assistant to complete the "
        "described task. Be concise. When you believe the task is complete, "
        "respond with exactly: TASK_COMPLETE"
    )

    def __init__(
        self,
        client: "AbstractClient",
        system_prompt: str | None = None,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt or self._DEFAULT_SYSTEM_PROMPT
        self.logger = logging.getLogger(__name__)

    async def respond(
        self,
        conversation: list[TurnRecord],
        scenario: str,
    ) -> str | None:
        """Generate the next user utterance via the client.

        Args:
            conversation: Conversation history so far.
            scenario: The user's goal description.

        Returns:
            Next user message, or ``None`` when the task is complete.
        """
        history_lines = []
        for turn in conversation:
            role = turn.role.upper()
            history_lines.append(f"{role}: {turn.content or ''}")
        history = "\n".join(history_lines)

        prompt = (
            f"Scenario: {scenario}\n\n"
            f"Conversation so far:\n{history}\n\n"
            "What is the user's next message? "
            "(Reply TASK_COMPLETE if the task is done, or GIVE_UP if stuck)"
        )

        try:
            model = getattr(self._client, "model", None) or "gpt-4o-mini"
            response = await self._client.ask(
                prompt=prompt,
                model=model,
                temperature=0.0,
                system_prompt=self._system_prompt,
            )
            text = _extract_text(response)
            if text is None or text.strip() in ("TASK_COMPLETE", "GIVE_UP", ""):
                return None
            return text.strip()
        except Exception as exc:
            self.logger.warning("LLMUserSimulator.respond failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# RolloutStrategy ABC
# ---------------------------------------------------------------------------


class RolloutStrategy(ABC):
    """Abstract strategy for driving an agent through a task.

    A rollout strategy calls ``bot.ask()`` or ``bot.conversation()`` and
    records the resulting ``Trajectory``.
    """

    @abstractmethod
    async def run(
        self,
        bot: "AbstractBot",
        task: EvalTask,
        sandbox: Sandbox,
    ) -> Trajectory:
        """Drive *bot* through *task* in *sandbox* and return the trajectory.

        Args:
            bot: The agent to drive.
            task: The evaluation task.
            sandbox: The sandbox the agent is executing in (used to capture
                ``final_state`` after the rollout, if not handled by the runner).

        Returns:
            Completed ``Trajectory`` with turns, latency, tokens, etc.
        """
        ...


# ---------------------------------------------------------------------------
# SingleTurnRollout
# ---------------------------------------------------------------------------


class SingleTurnRollout(RolloutStrategy):
    """One-shot rollout: a single ``bot.ask()`` call.

    Suitable for single-shot toolkit agents (e.g. "Do CRUD task X").
    Records one ``TurnRecord`` (role=``"agent"``) with the bot's response.
    """

    async def run(
        self,
        bot: "AbstractBot",
        task: EvalTask,
        sandbox: Sandbox,
    ) -> Trajectory:
        """Execute a single ``bot.ask()`` call and return the trajectory.

        Args:
            bot: Agent to query.
            task: Eval task; ``task.inputs`` must contain a ``"query"`` key
                (or another string-valued key used as the question).
            sandbox: Active sandbox (final_state captured by the runner).

        Returns:
            ``Trajectory`` with one turn, ``final_output``, and
            ``latency_ms``.
        """
        # Extract the question from task inputs
        question = _extract_question(task)

        t0 = time.perf_counter()
        try:
            response = await bot.ask(question)
            text = _extract_text(response)
            latency_ms = (time.perf_counter() - t0) * 1000.0

            turn = TurnRecord(
                role="agent",
                content=text,
                timestamp=time.time(),
            )
            return Trajectory(
                task_id=task.task_id,
                attempt=0,  # attempt is set by EvalRunner
                turns=[turn],
                final_output=text,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            logger.error("SingleTurnRollout failed for task %s: %s", task.task_id, exc)
            return Trajectory(
                task_id=task.task_id,
                attempt=0,
                latency_ms=latency_ms,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# ConversationalRollout
# ---------------------------------------------------------------------------


class ConversationalRollout(RolloutStrategy):
    """Multi-turn rollout that loops ``bot.conversation()`` against a simulator.

    The conversation continues until the simulator returns ``None`` or
    ``max_turns`` is reached.

    Args:
        user_sim: ``UserSimulator`` that generates user-side turns.
        max_turns: Maximum number of agent turns before giving up.
    """

    def __init__(
        self,
        user_sim: UserSimulator,
        max_turns: int = 30,
    ) -> None:
        self._user_sim = user_sim
        self._max_turns = max_turns
        self.logger = logging.getLogger(__name__)

    async def run(
        self,
        bot: "AbstractBot",
        task: EvalTask,
        sandbox: Sandbox,
    ) -> Trajectory:
        """Drive a multi-turn conversation until completion or max_turns.

        Args:
            bot: The conversational agent.
            task: Eval task with a ``user_scenario`` for the simulator.
            sandbox: Active sandbox.

        Returns:
            ``Trajectory`` with all turns, ``final_output`` (last agent
            response), and ``latency_ms``.
        """
        scenario = task.user_scenario or str(task.inputs)
        turns: list[TurnRecord] = []
        session_id = f"eval-{task.task_id}"
        t_start = time.perf_counter()
        final_output: Any = None

        # Seed the conversation with the task's initial query (if any)
        initial_question = _extract_question(task)
        current_message = initial_question

        try:
            for _turn_idx in range(self._max_turns):
                if current_message is None:
                    break

                # User turn
                turns.append(
                    TurnRecord(
                        role="user",
                        content=current_message,
                        timestamp=time.time(),
                    )
                )

                # Agent turn
                t_turn = time.perf_counter()
                response = await bot.conversation(
                    question=current_message,
                    session_id=session_id,
                )
                _turn_latency = (time.perf_counter() - t_turn) * 1000.0

                agent_text = _extract_text(response)
                final_output = agent_text
                turns.append(
                    TurnRecord(
                        role="agent",
                        content=agent_text,
                        timestamp=time.time(),
                    )
                )

                # Simulator decides next message
                current_message = await self._user_sim.respond(turns, scenario)

        except Exception as exc:
            latency_ms = (time.perf_counter() - t_start) * 1000.0
            self.logger.error(
                "ConversationalRollout failed for task %s: %s", task.task_id, exc
            )
            return Trajectory(
                task_id=task.task_id,
                attempt=0,
                turns=turns,
                latency_ms=latency_ms,
                error=str(exc),
            )

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        return Trajectory(
            task_id=task.task_id,
            attempt=0,
            turns=turns,
            final_output=final_output,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_question(task: EvalTask) -> str:
    """Extract a string question from task.inputs.

    Looks for common keys (``"query"``, ``"question"``, ``"input"``,
    ``"message"``) and falls back to a JSON-like representation.

    Args:
        task: The evaluation task.

    Returns:
        String question for the agent.
    """
    for key in ("query", "question", "input", "message", "prompt"):
        if key in task.inputs:
            val = task.inputs[key]
            if isinstance(val, str):
                return val
    # Fallback: serialize the whole inputs dict
    import json
    return json.dumps(task.inputs)


def _extract_text(response: Any) -> str | None:
    """Extract text content from an AIMessage or MessageResponse.

    Args:
        response: Return value from ``bot.ask()`` / ``client.ask()``.

    Returns:
        String content or ``None``.
    """
    if response is None:
        return None
    # AIMessage (AbstractBot.ask returns): .content attribute
    if hasattr(response, "content"):
        return str(response.content) if response.content is not None else None
    # MessageResponse (AbstractClient.ask returns): .response or .text
    if hasattr(response, "response"):
        return str(response.response) if response.response is not None else None
    if hasattr(response, "text"):
        return str(response.text) if response.text is not None else None
    return str(response)
