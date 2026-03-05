"""
Deliberation Agents
"""
from __future__ import annotations

from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    CIO_ARBITER,
    SECRETARY_MEMO_WRITER,
    MODEL_RECOMMENDATIONS,
)
from parrot.finance.schemas import InvestmentPolicyStatement


def create_cio(ips: InvestmentPolicyStatement | None = None) -> Agent:
    """Chief Investment Officer - orchestrates deliberation.

    Args:
        ips: Optional investment policy statement injected as a guardrail
            into the system prompt. When None, the prompt is unchanged.
    """
    system_prompt = CIO_ARBITER
    if ips:
        block = ips.to_prompt_block()
        if block:
            system_prompt = system_prompt + "\n\n" + block
    return Agent(
        name="Chief Investment Officer",
        agent_id="cio",
        llm=MODEL_RECOMMENDATIONS["cio"]["model"],
        system_prompt=system_prompt,
        use_tools=False,
        instructions=(
            "Challenge, probe, and refine the committee's analysis. "
            "Detect contradictions, identify gaps, and force resolution."
        ),
    )


def create_secretary(ips: InvestmentPolicyStatement | None = None) -> Agent:
    """Investment Committee Secretary - synthesizes the memo.

    Args:
        ips: Optional investment policy statement injected as a guardrail
            into the system prompt. When None, the prompt is unchanged.
    """
    system_prompt = SECRETARY_MEMO_WRITER
    if ips:
        block = ips.to_prompt_block()
        if block:
            system_prompt = system_prompt + "\n\n" + block
    return Agent(
        name="Investment Committee Secretary",
        agent_id="secretary",
        llm=MODEL_RECOMMENDATIONS["secretary"]["model"],
        system_prompt=system_prompt,
        use_tools=False,
        instructions=(
            "Synthesize the committee's deliberation into a clear, "
            "actionable Investment Memo with risk management applied."
        ),
    )


def create_all_deliberation_agents(
    ips: InvestmentPolicyStatement | None = None,
) -> dict[str, Agent]:
    """Create deliberation agents (CIO and Secretary).

    Args:
        ips: Optional investment policy statement forwarded to both factories.
    """
    return {
        "cio": create_cio(ips=ips),
        "secretary": create_secretary(ips=ips),
    }
