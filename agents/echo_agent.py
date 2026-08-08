"""EchoAgent — minimal agent for pipeline smoke-testing.

Uses ``gemini-3.1-flash-lite`` and a single ``get_current_datetime`` tool
so integration tests can verify the full ask() → guardrails → tool-calling
→ LLM round-trip without any heavyweight dependencies.
"""
from parrot.bots import Agent
from parrot.registry import register_agent
from parrot.tools.echo_tools import get_current_datetime


@register_agent(name='echo_agent', at_startup=True)
class EchoAgent(Agent):
    """Smoke-test agent: answers questions using a lightweight datetime tool."""

    agent_id: str = 'echo_agent'
    model = 'gemini-3.1-flash-lite'
    system_prompt = (
        "You are a concise test agent.  When the user asks about the "
        "current date or time, you MUST call the get_current_datetime tool "
        "and include the result in your answer.  Keep answers short — one "
        "sentence maximum."
    )

    def agent_tools(self):
        return [get_current_datetime]
