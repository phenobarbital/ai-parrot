from pathlib import Path
from typing import Any, List, Dict, Union, Optional
import re
from datetime import datetime, timezone, timedelta
from string import Template
import redis.asyncio as aioredis
import pandas as pd
from aiohttp import web
from datamodel.typedefs import SafeDict
from datamodel.parsers.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from navconfig import BASE_DIR
from navconfig.logging import logging
from querysource.queries.qs import QS
from querysource.queries.multi import MultiQS
from ..tools import AbstractTool
from ..tools.docx import DocxGeneratorTool
from .agent import BasicAgent
from ..models import AgentResponse
from ..conf import BASE_STATIC_URL, REDIS_HISTORY_URL
from .prompts import AGENT_PROMPT_SUFFIX, FORMAT_INSTRUCTIONS
from .prompts.data import (
    TOOL_CALLING_PROMPT_PREFIX,
    TOOL_CALLING_PROMPT_SUFFIX,
    REACT_PROMPT_PREFIX
)

## Enable Debug:
from langchain.globals import set_debug, set_verbose

# Enable verbosity for debugging
# set_debug(True)
# set_verbose(True)


def brace_escape(text: str) -> str:
    return text.replace('{', '{{').replace('}', '}}')

class PandasAgent(BasicAgent):
    """
    A simple agent that uses the pandas library to perform data analysis tasks.
    TODO
    - add notify tool (email, telegram, teams)
    - specific teams tool to send private messages from agents
    """

    def __init__(
        self,
        name: str = 'Agent',
        agent_type: str = None,
        llm: Optional[str] = None,
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        df: Union[list[pd.DataFrame], Dict[str, pd.DataFrame]] = None,
        query: Union[List[str], dict] = None,
        **kwargs
    ):
        self.chatbot_id: str = None
        self._queries = query
        self.df = self._define_dataframe(df)
        self.df_locals: dict = {}
        # Agent ID:
        self._prompt_prefix = None
        # Must be one of 'tool-calling', 'openai-tools', 'openai-functions', or 'zero-shot-react-description'.
        self.agent_type = agent_type or "tool-calling"
        if self.agent_type == "tool-calling":
            self._prompt_template = prompt_template or TOOL_CALLING_PROMPT_PREFIX
            self._format_instructions = ''
        else:
            self._prompt_template = prompt_template or REACT_PROMPT_PREFIX
            self._format_instructions: str = kwargs.get('format_instructions', FORMAT_INSTRUCTIONS)
        self._capabilities: str = kwargs.get('capabilities', None)
        self.name = name or "Pandas Agent"
        self.description = "A simple agent that uses the pandas library to perform data analysis tasks."
        self._static_path = BASE_DIR.joinpath('static')
        self.agent_report_dir = self._static_path.joinpath('reports', 'agents')
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            agent_type=self.agent_type,
            **kwargs
        )

    def _define_dataframe(
        self,
        df: Union[list[pd.DataFrame], Dict[str, pd.DataFrame]]
    ) -> Dict[str, pd.DataFrame]:
        """Define the dataframe."""
        _df = {}
        if isinstance(df, pd.DataFrame):
            # if data is one single dataframe
            _df['df1'] = df
        elif isinstance(df, list):
            # if data is a list of dataframes
            for i, dataframe in enumerate(df):
                df_name = f"df{i + 1}"
                _df[df_name] = dataframe.copy()
        elif isinstance(df, pd.Series):
            # if data is a pandas series
            # convert it to a dataframe
            df = pd.DataFrame(df)
            _df['df1'] = df
        elif isinstance(df, dict):
            _df = df
        else:
            raise ValueError(
                f"Expected pandas DataFrame, got {type(df)}"
            )
        return _df

    def get_query(self) -> Union[List[str], dict]:
        """Get the query."""
        return self._queries

    def get_capabilities(self) -> str:
        """Get the capabilities of the agent."""
        return self._capabilities

    def pandas_agent(self, **kwargs):
        """
        Creates a Pandas Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A Pandas-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        # Create the pandas agent
        dfs = list(self.df.values()) if isinstance(self.df, dict) else self.df
        # bind the tools to the LLM:
        llm = self._llm.bind_tools(self.tools)
        return create_pandas_dataframe_agent(
            llm,
            dfs,
            verbose=True,
            agent_type=self.agent_type,
            allow_dangerous_code=True,
            # prefix=self._prompt_prefix,
            max_iterations=10,
            extra_tools=self.tools,
            agent_executor_kwargs={"memory": self.memory, "handle_parsing_errors": True},
            return_intermediate_steps=True,
            **kwargs
        )

    async def configure(self, df: pd.DataFrame = None, app=None) -> None:
        """Basic Configuration of Pandas Agent.
        """
        if app:
            if isinstance(app, web.Application):
                self.app = app  # register the app into the Extension
            else:
                self.app = app.get_app()  # Nav Application
        # adding this configured chatbot to app:
        if self.app:
            self.app[f"{self.name.lower()}_bot"] = self
        if df is not None:
            self.df = self._define_dataframe(df)
        # Configure LLM:
        self.configure_llm(use_chat=True)
        # Configure VectorStore if enabled:
        if self._use_vector:
            self.configure_store()
        # Conversation History:
        self.memory = self.get_memory(input_key="input", output_key="output")
        # 1. Initialize the Agent (as the base for RunnableMultiActionAgent)
        self.agent = self.pandas_agent()
        # 2. Create Agent Executor - This is where we typically run the agent.
        self._agent = self.agent
        # 3. When agent is correctly created, caching the data:
        await self._cache_data(
            self.chatbot_id,
            self.df,
            cache_expiration=24
        )

    def mimefromext(self, ext: str) -> str:
        """Get the mime type from the file extension."""
        mime_types = {
            '.csv': 'text/csv',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
            '.json': 'application/json',
            '.txt': 'text/plain',
            '.html': 'text/html',
            '.htm': 'text/html',
            '.pdf': 'application/pdf',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.svg': 'image/svg+xml',
            '.md': 'text/markdown',
            '.ogg': 'audio/ogg',
            '.wav': 'audio/wav',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
        }
        return mime_types.get(ext, None)

    def extract_filenames(self, response: AgentResponse) -> List[Path]:
        """Extract filenames from the content."""
        # Split the content by lines
        output_lines = response.output.splitlines()
        current_filename = ""
        filenames = {}
        for line in output_lines:
            if 'filename:' in line:
                current_filename = line.split('filename:')[1].strip()
                if current_filename:
                    try:
                        filename_path = Path(current_filename).resolve()
                        if filename_path.is_file():
                            content_type = self.mimefromext(filename_path.suffix)
                            url = str(filename_path).replace(str(self._static_path), BASE_STATIC_URL)
                            filenames[filename_path.name] = {
                                'content_type': content_type,
                                'file_path': filename_path,
                                'filename': filename_path.name,
                                'url': url
                            }
                        continue
                    except AttributeError:
                        pass
        if filenames:
            response.filename = filenames

    async def invoke(
        self,
        query: str, llm: Optional[Any] = None,
        llm_params: Optional[Dict[str, Any]] = None
    ):
        """Invoke the agent with optional LLM override.

        Args:
            query (str): The query to ask the chatbot.
            llm (Optional[Any]): Optional LLM to use for this specific invocation.
            llm_params (Optional[Dict[str, Any]]): Optional parameters to modify LLM behavior
                                                (temperature, max_tokens, etc.)

        Returns:
            str: The response from the chatbot.

        """
        original_agent = None
        original_llm = None
        try:
            # If a different LLM or parameters are provided, create a temporary agent
            if llm is not None:
                # Get the current LLM if we're just updating parameters
                current_llm = llm if llm is not None else self._llm
                # Store original LLM for reference
                original_llm = self._llm
                # Store original agent for reference
                original_agent = self._agent
                # Temporarily update the instance LLM
                self._llm = current_llm
                # Create a new agent with the updated LLM
                self._agent = self.pandas_agent()
            # Invoke the agent with the query
            result = await self._agent.ainvoke(
                {"input": query}
            )
        except Exception as e:
            return None, e
        try:
            # Parse tool outputs if present
            try:
                if isinstance(result, dict):
                    output = result.get('output', '')
                    if '```tool_outputs' in output:
                        tool_json_match = re.search(r'```tool_outputs\n(.*?)\n```', output, re.DOTALL)
                        if tool_json_match:
                            tool_json = tool_json_match.group(1)
                            # Parse the JSON
                            tool_data = json_decoder(tool_json)
                            # Get the actual content
                            if "python_repl_ast_response" in tool_data:
                                python_response = tool_data["python_repl_ast_response"]
                                if isinstance(python_response, dict) and "content" in python_response:
                                    # Replace the output with just the content
                                    result['output'] = python_response["content"].strip()
            except Exception as parse_error:
                self.logger.error(
                    f"Error parsing tool output: {parse_error}"
                )
            response = AgentResponse(question=query, **result)
            # check if return is a file:
            try:
                self.extract_filenames(response)
            except Exception as exc:
                self.logger.error(
                    f"Unable to extract filenames: {exc}"
                )
            # Restore the original agent if any:
            if original_llm is not None:
                self._llm = original_llm
                self._agent = original_agent
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

    def _configure_python_tool(self, df_locals: dict, **kwargs) -> PythonAstREPLTool:
        """Configure the Python tool."""
        # Create the Python tool with the given locals and globals
        df_locals['execution_results'] = {}
        # Create the Python REPL tool
        PythonAstREPLTool_init = PythonAstREPLTool.__init__

        def PythonAstREPLTool_init_wrapper(self, *args, **kwargs):
            PythonAstREPLTool_init(self, *args, **kwargs)
            self.globals = self.locals

        PythonAstREPLTool.__init__ = PythonAstREPLTool_init_wrapper
        python_tool = PythonAstREPLTool(
            locals=df_locals,
            globals=kwargs.get('globals', {}),
            verbose=True,
            **kwargs
        )

        # Add essential library imports and helper functions
        setup_code = """
