import os
from typing import Dict, List, Mapping, Union, Any, Optional, AsyncGenerator, Type
import re
from string import Template
import json
import traceback
from pathlib import Path
from datetime import datetime, timezone
from typing_extensions import Annotated, TypedDict
from aiohttp import web
from pydantic import BaseModel
import pandas as pd
import langchain
from langchain_core.tools import BaseTool
from langchain_core.prompts import (
    ChatPromptTemplate
)
from langchain_core.tools import BaseTool, BaseToolkit, StructuredTool
from langchain_core.retrievers import BaseRetriever
from langchain import hub
from langchain.callbacks.base import BaseCallbackHandler, AsyncCallbackHandler
from langchain.agents import (
    create_react_agent,
    create_openai_functions_agent,
    create_openai_tools_agent,
    create_tool_calling_agent
)
from langchain.agents.agent import (
    AgentExecutor,
    RunnableAgent,
    RunnableMultiActionAgent,
)
from langchain.agents.agent_toolkits import create_retriever_tool
from langchain.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.agent_toolkits.json.base import create_json_agent
from langchain_community.tools.json.tool import JsonSpec
from langchain_community.agent_toolkits.json.toolkit import JsonToolkit
from langchain_community.utilities import TextRequestsWrapper
# for exponential backoff
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    RetryError
)  # for exponential backoff
from datamodel.typedefs import SafeDict
from datamodel.exceptions import ValidationError # noqa  pylint: disable=E0611
from datamodel.parsers.json import json_decoder  # noqa  pylint: disable=E0611
from navconfig import BASE_DIR
from navconfig.logging import logging
from .abstract import AbstractBot
from ..models import AgentResponse
from ..tools import AbstractTool, MathTool, DuckDuckGoSearchTool, PDFPrintTool
from ..tools.results import ResultStoreTool, GetResultTool, ListResultsTool
from ..tools.gvoice import GoogleVoiceTool
from .prompts import AGENT_PROMPT, AGENT_PROMPT_SUFFIX, FORMAT_INSTRUCTIONS


langchain.debug = True


# Disable gRPC fork support and TensorFlow logs
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # Hide TensorFlow logs if present


class StructuredDataTool(StructuredTool):
    """Tool that can return structured data types instead of strings."""

    def __init__(self, return_type: Type = str, **kwargs):
        super().__init__(**kwargs)
        self.return_type = return_type

    def _run(self, *args, **kwargs):
        """Override to handle structured returns."""
        result = super()._run(*args, **kwargs)

        # If the tool is designed to return non-string data, return it directly
        if self.return_type != str:
            return result

        # Otherwise, convert to string as usual
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2)
        elif isinstance(result, pd.DataFrame):
            return result.to_json(orient='records', indent=2)

        return str(result)


class ToolCapture(AsyncCallbackHandler):
    """Capture the output of tools called by the agent."""
    def __init__(self):
        self.tool_results = []             # filled with the raw tool dicts

    async def on_tool_end(self, output, **_):
        # output is the exact return value of your tool
        self.tool_results.append(output)


