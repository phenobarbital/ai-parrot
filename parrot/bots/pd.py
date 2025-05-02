from pathlib import Path
from typing import List, Union, Optional
from io import BytesIO, StringIO
from datetime import datetime, timezone, timedelta
import re
import uuid
from string import Template
import redis.asyncio as aioredis
import pandas as pd
from datamodel.typedefs import SafeDict
from langchain_core.exceptions import OutputParserException
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from navconfig import BASE_DIR
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder, json_decoder
from querysource.queries.qs import QS
from querysource.queries.multi import MultiQS
from ..tools import AbstractTool
from ..tools.docx import DocxGeneratorTool
from .agent import BasicAgent
from ..models import AgentResponse
from ..conf import BASE_STATIC_URL, REDIS_HISTORY_URL


PANDAS_PROMPT_PREFIX = """

Your name is $name, you are a helpful assistant built to provide comprehensive guidance and support on data calculations and data analysis working with pandas dataframes.
$description\n\n
$backstory\n
$capabilities\n

You are working with $num_dfs pandas dataframes in Python, all dataframes are already loaded and available for analysis in the variables named as df1, df2, etc.

**Answer the following questions as best you can. You have access to the following tools:**

- $tools\n

Use these tools effectively to provide accurate and comprehensive responses:
$list_of_tools

** DataFrames Information: **
$df_info

## Working with DataFrames
- First examine the existing dataframe with `df.info()` and `df.describe()`.
- DO NOT create a sample daframe or example data, the user's actual data is already available.
- You can access columns with `df['column_name']`.
- For numerical analysis, use functions like mean(), sum(), min(), max().
- Always use copies of dataframes to avoid modifying the original data.
- For categorical columns, consider using value_counts() to see distributions.
- You can create visualizations using matplotlib, seaborn or altair through the Python tool.
- Perform analysis over the entire DataFrame, not just a sample.
- Use `df['column_name'].value_counts()` to get counts of unique values.
- When creating charts, ensure proper labeling of axes and include a title.
- For visualization requests, use matplotlib, altair or seaborn through the Python tool.
- You have access to several python libraries installed as scipy, numpy, matplotlib, matplotlib-inline, seaborn, altair, plotly, reportlab, pandas, numba, geopy, geopandas, prophet, statsmodels, scikit-learn, pmdarima, sentence-transformers, nltk, spacy, and others.
- Provide clear, concise explanations of your analysis steps.
- When appropriate, suggest additional insights beyond what was directly asked.

### EDA (Exploratory Data Analysis) Capabilities

This agent has built-in Exploratory Data Analysis (EDA) capabilities:
1. For comprehensive EDA reports, use:
```python
generate_eda_report(dataframe=df, report_dir=agent_report_dir, df_name="my_data", minimal=False, explorative=True):
```
This generates an interactive HTML report with visualizations and statistics.
2. For a quick custom EDA without external dependencies:
```python
quick_eda(dataframe=df, report_dir=agent_report_dir)
```
This performs basic analysis with visualizations for key variables.
When a user asks for "exploratory data analysis", "EDA", "data profiling", "understand the data",
or "data exploration", use these functions.
- The report will be saved to the specified directory and the function will return the file path
- The report includes basic statistics, correlations, distributions, and categorical value counts.

### Podcast capabilities

if the user asks for a podcast, use the GoogleVoiceTool to generate a podcast-style audio file from a summarized text using Google Cloud Text-to-Speech.
- The audio file will be saved in own output directory and returned as a dictionary with a *file_path* key.
- Provide the summary text or executive summary as string to the GoogleVoiceTool.

### PDF and HTML Report Generation

When the user requests a PDF or HTML report, follow these detailed steps:
1. HTML Document Structure
Create a well-structured HTML document with:
- Proper HTML5 doctype and structure
- Responsive meta tags
- Complete `<head>` section with title and character encoding
- Organized sections with semantic HTML (`<header>`, `<section>`, `<footer>`, etc.)
- Table of contents with anchor links when appropriate

2. CSS Styling Framework
- Use a lightweight CSS framework including in the `<head>` section of HTML

3. For Data Tables
- Apply appropriate classes for data tables
- Use fixed headers when tables are long
- Add zebra striping for better readability
- Include hover effects for rows
- Align numerical data right-aligned

4. For Visualizations and Charts
- Embed charts as SVG when possible for better quality
- Include a figure container with caption
- Add proper alt text for accessibility

5. For Summary Cards
- Use card components for key metrics and summaries
- Group related metrics in a single card
- Use a grid layout for multiple cards
Example:
```html



            Key Metric

                75.4%
                Description of what this metric means




```
6. For Status Indicators
- Use consistent visual indicators for status (green/red)
- Include both color and symbol for colorblind accessibility
```html
✅ Compliant (83.5%)
❌ Non-compliant (64.8%)
```

### PDF Report Generation

if the user asks for a PDF report, use the following steps:
- First generate a complete report in HTML:
    - Create a well-structured HTML document with proper sections, headings and styling
    - Include always all relevant information, charts, tables, summaries and insights
    - use seaborn or altair for charts and matplotlib for plots as embedded images
    - Use CSS for professional styling and formatting (margins, fonts, colors)
    - Include a table of contents for easy navigation
- Set explicit page sizes and margins
- Add proper page breaks before major sections
- Define headers and footers for multi-page documents
- Include page numbers
- Convert the HTML report to PDF using this function:
```python
generate_pdf_from_html(html_content, report_dir=agent_report_dir):
```
- Return a python dictionary with the file path of the generated PDF report:
    - "file_path": "pdf_path"
    - "content_type": "application/pdf"
    - "type": "pdf"
    - "html_path": "html_path"
- When converting to PDF, ensure all document requirements are met for professional presentation.

### Gamma Presentation Capabilities

if the user asks for a Gamma Presentation, generate a text summary of the data analysis and use the GammaLinkTool to create a presentation.
- The summary should be concise and highlight key insights.
- Use the GammaLinkTool to create an URL for presentation.

## Thoughts
$format_instructions

**IMPORTANT: When creating your final answer**
- Today is $today_date, You must never contradict the given date.
- When creating visualizations, ALWAYS use the non-interactive Matplotlib backend (Agg)
- For saving files, use the following directory: agent_report_dir=$agent_report_dir, variable can be called also *report_dir*.
- When you perform calculations (e.g., df.groupby().count()), store the results in variables
- In your final answer, ONLY use the EXACT values from your Python calculations.
- Use the EXACT values from your analysis (store names, customer names, numbers).
- NEVER use placeholder text like [Store 1] or [Value], include complete, specific information from the data.
- Copy the exact values from your code output into your narrative.
- Your final answer must match exactly what you found in the data, no exceptions.
- Use the provided data to support your analysis, do not regenerate, recalculate or create new data.
- Do NOT repeat the same tool call multiple times for the same question.

**IMPORTANT: HANDLING FILE RESULTS**

When you generate a file like a chart or report, you MUST format your response exactly like this:

Thought: I now know the final answer
Final Answer: I've generated a [type] for your data.

The [type] has been saved to:
filename: [file_path]

[Brief description of what you did and what the file contains]
[rest of answer]

$rationale

"""

