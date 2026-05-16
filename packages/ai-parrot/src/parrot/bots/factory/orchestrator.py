"""AgentFactoryOrchestrator — the user-facing entry point of the factory.

The orchestrator runs a small LLM router to pick a specialist, gates that
choice through a pre-delegation HITL checkpoint, delegates the actual
drafting to the specialist, gates the resulting ``AgentDefinition`` through a
pre-finalize HITL checkpoint, and finally writes + registers the YAML.

The two HITL checkpoints are the cost-protection mechanism: if the user
times out or cancels at either gate, the orchestrator returns immediately
without invoking the next LLM stage.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Mapping, Optional

import yaml

from parrot.bots.agent import BasicAgent
from parrot.bots.factory.builders import (
    BaseFactoryBuilder,
    CloneAgentBuilder,
    RAGBuilderAgent,
    ToolAgentBuilderAgent,
)
from parrot.bots.factory.contracts import (
    BuilderOutput,
    BuilderType,
    FactoryRequest,
    FactoryResult,
    FactoryStatus,
    HITLCheckpoint,
    RouterDecision,
)
from parrot.bots.factory.tools.finalize import finalize_agent_registration
from parrot.bots.factory.tools.introspection import _list_registered_agents_tool
from parrot.human.manager import HumanInteractionManager
from parrot.human.models import (
    ChoiceOption,
    HumanInteraction,
    InteractionStatus,
    InteractionType,
    TimeoutAction,
)


_ROUTER_PROMPT = """\
You are the AgentFactory router. The user wants to create a new agent.
Inspect the request and pick exactly one specialist builder.

BuilderType options:
- "rag": user wants a retrieval-augmented chatbot (mentions corpus,
  knowledge base, documents, embeddings, "ask questions about X").
- "tool_agent": user wants an agent that takes actions via APIs / toolkits
  (mentions integrations, "post to", "search the web", "create a ticket").
- "clone": user explicitly asks to clone, copy, or replicate an existing
  agent ("a partir de X crea otro Bot para Y"). Call list_registered_agents
  first to confirm the source exists; populate detected_integrations with
  the source agent name.