class BasicAgent(AbstractBot):
    """Represents an Agent in Navigator.

        Agents are chatbots that can access to Tools and execute commands.
        Each Agent has a name, a role, a goal, a backstory,
        and an optional language model (llm).

        These agents are designed to interact with structured and unstructured data sources.
    """
    def __init__(
        self,
        name: str = 'Agent',
        agent_type: str = None,
        use_llm: str = 'vertexai',
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
            **kwargs
        )
        self.agent = None
        self.agent_type = agent_type or 'tool-calling'
        self._use_chat: bool = True  # For Agents, we use chat models
        self._agent = None  # Agent Executor
        self.system_prompt_template = prompt_template or AGENT_PROMPT
        self._system_prompt_base = system_prompt or ''
        self.tools = self.default_tools(tools)
        self._structured_llm: Any = None
        ##  Logging:
        self.logger = logging.getLogger(
            f'{self.name}.Agent'
        )

    def default_tools(self, tools: list = None) -> List[AbstractTool]:
        ctools = [
            DuckDuckGoSearchTool(),
            MathTool(),
        ]
        # result_store_tool = ResultStoreTool()
        # get_result_tool = GetResultTool()
        # list_results_tool = ListResultsTool()
        # adding result management:
        # ctools.extend([result_store_tool, get_result_tool, list_results_tool])
        if tools:
            ctools.extend(tools)
        return ctools

    # Add helper methods to directly access the stored results
    def get_stored_result(self, key: str) -> Any:
        """Retrieve a stored result directly."""
        return ResultStoreTool.get_result(key)

    def list_stored_results(self) -> Dict[str, Dict[str, Any]]:
        """List all stored results directly."""
        return ResultStoreTool.list_results()

    def clear_stored_results(self) -> None:
        """Clear all stored results."""
        ResultStoreTool.clear_results()

    def _define_prompt(self, **kwargs):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        list_of_tools = ""
        for tool in self.tools:
            name = tool.name
            description = tool.description  # noqa  pylint: disable=E1101
            list_of_tools += f'- {name}: {description}\n'
        list_of_tools += "\n"
        tools_names = [tool.name for tool in self.tools]
        tmpl = Template(self.system_prompt_template)
        final_prompt = tmpl.safe_substitute(
            name=self.name,
            role=self.role,
            goal=self.goal,
            capabilities=self.capabilities,
            system_prompt_base=self._system_prompt_base,
            today_date=now,
            tools=tools_names,
            list_of_tools=list_of_tools,
            backstory=self.backstory,
            rationale=self.rationale,
            format_instructions=""
        )
        # Define a structured system message
        final_prompt += AGENT_PROMPT_SUFFIX
        chat_prompt = ChatPromptTemplate.from_messages([
            # SystemMessagePromptTemplate.from_template(system_message),
            ChatPromptTemplate.from_template(final_prompt)
        ])
        self.system_prompt_template = chat_prompt.partial(
            tools=self.tools,
            tool_names=", ".join([tool.name for tool in self.tools]),
            name=self.name,
            **kwargs
        )

    def get_retriever_tool(
        self,
        retriever: BaseRetriever,
        name: str = 'vector_retriever',
        description: str = 'Search for information about a topic in a Vector Retriever.',
    ):
        return create_retriever_tool(
            name=name,
            description=description,
            retriever=retriever,
        )

    def runnable_json_agent(self, json_file: Union[str, Path], **kwargs):
        """
        Creates a JSON Agent using `create_json_agent`.

        This agent is designed to work with structured JSON input and output.

        Returns:
            RunnableMultiActionAgent: A JSON-based agent.

        ✅ Use Case: Best when dealing with structured JSON data and needing a predictable schema.
        """
        data = None
        if isinstance(json_file, str):
            data = json_file
        elif isinstance(json_file, Path):
            data = json_file.read_text()
        data = json_decoder(data)
        json_spec = JsonSpec(dict_= data, max_value_length=4000)
        json_toolkit = JsonToolkit(spec=json_spec)
        agent = create_json_agent(
            llm=self._llm,
            toolkit=json_toolkit,
            verbose=True,
            prompt=self.system_prompt_template,
        )
        return self.system_prompt_template | self._llm | agent

    def runnable_agent(self, **kwargs):
        """
        Creates a ZeroShot ReAct Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A ReAct-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        return RunnableMultiActionAgent(
            runnable = create_react_agent(
                self._llm,
                self.tools,
                prompt=self.system_prompt_template,
            ),  # type: ignore
            input_keys_arg=["input"],
            return_keys_arg=["output"],
            **kwargs
        )

    def function_calling_agent(self, **kwargs):
        """
        Creates a Function Calling Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A ReAct-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        # capture = ToolCapture()
        return RunnableMultiActionAgent(
            runnable = create_tool_calling_agent(
                self._llm,
                self.tools,
                prompt=self.system_prompt_template,
            ),  # type: ignore
            input_keys_arg=["input"],
            return_keys_arg=["output"],
            memory=self.memory,
            **kwargs
        )

    def openai_agent(self, **kwargs):
        """
        Creates OpenAI-like task executor Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A ReAct-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        return RunnableMultiActionAgent(
            runnable = create_openai_functions_agent(
                self._llm,
                self.tools,
                prompt=self.system_prompt_template
            ),  # type: ignore
            input_keys_arg=["input"],
            return_keys_arg=["output"],
            **kwargs
        )

    def sql_agent(self, dsn: str, **kwargs):
        """
        Creates a SQL Agent.

        This agent is designed to work with SQL queries and databases.

        Returns:
            AgentExecutor: A SQL-based AgentExecutor.

        ✅ Use Case: Best for querying databases and working with SQL data.
        """
        db = SQLDatabase.from_uri(dsn)
        toolkit = SQLDatabaseToolkit(db=db, llm=self._llm)
        # prompt_template = hub.pull("langchain-ai/sql-agent-system-prompt")
        return create_sql_agent(
            llm=self._llm,
            toolkit=toolkit,
            db=db,
            agent_type= "openai-tools",
            extra_tools=self.tools,
            max_iterations=5,
            handle_parsing_errors=True,
            verbose=True,
            prompt=self.system_prompt_template,
            agent_executor_kwargs = {"return_intermediate_steps": False}
        )

    def get_executor(
        self,
        agent: RunnableAgent,
        tools: list,
        verbose: bool = True,
        max_iterations: int = 30,
        max_execution_time: int = 360,
        handle_parsing_errors: bool = True,
        **kwargs
    ):
        """Create a new AgentExecutor.
        """
        return AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=verbose,
            return_intermediate_steps=True,
            max_iterations=max_iterations,
            max_execution_time=max_execution_time,
            handle_parsing_errors=handle_parsing_errors,
            memory=self.memory,
            **kwargs,
        )

    def get_agent(self):
        return self.get_executor(self.agent, self.tools)

    async def configure(self, app=None) -> None:
        """Basic Configuration of Agent.
        """
        if app:
            if isinstance(app, web.Application):
                self.app = app  # register the app into the Extension
            else:
                self.app = app.get_app()  # Nav Application
        # adding this configured chatbot to app:
        if self.app:
            self.app[f"{self.name.lower()}_bot"] = self
        # Configure LLM:
        self.configure_llm(use_chat=True)
        # And define Prompt:
        self._define_prompt()
        # Configure VectorStore if enabled:
        if self._use_vector:
            self.configure_store()
        # Conversation History:
        self.memory = self.get_memory(input_key="input", output_key="output")
        # 1. Initialize the Agent (as the base for RunnableMultiActionAgent)
        if self.agent_type == 'zero_shot':
            self.agent = self.runnable_agent()
        elif self.agent_type in ('function_calling', 'tool-calling', ):
            self.agent = self.function_calling_agent()
        elif self.agent_type == 'openai-tools':
            self.agent = self.openai_agent()
        # elif self.agent_type == 'json':
        #     self.agent = self.runnable_json_agent()
        # elif self.agent_type == 'sql':
        #     self.agent = self.sql_agent()
        else:
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
            return response, result
        except Exception as e:
            self.logger.exception(
                f"Error on response: {e}"
            )
            raise

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
    async def invoke(self, query: str):
        """invoke.

        Args:
            query (str): The query to ask the chatbot.

        Returns:
            a tuple with:
                - str: The response from the Agent, formatted as Markdown.
                - AgentResponse: The structured response object.
                - dict: The raw result from the agent invocation, which may include additional metadata or output
                - Exception: Any exception that occurred during the invocation, if applicable.

        """
        input_question = {
            "input": query
        }
        result = None
        try:
            result = await self._agent.ainvoke(input_question)
        except RetryError as err:
            # 🔑 1.  Tenacity keeps the *last* attempt in .last_attempt
            last_exc = err.last_attempt.exception()          # this is your TypeError
            logging.error(
                "Tenacity retries exhausted:\n%s", "".join(traceback.format_exception(last_exc))
            )
            raise
        except Exception as e:
            return 'Empty Answer', result, e
        try:
            output = result.get('output', None)
            if isinstance(output, pd.DataFrame):
                result['output'] = output.to_json(orient='records', indent=2)
            response = AgentResponse(question=query, **result)
        except ValueError as ve:
            self.logger.exception(
                f"Error creating AgentResponse: {ve}"
            )
            return result.get('output', None), ve, result
        except ValidationError as e:
            self.logger.exception(
                "Validation error in AgentResponse creation"
            )
            return result.get('output', None), e, result
        try:
            return self.as_markdown(
                response
            ), response, result
        except Exception as exc:
            self.logger.exception(
                f"Error on response: {exc}"
            )
            return result.get('output', None), exc, result
        except Exception as e:
            return 'Empty Answer', result, e

    async def __aenter__(self):
        if not self._agent:
            await self.configure()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._agent = None

    def sanitize_prompt_text(self, text: str) -> str:
        """
        Sanitize text for use in prompts to avoid parsing issues.

        This function:
        1. Escapes any triple backticks that might interfere with code blocks
        2. Normalizes newlines
        3. Removes any potentially problematic characters
        4. Ensures proper escaping of markdown formatting

        Args:
            text (str): The text to sanitize

        Returns:
            str: The sanitized text
        """
        if not text:
            return ""

        # Convert None to empty string
        if text is None:
            return ""

        # Normalize newlines
        text = text.replace('\r\n', '\n').replace('\r', '\n')

        # Escape triple backticks - this is crucial as they can interfere with code blocks
        # Replace triple backticks with escaped version
        text = text.replace("```", "\\`\\`\\`")

        # Handle markdown code blocks more safely
        # If we detect a python code block, ensure it's properly formatted
        pattern = r'\\`\\`\\`python\n(.*?)\\`\\`\\`'
        text = re.sub(
            pattern,
            r'The following is Python code:\n\1\nEnd of Python code.',
            text,
            flags=re.DOTALL
        )

        # Remove any control characters that might cause issues
        text = ''.join(ch for ch in text if ord(ch) >= 32 or ch in '\n\t')

        return text

    def with_structured_output(
        self,
        schema: Union[Type[BaseModel], Mapping[str, Any],],
        include_raw: bool = False,
        few_shot_examples: Optional[List[Dict]] = None
    ):
        """
        Create a structured output version of the agent's LLM.

        Args:
            schema: The output schema (Pydantic model, TypedDict, or JSON schema dict)
            include_raw: Whether to include raw response alongside structured
            few_shot_examples: List of example inputs/outputs for few-shot prompting

        Returns:
            A structured LLM that enforces the given schema
        """
        # Build few-shot prompt if examples provided
        few_shot_prompt = ""
        if few_shot_examples:
            few_shot_prompt = "\n\nHere are some examples:\n"
            for i, example in enumerate(few_shot_examples, 1):
                few_shot_prompt += f"\nExample {i}:\n"
                few_shot_prompt += f"Input: {example.get('input', '')}\n"
                few_shot_prompt += f"Output: {json.dumps(example.get('output', {}), indent=2)}\n"

        # Create structured LLM with enhanced prompt
        if few_shot_examples:
            # Wrap the LLM with few-shot prompting
            enhanced_prompt = ChatPromptTemplate.from_messages([
                ("system", f"You are an expert assistant. Follow the examples below and provide responses in the exact same format.{few_shot_prompt}"),
                ("human", "{input}")
            ])

            structured_chain = enhanced_prompt | self._llm.with_structured_output(
                schema, include_raw=include_raw
            )
            self._structured_llm = structured_chain
        else:
            self._structured_llm = self._llm.with_structured_output(
                schema, include_raw=include_raw
            )

        return self._structured_llm

    def get_json_output(self, schema: str) -> JsonSpec:
        """
        Define a JSON output parser for the agent.
        This allows the agent to return structured JSON responses based on a schema.
        Args:
            schema (str): The JSON schema to use for output parsing.
        Returns:
            JsonSpec: A JSON output parser.

        Example:
        ```python
        my_json_schema = {
            "type": "object",
            "properties": {
                "zipcode": {"type": "string"},
                "population": {"type": "number"},
                "income_by_bracket": {
                    "type": "object",
                    "properties": {
                        "0-25k": {"type": "number"},
                        "25k-50k": {"type": "number"},
                        # …
                    },
                },
            },
            "required": ["zipcode", "population"],
        }
        ```
        tool = Tool(
            name="get_demographics_data",
            func=get_demographics_data,
            description="…",
            return_direct=True,
            args_schema=DemographicsInput,
            output_parser=agent.get_json_output(schema=my_json_schema),
        )
        """
        return JsonSpec(schema=schema)


    def create_structured_tool(
        self,
        name: str,
        func: callable,
        description: str,
        schema: Type[BaseModel],
        return_type: Type = dict,
        **kwargs
    ) -> StructuredDataTool:
        """
        Create a tool that returns structured data instead of string.

        Args:
            name: Tool name
            func: Tool function
            description: Tool description
            args_schema: Input schema
            return_type: Expected return type (dict, DataFrame, etc.)

        Returns:
            StructuredDataTool instance
        """
        return StructuredDataTool(
            name=name,
            func=func,
            description=description,
            args_schema=schema,
            return_type=return_type,
            **kwargs
        )
