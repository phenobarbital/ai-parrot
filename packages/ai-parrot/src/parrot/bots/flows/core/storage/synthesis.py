"""Flow Primitives — SynthesisMixin + synthesize_results util.

Copied from ``parrot.bots.flow.storage.synthesis`` into the shared core
storage location.  Relative imports updated for the new package depth.

Accepts both ``CrewResult`` and ``FlowResult`` via duck-typing: only the
``.agents`` (iterable of info objects) and ``.responses`` (dict) attributes
are used. Full migration to ``FlowResult`` will happen in Spec 2.

FEAT-163 additions:
    ``synthesize_results(ctx, result) -> str`` — top-level async util that
    replaces the ``SynthesisMixin._synthesize_results`` method for new-style
    ``AgentsFlow`` callers. Compatible with both ``on_complete`` hooks and
    in-graph ``SynthesisNode`` DAG nodes.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional, Union

from navconfig.logging import logging

from .....models.crew import CrewResult

if TYPE_CHECKING:
    from ..context import FlowContext
    from ..result import FlowResult


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
        crew_result: Union[CrewResult, "FlowResult"],
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
            crew_result: Result from any execution mode (``CrewResult`` or
                ``FlowResult`` — both expose ``.agents`` and ``.responses``).
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


# ---------------------------------------------------------------------------
# synthesize_results — top-level util (FEAT-163 TASK-1063)
# ---------------------------------------------------------------------------

_logger = logging.getLogger(__name__)


async def synthesize_results(
    ctx: "FlowContext",
    result: "FlowResult",
    *,
    max_tokens: int = 8192,
    temperature: float = 0.1,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """LLM-summarize all agent responses collected in a ``FlowResult``.

    This is the single source of truth for synthesis used by both:
    - ``AgentsFlow.run_flow(on_complete=[synthesize_results])`` hooks.
    - ``SynthesisNode.execute()`` for in-graph summarization (TASK-1066).

    The function mirrors ``SynthesisMixin._synthesize_results``'s prompt-
    building and LLM-call logic, adapted for the new-style context-based API.

    Args:
        ctx: The current flow execution context. Must have a
            ``synthesis_client`` attribute that is an ``AbstractClient``-
            compatible object (has ``ask(prompt=...) -> response``).
        result: The ``FlowResult`` (or duck-type) whose ``.responses``
            dict provides per-node results to synthesize.
        max_tokens: Maximum tokens for the LLM response.
        temperature: LLM sampling temperature.
        user_id: Optional user identifier forwarded to the LLM.
        session_id: Optional session identifier forwarded to the LLM.

    Returns:
        Synthesized summary string.

    Raises:
        RuntimeError: If ``ctx.synthesis_client`` is ``None`` or absent.
    """
    client = getattr(ctx, "synthesis_client", None)
    if client is None:
        raise RuntimeError(
            "No synthesis client bound on FlowContext. "
            "Set ctx.synthesis_client = <AbstractClient instance> before calling "
            "synthesize_results(), or pass synthesis_client= when constructing FlowContext."
        )

    # Build context from node responses (mirrors SynthesisMixin._synthesize_results)
    context_parts = ["# Agent Execution Results\n"]

    responses: dict = getattr(result, "responses", {}) or {}
    for i, (node_id, response) in enumerate(responses.items()):
        if hasattr(response, "content"):
            text = response.content
        elif hasattr(response, "output"):
            text = response.output
        else:
            text = str(response)

        context_parts.extend([
            f"\n## Agent {i + 1}: {node_id}\n",
            str(text),
            "\n---\n",
        ])

    research_context = "\n".join(context_parts)
    final_prompt = f"{research_context}\n\n{SYNTHESIS_PROMPT}"

    _logger.info("synthesize_results: calling LLM for flow result synthesis")

    synthesis_response = await client.ask(
        question=final_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        user_id=user_id or "flow_user",
        session_id=session_id or str(uuid.uuid4()),
        use_conversation_history=False,
    )

    summary = (
        synthesis_response.content
        if hasattr(synthesis_response, "content")
        else str(synthesis_response)
    )

    # Store on result if it supports the summary attribute
    if hasattr(result, "summary"):
        result.summary = summary  # type: ignore[assignment]

    return summary
