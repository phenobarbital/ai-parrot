from typing import Union
import pandas as pd
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from .base import BaseAgent


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


class DataFrameAgent(BaseAgent):
    """Dataframe Agent.

    This is the Pandas Agent Chatbot.
    """
    def __init__(
        self,
        name: str = 'Agent',
        llm: str = 'vertexai',
        tools: list = None,
        df: Union[list[pd.DataFrame], pd.DataFrame] = None,
        prompt_template: str = None,
        **kwargs
    ):
        super().__init__(name, llm, tools, prompt_template, **kwargs)
        for _df in df if isinstance(df, list) else [df]:
            if not isinstance(_df, pd.DataFrame):
                raise ValueError(
                    f"Expected pandas DataFrame, got {type(_df)}"
                )
        self.df = df
        df_locals = {}
        dfs_head = ""
        num_dfs = 1
        if isinstance(df, pd.DataFrame):
            df = [df]
        num_dfs = len(df)
        for i, dataframe in enumerate(df):
                    df_locals[f"df{i + 1}"] = dataframe
                    dfs_head += (
                        f"\n\n- This is the result of `print(df{i + 1}.head())`:\n"
                        + dataframe.head().to_markdown() + "\n"
                    )
        prompt_template = BASEPROMPT
        self.tools = [PythonAstREPLTool(locals=df_locals)] + list(tools)
        self.prompt = self.get_prompt(
            prompt_template,
            num_dfs=num_dfs,
            dfs_head=dfs_head
        )
