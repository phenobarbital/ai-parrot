from typing import List
from langchain_core.prompts import (
    PromptTemplate,
    ChatPromptTemplate
)
from langchain.agents.agent import (
    AgentExecutor,
    RunnableAgent,
    RunnableMultiActionAgent,
)
from langchain.agents import (
    create_react_agent,
    initialize_agent,
    AgentType
)
from navconfig.logging import logging
from .abstract import AbstractBot
from .prompts import AGENT_PROMPT
from ..tools import AbstractTool


class BasicAgent(AbstractBot):
    """Represents an Agent in Navigator.

        Agents are chatbots that can access to Tools and execute commands.
        Each Agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).
    """
    def __init__(
        self,
        name: str = 'Agent',
        llm: str = 'vertexai',
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            **kwargs
        )
        self.prompt_template = prompt_template or AGENT_PROMPT
        self.tools = tools or []
        self.prompt = self.define_prompt(self.prompt_template)
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )

    def define_prompt(self, prompt, **kwargs):
        partial_prompt = ChatPromptTemplate.from_template(prompt)
        return partial_prompt.partial(
            tools=self.tools,
            name=self.name,
            **kwargs
        )
