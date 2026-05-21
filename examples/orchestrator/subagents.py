"""Three specialist sub-agents for the helpdesk orchestrator.

Each agent is a regular :class:`BasicAgent` wired with one retrieval tool
covering its domain. The orchestrator picks them up via
:func:`BasicAgent.as_tool` / :func:`register_as_tool`.
"""
from __future__ import annotations

from parrot.bots.agent import BasicAgent

from .knowledge import handbook_search, pageindex_lookup


HR_PROMPT = """\
You are the HR specialist for Acme. You only answer questions about
onboarding, time off, benefits, parental leave, learning budget, and
the code of conduct.

Always ground answers in the onboarding handbook by calling
`pageindex_lookup` with a focused query before composing your answer.
Quote the section title when relevant. If the answer is not in the
manual, say so explicitly — do not invent policy.
"""


IT_PROMPT = """\
You are the IT support specialist for Acme. You only answer questions
about accounts, passwords, MFA, VPN, workstations, email, and the
classification of production incidents.

Always ground answers in the troubleshooting manual by calling
`pageindex_lookup` first. When the user describes a production
incident, identify the severity level (Sev-1/2/3) using the manual's
guidance and return that classification clearly to the orchestrator.
"""


FINANCE_PROMPT = """\
You are the Finance specialist for Acme. You only answer questions
about expense reimbursement, travel policy, corporate cards,
procurement, and how to report fraud.

Always ground answers in the company handbook by calling
`handbook_search` first. Quote the relevant section. If the user is
missing a receipt or a required approval, say so explicitly.
"""


async def build_hr_specialist() -> BasicAgent:
    agent = BasicAgent(
        name="HRSpecialist",
        agent_id="hr_specialist",
        system_prompt=HR_PROMPT,
    )
    await agent.configure()
    agent.tool_manager.register_tool(pageindex_lookup)
    agent.sync_tools()
    return agent


async def build_it_specialist() -> BasicAgent:
    agent = BasicAgent(
        name="ITSpecialist",
        agent_id="it_specialist",
        system_prompt=IT_PROMPT,
    )
    await agent.configure()
    agent.tool_manager.register_tool(pageindex_lookup)
    agent.sync_tools()
    return agent


async def build_finance_specialist() -> BasicAgent:
    agent = BasicAgent(
        name="FinanceSpecialist",
        agent_id="finance_specialist",
        system_prompt=FINANCE_PROMPT,
    )
    await agent.configure()
    agent.tool_manager.register_tool(handbook_search)
    agent.sync_tools()
    return agent