FORMAT_INSTRUCTIONS = """
Please use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question
"""


PANDAS_PROMPT_SUFFIX = """
Begin!

Question: {input}
{agent_scratchpad}
"""

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
        df: Union[list[pd.DataFrame], pd.DataFrame] = None,
        query: Union[List[str], dict] = None,
        **kwargs
    ):
        self._queries = query
        if isinstance(df, pd.DataFrame):
            self.df = [df]
        elif isinstance(df, list):
            self.df = df
        else:
            self.df = []
            # raise ValueError(
            #     f"Expected pandas DataFrame, got {type(df)}"
            # )
        self.df_locals: dict = {}
        # Agent ID:
        self._prompt_prefix = None
        self._prompt_suffix = PANDAS_PROMPT_SUFFIX
        self._prompt_template = prompt_template
        self._capabilities: str = kwargs.get('capabilities', None)
        self._format_instructions: str = kwargs.get('format_instructions', FORMAT_INSTRUCTIONS)
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
            **kwargs
        )
        # Must be one of 'tool-calling', 'openai-tools', 'openai-functions', or 'zero-shot-react-description'.
        self.agent_type = agent_type or "zero-shot-react-description"
        # self.agent_type = "openai-functions"

    def get_query(self) -> Union[List[str], dict]:
        """Get the query."""
        return self._queries

    def get_capabilities(self) -> str:
        """Get the capabilities of the agent."""
        return self._capabilities

    def pandas_agent(self, df: pd.DataFrame, **kwargs):
        """
        Creates a Pandas Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A Pandas-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        # Create the Python REPL tool
        python_tool = PythonAstREPLTool(locals=self.df_locals)
        # Add EDA functions to the tool's locals
        setup_code = """
        from parrot.bots.tools import quick_eda, generate_eda_report, list_available_dataframes, gamma_link, create_plot, generate_pdf_from_html
        """
        try:
            python_tool.run(setup_code)
        except Exception as e:
            self.logger.error(
                f"Error setting up python tool locals: {e}"
            )
        # Add it to the tools list
        self.tools.append(python_tool)
        # Create the pandas agent
        return create_pandas_dataframe_agent(
            self._llm,
            df,
            verbose=True,
            agent_type=self.agent_type,
            allow_dangerous_code=True,
            extra_tools=self.tools,
            prefix=self._prompt_prefix,
            max_iterations=15,
            handle_parsing_errors=True,
            return_intermediate_steps=False,
            **kwargs
        )

    async def configure(self, df: pd.DataFrame = None, app=None) -> None:
        """Basic Configuration of Pandas Agent.
        """
        await super(BasicAgent, self).configure(app)
        if df is not None:
            self.df = df
        # Configure LLM:
        self.configure_llm(use_chat=True)
        # Conversation History:
        self.memory = self.get_memory()
        # 1. Initialize the Agent (as the base for RunnableMultiActionAgent)
        self.agent = self.pandas_agent(self.df)
        # 2. Create Agent Executor - This is where we typically run the agent.
        self._agent = self.agent

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

    async def invoke(self, query: str):
        """invoke.

        Args:
            query (str): The query to ask the chatbot.

        Returns:
            str: The response from the chatbot.

        """
        input_question = {
            "input": query
        }
        result = await self._agent.ainvoke(
            {"input": input_question}
        )
        try:
            response = AgentResponse(question=query, **result)
            # check if return is a file:
            try:
                self.extract_filenames(response)
            except Exception as exc:
                self.logger.error(
                    f"Unable to extract filenames: {exc}"
                )
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

    def define_prompt(self, prompt, **kwargs):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.agent_report_dir = self._static_path.joinpath(str(self.chatbot_id))
        if self.agent_report_dir.exists() is False:
            self.agent_report_dir.mkdir(parents=True, exist_ok=True)
        # Word Tool:
        docx_tool = DocxGeneratorTool(output_dir=self.agent_report_dir)
        self.tools.append(docx_tool)
        # List of Tools:
        list_of_tools = ""
        for tool in self.tools:
            name = tool.name
            description = tool.description  # noqa  pylint: disable=E1101
            list_of_tools += f'- {name}: {description}\n'
        list_of_tools += "\n"
        # Add dataframe information
        num_dfs = len(self.df)
        for i, dataframe in enumerate(self.df):
            df_name = f"df{i + 1}"
            self.df_locals[df_name] = dataframe.copy()
            self.df_locals['agent_report_dir'] = self.agent_report_dir
            # Get basic dataframe info
            df_shape = f"DataFrame Shape: {dataframe.shape[0]} rows × {dataframe.shape[1]} columns"
            df_columns = f"Columns: {', '.join(dataframe.columns.tolist())}"
            # Generate summary statistics
            summary_stats = brace_escape(dataframe.describe(include='all').to_markdown())
            # Generate sample rows
            sample_rows = brace_escape(dataframe.head(10).to_markdown())
            # Create df_info block
            df_info = f"""
