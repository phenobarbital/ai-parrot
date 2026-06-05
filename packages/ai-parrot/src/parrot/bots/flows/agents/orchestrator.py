"""Orchestrator agent for coordinating multiple specialized agents.

Moved from ``parrot.bots.orchestration.agent`` to
``parrot.bots.flows.agents.orchestrator`` (FEAT-143).

Import paths are recalculated for the new package depth
(``flows/agents/`` is two levels deep under ``bots/``).
All class signatures are preserved; no API changes.
"""
import asyncio
from typing import Dict, List, Any, Optional, Tuple, Union, Callable

from ...agent import BasicAgent
from ...abstract import AbstractBot
from ....tools.agent import AgentContext, AgentTool
from ....registry import agent_registry
from ....models.responses import AIMessage
from ....models.basic import CompletionUsage
from ....models.conference import PeerVote, ConferenceRound, ConferenceResult
from ..core.result import NodeResult


class OrchestratorAgent(BasicAgent):
    """An orchestrator agent that can coordinate multiple specialized agents.

    This agent decides which specialists to consult and synthesizes their
    responses.
    """

    def __init__(
        self,
        name: str = "OrchestratorAgent",
        orchestration_prompt: str = None,
        agent_names: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)

        # Store wrapped agents and their tools
        self.agent_tools: Dict[str, AgentTool] = {}
        self.specialist_agents: Dict[str, Union[BasicAgent, AbstractBot]] = {}
        # Store pending agent names for deferred registry resolution
        self._pending_agent_names: List[str] = agent_names or []
        # Set orchestration-specific system prompt
        if orchestration_prompt:
            self.system_prompt_template = orchestration_prompt
        else:
            self._set_default_orchestration_prompt()

    def _set_default_orchestration_prompt(self):
        """Set default system prompt for orchestration behavior."""
        self.system_prompt_template = """
You are an orchestrator agent that coordinates multiple specialized agents to provide comprehensive answers.

Your responsibilities:
1. Analyze user queries to understand what type of information is needed
2. Decide which specialized agents to consult based on their capabilities
3. Call the appropriate agent tools with well-formed queries
4. Coordinate between multiple agents when different perspectives are needed
5. Synthesize responses from multiple agents into a coherent, comprehensive answer

Available specialized agents will be provided as tools you can call.

## Core Rules
- YOU MUST USE AT LEAST ONE SPECIALIZED AGENT FOR EVERY REQUEST.
- DO NOT ANSWER DIRECTLY USING YOUR OWN KNOWLEDGE.
- Always explain which agents you're consulting and why.
- Provide a unified answer that addresses all aspects of the user's question.
- Always maintain context and avoid redundant information.

## Agent Coordination Strategies

Choose the appropriate strategy based on the nature of the user's request:

### 1. Parallel Query
When you need independent information from different agents, call them in the same turn.
Use this when each agent brings a distinct piece of information that does not depend
on the others.
Example: asking an HR agent about policies AND an employee data agent about a profile.

### 2. Sequential Chain (Cross-Pollination)
When the answer from Agent A is needed to formulate a better question for Agent B:
- First, call Agent A with the user's question.
- Read Agent A's response carefully.
- Then, call Agent B with a NEW question that INCLUDES relevant context from Agent A's response.
- Use `include_previous_results: true` when you want the system to automatically
  inject all previous agent results as context into the next agent call.
- You can also manually embed specific excerpts in your question for targeted context.

Example flow:
  1. Call `data_agent(question: "Get employee John's current salary and tenure")`
  2. Call `policy_agent(question: "Based on the following employee data: [salary: $85K, tenure: 5 years], what bonus tier does this employee qualify for?", include_previous_results: true)`

### 3. Iterative Refinement
When one agent's response needs validation or enrichment from another:
- Call Agent A for an initial answer.
- Call Agent B to validate, critique, or enrich Agent A's response.
- Optionally call Agent A again with Agent B's feedback for a refined answer.

### 4. Synthesis
After gathering responses from one or more agents:
- Integrate key findings from all agents into a coherent narrative.
- Highlight the most important insights.
- Resolve any contradictions between agent responses.
- Provide actionable conclusions.
- Do NOT simply concatenate agent responses — synthesize them.

"""

    async def configure(self, app=None) -> None:
        """Configure the OrchestratorAgent and register specialist agents."""
        await super().configure(app)
        for name in self._pending_agent_names:
            await self.add_agent_by_name(name)
        # Hook for child classes to register their agents
        await self.register_specialist_agents()

    async def register_specialist_agents(self):
        """Hook method for registering specialist agents.

        This method should be overridden by subclasses to create and add
        specialist agents to the orchestrator.
        """
        pass

    def add_agent(
        self,
        agent: Union[BasicAgent, AbstractBot],
        tool_name: str = None,
        description: str = None,
        use_conversation_method: bool = True,
        context_filter: Optional[Callable[[AgentContext], AgentContext]] = None
    ) -> None:
        """Add a specialized agent to this orchestrator.

        Args:
            agent: The specialized agent to add.
            tool_name: Custom name for the tool (optional).
            description: Description of what this agent handles.
            use_conversation_method: Whether to use conversation() or invoke().
            context_filter: Optional function to filter context before passing
                to the agent.
        """
        # Create agent tool wrapper
        agent_tool = AgentTool(
            agent=agent,
            tool_name=tool_name,
            tool_description=description,
            use_conversation_method=use_conversation_method,
            context_filter=context_filter
        )

        # Store references
        self.agent_tools[agent_tool.name] = agent_tool
        self.specialist_agents[agent.name] = agent

        # Add to the existing ToolManager
        self.tool_manager.add_tool(agent_tool)

        # Sync tools to LLM
        if self._llm:
            self.sync_tools()

        self.logger.info(
            "Added specialist agent '%s' as tool '%s'",
            agent.name,
            agent_tool.name,
        )

    async def add_agent_by_name(
        self,
        agent_name: str,
        tool_name: str = None,
        description: str = None,
        **kwargs
    ) -> None:
        """Resolve an agent by name from AgentRegistry and add it as a specialist.

        Args:
            agent_name: The registered name of the agent in the AgentRegistry.
            tool_name: Optional custom name for the tool exposed to the LLM.
            description: Optional description of what this agent handles.
            **kwargs: Additional arguments forwarded to add_agent().

        Raises:
            ValueError: If the agent is not found in the registry.
        """
        agent = await agent_registry.get_instance(agent_name)
        if agent is None:
            raise ValueError(
                f"Agent '{agent_name}' not found in registry"
            )
        if not getattr(agent, 'is_configured', False):
            await agent.configure(app=getattr(self, 'app', None))
        self.add_agent(
            agent=agent,
            tool_name=tool_name,
            description=description,
            **kwargs
        )

    def _init_execution_memory(self, question: str):
        """Create fresh execution memory and wire it to all AgentTools."""
        from ..core.storage.memory import ExecutionMemory
        self._execution_memory = ExecutionMemory(original_query=question)
        for agent_tool in self.agent_tools.values():
            agent_tool.execution_memory = self._execution_memory

    def _collect_agent_results(self) -> Dict[str, NodeResult]:
        """Get all agent results from the current execution."""
        memory = getattr(self, '_execution_memory', None)
        if memory is None:
            return {}
        return dict(memory.results)

    def _is_passthrough_eligible(self, agent_results: Dict[str, NodeResult]) -> bool:
        """Check if response should pass through the specialist's AIMessage directly."""
        if not agent_results:
            return False
        agent_result = next(iter(agent_results.values()))
        if agent_result.ai_message is None:
            return False
        specialist = agent_result.ai_message
        return bool(
            specialist.data is not None
            or specialist.artifacts
            or specialist.images
            or specialist.code
        )

    def _build_passthrough_response(
        self,
        orchestrator_response: AIMessage,
        agent_results: Dict[str, NodeResult]
    ) -> AIMessage:
        """Return the specialist's AIMessage with orchestrator session metadata."""
        agent_result = next(iter(agent_results.values()))
        specialist_msg = agent_result.ai_message.model_copy(deep=False)
        specialist_msg.session_id = orchestrator_response.session_id
        specialist_msg.turn_id = orchestrator_response.turn_id
        specialist_msg.input = orchestrator_response.input
        specialist_msg.metadata = {
            **specialist_msg.metadata,
            "orchestrated": True,
            "mode": "passthrough",
            "routed_to": agent_result.agent_name,
        }
        return specialist_msg

    def _build_synthesis_response(
        self,
        orchestrator_response: AIMessage,
        agent_results: Dict[str, NodeResult]
    ) -> AIMessage:
        """Merge data from multiple agents into the orchestrator's response."""
        merged_data = {}
        merged_artifacts = []
        merged_sources = []

        for agent_name, agent_result in agent_results.items():
            if agent_result.ai_message is None:
                continue
            msg = agent_result.ai_message
            if msg.data is not None:
                merged_data[agent_name] = msg.data
            for artifact in (msg.artifacts or []):
                merged_artifacts.append({
                    **artifact,
                    "source_agent": agent_name,
                })
            merged_sources.extend(msg.source_documents or [])

        if merged_data:
            orchestrator_response.data = merged_data
        if merged_artifacts:
            orchestrator_response.artifacts = merged_artifacts
        if merged_sources:
            orchestrator_response.source_documents = merged_sources

        orchestrator_response.metadata = {
            **orchestrator_response.metadata,
            "orchestrated": True,
            "mode": "synthesis",
            "agents_consulted": list(agent_results.keys()),
        }
        return orchestrator_response

    async def ask(self, question: str, **kwargs) -> AIMessage:
        """Ask with automatic pass-through or synthesis based on agent responses."""
        self._init_execution_memory(question)
        response = await super().ask(question, **kwargs)
        agent_results = self._collect_agent_results()

        if not agent_results:
            return response

        if len(agent_results) == 1 and self._is_passthrough_eligible(agent_results):
            return self._build_passthrough_response(response, agent_results)

        return self._build_synthesis_response(response, agent_results)

    def remove_agent(self, agent_name: str) -> None:
        """Remove a specialized agent from this orchestrator."""
        # Find and remove the agent tool
        if tool_to_remove := next(
            (
                tool_name
                for tool_name, agent_tool in self.agent_tools.items()
                if agent_tool.agent.name == agent_name
            ),
            None,
        ):
            del self.agent_tools[tool_to_remove]
            self.tool_manager.remove_tool(tool_to_remove)
            self.logger.info(
                f"Removed agent tool: {tool_to_remove}"
            )

        if agent_name in self.specialist_agents:
            del self.specialist_agents[agent_name]
            self.logger.info(
                f"Removed specialist agent: {agent_name}"
            )

        # Sync tools to LLM
        if self._llm:
            self.sync_tools()

    def list_agents(self) -> List[str]:
        """List all registered specialist agents."""
        return list(self.specialist_agents.keys())

    def get_orchestration_stats(self) -> Dict[str, Any]:
        """Get statistics about agent usage in orchestration."""
        stats = {
            'total_specialists': len(self.specialist_agents),
            'agent_tools': {}
        }

        for tool_name, agent_tool in self.agent_tools.items():
            stats['agent_tools'][tool_name] = agent_tool.get_usage_stats()

        return stats

    # ──────────────────────────────────────────────────────────────────────
    # Multi-Party Conferencing (FEAT-223)
    #
    # A deterministic, additive path that broadcasts one question to every
    # specialist, cross-pollinates their answers anonymously, and lets each
    # agent vote. It does NOT use the ReAct ``ask()`` loop above.
    # ──────────────────────────────────────────────────────────────────────

    def _resolve_agents(self, agents: Optional[List[str]] = None) -> List[str]:
        """Resolve the panel of specialist names for a conference.

        Args:
            agents: Explicit subset of specialist names, or ``None`` for all.

        Returns:
            The list of specialist names to consult.

        Raises:
            ValueError: If any requested name is not a registered specialist.
        """
        if agents is None:
            return list(self.specialist_agents.keys())
        unknown = [name for name in agents if name not in self.specialist_agents]
        if unknown:
            raise ValueError(
                f"Unknown specialist agent(s): {unknown}. "
                f"Available: {list(self.specialist_agents.keys())}"
            )
        return list(agents)

    @staticmethod
    def _extract_answer_text(response: Any) -> str:
        """Extract plain answer text from a specialist's response.

        Mirrors the precedent in ``AgentTool._execute`` (``parrot/tools/agent.py``):
        prefer ``content``, fall back to ``output``, then ``str(response)``.
        """
        text = getattr(response, "content", None)
        if text is None:
            text = getattr(response, "output", None)
        if text is None:
            text = str(response)
        return text

    async def _invoke_specialist(
        self,
        agent: Union[BasicAgent, AbstractBot],
        question: str,
        **kwargs,
    ) -> Any:
        """Call a specialist, preferring ``ask`` then ``conversation``/``invoke``.

        ``structured_output`` is only forwarded to ``ask`` (the only method that
        accepts it); for ``conversation``/``invoke`` it is dropped so a
        specialist that lacks ``ask`` still participates (degrades gracefully).
        """
        if hasattr(agent, "ask"):
            return await agent.ask(question=question, **kwargs)
        kwargs.pop("structured_output", None)
        if hasattr(agent, "conversation"):
            return await agent.conversation(
                question=question, use_conversation_history=False, **kwargs
            )
        if hasattr(agent, "invoke"):
            return await agent.invoke(
                question=question, use_conversation_history=False, **kwargs
            )
        raise AttributeError(
            f"Agent {getattr(agent, 'name', '?')} supports no "
            "ask/conversation/invoke method"
        )

    async def _broadcast_round(
        self,
        question: str,
        agents: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Broadcast one question to every selected specialist, in parallel.

        Uses ``asyncio.gather`` (same fan-out pattern as
        ``AgentCrew.run_parallel``) so all specialists answer concurrently.

        Args:
            question: The shared question for all specialists.
            agents: Optional subset of specialist names; ``None`` = all.

        Returns:
            ``{agent_name: answer_text}`` — one answer per specialist that
            responded successfully. A specialist that raises during the broadcast
            is logged and skipped (it does not abort the conference).
        """
        names = self._resolve_agents(agents)
        self.logger.info(
            "Conference broadcast (round-0) to %d specialist(s): %s",
            len(names), names,
        )

        async def _one(name: str) -> Optional[Tuple[str, str]]:
            agent = self.specialist_agents[name]
            try:
                response = await self._invoke_specialist(
                    agent, question, use_conversation_history=False
                )
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                self.logger.warning(
                    "Specialist %s failed during broadcast; skipping: %s",
                    name, exc,
                )
                return None
            return name, self._extract_answer_text(response)

        pairs = await asyncio.gather(*[_one(name) for name in names])
        return {pair[0]: pair[1] for pair in pairs if pair is not None}

    def _build_anonymous_peer_block(
        self,
        answers: Dict[str, str],
        max_result_length: int = 2000,
    ) -> Tuple[str, Dict[str, str]]:
        """Build an anonymized peer-answer block + internal label map.

        Each answer is labelled ``A``, ``B``, ``C``... and truncated to
        ``max_result_length`` chars. The returned text contains NO agent name,
        role, or goal — only anonymous labels — to avoid authority bias. The
        ``label_to_agent`` map correlates labels back to authors internally and
        MUST NOT be serialized into a prompt.

        Args:
            answers: ``{agent_name: answer_text}`` from a broadcast/vote round.
            max_result_length: Per-answer truncation length (default 2000).

        Returns:
            ``(peer_block_text, label_to_agent)``.
        """
        labels = [chr(ord("A") + i) for i in range(len(answers))]
        label_to_agent: Dict[str, str] = {}
        lines = ["## Peer answers (anonymous)\n"]
        for label, (agent_name, text) in zip(labels, answers.items()):
            label_to_agent[label] = agent_name
            if len(text) > max_result_length:
                text = text[:max_result_length] + "\n... [truncated]"
            lines.append(f"### Answer {label}\n{text}\n")
        return "\n".join(lines), label_to_agent

    def _fallback_vote(
        self,
        agent_name: str,
        content: str,
        agent_to_label: Dict[str, str],
        default_confidence: float = 50.0,
    ) -> PeerVote:
        """Build a normalized vote for a specialist that lacks structured output.

        The specialist keeps its own answer at a neutral confidence so the round
        never fails because one provider could not emit a structured payload.
        """
        own_label = agent_to_label.get(agent_name) or "A"
        return PeerVote(
            chosen_label=own_label,
            revised_answer=content or "",
            confidence=default_confidence,
            rationale="Fallback vote: specialist produced no structured output.",
        )

    async def _collect_votes(
        self,
        question: str,
        peer_block: str,
        label_to_agent: Dict[str, str],
        agents: Optional[List[str]] = None,
    ) -> Dict[str, PeerVote]:
        """Collect a structured ``PeerVote`` from every specialist, in parallel.

        Each specialist sees the question plus the anonymous peer block and votes
        via ``ask(structured_output=PeerVote)``. If a specialist returns no
        structured payload, its vote is normalized from text (see
        :meth:`_fallback_vote`) with a warning — the round must not fail.

        Args:
            question: The original conference question.
            peer_block: The anonymized peer-answer block.
            label_to_agent: Internal label -> agent map for this round.
            agents: Optional subset of specialist names; ``None`` = all. The
                voting panel is intersected with the agents that produced an
                answer this round, so a specialist skipped during the broadcast
                does not vote on an answer set it is not part of.

        Returns:
            ``{agent_name: PeerVote}``.
        """
        agent_to_label = {agent: label for label, agent in label_to_agent.items()}
        # Only agents that produced an answer this round may vote.
        names = [n for n in self._resolve_agents(agents) if n in agent_to_label]
        prompt = f"{question}\n\n{peer_block}"

        async def _one(name: str) -> Tuple[str, PeerVote]:
            agent = self.specialist_agents[name]
            try:
                response = await self._invoke_specialist(
                    agent, prompt,
                    structured_output=PeerVote,
                    use_conversation_history=False,
                )
            except Exception as exc:  # noqa: BLE001 - degrade gracefully
                self.logger.warning(
                    "Specialist %s failed to vote (%s); using fallback.",
                    name, exc,
                )
                return name, self._fallback_vote(name, "", agent_to_label)

            vote = getattr(response, "structured_output", None)
            if isinstance(vote, PeerVote):
                if vote.chosen_label in label_to_agent:
                    return name, vote
                # Structured, but voted for a label that does not exist this
                # round (LLM hallucination) -> normalize to its own answer.
                self.logger.warning(
                    "Specialist %s voted for unknown label '%s'; using fallback.",
                    name, vote.chosen_label,
                )
                return name, self._fallback_vote(
                    name, vote.revised_answer, agent_to_label
                )

            content = self._extract_answer_text(response)
            self.logger.warning(
                "Specialist %s returned no structured vote; "
                "normalizing from text.", name,
            )
            return name, self._fallback_vote(name, content, agent_to_label)

        pairs = await asyncio.gather(*[_one(name) for name in names])
        return dict(pairs)

    def _tally_weighted_votes(
        self,
        votes: Dict[str, PeerVote],
    ) -> Tuple[str, Dict[str, float]]:
        """Aggregate votes by confidence-weighting (deterministic).

        ``scores[chosen_label] += vote.confidence``; the winner is the label with
        the highest summed confidence. Ties are broken deterministically by the
        lowest (alphabetically first) label.

        Args:
            votes: ``{agent_name: PeerVote}``.

        Returns:
            ``(winner_label, breakdown)`` where ``breakdown`` is
            ``{label: accumulated_confidence}``.

        Raises:
            ValueError: If there are no votes to tally.
        """
        scores: Dict[str, float] = {}
        for vote in votes.values():
            scores[vote.chosen_label] = (
                scores.get(vote.chosen_label, 0.0) + vote.confidence
            )
        if not scores:
            raise ValueError(
                "No votes to tally: every specialist failed to produce a vote."
            )
        # Highest score wins; tie-break -> lowest label (ascending).
        winner_label = min(scores, key=lambda lbl: (-scores[lbl], lbl))
        return winner_label, scores

    def _build_conference_result(
        self,
        winner_agent: str,
        winner_label: str,
        final_answer: str,
        vote_breakdown: Dict[str, float],
        rounds: List[ConferenceRound],
        converged: bool,
    ) -> ConferenceResult:
        """Assemble the aggregated :class:`ConferenceResult`."""
        return ConferenceResult(
            winner_agent=winner_agent,
            final_answer=final_answer,
            confidence_score=vote_breakdown.get(winner_label, 0.0),
            rounds=rounds,
            vote_breakdown=vote_breakdown,
            converged=converged,
        )

    async def confer(
        self,
        question: str,
        agents: Optional[List[str]] = None,
        max_rounds: int = 3,
        until_convergence: bool = True,
        **kwargs,
    ) -> AIMessage:
        """Run a deterministic multi-party conference over the specialists.

        Unlike :meth:`ask` (the LLM-driven ReAct loop), ``confer`` broadcasts the
        same question to every selected specialist, cross-pollinates their
        answers anonymously, and lets each agent vote. The consensus is resolved
        by confidence-weighted tally (no extra LLM synthesis). The loop iterates
        until the winning agent stabilizes between consecutive rounds or
        ``max_rounds`` is reached.

        Args:
            question: The shared question for the panel.
            agents: Optional subset of specialist names; ``None`` = all.
            max_rounds: Hard cap on the number of vote rounds (default 3).
            until_convergence: Stop early when the winner repeats (default True).

        Returns:
            An :class:`AIMessage` whose ``content`` is the final answer and whose
            ``structured_output`` is a :class:`ConferenceResult`
            (``is_structured=True``). Each round is persisted to
            ``self._execution_memory``.

        Raises:
            ValueError: If ``max_rounds`` < 1, or no specialist is available
                to answer.
        """
        if max_rounds < 1:
            raise ValueError(f"max_rounds must be >= 1; got {max_rounds}")

        self._init_execution_memory(question)
        answers = await self._broadcast_round(question, agents)
        if not answers:
            raise ValueError("confer() requires at least one specialist agent.")

        rounds: List[ConferenceRound] = []
        prev_winner: Optional[str] = None
        winner_agent: Optional[str] = None
        winner_label: Optional[str] = None
        breakdown: Dict[str, float] = {}
        converged = False

        for k in range(1, max_rounds + 1):
            block, label_to_agent = self._build_anonymous_peer_block(answers)
            votes = await self._collect_votes(
                question, block, label_to_agent, agents
            )
            winner_label, breakdown = self._tally_weighted_votes(votes)
            winner_agent = label_to_agent[winner_label]

            rnd = ConferenceRound(
                round_index=k,
                answers={
                    lbl: answers[label_to_agent[lbl]] for lbl in label_to_agent
                },
                label_to_agent=label_to_agent,
                votes=votes,
            )
            rounds.append(rnd)
            self._execution_memory.add_result(
                NodeResult(
                    node_id=f"conference_round_{k}",
                    node_name="conference",
                    task=question,
                    result=rnd.model_dump(),
                    ai_message=None,
                ),
                vectorize=False,
            )
            self.logger.info(
                "Conference round %d: winner=%s (label=%s, score=%.1f)",
                k, winner_agent, winner_label, breakdown.get(winner_label, 0.0),
            )

            # Next candidates = each agent's revised answer.
            answers = {a: v.revised_answer for a, v in votes.items()}

            if until_convergence and winner_agent == prev_winner:
                converged = True
                break
            prev_winner = winner_agent

        final_answer = answers.get(winner_agent, "")
        result = self._build_conference_result(
            winner_agent, winner_label, final_answer, breakdown, rounds, converged
        )
        # ``content`` is a read-only alias of ``output`` on AIMessage, so the
        # final answer is placed in ``output``; the required provider/model/usage
        # fields are filled with orchestrator-level defaults.
        return AIMessage(
            input=question,
            output=result.final_answer,
            model=getattr(self, "model", None) or "orchestrator",
            provider=getattr(self, "provider", None) or "orchestrator",
            usage=CompletionUsage(),
            structured_output=result,
            is_structured=True,
        )
