from typing import List, Union
from datetime import datetime, timezone
import pandas as pd
from datamodel.typedefs import SafeDict
from langchain.agents import AgentExecutor
from langchain.prompts import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from ..tools import AbstractTool
from .agent import BasicAgent
from ..models import AgentResponse


PANDAS_PROMPT = """
Your name is {name}.

{system_prompt_base}

**Answer the following questions as best you can. You have access to the following tools:**

- {tools}\n

Use these tools effectively to provide accurate and comprehensive responses:
{list_of_tools}

**DataFrame Information:**
{df_info}

**Important**: Today is {today_date}, You must never contradict the given date.

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
        agent_type: str = None,
        llm: str = 'vertexai',
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = PANDAS_PROMPT,
        df: Union[list[pd.DataFrame], pd.DataFrame] = None,
        **kwargs
    ):
        super().__init__(
            name=name,
            llm=llm,
            system_prompt=system_prompt,
            human_prompt=human_prompt,
            **kwargs
        )
        self.name = name or "Pandas Agent"
        self.description = "A simple agent that uses the pandas library to perform data analysis tasks."
        self.agent_type = agent_type or "zero-shot-react-description"
        self.df = df
        self.prompt = self.define_prompt(PANDAS_PROMPT)

    def pandas_agent(self, df: pd.DataFrame, **kwargs):
        """
        Creates a Pandas Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A Pandas-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        df_locals = {}
        dfs_head = ""
        df_locals["df"] = self.df
        dfs_head += (
            f"\n\n- This is the result of `print(df.head())`:\n"
            + self.df.head().to_markdown() + "\n"
        )
        # Create the Python REPL tool
        python_tool = PythonAstREPLTool(locals=df_locals)
        # Add it to the tools list
        additional_tools = [python_tool]
        # Create the pandas agent
        return create_pandas_dataframe_agent(
            self._llm,
            df,
            number_of_head_rows=10,
            verbose=True,
            agent_type=self.agent_type,
            allow_dangerous_code=True,
            extra_tools=additional_tools,
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
        # Add dataframe information
        df_info = ""
        if hasattr(self, 'df') and self.df is not None:
            # Get basic dataframe info
            df_shape = f"DataFrame Shape: {self.df.shape[0]} rows × {self.df.shape[1]} columns"
            df_columns = f"Columns: {', '.join(self.df.columns.tolist())}"
            # Generate summary statistics
            summary_stats = self.df.describe(include='all').to_markdown()

            # Generate sample rows
            sample_rows = self.df.head(10).to_markdown()
            # Create df_info block
            df_info = f"""
## DataFrame Information
{df_shape}
{df_columns}

## Summary Statistics
{summary_stats}

## Sample Rows (First 10)
{sample_rows}

## Working with this DataFrame
- Use `df` to access the entire DataFrame
- You can access columns with `df['column_name']`
- For numerical analysis, use functions like mean(), sum(), min(), max()
- For categorical columns, consider using value_counts() to see distributions
- You can create visualizations using matplotlib or seaborn through the Python tool
- When creating charts, ensure proper labeling of axes and include a title
- For visualization requests, use matplotlib or seaborn through the Python tool
- Provide clear, concise explanations of your analysis steps
- When appropriate, suggest additional insights beyond what was directly asked
"""

        final_prompt = prompt.format_map(
            SafeDict(
                today_date=now,
                list_of_tools=list_of_tools,
                df_info=df_info,
                **kwargs
            )
        )
        # Define a structured system message
        system_message = f"""
        Today is {now}.

        You are a data analysis assistant working with pandas DataFrames.

        If an event is expected to have occurred before this date, assume that results exist.
        If you call a tool and receive a valid answer, finalize your response immediately.
        Do NOT repeat the same tool call multiple times for the same question.
        """
        chat_prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(system_message),
            ChatPromptTemplate.from_template(final_prompt)
        ])
        return chat_prompt.partial(
            tools=self.tools,
            tool_names=", ".join([tool.name for tool in self.tools]),
            name=self.name,
            **kwargs
        )