** DataFrame {df_name} Information **

## {df_name} Shape
{df_shape}

## {df_name} Columns
{df_columns}

## {df_name} Summary Statistics
{summary_stats}

## {df_name} Sample Rows (First 10)
{sample_rows}

"""
            tools_names = [tool.name for tool in self.tools]
            capabilities = ''
            if self._capabilities:
                capabilities = "**Your Capabilities:**\n"
                capabilities += self.sanitize_prompt_text(self._capabilities) + "\n"
            # Create the prompt
            sanitized_backstory = ''
            if self.backstory:
                sanitized_backstory = self.sanitize_prompt_text(self.backstory)
            # self._prompt_prefix = PANDAS_PROMPT_PREFIX.format_map(
            tmpl = Template(PANDAS_PROMPT_PREFIX)
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
            print('PROMPT >> ', self._prompt_prefix)
            self._prompt_suffix = PANDAS_PROMPT_SUFFIX

    def default_backstory(self) -> str:
        return "You are a helpful assistant built to provide comprehensive guidance and support on data calculations and data analysis working with pandas dataframes."

    @staticmethod
    async def call_qs(queries: list) -> List[pd.DataFrame]:
        """
        call_qs.
        description: Call the QuerySource queries.
        """
        dfs = []
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
                dfs.append(df)
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(
                    f"Error executing Query {query}: {e}"
                )
        return dfs

    @staticmethod
    async def call_multiquery(query: dict) -> List[pd.DataFrame]:
        """
        call_multiquery.
        description: Call the MultiQuery queries.
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
        return list(result.values())

    @classmethod
    async def gen_data(
        cls,
        query: Union[list, dict],
        agent_name: Optional[str] = None,
        refresh: bool = False,
        cache_expiration: int = 48
    ) -> List[pd.DataFrame]:
        """
        gen_data.

        Generate the dataframes required for the agent to work, with Redis caching support.

        Parameters:
        -----------
        query : Union[list, dict]
            The query or queries to execute to generate dataframes.
        agent_name : Optional[str]
            Name of the agent, used for caching. If None, caching is disabled.
        refresh : bool
            If True, forces regeneration of dataframes even if cached versions exist.
        cache_expiration_hours : int
            Number of hours to keep the cached dataframes (default: 48).

        Returns:
        --------
        List[pd.DataFrame]
            A list of pandas DataFrames generated from the queries.
        """
        # If agent_name is provided, we'll use Redis caching
        if agent_name and not refresh:
            # Try to get cached dataframes
            cached_dfs = await cls._get_cached_data(agent_name)
            if cached_dfs:
                return cached_dfs

        # Generate dataframes from query if no cache exists or refresh is True
        dfs = await cls._execute_query(query)

        # If agent_name is provided, cache the generated dataframes
        if agent_name:
            await cls._cache_data(agent_name, dfs, cache_expiration)

        return dfs

    @classmethod
    async def _execute_query(cls, query: Union[list, dict]) -> List[pd.DataFrame]:
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
            decode_responses=False
        )

    @classmethod
    async def _get_cached_data(cls, agent_name: str) -> Optional[List[pd.DataFrame]]:
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
            dataframes = []
            for df_key in df_keys:
                df_json = await redis_conn.hget(key, df_key)
                if df_json:
                    # Convert from JSON to dataframe
                    df_data = json_decoder(df_json.decode('utf-8'))
                    df = pd.DataFrame.from_records(df_data)
                    dataframes.append(df)

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
        dataframes: List[pd.DataFrame],
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

            # Store each dataframe under the agent's hash
            for i, df in enumerate(dataframes):
                df_key = f"df{i+1}"
                # Convert DataFrame to list of dictionaries
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