Always emit a RouterDecision via structured output. Keep reasoning under 4
sentences — it goes to the user verbatim at the pre-delegation gate."""


def _default_timeouts() -> Dict[HITLCheckpoint, float]:
    return {
        HITLCheckpoint.PRE_DELEGATION: float(
            os.getenv("FACTORY_HITL_DELEGATION_TIMEOUT", "120")
        ),
        HITLCheckpoint.PRE_FINALIZE: float(
            os.getenv("FACTORY_HITL_FINALIZE_TIMEOUT", "600")
        ),
    }


class AgentFactoryOrchestrator:
    """Orchestrate router → specialist → finalize with HITL gates."""

    def __init__(
        self,
        *,
        human_manager: HumanInteractionManager,
        human_channel: str = "cli",
        human_targets: Optional[list] = None,
        llm: Optional[str] = None,
        use_llm: str = "google",
        builders: Optional[Mapping[BuilderType, BaseFactoryBuilder]] = None,
        category: str = "general",
        timeouts: Optional[Mapping[HITLCheckpoint, float]] = None,
    ) -> None:
        self.logger = logging.getLogger("Parrot.Factory.Orchestrator")
        self.human_manager = human_manager
        self.human_channel = human_channel
        self.human_targets = human_targets or ["local"]
        self.category = category
        self.timeouts = {**_default_timeouts(), **(timeouts or {})}

        self.builders: Dict[BuilderType, BaseFactoryBuilder] = dict(
            builders
            or {
                BuilderType.RAG: RAGBuilderAgent(llm=llm, use_llm=use_llm),
                BuilderType.TOOL_AGENT: ToolAgentBuilderAgent(llm=llm, use_llm=use_llm),
                BuilderType.CLONE: CloneAgentBuilder(llm=llm, use_llm=use_llm),
            }
        )

        self._llm = llm
        self._use_llm = use_llm

    # ---- public entry point -------------------------------------------------

    async def run(self, request: FactoryRequest) -> FactoryResult:
        """Drive the full factory flow for a single user request."""
        # Phase 1: route
        decision = await self._route(request)
        self.logger.info("Router picked %s — %s", decision.builder.value,
                         decision.reasoning[:120])

        # Phase 2: HITL pre-delegation
        delegation_ok = await self._confirm_delegation(decision)
        if not delegation_ok.approved:
            return FactoryResult(
                status=delegation_ok.status,
                router_decision=decision,
                cancelled_at=HITLCheckpoint.PRE_DELEGATION,
            )

        # Phase 3: specialist build
        builder = self.builders[decision.builder]
        try:
            output = await builder.build(request, decision)
        except Exception as exc:  # noqa: BLE001 — surface as FAILED to caller
            self.logger.exception("Specialist %s failed", decision.builder.value)
            return FactoryResult(
                status=FactoryStatus.FAILED,
                router_decision=decision,
                error=str(exc),
            )

        # Phase 4: HITL pre-finalize
        finalize_ok = await self._confirm_finalize(output)
        if not finalize_ok.approved:
            return FactoryResult(
                status=finalize_ok.status,
                router_decision=decision,
                cancelled_at=HITLCheckpoint.PRE_FINALIZE,
                definition=output.definition,
                provisioning=output.provisioning,
            )

        # Phase 5: persist + reload
        try:
            registration = await finalize_agent_registration(
                output.definition, category=self.category
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Finalize failed for %s", output.definition.name)
            return FactoryResult(
                status=FactoryStatus.FAILED,
                router_decision=decision,
                definition=output.definition,
                provisioning=output.provisioning,
                error=str(exc),
            )

        return FactoryResult(
            status=FactoryStatus.SUCCESS,
            router_decision=decision,
            definition=output.definition,
            yaml_path=registration["yaml_path"],
            provisioning=output.provisioning,
        )

    # ---- phase 1: routing ---------------------------------------------------

    async def _route(self, request: FactoryRequest) -> RouterDecision:
        if request.clone_from:
            # User explicitly asked to clone — skip the LLM, the answer is
            # already known.
            return RouterDecision(
                builder=BuilderType.CLONE,
                reasoning=(
                    f"User asked to clone from '{request.clone_from}'. "
                    f"Delegating to CloneAgentBuilder."
                ),
                detected_integrations=[request.clone_from],
            )

        hinted = request.hints.get("builder")
        if hinted:
            try:
                builder_type = BuilderType(hinted)
            except ValueError:
                pass
            else:
                return RouterDecision(
                    builder=builder_type,
                    reasoning=f"Caller pinned builder={builder_type.value} via hints.",
                    detected_integrations=request.hints.get("integrations", []) or [],
                )

        router_agent = BasicAgent(
            name="factory_router",
            agent_id="factory_router",
            use_llm=self._use_llm,
            llm=self._llm,
            tools=[_list_registered_agents_tool],
            system_prompt=_ROUTER_PROMPT,
        )

        result = await router_agent.ask(
            request.description, response_model=RouterDecision
        )
        candidate = getattr(result, "output", result)
        if isinstance(candidate, RouterDecision):
            return candidate
        if isinstance(candidate, dict):
            return RouterDecision(**candidate)
        if isinstance(candidate, str):
            return RouterDecision(**json.loads(candidate))
        raise TypeError(
            f"Router returned unsupported type: {type(result).__name__}"
        )

    # ---- HITL helpers -------------------------------------------------------

    async def _confirm_delegation(self, decision: RouterDecision) -> "_GateResult":
        question = (
            f"I will use the **{decision.builder.value}** specialist to draft "
            f"this agent.\n\nReasoning: {decision.reasoning}"
        )
        if decision.detected_integrations:
            question += (
                f"\n\nDetected integrations: "
                f"{', '.join(decision.detected_integrations)}"
            )
        return await self._gate(
            checkpoint=HITLCheckpoint.PRE_DELEGATION,
            question=question,
        )

    async def _confirm_finalize(self, output: BuilderOutput) -> "_GateResult":
        yaml_preview = yaml.safe_dump(
            output.definition.model_dump(mode="json", exclude_none=True),
            sort_keys=False,
            allow_unicode=True,
        )
        provisioning_note = ""
        if output.provisioning:
            items = ", ".join(
                f"{p.kind}:{p.name}" for p in output.provisioning
            )
            provisioning_note = f"\nSide-effects already applied: {items}\n"
        question = (
            f"Review the generated agent definition.{provisioning_note}\n"
            f"```yaml\n{yaml_preview}```\n\n"
            f"Approve to write `agents/{self.category}/"
            f"{output.definition.name.lower()}.yaml` and reload the registry."
        )
        return await self._gate(
            checkpoint=HITLCheckpoint.PRE_FINALIZE,
            question=question,
            notes=output.notes,
        )

    async def _gate(
        self,
        *,
        checkpoint: HITLCheckpoint,
        question: str,
        notes: Optional[str] = None,
    ) -> "_GateResult":
        interaction = HumanInteraction(
            question=question,
            context=notes,
            interaction_type=InteractionType.APPROVAL,
            options=[
                ChoiceOption(key="confirm", label="Approve"),
                ChoiceOption(key="cancel", label="Cancel"),
            ],
            timeout=self.timeouts[checkpoint],
            timeout_action=TimeoutAction.CANCEL,
            target_humans=list(self.human_targets),
            source_agent="agent_factory",
            source_node=checkpoint.value,
        )

        result = await self.human_manager.request_human_input(
            interaction, channel=self.human_channel
        )
        return _GateResult.from_interaction_result(result)


class _GateResult:
    """Internal helper — normalises an InteractionResult to (approved, status)."""

    __slots__ = ("approved", "status")

    def __init__(self, approved: bool, status: FactoryStatus) -> None:
        self.approved = approved
        self.status = status

    @classmethod
    def from_interaction_result(cls, result: Any) -> "_GateResult":
        status = getattr(result, "status", None)
        value = getattr(result, "consolidated_value", None)

        if status == InteractionStatus.COMPLETED and _is_approval(value):
            return cls(True, FactoryStatus.SUCCESS)
        if status == InteractionStatus.TIMEOUT:
            return cls(False, FactoryStatus.TIMEOUT)
        return cls(False, FactoryStatus.CANCELLED_BY_USER)


def _is_approval(value: Any) -> bool:
    """Accept 'confirm', 'approve', True, or first-option behaviour."""
    if value is True:
        return True
    if isinstance(value, str):
        return value.lower() in {"confirm", "approve", "approved", "yes", "y"}
    if isinstance(value, dict):
        key = value.get("key") or value.get("value") or value.get("response")
        return _is_approval(key)
    return False
