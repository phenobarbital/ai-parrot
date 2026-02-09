"""
Performance Tracker Agent
"""
from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    PERFORMANCE_TRACKER,
    MODEL_RECOMMENDATIONS,
)
from parrot.finance.schemas import (
    Capability,
    AgentCapabilityProfile,
)


def create_performance_tracker() -> Agent:
    """Performance tracker - evaluates trade outcomes."""
    capabilities = AgentCapabilityProfile(
        agent_id="performance_tracker",
        role="performance_tracker",
        capabilities={
            Capability.READ_PORTFOLIO,
            Capability.READ_MEMORY,
            Capability.WRITE_MEMORY,
            Capability.SEND_MESSAGE,
        },
        platforms=[],  # Read-only access
        asset_classes=[],
        constraints=None,
    )

    agent = Agent(
        name="Performance Tracker",
        agent_id="performance_tracker",
        llm=MODEL_RECOMMENDATIONS["performance_tracker"]["model"],
        system_prompt=PERFORMANCE_TRACKER,
        use_tools=True,
        instructions=(
            "Evaluate trade outcomes and maintain analyst track records. "
            "Create the feedback loop for system improvement."
        ),
    )
    agent.capabilities = capabilities
    return agent
