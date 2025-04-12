from typing import List, Union
from datetime import datetime, timezone
import pandas as pd
from datamodel.typedefs import SafeDict
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from ..tools import AbstractTool
from .agent import BasicAgent
from ..models import AgentResponse


PANDAS_PROMPT_PREFIX = """
Your name is {name}.

You are a data analysis expert working with a pandas dataframe.

{system_prompt_base}

**Answer the following questions as best you can. You have access to the following tools:**

- {tools}\n

Use these tools effectively to provide accurate and comprehensive responses:
{list_of_tools}

## DataFrame Information:
{df_info}

## Working with this DataFrame
- The dataframe is already loaded and available for analysis in the variable name `df`.
- First examine the existing dataframe with `df.info()` and `df.describe()`.
- Use `df.head()` to see the first few rows.
- Use `df.tail()` to see the last few rows.
- DO NOT create a sample daframe or example data, the user's actual data is already available.
- You can access columns with `df['column_name']`.
- For numerical analysis, use functions like mean(), sum(), min(), max().
- For categorical columns, consider using value_counts() to see distributions.
- You can create visualizations using matplotlib or seaborn through the Python tool.
- Perform analysis over the entire DataFrame, not just a sample.
- Use `df['column_name'].value_counts()` to get counts of unique values.
- When creating charts, ensure proper labeling of axes and include a title.
- For visualization requests, use matplotlib or seaborn through the Python tool.
- Provide clear, concise explanations of your analysis steps.
- When appropriate, suggest additional insights beyond what was directly asked.
- When someone asks for a chart or visualization:
    - Use matplotlib or seaborn to create the chart
    - Set an appropriate figure size with plt.figure(figsize=(10, 6))
    - Add proper titles, labels, and legend
    - Use plt.savefig('chart.png') to save the chart
    - Use display_image('chart.png') at the end to show the image
    - Do NOT just return the code - execute it completely

Example of chart creation:
```python
import matplotlib.pyplot as plt
import seaborn as sns

# Create figure with good size
plt.figure(figsize=(10, 6))

# Create visualization (example: bar chart)
sns.barplot(x='store_name', y='visit_count', data=top_stores.head(10))
plt.title('Top 10 Stores by Visit Count')
plt.xticks(rotation=45, ha='right')
plt.tight_layout()

# Save and display
plt.savefig('store_visits.png')
display_image('store_visits.png')
```


{format_instructions}

**IMPORTANT: When creating your final answer:**:
- Today is {today_date}, You must never contradict the given date.
- When you perform calculations (e.g., df.groupby().count()), store the results in variables
- In your final answer, ONLY use the EXACT values from your Python calculations.
- Use the EXACT values from your analysis (store names, customer names, numbers).
- NEVER use placeholder text like [Store 1] or [Value].
- Include complete, specific information from the data.
- Copy the exact values from your code output into your narrative.
- Your final answer must match exactly what you found in the data, no exceptions.
- Use the provided data to support your analysis, do not regenerate, recalculate or create new data.
- Do NOT repeat the same tool call multiple times for the same question.

** Your Style: **
- Maintain a professional and friendly tone.
- Be clear and concise in your explanations.
- Use simple language for complex topics to ensure user understanding.

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
        agent_type: str = None,
        llm: str = 'vertexai',
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        prompt_template: str = None,
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
        self.agent_type = agent_type or "zero-shot-react-description"  # 'openai-tools'
        # self.agent_type = "openai-functions"
        self.df = df
        self._prompt_prefix = PANDAS_PROMPT_PREFIX
        self._prompt_suffix = PANDAS_PROMPT_SUFFIX
        self._prompt_template = prompt_template
        self.define_prompt(prompt_template)

    def pandas_agent(self, df: pd.DataFrame, **kwargs):
        """
        Creates a Pandas Agent.

        This agent uses reasoning and tool execution iteratively to generate responses.

        Returns:
            RunnableMultiActionAgent: A Pandas-based agent.

        ✅ Use Case: Best for decision-making and reasoning tasks where the agent must break problems down into multiple steps.

        """
        # Create the Python REPL tool
        python_tool = PythonAstREPLTool(locals={"df": df})
        # Add it to the tools list
        additional_tools = [python_tool]
        # Create the pandas agent
        return create_pandas_dataframe_agent(
            self._llm,
            df,
            verbose=True,
            agent_type=self.agent_type,
            allow_dangerous_code=True,
            extra_tools=additional_tools,
            #include_df_in_prompt=False,
            # number_of_head_rows=10,
            handle_parsing_errors=True,
            prefix=self._prompt_prefix,
            # suffix=self._prompt_suffix,
            max_iterations=3,
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
        # List of Tools:
        list_of_tools = ""
        for tool in self.tools:
            name = tool.name
            description = tool.description  # noqa  pylint: disable=E1101
            list_of_tools += f'- {name}: {description}\n'
        list_of_tools += "\n"
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
## DataFrame Shape
{df_shape}

## DataFrame Columns
{df_columns}

## Summary Statistics
{summary_stats}

## Sample Rows (First 10)
{sample_rows}

"""
            tools_names = [tool.name for tool in self.tools]
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
                    **kwargs
                )
            )
            self._prompt_suffix = PANDAS_PROMPT_SUFFIX
