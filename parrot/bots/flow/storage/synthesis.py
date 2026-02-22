"""SynthesisMixin — LLM-based result synthesis for crew/flow orchestrators."""

import uuid
import logging
from typing import Any, Optional

from ....models.crew import CrewResult


SYNTHESIS_PROMPT = """Based on the research findings from our specialist agents above,
provide a comprehensive synthesis that:
1. Integrates all the key findings
2. Highlights the most important insights
3. Identifies any patterns or contradictions
4. Provides actionable conclusions
5. Generate useful widgets, cards, and charts (image or svg inline) to display the results and enrich the response.

Create a clear, well-structured response."""


class SynthesisMixin:
    """Mixin that adds LLM-based result synthesis to crew/flow orchestrators.

    Requires the host class to have a ``logger`` attribute.
    The ``llm`` client is passed explicitly to avoid hard-coupling to a
    specific ``self._llm`` attribute.
    """

    async def _synthesize_results(
        self,
        crew_result: CrewResult,
        synthesis_prompt: Optional[str] = None,
        *,
        llm: Any = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.1,
        **kwargs,
    ) -> Optional[str]:
        """Synthesize crew/flow results using an LLM.

        Args:
            crew_result: Result from any execution mode.
            synthesis_prompt: Prompt instructing the LLM how to synthesize.
                If ``None`` the method returns ``None`` immediately.
            llm: An ``AbstractClient`` instance. If ``None`` the method
                returns ``None`` immediately.
            user_id: User identifier.
            session_id: Session identifier.
            max_tokens: Max tokens for synthesis.
            temperature: LLM temperature.
            **kwargs: Extra arguments forwarded to the LLM.

        Returns:
            Synthesized summary string, or ``None`` if synthesis was skipped.
        """
        logger = getattr(self, "logger", logging.getLogger(__name__))

        if not synthesis_prompt or not llm:
            return None

        # Build context from agent results
        context_parts = ["# Agent Execution Results\n"]

        for i, agent_info in enumerate(crew_result.agents):
            agent_name = agent_info.agent_name
            agent_id = agent_info.agent_id
            response = crew_result.responses.get(agent_id)

            if hasattr(response, "content"):
                result = response.content
            elif hasattr(response, "output"):
                result = response.output
            else:
                result = str(response)

            context_parts.extend([
                f"\n## Agent {i + 1}: {agent_name}\n",
                str(result),
                "\n---\n",
            ])

        research_context = "\n".join(context_parts)
        final_prompt = f"{research_context}\n\n{synthesis_prompt}"

        logger.info("Synthesizing results with LLM")

        try:
            async with llm as client:
                synthesis_response = await client.ask(
                    prompt=final_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    user_id=user_id or "crew_user",
                    session_id=session_id or str(uuid.uuid4()),
                    use_conversation_history=False,
                    **kwargs,
                )

            return (
                synthesis_response.content
                if hasattr(synthesis_response, "content")
                else str(synthesis_response)
            )
        except Exception as e:
            logger.error("Error during synthesis: %s", e, exc_info=True)
            return None
