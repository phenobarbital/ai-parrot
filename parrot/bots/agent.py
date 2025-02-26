from typing import List, Any
import os
from datetime import datetime, timezone
from langchain_core.prompts import (
    PromptTemplate,
    ChatPromptTemplate
)
from langchain.agents.mrkl.base import ZeroShotAgent
from langchain.agents import create_react_agent
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
from langchain.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
# for exponential backoff
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)  # for exponential backoff
from datamodel.typedefs import SafeDict
from navconfig.logging import logging
from .abstract import AbstractBot
from .prompts import AGENT_PROMPT
from ..models import AgentResponse
from ..tools import AbstractTool, SearchTool, MathTool, DuckDuckGoSearchTool


os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # Hide TensorFlow logs if present
logging.getLogger("grpc").setLevel(logging.CRITICAL)

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
        self.agent = None
        self._agent = None # Agent Executor
        self.prompt_template = prompt_template or AGENT_PROMPT
        self.tools = tools or self.default_tools()
        self.prompt = self.define_prompt(self.prompt_template)
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )

    def default_tools(self) -> List[AbstractTool]:
        return [
            DuckDuckGoSearchTool(),
            SearchTool(),
            MathTool()
        ]

    def define_prompt(self, prompt, **kwargs):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        list_of_tools = ""
        for tool in self.tools:
            name = tool.name
            description = tool.description  # noqa  pylint: disable=E1101
            list_of_tools += f'- {name}: {description}\n'
        list_of_tools += "\n"
        final_prompt = prompt.format_map(
            SafeDict(
                today_date=now,
                list_of_tools=list_of_tools
            )
        )
        # Define a structured system message
        system_message = f"""
        Today is {now}. If an event is expected to have occurred before this date,
        assume that results exist and verify using a web search tool.

        If you call a tool and receive a valid answer, finalize your response immediately.
        Do NOT repeat the same tool call multiple times for the same question.
        """
        chat_prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_message),
            ChatPromptTemplate.from_template(final_prompt)
        ])
        return chat_prompt.partial(
            tools=self.tools,
            name=self.name,
            **kwargs
        )

    def zero_agent(self, **kwargs):
        agent_kwargs = {
            "extra_prompt_messages": [MessagesPlaceholder(variable_name="memory")],
        }
        return ZeroShotAgent.from_llm_and_tools(
            llm=self._llm,
            tools=self.tools,
            prompt=self.prompt,
            agent_kwargs=agent_kwargs,
            **kwargs
        )

    def runnable_agent(self, **kwargs):
        # Create a ReAct Agent:
        return RunnableAgent(
            runnable = create_react_agent(
                self.llm,
                self.tools,
                prompt=self.prompt,
            ),  # type: ignore
            input_keys_arg=["input"],
            return_keys_arg=["output"],
            **kwargs
        )

    def get_executor(
        self,
        agent: RunnableAgent,
        tools: list,
        verbose: bool = True,
        **kwargs
    ):
        """Create a new AgentExecutor.
        """
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=verbose,
            return_intermediate_steps=True,
            max_iterations=5,
            max_execution_time=360,
            handle_parsing_errors=True,
            # memory=self.memory,
            **kwargs,
        )

    def get_agent(self):
        return self.get_executor(self.agent, self.tools)

    async def configure(self, app=None) -> None:
        """Basic Configuration of Agent.
        """
        await super(BasicAgent, self).configure(app)
        # Configure LLM:
        self.configure_llm()
        # Conversation History:
        self.memory = self.get_memory()
        # 1. Initialize the Agent (as the base for RunnableMultiActionAgent)
        self.agent = self.runnable_agent()
        # 2. Create Agent Executor - This is where we typically run the agent.
        #  While RunnableMultiActionAgent itself might be "runnable",
        #  we often use AgentExecutor to manage the agent's execution loop.
        self._agent = self.get_executor(self.agent, self.tools)

    async def question(
            self,
            question: str = None,
            **kwargs
    ):
        """question.

        Args:
            question (str): The question to ask the chatbot.
            memory (Any): The memory to use.

        Returns:
            Any: The response from the Agent.

        """
        # TODO: adding the vector-search to the agent
        input_question = {
            "input": question
        }
        result = self._agent.invoke(input_question)
        try:
            response = AgentResponse(question=question, **result)
            # response.response = self.as_markdown(
            #     response
            # )
            return response
        except Exception as e:
            self.logger.exception(
                f"Error on response: {e}"
            )
            raise

    def invoke(self, query: str):
        """invoke.

        Args:
            query (str): The query to ask the chatbot.

        Returns:
            str: The response from the chatbot.

        """
        input_question = {
            "input": query
        }
        result = self._agent.invoke(input_question)
        try:
            response = AgentResponse(question=query, **result)
            try:
                return self.as_markdown(
                    response
                ), response
            except Exception as exc:
                self.logger.exception(
                    f"Error on response: {exc}"
                )
                return result.get('output', None), None
        except Exception as e:
            return result, e
