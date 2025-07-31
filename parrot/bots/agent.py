import os
from typing import List
from navconfig.logging import logging
from .chatbot import Chatbot
from .prompts import AGENT_PROMPT
from ..tools.abstract import AbstractTool


class BasicAgent(Chatbot):
    """Represents an Agent in Navigator.

        Agents are chatbots that can access to Tools and execute commands.
        Each Agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).

        These agents are designed to interact with structured and unstructured data sources.
    """
    def __init__(
        self,
        name: str = 'Agent',
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
        self.system_prompt_template = prompt_template or AGENT_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.enable_tools = True  # Enable tools by default
        self.auto_tool_detection = True  # Enable auto tool detection by default
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )
