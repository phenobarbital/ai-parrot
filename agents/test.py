from parrot.registry import register_agent
from parrot.bots.agent import BasicAgent
from parrot.tools.excel import ExcelTool
from parrot.tools.google import GoogleSearchTool, GoogleLocationTool
from parrot.tools.zipcode import ZipcodeAPIToolkit


@register_agent(name="TestAgent", priority=10, singleton=True, tags=["reporting", "pdf", "speech"])
class TestAgent(BasicAgent):
    """A test agent for demonstration purposes."""
    llm_client: str = 'google'
    default_model: str = 'gemini-2.5-flash'
    temperature: float = 0.1
    max_tokens: int = 2048


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "Test Agent"
        self.description = "An agent designed for testing and demonstration purposes."
        self.version = "1.0.0"
        self.author = "Your Name"
        self.logger.debug(
            f"{self.name} initialized with model {self.default_model}"
        )

    def agent_tools(self):
        """Return the agent-specific tools."""
        tools = [
            ExcelTool(),
            GoogleSearchTool(),
            GoogleLocationTool()
        ] + ZipcodeAPIToolkit().get_tools()

        return tools
