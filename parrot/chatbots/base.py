from abc import ABC
# Langchain:
from langchain_core.prompts import (
    PromptTemplate,
    ChatPromptTemplate
)
from langchain.agents.agent import (
    AgentExecutor,
    RunnableAgent,
    RunnableMultiActionAgent,
)
from langchain.agents import create_react_agent
from navconfig.logging import logging
## LLM configuration
# Vertex
try:
    from ..llms.vertex import VertexLLM
    VERTEX_ENABLED = True
except (ModuleNotFoundError, ImportError):
    VERTEX_ENABLED = False

# Google
try:
    from ..llms.google import GoogleGenAI
    GOOGLE_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GOOGLE_ENABLED = False

# Anthropic:
try:
    from ..llms.anthropic import Anthropic
    ANTHROPIC_ENABLED = True
except (ModuleNotFoundError, ImportError):
    ANTHROPIC_ENABLED = False

# OpenAI
try:
    from ..llms.openai import OpenAILLM
    OPENAI_ENABLED = True
except (ModuleNotFoundError, ImportError):
    OPENAI_ENABLED = False

# Groq
try:
    from ..llms.groq import GroqLLM
    GROQ_ENABLED = True
except (ModuleNotFoundError, ImportError):
    GROQ_ENABLED = False

from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
)  # for exponential backoff
from ..interfaces import DBInterface
from ..models import AgentResponse


BASEPROMPT = """
Your name is {name}, You are a helpful assistant built to provide comprehensive guidance and support on data calculations and various aspects of payroll, such as earnings, deductions, salary information, and payroll tax. The goal is to ensure accurate, timely, and compliant payroll processing.

**Your Capabilities:**

1. **Earnings Calculation:**
   - Calculate regular earnings based on hourly rates or salaries.
   - Handle overtime calculations, including differentials and double-time as needed.
   - Include bonuses, commissions, and other incentive earnings.

2. **Deductions:**
   - Calculate mandatory deductions including federal, state, and local taxes.
   - Handle other withholdings such as Social Security, Medicare, disability insurance, and unemployment insurance.
   - Process voluntary deductions (e.g., health insurance premiums, retirement plan contributions, charitable donations).

3. **Salary Information:**
   - Provide gross and net salary breakdowns.
   - Assist in setting up and adjusting salary structures.
   - Manage payroll for part-time, full-time, and contract employees.

These keywords must never be translated and transformed:
- Action:
- Thought:
- Action Input:
because they are part of the thinking process instead of the output.

You are working with {num_dfs} pandas dataframes in Python named df1, df2, etc. You should use the tools below to answer the question posed to you:

- python_repl_ast: A Python shell. Use this to execute python commands. Input should be a valid python command. When using this tool, sometimes output is abbreviated - make sure it does not look abbreviated before using it in your answer.
- {tools}

To use a tool, please use the following format:

```
Question: the input question you must answer.
Thought: You should always think about what to do, don't try to reason out the answer on your own.
Action: the action to take, should be one of [python_repl_ast,{tool_names}] if using a tool, otherwise answer on your own.
Action Input: the input to the action.
Observation: the result of the action.
... (this Thought/Action/Action Input/Observation can repeat N times)
Final Thought: I now know the final answer.
Final Answer: the final answer to the original input question.
```


```
This is the result of `print(df1.head())` for each dataframe:
{dfs_head}
```

Begin!

Question: {input}
{agent_scratchpad}
"""


class BaseAgent(ABC, DBInterface):
    """Base Agent Interface.

    This is the base class for all Agent Chatbots. It is an abstract class that
    must be implemented by all Agent Chatbots.

    """
    def __init__(
        self,
        name: str = 'Agent',
        llm: str = 'vertexai',
        tools: list = None,
        prompt_template: str = None,
        **kwargs
    ):
        self.name = name
        self.tools = tools
        self.prompt_template = prompt_template
        if not self.prompt_template:
            self.prompt_template = BASEPROMPT
        self.llm = self.llm_chain(llm, **kwargs)
        self.prompt = self.get_prompt(self.prompt_template)
        self.kwargs = kwargs
        # Bot:
        self._agent = None
        self.agent = None
        # Logger:
        self.logger = logging.getLogger('Parrot.Agent')

    def get_prompt(self, prompt, **kwargs):
        partial_prompt = ChatPromptTemplate.from_template(prompt)
        return partial_prompt.partial(tools=self.tools, name=self.name, **kwargs)

    def create_agent(self, **kwargs):
        # Create a ReAct Agent:
        self.agent = RunnableAgent(
            runnable=create_react_agent(
                self.llm,
                self.tools,
                prompt=self.prompt,
            ),  # type: ignore
            input_keys_arg=["input"],
            return_keys_arg=["output"],
        )
        return self.agent

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def llm_chain(
        self, llm: str = "vertexai", **kwargs
    ):
        """llm_chain.

        Args:
            llm (str): The language model to use.

        Returns:
            str: The language model to use.

        """
        if llm == 'openai':
            mdl = OpenAILLM(model="gpt-3.5-turbo", **kwargs)
        elif llm == 'vertexai':
            mdl = VertexLLM(model="gemini-1.5-pro", **kwargs)
        elif llm == 'anthropic':
            mdl = Anthropic(model="claude-3-opus-20240229", **kwargs)
        elif llm == 'groq':
            mdl = GroqLLM(model="llama3-70b-8192", **kwargs)
        elif llm == 'mixtral':
            mdl = GroqLLM(model="mixtral-8x7b-32768", **kwargs)
        elif llm == 'google':
            mdl = GoogleGenAI(model="models/gemini-1.5-pro-latest", **kwargs)
        else:
            raise ValueError(f"Invalid llm: {llm}")

        # get the LLM:
        return mdl.get_llm()

    def get_executor(self, agent: RunnableAgent, tools: list, verbose: bool = True):
        return AgentExecutor(
            agent=agent,
            tools=tools,
            # callback_manager=callback_manager,
            verbose=verbose,
            return_intermediate_steps=True,
            max_iterations=5,
            max_execution_time=360,
            handle_parsing_errors=True,
            # memory=self.memory,
            # early_stopping_method='generate',
            **(self.kwargs or {}),
        )

    def get_chatbot(self):
        return self.get_executor(self.agent, self.tools)


    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._agent = None

    def get_conversation(self):
        # Create the agent:
        self.create_agent()
        # define conversation:
        self._agent = self.get_chatbot()
        return self

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

    def as_markdown(self, response: AgentResponse) -> str:
        markdown_output = f"**Question**: {response.question}  \n"
        markdown_output += f"**Answer**: {response.output}  \n"
        markdown_output += "```"
        return markdown_output
