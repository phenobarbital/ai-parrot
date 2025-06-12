# basic requirements:
import os
from typing import Any, Dict, Type, Union, List
import json
import asyncio
# Pydantic:
from pydantic import BaseModel, Field
# Pandas:
import pandas as pd
# Langchain Tools:
from langchain_core.tools import (
    BaseTool,
    BaseToolkit,
    StructuredTool,
    ToolException,
)
# AsyncDB database connections
from asyncdb import AsyncDB
from querysource.conf import default_dsn
# Parrot Agent
from parrot.bots.agent import BasicAgent
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
from parrot.llms.openai import OpenAILLM
from parrot.tools import PythonREPLTool
from parrot.bots.data import PandasAgent


# Function: Agent Creation:
# If use LLama4 with Groq (fastest model)
vertex = VertexLLM(
    model="gemini-2.0-flash-001",
    preset="analytical",
    use_chat=True
)

vertex_pro = VertexLLM(
    model="gemini-2.5-pro-preview-05-06",
    preset="concise",
    use_chat=True
)

groq = GroqLLM(
    model="llama-3.1-8b-instant",
    max_tokens=2048
)

openai = OpenAILLM(
    model="gpt-4.1",
    temperature=0.1,
    max_tokens=2048,
    use_chat=True
)

claude = AnthropicLLM(
    model="claude-3-5-sonnet-20240620",
    temperature=0,
    use_tools=True
)

backstory = """
You have a pandas DataFrame with visits made by Reps to stores, for every visit a form (recap) is filled with information about the visit, the store, and the Rep.
Columns:
- form_id (int): Unique identifier for the form.
- formid (str): Identifier of the form.
- visit_date (date): Date of the visit.
- visit_timestamp (datetime): Timestamp of the visit.
- visit_length (int): Length of the visit in minutes.
- time_in (time): Time when the visit started.
- time_out (time): Time when the visit ended.
- store_id (int): Unique identifier for the store.
- store_number (str): Number of the store.
- column_name (str): Identifier of the question in the form.
- question (str): The question asked in the form.
- data (str): The answer to the question.
- visitor_name (str): Name of the visitor (Rep).
- visitor_username (str): Username of the visitor.
- visitor_role (str): Role of the visitor (Rep).
- visit_data (jsonb): Aggregated data from the form.
Basic requirements:
- Analyze the visits made by Reps to stores.
- Provide insights on store performance based on visit data.
- Identify trends in Rep visits and store interactions.
- Suggest improvements based on visit data analysis.
- Use the provided columns to analyze store performance and Rep interactions.
- Use the visit_data JSONB field to extract relevant information.
- Use the visitor field to analyze Rep demographics and roles.
- The data is aggregated by form_id, visit_date, and store_id.
- The visit_data field contains aggregated visit information (questions answered by Reps).
- Questions are related to subjective perceptions of the store, such as cleanliness, product availability, and customer service, for example: What were the key wins or successes from today’s visit?
"""

sql = f"""
SELECT
form_id,
formid,
visit_date,
visit_timestamp,
visit_length,
time_in,
time_out,
store_id,
store_number,
jsonb_agg(
    jsonb_build_object(
    'column_name',   column_name,
    'question',      question,
    'data',          data
    ) ORDER BY column_name
) AS visit_data,
jsonb_agg(
    DISTINCT
    jsonb_build_object(
    'visitor_name',     visitor_name,
    'username', visitor_username,
    'role', visitor_role
    )
) AS visitor
FROM hisense.form_data
WHERE visit_date::date
BETWEEN (date_trunc('week', CURRENT_DATE) - INTERVAL '1 week')::date AND CURRENT_DATE
AND column_name IN ('9733','9731','9732','9730')
GROUP BY
form_id,
formid,
visit_date,
visit_timestamp,
visit_length,
store_id,
store_number,
time_in,
time_out
ORDER BY
form_id,
visit_timestamp DESC;
"""

# Toolkit for NextStop Copilot:
tools = [PythonREPLTool()]

async def get_agent(llm, backstory=None) -> BasicAgent:
    """Create and configure a NextStop Copilot agent with store analysis tools.

    Args:
        llm: The language model instance to use for the agent.

    Returns:
        BasicAgent: Configured agent ready for store and demographic analysis.
    """
    db = AsyncDB('pg', dsn=default_dsn)
    errors = None
    async with await db.connection() as conn:  # pylint: disable=E1101  # noqa
        conn.output_format('pandas')
        data, errors = await conn.query(sql)
    if errors:
        raise ToolException(f"Error executing SQL query: {errors}")
    if not isinstance(data, pd.DataFrame):
        raise TypeError("Expected a pandas DataFrame from the SQL query.")
    if data.empty:
        raise ValueError("No data found for the specified query.")
    agent = PandasAgent(
        name='NextStop Analytics',
        llm=llm,
        tools=tools,
        df=data,
        backstory=backstory,
        agent_type='tool-calling'
    )
    await agent.configure()
    return agent


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent(llm=openai, backstory=backstory)
    )
    prompt = """
    Analyze the visits made by Reps to stores.
    Provide insights on store performance based on visit data.
    Identify trends in Rep visits and store interactions.
    Suggest improvements based on visit data analysis.
    Use the provided columns to analyze store performance and Rep interactions.
    Use the visit_data JSONB field to extract relevant information.
    Common problems detected by Reps based on visit data.

    Return the evaluation as a detailed report, including:
    1. **Executive Summary:** A brief overview of key findings.
    2. **Detailed Analysis:**
        - A breakdown of store performance metrics, include visualizations if necessary.
        - Average visit length and time spent per store.
        - Average and total duration per Rep.
        - Analysis of Rep demographics and roles.
    3. **Trends and Patterns:** Insights into Rep visits and store interactions.
        - Identify any patterns in visit frequency, store performance, and Rep interactions.
        - Unusual patterns or outliers in visit data.
    4. **Common Issues:** Problems detected by Reps based on visit data.
    5. **Recommendations:** Suggestions for improvements based on visit data analysis.
    Ensure the analysis is actionable and relevant to store management.

    Export the analysis as a PDF report using the pdf_print_tool.
    """
    answer, response = asyncio.run(
        agent.invoke(prompt)
    )
    print(response.output)