# Ensure essential libraries are imported
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter, defaultdict
from parrot.bots.tools import quick_eda, generate_eda_report, list_available_dataframes, create_plot, generate_pdf_from_html

# Set plotting style
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette('Set2')

# Verify pandas is loaded correctly
print(f"Pandas version: {pd.__version__}")
"""
        try:
            python_tool.run(setup_code)
        except Exception as e:
            self.logger.error(
                f"Error setting up python tool: {e}"
            )
        print(':: PYTHON TOOL > ', python_tool)
        return python_tool

    def _metrics_guide(self, df_key: str, df_name: str, columns: list) -> str:
        """Generate a guide for the dataframe columns."""
        # Create a markdown table with column category, column name, type and with dataframe is present:
        table = "\n| Category | Column Name | Type | DataFrame | Dataframe Name |\n"
        table += "|------------------|-------------|------|-----------|\n"
        for column in columns:
            # Get the column name
            column_name = column
            # split by "_" and first element is the category (if any):
            # Get the column category
            try:
                column_category = column.split('_')[0]
            except IndexError:
                column_category = df_name
            # Get the type of the column
            column_type = str(self.df[df_name][column].dtype)
            # Add the row to the table
            table += f"| {column_category} | {column_name} | {column_type} | {df_key} | {df_name} |\n\n\n"
        # Add a note about the dataframe
        table += f"\nNote: {df_key} is also available as {df_name}\n"
        return table

    def define_prompt(self, prompt, **kwargs):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.agent_report_dir = self._static_path.joinpath(str(self.chatbot_id))
        if self.agent_report_dir.exists() is False:
            self.agent_report_dir.mkdir(parents=True, exist_ok=True)
        # Add dataframe information
        num_dfs = len(self.df)
        self.df_locals['agent_report_dir'] = self.agent_report_dir
        df_info = ''
        for i, (df_name, df) in enumerate(self.df.items()):
            df_key = f"df{i + 1}"
            self.df_locals[df_name] = df
            self.df_locals[df_key] = df
            row_count = len(df)
            self.df_locals[f"{df_key}_row_count"] = row_count
            # Get basic dataframe info
            df_shape = f"DataFrame Shape: {df.shape[0]} rows × {df.shape[1]} columns"
            df_columns = self._metrics_guide(df_key, df_name, df.columns.tolist())
            # Generate summary statistics
            summary_stats = brace_escape(df.describe(include='all').to_markdown())
            df_head = brace_escape(df.head(4).to_markdown())
            # Create df_info block
            if self.agent_type == "tool-calling":
                df_info += f"""
                ## Dataframe Name: {df_key}:
                ## DataFrame: {df_key} (also accessible as {df_name} in Python code)

                **Shape {df_key}**: {df_shape}

                **Column Details (Name, Type, Category)**:
                {df_columns}

                **First 4 Rows (`print({df_key}.head(4).to_markdown())`)**:
                {df_head}

                **Summary Statistics (`print({df_key}.describe(include='all').to_markdown())`)**:
                {summary_stats}
                """
            else:
                df_info += f"""
                ## DataFrame {df_key}:

                ### {df_key} Shape:
                {df_shape}

                ### {df_key} Info:
                {df_columns}

                ### {df_key} Summary Statistics:
                {summary_stats}
                """
        # Configure Python tool:
        python_tool = self._configure_python_tool(
            df_locals=self.df_locals,
            **kwargs
        )
        # Add the Python tool to the tools list
        self.tools.append(python_tool)
        # List of Tools:
        list_of_tools = ""
        for tool in self.tools:
            name = tool.name
            description = tool.description  # noqa  pylint: disable=E1101
            list_of_tools += f'- {name}: {description}\n'
        list_of_tools += "\n"
        tools_names = [tool.name for tool in self.tools]
        capabilities = ''
        if self._capabilities:
            capabilities = "**Your Capabilities:**\n"
            capabilities += self.sanitize_prompt_text(self._capabilities) + "\n"
        # Create the prompt
        sanitized_backstory = ''
        if self.backstory:
            sanitized_backstory = self.sanitize_prompt_text(self.backstory)
        tmpl = Template(self._prompt_template)
        self._prompt_prefix = tmpl.safe_substitute(
            name=self.name,
            description=self.description,
            list_of_tools=list_of_tools,
            backstory=sanitized_backstory,
            capabilities=capabilities,
            today_date=now,
            system_prompt_base=prompt,
            tools=", ".join(tools_names),
            format_instructions=self._format_instructions.format(
                tool_names=", ".join(tools_names)),
            df_info=df_info,
            num_dfs=num_dfs,
            rationale=self.rationale,
            agent_report_dir=self.agent_report_dir,
            **kwargs
        )
        if self.agent_type == "tool-calling":
            tmpl = Template(TOOL_CALLING_PROMPT_SUFFIX)
            self._prompt_suffix = tmpl.safe_substitute(
                df_info=df_info,
                num_dfs=num_dfs
            )
        else:
            self._prompt_suffix = AGENT_PROMPT_SUFFIX

    def default_backstory(self) -> str:
        return "You are a helpful assistant built to provide comprehensive guidance and support on data calculations and data analysis working with pandas dataframes."

    @staticmethod
    async def call_qs(queries: list) -> Dict[str, pd.DataFrame]:
        """
        call_qs.
        description: Call the QuerySource queries.

        This method is used to execute multiple queries and files on the QueryObject.
        It returns a dictionary with the results.
        """
        dfs = {}
        for query in queries:
            if not isinstance(query, str):
                raise ValueError(
                    f"Query {query} is not a string."
                )
            # now, the only query accepted is a slug:
            try:
                qy = QS(
                    slug=query
                )
                df, error = await qy.query(output_format='pandas')
                if error:
                    raise ValueError(
                        f"Query {query} fail with error {error}."
                    )
                if not isinstance(df, pd.DataFrame):
                    raise ValueError(
                        f"Query {query} is not returning a dataframe."
                    )
                dfs[query] = df
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(
                    f"Error executing Query {query}: {e}"
                )
        return dfs

    @staticmethod
    async def call_multiquery(query: dict) -> Dict[str, pd.DataFrame]:
        """
        call_multiquery.
        description: Call the MultiQuery queries.

        This method is used to execute multiple queries and files on the QueryObject.
        It returns a dictionary with the results.
        """
        data = {}
        _queries = query.pop('queries', {})
        _files = query.pop('files', {})
        if not _queries and not _files:
            raise ValueError(
                "Queries or files are required."
            )
        try:
            ## Step 1: Running all Queries and Files on QueryObject
            qs = MultiQS(
                slug=[],
                queries=_queries,
                files=_files,
                query=query,
                conditions=data,
                return_all=True
            )
            result, _ = await qs.execute()
        except Exception as e:
            raise ValueError(
                f"Error executing MultiQuery: {e}"
            )
        if not isinstance(result, dict):
            raise ValueError(
                "MultiQuery is not returning a dictionary."
            )
        # MultiQuery returns a dictionary with the results
        return result

    @classmethod
    async def gen_data(
        cls,
        query: Union[list, dict],
        agent_name: Optional[str] = None,
        refresh: bool = False,
        cache_expiration: int = 48,
        no_cache: bool = False
    ) -> Dict[str, pd.DataFrame]:
        """
        gen_data.

        Generate the dataframes required for the agent to work, with Redis caching support.

        Parameters:
        -----------
        query : Union[list, dict]
            The query or queries to execute to generate dataframes.
        refresh : bool
            If True, forces regeneration of dataframes even if cached versions exist.
        cache_expiration_hours : int
            Number of hours to keep the cached dataframes (default: 48).
        no_cache : bool
            If True, disables caching even if no agent_name is provided.

        Returns:
        --------
        Dict[str, pd.DataFrame]
            A Dictionary of named pandas DataFrames generated from the queries.
        """
        # If agent_name is provided, we'll use Redis caching
        if not agent_name:
            agent_name = cls.chatbot_id

        if not refresh:
            # Try to get cached dataframes
            cached_dfs = await cls._get_cached_data(agent_name)
            if cached_dfs:
                return cached_dfs

        # Generate dataframes from query if no cache exists or refresh is True
        dfs = await cls._execute_query(query)

        # If agent_name is provided, cache the generated dataframes
        if no_cache is False:
            await cls._cache_data(agent_name, dfs, cache_expiration)
        return dfs

    @classmethod
    async def _execute_query(cls, query: Union[list, dict]) -> Dict[str, pd.DataFrame]:
        """Execute the query and return the generated dataframes."""
        if isinstance(query, dict):
            # is a MultiQuery execution, use the MultiQS class engine to do it:
            try:
                return await cls.call_multiquery(query)
            except ValueError as e:
                raise ValueError(f"Error creating Query For Agent: {e}")
        elif isinstance(query, (str, list)):
            if isinstance(query, str):
                query = [query]
            try:
                return await cls.call_qs(query)
            except ValueError as e:
                raise ValueError(f"Error creating Query For Agent: {e}")
        else:
            raise ValueError(
                f"Expected a list of queries or a dictionary, got {type(query)}"
            )

    @classmethod
    async def _get_redis_connection(cls):
        """Get a connection to Redis."""
        # You should adjust these parameters according to your Redis configuration
        # Consider using environment variables for these settings
        return await aioredis.Redis.from_url(
            REDIS_HISTORY_URL,
            decode_responses=True
        )

    @classmethod
    async def _get_cached_data(cls, agent_name: str) -> Optional[Dict[str, pd.DataFrame]]:
        """
        Retrieve cached data from Redis if they exist.

        Returns None if no cache exists or on error.
        """
        try:
            redis_conn = await cls._get_redis_connection()
            # Check if the agent key exists
            key = f"agent_{agent_name}"
            if not await redis_conn.exists(key):
                await redis_conn.close()
                return None

            # Get all dataframe keys stored for this agent
            df_keys = await redis_conn.hkeys(key)
            if not df_keys:
                await redis_conn.close()
                return None

            # Retrieve and convert each dataframe
            dataframes = {}
            for df_key in df_keys:
                df_json = await redis_conn.hget(key, df_key)
                if df_json:
                    # Convert from JSON to dataframe
                    df_data = json_decoder(df_json)
                    df = pd.DataFrame.from_records(df_data)
                    dataframes[df_key] = df

            await redis_conn.close()
            return dataframes if dataframes else None

        except Exception as e:
            # Log the error but continue execution without cache
            print(f"Error retrieving cache: {e}")
            return None

    @classmethod
    async def _cache_data(
        cls,
        agent_name: str,
        dataframes: Dict[str, pd.DataFrame],
        cache_expiration: int
    ) -> None:
        """
        Cache the given dataframes in Redis.

        The dataframes are stored as JSON records under a hash key named after the agent.
        """
        try:
            if not dataframes:
                return

            redis_conn = await cls._get_redis_connection()
            key = f"agent_{agent_name}"

            # Delete any existing cache for this agent
            await redis_conn.delete(key)
            hkeys = await redis_conn.hkeys(key)
            if hkeys:
                await redis_conn.hdel(key, *hkeys)

            # Store each dataframe under the agent's hash
            for df_key, df in dataframes.items():
                # Convert DataFrame to JSON
                df_json = json_encoder(df.to_dict(orient='records'))
                await redis_conn.hset(key, df_key, df_json)

            # Set expiration time
            expiration = timedelta(hours=cache_expiration)
            await redis_conn.expire(key, int(expiration.total_seconds()))

            logging.info(
                f"Data was cached for agent {agent_name} with expiration of {cache_expiration} hours"
            )

            await redis_conn.close()

        except Exception as e:
            # Log the error but continue execution
            print(f"Error caching dataframes: {e}")
