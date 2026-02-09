"""
Deliberation Agents
"""
from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    CIO_ARBITER,
    SECRETARY_MEMO_WRITER,
    MODEL_RECOMMENDATIONS,
)


def create_cio() -> Agent:
    """Chief Investment Officer - orchestrates deliberation."""
    return Agent(
        name="Chief Investment Officer",
        agent_id="cio",
        llm=MODEL_RECOMMENDATIONS["cio"]["model"],
        system_prompt=CIO_ARBITER,
        use_tools=False,
        instructions=(
            "Challenge, probe, and refine the committee's analysis. "
            "Detect contradictions, identify gaps, and force resolution."
        ),
    )


def create_secretary() -> Agent:
    """Investment Committee Secretary - synthesizes the memo."""
    return Agent(
        name="Investment Committee Secretary",
        agent_id="secretary",
        llm=MODEL_RECOMMENDATIONS["secretary"]["model"],
        system_prompt=SECRETARY_MEMO_WRITER,
        use_tools=False,
        instructions=(
            "Synthesize the committee's deliberation into a clear, "
            "actionable Investment Memo with risk management applied."
        ),
    )


def create_all_deliberation_agents() -> dict[str, Agent]:
    """Create deliberation agents (CIO and Secretary)."""
    return {
        "cio": create_cio(),
        "secretary": create_secretary(),
    }
