
from typing import List, Optional
from pathlib import Path
from .agent import BasicAgent
from ..tools.webapp_tool import WebAppGeneratorTool
from ..tools.abstract import AbstractTool


class WebDeveloperAgent(BasicAgent):
    """
    Specialized agent for web application development.

    This agent has deep expertise in creating web applications using Streamlit,
    React, and HTML/JavaScript. It can generate complete, production-ready apps
    based on natural language descriptions.
    """

    def __init__(
        self,
        name: str = 'WebDeveloper',
        agent_id: str = 'webdev',
        use_llm: str = 'google',
        output_dir: Optional[Path] = None,
        **kwargs
    ):
        """
        Initialize the WebDeveloper Agent.

        Args:
            name: Agent name
            agent_id: Unique agent identifier
            use_llm: LLM provider to use
            output_dir: Directory for saving generated apps
            **kwargs: Additional arguments
        """
        self.output_dir = output_dir or Path('./generated_apps')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            name=name,
            agent_id=agent_id,
            use_llm=use_llm,
            system_prompt=self._get_system_prompt(),
            **kwargs
        )

    def agent_tools(self) -> List[AbstractTool]:
        """Return web development specific tools."""
        return [
            WebAppGeneratorTool(
                llm_client=self.llm,
                output_dir=self.output_dir,
                default_type='streamlit'
            )
        ]

    def _get_system_prompt(self) -> str:
        """Return the specialized system prompt for web development."""
        return """You are an expert full-stack web developer specializing in rapid application development.

Your expertise includes:
- Building data-driven applications with Streamlit
- Creating modern single-page applications with React
- Developing standalone web pages with HTML/CSS/JavaScript
- UI/UX design and responsive layouts
- Data visualization and interactive dashboards

When users ask you to create applications:
1. Ask clarifying questions about requirements if needed
2. Choose the most appropriate technology (Streamlit for data apps, React for complex UIs, HTML for simple pages)
3. Use the web_app_generator tool to create the application
4. Explain the generated code and how to run/deploy it
5. Offer to make modifications or improvements

Always generate production-ready, well-structured code with:
- Clear documentation and comments
- Proper error handling
- Responsive design
- Accessibility considerations
- Modern best practices

Be conversational and helpful. Guide users through the development process."""
