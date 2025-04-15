from pathlib import Path
from typing import List, Union, Optional
from io import BytesIO, StringIO
from datetime import datetime, timezone
import uuid
import pandas as pd
from datamodel.typedefs import SafeDict
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from navconfig import BASE_DIR
from ..tools import AbstractTool
from .agent import BasicAgent
from ..models import AgentResponse
from ..conf import BASE_STATIC_URL


PANDAS_PROMPT_PREFIX = """
Your name is {name}.

{backstory}

{capabilities}

You are working with {num_dfs} pandas dataframes in Python, all dataframes are already loaded and available for analysis in the variables named as df1, df2, etc.

**Answer the following questions as best you can. You have access to the following tools:**

- {tools}\n

Use these tools effectively to provide accurate and comprehensive responses:
{list_of_tools}

** DataFrames Information: **
{df_info}

## Working with DataFrames
- First examine the existing dataframe with `df.info()` and `df.describe()`.
- DO NOT create a sample daframe or example data, the user's actual data is already available.
- You can access columns with `df['column_name']`.
- For numerical analysis, use functions like mean(), sum(), min(), max().
- For categorical columns, consider using value_counts() to see distributions.
- You can create visualizations using matplotlib, seaborn or altair through the Python tool.
- Perform analysis over the entire DataFrame, not just a sample.
- Use `df['column_name'].value_counts()` to get counts of unique values.
- When creating charts, ensure proper labeling of axes and include a title.
- For visualization requests, use matplotlib or seaborn through the Python tool.
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
or "data exploration", use these functionss.
- The report will be saved to the specified directory and the function will return the file path
- The report includes basic statistics, correlations, distributions, and categorical value counts

### Podcast capabilities

if the user asks for a podcast, use the GoogleVoiceTool to generate a podcast-style audio file from a summarized text using Google Cloud Text-to-Speech.
- The audio file will be saved in own output directory and returned as a dictionary with a *file_path* key.
- Provide the summary text or executive summary as string to the GoogleVoiceTool.

## Thoughts
{format_instructions}

**IMPORTANT: When creating your final answer**
- Today is {today_date}, You must never contradict the given date.
- When creating visualizations, ALWAYS use the non-interactive Matplotlib backend (Agg)
- For saving files, use the following directory: agent_report_dir={agent_report_dir}.
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

{rationale}

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
Final Answer: the final answer to the original input question"""


PANDAS_PROMPT_SUFFIX = """
Begin!

Question: {input}
{agent_scratchpad}
"""


class PandasAgent(BasicAgent):
    """
    A simple agent that uses the pandas library to perform data analysis tasks.
    """

    def __init__(
        self,
        name: str = 'Agent',
        agent_id: str = None,
        agent_type: str = None,
        llm: str = 'vertexai',
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
        df: Union[list[pd.DataFrame], pd.DataFrame] = None,
        queries: List[str] = None,
        **kwargs
    ):
        if isinstance(df, pd.DataFrame):
            self.df = [df]
        elif isinstance(df, list):
            self.df = df
        else:
            raise ValueError(
                f"Expected pandas DataFrame, got {type(df)}"
            )
        self.df_locals: dict = {}
        # Chatbot ID:
        self.chatbot_id: uuid.UUID = kwargs.pop(
            'chatbot_id',
            str(uuid.uuid4().hex)
        )
        if self.chatbot_id is None:
            self.chatbot_id = uuid.uuid4().hex
        # Agent ID:
        self._prompt_prefix = PANDAS_PROMPT_PREFIX
        self._prompt_suffix = PANDAS_PROMPT_SUFFIX
        self._prompt_template = prompt_template
        self._capabilities: str = kwargs.get('capabilities', None)
        self.name = name or "Pandas Agent"
        self.description = "A simple agent that uses the pandas library to perform data analysis tasks."
        self._static_path = BASE_DIR.joinpath('static')
        self.agent_report_dir = self._static_path.joinpath('reports', 'agents', self.chatbot_id)
        if self.agent_report_dir.exists() is False:
            self.agent_report_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(
            name=name,
            chatbot_id=self.chatbot_id,
            llm=llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            tools=tools,
            **kwargs
        )
        self.agent_type = agent_type or "zero-shot-react-description"  # 'openai-tools'

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
        python_tool.run("from parrot.bots.tools.eda import quick_eda, generate_eda_report, list_available_dataframes")
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
            max_iterations=3,
            handle_parsing_errors=True,
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
            self.df_locals[df_name] = dataframe
            self.df_locals['agent_report_dir'] = self.agent_report_dir
            # Get basic dataframe info
            df_shape = f"DataFrame Shape: {dataframe.shape[0]} rows × {dataframe.shape[1]} columns"
            df_columns = f"Columns: {', '.join(dataframe.columns.tolist())}"
            # Generate summary statistics
            summary_stats = dataframe.describe(include='all').to_markdown()
            # Generate sample rows
            sample_rows = dataframe.head(10).to_markdown()
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
                capabilities = """
                **Your Capabilities:**

                {capabilities}
                """
            # Create the prompt
            self._prompt_prefix = PANDAS_PROMPT_PREFIX.format_map(
                SafeDict(
                    name=self.name,
                    list_of_tools=list_of_tools,
                    today_date=now,
                    system_prompt_base=prompt,
                    tools=", ".join(tools_names),
                    format_instructions=FORMAT_INSTRUCTIONS.format(
                        tool_names=", ".join(tools_names)),
                    df_info=df_info,
                    num_dfs=num_dfs,
                    capabilities=capabilities,
                    rationale=self.rationale,
                    backstory=self.backstory,
                    agent_report_dir=self.agent_report_dir,
                    **kwargs
                )
            )
            self._prompt_suffix = PANDAS_PROMPT_SUFFIX

    def default_backstory(self) -> str:
        return "You are a helpful assistant built to provide comprehensive guidance and support on data calculations and data analysis working with pandas dataframes."
