"""Build the helpdesk OrchestratorAgent with sub-agents and escalation tools."""
from __future__ import annotations

import logging

from parrot.bots.flows.agents import OrchestratorAgent

from examples.orchestrator.escalation import escalate_tier1, escalate_tier2
from examples.orchestrator.hitl import ask_user_question
from examples.orchestrator.rules import SYSTEM_PROMPT
from examples.orchestrator.subagents import (
    build_finance_specialist,
    build_hr_specialist,
    build_it_specialist,
)


_LOG = logging.getLogger("orchestrator")


async def build_helpdesk_orchestrator(
    use_llm: str = "google",
) -> OrchestratorAgent:
    """Assemble the orchestrator with three specialists and escalation tools.

    Args:
        use_llm: Which LLM to back the orchestrator. Defaults to Google,
            matching the convention in ``examples/crew/`` so the demo
            works with ``GOOGLE_API_KEY`` set.
    """
    orchestrator = OrchestratorAgent(
        name="HelpdeskOrchestrator",
        agent_id="helpdesk_orchestrator",
        orchestration_prompt=SYSTEM_PROMPT,
        use_llm=use_llm,
    )
    await orchestrator.configure()

    # Specialists as tools.
    hr = await build_hr_specialist()
    it = await build_it_specialist()
    finance = await build_finance_specialist()

    orchestrator.add_agent(
        hr,
        tool_name="hr_specialist",
        description=(
            "Handles HR questions: onboarding, time off, benefits, "
            "parental leave, learning budget, code of conduct."
        ),
    )
    orchestrator.add_agent(
        it,
        tool_name="it_specialist",
        description=(
            "Handles IT support: accounts, passwords, MFA, VPN, "
            "workstations, email, production incident classification."
        ),
    )
    orchestrator.add_agent(
        finance,
        tool_name="finance_specialist",
        description=(
            "Handles Finance: expenses, travel, corporate cards, "
            "procurement, fraud reporting."
        ),
    )

    # Operational + escalation tools.
    orchestrator.tool_manager.register_tool(ask_user_question)
    orchestrator.tool_manager.register_tool(escalate_tier1)
    orchestrator.tool_manager.register_tool(escalate_tier2)
    orchestrator.sync_tools()

    _LOG.info(
        "Orchestrator ready with %d specialists and %d local tools.",
        len(orchestrator.specialist_agents),
        len(orchestrator.tool_manager.list_tools()),
    )
    return orchestrator


__all__ = ["build_helpdesk_orchestrator"]
