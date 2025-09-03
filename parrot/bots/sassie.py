from __future__ import annotations
from typing import List
import textwrap
from datetime import datetime
from navconfig import BASE_DIR
from .agent import BasicAgent
from .prompts.nextstop import (
    AGENT_PROMPT,
    DEFAULT_BACKHISTORY,
    DEFAULT_CAPABILITIES
)
from ..tools import AbstractTool
from ..tools.sassie import VisitsToolkit
from ..tools.pythonpandas import PythonPandasTool
from ..models.responses import AgentResponse
from ..conf import STATIC_DIR

SASSIE_PROMPT = """
Your name is SassieSurvey, an IA Copilot specialized in providing detailed information Sassie Surveys.

$capabilities

**Mission:** Provide all the necessary information about surveys.
**Background:** Visits are mystery shopper evaluations conducted by employees to assess the performance of retail stores. The evaluations focus on various aspects such as customer service, product availability, store cleanliness, and overall shopping experience. The goal of these visits is to ensure that stores meet company standards and provide a positive experience for customers.

**Knowledge Base:**
$pre_context
$context

**Conversation History:**
$chat_history

**Instructions:**
Given the above context, available tools, and conversation history, please provide comprehensive and helpful responses. When appropriate, use the available tools to enhance your answers with accurate, up-to-date information or to perform specific tasks.

$rationale

"""


class SassieAgent(BasicAgent):
    """SassieAgent in Navigator.

        SassieAgent generates Visit Reports for Sassie Surveys on T-ROC.
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
    num_speakers: int = 2  # Default number of speakers for the podcast

    def __init__(
        self,
        name: str = 'SassieAgent',
        agent_id: str = 'sassie',
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
        self.system_prompt_template = prompt_template or SASSIE_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.tools = self.default_tools(tools)

    def default_tools(self, tools: List[AbstractTool]) -> List[AbstractTool]:
        """Return the default tools for the agent."""
        new_tools = []
        new_tools.append(
            PythonPandasTool(
                    report_dir=STATIC_DIR.joinpath(self.agent_id, 'documents')
            )
        )
        new_tools.extend(
            VisitsToolkit(
                agent_name='sassie',
                program='google'
            ).get_tools()
        )
        if tools is None:
            return new_tools
        if isinstance(tools, list):
            return new_tools + tools
        if isinstance(tools, AbstractTool):
            return new_tools + [tools]
        raise TypeError(
            f"Expected tools to be a list or an AbstractTool instance, got {type(tools)}"
        )
