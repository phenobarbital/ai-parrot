from __future__ import annotations
from typing import List
from .agent import BasicAgent
from .prompts.nextstop import (
    AGENT_PROMPT,
    DEFAULT_BACKHISTORY,
    DEFAULT_CAPABILITIES
)
from ..tools import AbstractTool
from ..tools.nextstop import StoreInfo, EmployeeToolkit
from ..models.responses import AgentResponse


class NextStop(BasicAgent):
    """NextStop in Navigator.

        Next Stop Agent generate Visit Reports for T-ROC employees.
        based on user preferences and location data.
    """
    _agent_response = AgentResponse
    speech_context: str = (
        "The report evaluates the performance of the employee's previous visits and defines strengths and weaknesses."
    )
    speech_system_prompt: str = (
        "You are an expert brand ambassador for T-ROC, a leading retail solutions provider."
        " Your task is to create a conversational script about the strengths and weaknesses of previous visits and what"
        " factors should be addressed to achieve a perfect visit."
    )
    speech_length: int = 20  # Default length for the speech report
    num_speakers: int = 1  # Default number of speakers for the podcast

    def __init__(
        self,
        name: str = 'NextStop',
        agent_id: str = 'nextstop',
        use_llm: str = 'openai',
        llm: str = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            agent_id=agent_id,
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

    def agent_tools(self) -> List[AbstractTool]:
        """Return the agent-specific tools."""
        return StoreInfo().get_tools() + EmployeeToolkit().get_tools()
