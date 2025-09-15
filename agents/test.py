from parrot.registry import register_agent
from parrot.bots.agent import BasicAgent


@register_agent(name="TestAgent", priority=10, singleton=True, tags=["reporting", "pdf"])
class TestAgent(BasicAgent):
    """A test agent for demonstration purposes."""
    llm_client: str = 'google'
    default_model: str = 'gemini-2.5-flash'
    temperature: float = 0.1
    max_tokens: int = 1024


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "Test Agent"
        self.description = "An agent designed for testing and demonstration purposes."
        self.version = "1.0.0"
        self.author = "Your Name"
        self.logger.debug(f"{self.name} initialized with model {self.default_model}")
