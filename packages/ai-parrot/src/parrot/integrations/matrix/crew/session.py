"""Collaborative session orchestrator for Matrix multi-agent investigation.

``MatrixCollaborativeSession`` manages the full lifecycle of a phased
collaborative investigation triggered by ``!investigate`` in a Matrix room:

1. **INVESTIGATING** — All registered agents investigate the question in parallel.
2. **CROSS_POLLINATING** (1-N configurable rounds) — Agents see each other's
   results injected as enriched context and refine their analysis.
3. **SYNTHESIZING** — A dedicated summarizer agent (or raw results fallback)
   produces the final answer.
4. **COMPLETED** (or **FAILED** on error) — Session archived, transport
   returns to normal routing.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional

from .config import CollaborativeConfig
from .mention import parse_mention
from .session_models import (
    AgentRoundResult,
    CollaborativeSessionState,
    SessionPhase,
)

try:
    from parrot.manager import BotManager  # type: ignore
except ImportError:
    BotManager = None  # type: ignore

if TYPE_CHECKING:
    from ..appservice import MatrixAppService
    from .crew_wrapper import MatrixCrewAgentWrapper
    from .registry import MatrixAgentCard, MatrixCrewRegistry


class MatrixCollaborativeSession:
    """Stateful session managing one collaborative investigation in a Matrix room.

    Orchestrates phased rounds directly via Matrix messages. The Matrix room
    is the shared memory — agents communicate by posting messages that others
    can see.

    Args:
        session_id: Unique identifier for this session (UUID string).
        room_id: Matrix room where the session takes place.
        question: The original question from the ``!investigate`` command.
        config: Collaborative session configuration.
        appservice: Shared ``MatrixAppService`` for sending messages.
        registry: ``MatrixCrewRegistry`` for agent discovery.
        wrappers: Mapping of agent_name → ``MatrixCrewAgentWrapper``.
        server_name: Matrix server domain (e.g. "example.com").
    """

    def __init__(
        self,
        session_id: str,
        room_id: str,
        question: str,
        config: CollaborativeConfig,
        appservice: "MatrixAppService",
        registry: "MatrixCrewRegistry",
        wrappers: Dict[str, "MatrixCrewAgentWrapper"],
        server_name: str,
    ) -> None:
        self._session_id = session_id
        self._room_id = room_id
        self._question = question
        self._config = config
        self._appservice = appservice
        self._registry = registry
        self._wrappers = wrappers
        self._server_name = server_name
        self._state = CollaborativeSessionState(
            session_id=session_id,
            room_id=room_id,
            question=question,
            max_rounds=config.max_rounds,
        )
        self._cancelled = False
        self._cancel_reason: Optional[str] = None
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def phase(self) -> SessionPhase:
        """Current lifecycle phase of the session."""
        return self._state.phase

    @property
    def is_active(self) -> bool:
        """Whether the session is still in progress (not completed/failed)."""
        return self._state.phase not in (
            SessionPhase.COMPLETED,
            SessionPhase.FAILED,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> CollaborativeSessionState:
        """Execute the full session lifecycle.

        Phases: investigate → cross-pollinate (N rounds) → synthesize.
        The entire run is wrapped in ``session_timeout``.

        Returns:
            The final ``CollaborativeSessionState`` after the session ends.
        """
        self._state.started_at = datetime.now(timezone.utc)

        try:
            await asyncio.wait_for(
                self._run_inner(),
                timeout=self._config.session_timeout,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Session %s timed out after %s seconds",
                self._session_id,
                self._config.session_timeout,
            )
            self._state.phase = SessionPhase.FAILED
            await self._announce(
                f"Session timed out after {self._config.session_timeout:.0f} seconds."
            )
        except Exception as exc:
            self.logger.error(
                "Session %s failed: %s", self._session_id, exc, exc_info=True
            )
            self._state.phase = SessionPhase.FAILED
            await self._announce(
                f"Collaborative session failed: {exc}"
            )

        self._state.completed_at = datetime.now(timezone.utc)
        return self._state

    async def handle_inter_agent_message(
        self,
        sender_mxid: str,
        body: str,
        event_id: str,
    ) -> None:
        """Route an @mention from one agent to another during an active session.

        Called by the transport when an agent message containing an @mention
        is received during an active collaborative session.

        Args:
            sender_mxid: Full MXID of the sending agent.
            body: Message body containing the @mention.
            event_id: Matrix event ID of the incoming message.
        """
        if not self.is_active:
            return

        localpart = parse_mention(body, self._server_name)
        if not localpart:
            return

        # Find the target wrapper by mxid_localpart
        target_wrapper = None
        target_agent_name = None
        for agent_name, wrapper in self._wrappers.items():
            if hasattr(wrapper, "_config") and wrapper._config.mxid_localpart == localpart:
                target_wrapper = wrapper
                target_agent_name = agent_name
                break

        if not target_wrapper:
            self.logger.debug(
                "No wrapper found for @%s during session", localpart
            )
            return

        self.logger.info(
            "Session %s: routing inter-agent message from %s to %s",
            self._session_id,
            sender_mxid,
            target_agent_name,
        )
        await target_wrapper.handle_message(
            self._room_id,
            sender_mxid,
            body,
            event_id,
        )

    async def cancel(self, reason: str = "Cancelled by user") -> None:
        """Cancel the session and post a notice to the room.

        Args:
            reason: Human-readable cancellation reason.
        """
        self._cancelled = True
        self._cancel_reason = reason
        self._state.phase = SessionPhase.FAILED
        self._state.completed_at = datetime.now(timezone.utc)
        await self._announce(f"Collaborative session cancelled: {reason}")
        self.logger.info(
            "Session %s cancelled: %s", self._session_id, reason
        )

    # ------------------------------------------------------------------
    # Internal lifecycle
    # ------------------------------------------------------------------

    async def _run_inner(self) -> None:
        """Execute phases without the outer timeout wrapper."""
        # Phase 1: INVESTIGATING
        self._state.phase = SessionPhase.INVESTIGATING
        await self._announce("Starting investigation…")
        await self._investigate_phase()

        if self._cancelled:
            return

        # Check if all agents failed
        if not self._has_any_results():
            self._state.phase = SessionPhase.FAILED
            await self._announce(
                "All agents failed to respond. Cannot continue session."
            )
            return

        # Phase 2: CROSS_POLLINATING (N rounds)
        for round_num in range(1, self._config.max_rounds + 1):
            if self._cancelled:
                return
            self._state.phase = SessionPhase.CROSS_POLLINATING
            self._state.current_round = round_num
            await self._announce(
                f"Cross-pollination round {round_num}/{self._config.max_rounds}…"
            )
            await self._cross_pollinate_phase(round_num)

        if self._cancelled:
            return

        # Phase 3: SYNTHESIZING
        self._state.phase = SessionPhase.SYNTHESIZING
        await self._announce("Synthesizing findings…")
        await self._synthesize_phase()

        if not self._cancelled:
            self._state.phase = SessionPhase.COMPLETED
            await self._announce("Investigation complete.")

    async def _investigate_phase(self) -> None:
        """Call all non-summarizer agents in parallel with per-agent timeout."""
        agents = await self._registry.all_agents()
        tasks = []
        for card in agents:
            if card.agent_name == self._config.summarizer_agent:
                continue  # Skip summarizer during investigation
            wrapper = self._wrappers.get(card.agent_name)
            if wrapper:
                tasks.append(
                    self._call_agent_with_timeout(card, wrapper, self._question, round_number=0)
                )

        if not tasks:
            self.logger.warning(
                "Session %s: no agents found for investigation", self._session_id
            )
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                self.logger.warning(
                    "Agent task raised exception: %s", result
                )

    async def _cross_pollinate_phase(self, round_num: int) -> None:
        """Inject enriched context from prior results, call all agents."""
        agents = await self._registry.all_agents()
        tasks = []
        for card in agents:
            if card.agent_name == self._config.summarizer_agent:
                continue
            wrapper = self._wrappers.get(card.agent_name)
            if wrapper:
                enriched_prompt = self._build_enriched_context(
                    round_num, card.agent_name
                )
                tasks.append(
                    self._call_agent_with_timeout(
                        card, wrapper, enriched_prompt, round_number=round_num
                    )
                )

        if not tasks:
            return

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                self.logger.warning(
                    "Agent task raised exception during cross-pollination: %s", result
                )

    async def _synthesize_phase(self) -> None:
        """Call the summarizer agent with a structured payload."""
        if not self._config.summarizer_agent:
            # Fallback: post raw results
            await self._post_raw_results()
            return

        summarizer_wrapper = self._wrappers.get(self._config.summarizer_agent)
        if not summarizer_wrapper:
            self.logger.warning(
                "Summarizer agent '%s' not found in wrappers, posting raw results",
                self._config.summarizer_agent,
            )
            await self._post_raw_results()
            return

        # Build structured payload
        payload = self._build_synthesizer_payload()

        try:
            agent = await BotManager.get_bot(  # type: ignore[union-attr]
                summarizer_wrapper._config.chatbot_id
            )
            if agent is None:
                raise RuntimeError(
                    f"Summarizer '{summarizer_wrapper._config.chatbot_id}' not found"
                )

            synthesis = await asyncio.wait_for(
                agent.ask(payload),
                timeout=self._config.agent_timeout,
            )
            synthesis_text = str(synthesis)

            event_id = await self._appservice.send_as_agent(
                self._config.summarizer_agent,
                self._room_id,
                synthesis_text,
            )

            self._state.final_synthesis = synthesis_text
            self.logger.info(
                "Session %s: synthesis posted (event %s)",
                self._session_id,
                event_id,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Session %s: summarizer timed out, posting raw results",
                self._session_id,
            )
            await self._announce("Summarizer timed out. Posting raw results.")
            await self._post_raw_results()
        except Exception as exc:
            self.logger.error(
                "Session %s: synthesizer failed: %s", self._session_id, exc
            )
            await self._announce(f"Synthesis failed: {exc}. Posting raw results.")
            await self._post_raw_results()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_agent_with_timeout(
        self,
        card: "MatrixAgentCard",
        wrapper: "MatrixCrewAgentWrapper",
        prompt: str,
        round_number: int,
    ) -> Optional[AgentRoundResult]:
        """Call one agent with agent_timeout, posting result to the room.

        Args:
            card: Agent registry card.
            wrapper: Agent wrapper for invocation.
            prompt: Question or enriched context prompt.
            round_number: Current round (0=investigation, 1+= cross-pollination).

        Returns:
            ``AgentRoundResult`` on success, ``None`` on timeout/error.
        """
        try:
            agent = await BotManager.get_bot(wrapper._config.chatbot_id)
            if agent is None:
                raise RuntimeError(
                    f"Agent '{wrapper._config.chatbot_id}' not found"
                )

            response_obj = await asyncio.wait_for(
                agent.ask(prompt),
                timeout=self._config.agent_timeout,
            )
            response_text = str(response_obj)

            # Post the result to the room
            event_id = await self._appservice.send_as_agent(
                card.agent_name,
                self._room_id,
                response_text,
            )

            result = AgentRoundResult(
                agent_name=card.agent_name,
                display_name=card.display_name,
                mxid=card.mxid,
                round_number=round_number,
                result_text=response_text,
                event_id=event_id,
                timestamp=datetime.now(timezone.utc),
            )

            # Store in state
            if card.agent_name not in self._state.agent_results:
                self._state.agent_results[card.agent_name] = []
            self._state.agent_results[card.agent_name].append(result)

            self.logger.info(
                "Session %s: agent '%s' responded (round %d, event %s)",
                self._session_id,
                card.agent_name,
                round_number,
                event_id,
            )
            return result

        except asyncio.TimeoutError:
            self.logger.warning(
                "Session %s: agent '%s' timed out (round %d)",
                self._session_id,
                card.agent_name,
                round_number,
            )
            await self._announce(
                f"{card.display_name} timed out, skipping."
            )
            return None

        except Exception as exc:
            self.logger.error(
                "Session %s: agent '%s' error: %s",
                self._session_id,
                card.agent_name,
                exc,
            )
            return None

    def _build_enriched_context(self, round_num: int, requesting_agent: str) -> str:
        """Build the enriched context prompt for a cross-pollination round.

        Includes the original question and a summary of all other agents'
        prior results. The agent is prompted to review peers' findings and
        refine its analysis.

        Args:
            round_num: Current cross-pollination round number.
            requesting_agent: Agent that will receive this prompt (their own
                prior results are excluded to reduce repetition).

        Returns:
            Enriched prompt string.
        """
        lines = [
            f"Original question: {self._question}",
            f"Round {round_num} cross-pollination. Other agents' findings:",
        ]

        for agent_name, results_list in self._state.agent_results.items():
            if agent_name == requesting_agent:
                continue
            if results_list:
                # Use the most recent result
                latest = results_list[-1]
                # Truncate long results to keep the prompt manageable
                summary = latest.result_text[:500]
                if len(latest.result_text) > 500:
                    summary += "…"
                lines.append(f"- [{latest.display_name}]: {summary}")

        if len(lines) == 2:
            # No other agents had results
            lines.append("(No other agent results available yet)")

        lines.extend([
            "",
            "Review your peers' findings and refine your analysis. You may @mention"
            " a colleague to ask them a question or request them to use a tool.",
        ])

        return "\n".join(lines)

    def _build_synthesizer_payload(self) -> str:
        """Build the structured payload for the summarizer agent.

        Returns a formatted string with the original question and all
        agent results organized by agent name.

        Returns:
            Structured synthesis prompt string.
        """
        lines = [
            "Synthesize the following investigation results for the question:",
            f'"{self._question}"',
            "",
            "Agent findings:",
        ]

        for agent_name, results_list in self._state.agent_results.items():
            if not results_list:
                continue
            # Use the most recent result for each agent
            latest = results_list[-1]
            lines.append(f"\n[{latest.display_name}]:")
            lines.append(latest.result_text)

        lines.extend([
            "",
            "Provide a comprehensive synthesis of these findings, highlighting"
            " agreements, discrepancies, and actionable conclusions.",
        ])

        return "\n".join(lines)

    async def _post_raw_results(self) -> None:
        """Post raw agent results as a fallback when synthesis is unavailable."""
        if not self._state.agent_results:
            await self._announce("No agent results to synthesize.")
            return

        lines = [f"Investigation complete for: {self._question}", ""]
        for agent_name, results_list in self._state.agent_results.items():
            if not results_list:
                continue
            latest = results_list[-1]
            lines.append(f"**{latest.display_name}**: {latest.result_text}")
            lines.append("")

        summary = "\n".join(lines)
        await self._appservice.send_as_bot(self._room_id, summary)
        self._state.final_synthesis = summary

    def _has_any_results(self) -> bool:
        """Return True if at least one agent produced a result."""
        return any(
            bool(results) for results in self._state.agent_results.values()
        )

    async def _announce(self, message: str) -> None:
        """Post a phase announcement via the coordinator bot.

        Respects ``session_verbosity`` — 'minimal' suppresses status messages
        other than errors; 'full' (default) posts all announcements.

        Args:
            message: Announcement text.
        """
        verbosity = self._config.session_verbosity
        if verbosity == "silent":
            return

        # In minimal mode, only post errors/important messages (simplified heuristic)
        if verbosity == "minimal":
            lower = message.lower()
            if not any(
                kw in lower
                for kw in ("fail", "error", "cancel", "timeout", "complete")
            ):
                return

        try:
            await self._appservice.send_as_bot(self._room_id, message)
        except Exception as exc:
            self.logger.warning(
                "Session %s: failed to post announcement: %s",
                self._session_id,
                exc,
            )
