import os
from typing import List
from navconfig.logging import logging
from .agent import BasicAgent
from .prompts.nextstop import AGENT_PROMPT, DEFAULT_BACKHISTORY, DEFAULT_CAPABILITIES
from ..tools import AbstractTool
from ..tools.pythonpandas import PythonPandasTool
from ..tools.google import GoogleLocationTool, GoogleRoutesTool
from ..tools.openweather import OpenWeatherTool


class NextStop(BasicAgent):
    """NextStop in Navigator.

        Next Stop Agent generate travel itineraries and recommendations
        based on user preferences and location data.
    """
    def __init__(
        self,
        name: str = 'NextStop',
        use_llm: str = 'google',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            llm=llm,
            use_llm=use_llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            **kwargs
        )
        self.backstory = kwargs.get('backstory', DEFAULT_BACKHISTORY)
        self.capabilities = kwargs.get('capabilities', DEFAULT_CAPABILITIES)
        self.system_prompt_template = prompt_template or AGENT_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.enable_tools = True  # Enable tools by default
        self.auto_tool_detection = True  # Enable auto tool detection by default
        # Register all the tools:
        tools = []
        tools.extend(
            [
                OpenWeatherTool(default_request='weather'),
                PythonPandasTool(),
                GoogleLocationTool(),
                GoogleRoutesTool()
            ]
        )
        self.tools = tools
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )
