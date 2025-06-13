# basic requirements:
import os
from typing import Any, Dict, Type, Union, List
import textwrap
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
You have a pandas DataFrame with visits made by Reps to stores.
**Store Visit Analytics - Column Descriptions**
Basic Visit Information:
- form_id (int): Unique identifier for the form used during the visit
- formid (int): Secondary identifier of the form
- visit_date (date): Date when the store visit occurred (YYYY-MM-DD format)
- visit_timestamp (datetime): Complete timestamp of when the visit was recorded
- visit_length (int): Length of the visit in minutes (from form data)
- time_in (time): Time when the visitor entered the store (HH:MM:SS format)
- time_out (time): Time when the visitor left the store (HH:MM:SS format)
- time_spent_minutes (decimal): Calculated time spent in store in minutes (time_out - time_in)

Store Information:
- store_id (string): Unique alphanumeric identifier for the store (e.g., "LWS0615")
- store_number (int): Numeric identifier/number assigned to the store

Visitor Information:
- visitor_name (string): Full name of the store visitor/representative
- visitor_username (string): Username/login ID of the visitor
- visitor_role (string): Role/title of the visitor (e.g., "Brand Ambassador")

Visit Content Data:
- visit_data (jsonb): Aggregated JSON containing all form responses with structure:
- visitor (jsonb): Aggregated visitor information in JSON format

Period Flags (Internal Calculations):
- in_7_days (int): 1 if visit occurred in last 7 days, 0 otherwise
- in_14_days (int): 1 if visit occurred in last 14 days, 0 otherwise
- in_21_days (int): 1 if visit occurred in last 21 days, 0 otherwise
- in_week_1 (int): 1 if visit occurred in most recent 7 days, 0 otherwise
- in_week_2 (int): 1 if visit occurred in days 8-14 ago, 0 otherwise
- in_week_3 (int): 1 if visit occurred in days 15-21 ago, 0 otherwise

Employee Performance Analytics:
Visit Counts by Employee:
- employee_visits_7_days (int): Total visits made by this employee in last 7 days
- employee_visits_14_days (int): Total visits made by this employee in last 14 days
- employee_visits_21_days (int): Total visits made by this employee in last 21 days

Employee Averages:
- employee_avg_daily_7d (decimal): Average visit length for this employee in last 7 days
- employee_avg_daily_14d (decimal): Average visit length for this employee in last 14 days
- employee_avg_daily_21d (decimal): Average visit length for this employee in last 21 days

Employee Store Coverage:
- employee_stores_7d (int): Number of unique stores visited by this employee in last 7 days
- employee_stores_14d (int): Number of unique stores visited by this employee in last 14 days
- employee_stores_21d (int): Number of unique stores visited by this employee in last 21 days

Employee Trend Analysis:
- stores_visited_7_vs_21_day_trend_pct (decimal): Percentage change in stores visited comparing 7-day vs 21-day periods

Company-Wide Summary Statistics:
Total Visits by Period:
- total_visits_7_days (int): Total visits across all employees in last 7 days
- total_visits_14_days (int): Total visits across all employees in last 14 days
- total_visits_21_days (int): Total visits across all employees in last 21 days

Unique Store Coverage:
- stores_visited_7_days (int): Total unique stores visited by all employees in last 7 days
- stores_visited_14_days (int): Total unique stores visited by all employees in last 14 days
- stores_visited_21_days (int): Total unique stores visited by all employees in last 21 days

Daily Averages:
- avg_daily_visits_7_days (decimal): Average visits per day across company in last 7 days
- avg_daily_visits_14_days (decimal): Average visits per day across company in last 14 days
- avg_daily_visits_21_days (decimal): Average visits per day across company in last 21 days

Store Visit Distribution:
- median_visits_per_store_7_days (decimal): Median number of visits per store in last 7 days
- median_visits_per_store_14_days (decimal): Median number of visits per store in last 14 days
- median_visits_per_store_21_days (decimal): Median number of visits per store in last 21 days

Weekly Breakdown Analysis:
Weekly Visit Counts
- week_1_total_visits (int): Total visits in most recent week (days 1-7)
- week_2_total_visits (int): Total visits in second week (days 8-14)
- week_3_total_visits (int): Total visits in third week (days 15-21)

Weekly Store Coverage:
- week_1_unique_stores (int): Unique stores visited in week 1
- week_2_unique_stores (int): Unique stores visited in week 2
- week_3_unique_stores (int): Unique stores visited in week 3

Weekly Averages:
- week_1_avg_daily_visits (decimal): Average daily visits in week 1
- week_2_avg_daily_visits (decimal): Average daily visits in week 2
- week_3_avg_daily_visits (decimal): Average daily visits in week 3

Weekly Medians:
- week_1_median_visits_per_store (decimal): Median visits per store in week 1
- week_2_median_visits_per_store (decimal): Median visits per store in week 2
- week_3_median_visits_per_store (decimal): Median visits per store in week 3

Week-over-Week Variance Analysis (%)
Total Visits Variance:
- week_1_vs_week_2_total_visits_variance_pct (decimal): % change in total visits from week 2 to week 1
- week_2_vs_week_3_total_visits_variance_pct (decimal): % change in total visits from week 3 to week 2

Daily Average Variance:
- week_1_vs_week_2_avg_daily_variance_pct (decimal): % change in daily averages from week 2 to week 1
- week_2_vs_week_3_avg_daily_variance_pct (decimal): % change in daily averages from week 3 to week 2

Median Variance:
- week_1_vs_week_2_median_variance_pct (decimal): % change in median visits per store from week 2 to week 1
- week_2_vs_week_3_median_variance_pct (decimal): % change in median visits per store from week 3 to week 2

Store Coverage Variance:
- week_1_vs_week_2_unique_stores_variance_pct (decimal): % change in unique stores visited from week 2 to week 1
- week_2_vs_week_3_unique_stores_variance_pct (decimal): % change in unique stores visited from week 3 to week 2

Employee Performance Rankings:
- employee_7day_visits_rank (int): Employee's rank based on 7-day visit count (1 = highest)
- employee_14day_visits_rank (int): Employee's rank based on 14-day visit count (1 = highest)
- employee_21day_visits_rank (int): Employee's rank based on 21-day visit count (1 = highest)

"""

sql = f"""
WITH visit_data AS (
    SELECT
        form_id,
        formid,
        visit_date::date AS visit_date,
        visitor_name,
        visitor_username,
        visitor_role,
        visit_timestamp,
        visit_length,
        time_in,
        time_out,
        store_id,
        store_number,
        -- Calculate time spent in decimal minutes
        CASE
            WHEN time_in IS NOT NULL AND time_out IS NOT NULL THEN
                EXTRACT(EPOCH FROM (time_out::time - time_in::time)) / 60.0
            ELSE NULL
         END AS time_spent_minutes,

        -- Aggregate visit data
        jsonb_agg(
            jsonb_build_object(
                'column_name', column_name,
                'question', question,
                'data', data
            ) ORDER BY column_name
        ) AS visit_data,

        -- Aggregate visitor data
        jsonb_agg(
            DISTINCT jsonb_build_object(
                'visitor_name', visitor_name,
                'username', visitor_username,
                'role', visitor_role
            )
        ) AS visitor,

        -- Period calculations
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '7 days' THEN 1 ELSE 0 END AS in_7_days,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '14 days' THEN 1 ELSE 0 END AS in_14_days,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '21 days' THEN 1 ELSE 0 END AS in_21_days,

        -- Week-specific calculations for variance analysis
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '7 days' THEN 1 ELSE 0 END AS in_week_1,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '14 days'
             AND visit_date::date < CURRENT_DATE - INTERVAL '7 days' THEN 1 ELSE 0 END AS in_week_2,
        CASE WHEN visit_date::date >= CURRENT_DATE - INTERVAL '21 days'
             AND visit_date::date < CURRENT_DATE - INTERVAL '14 days' THEN 1 ELSE 0 END AS in_week_3

    FROM hisense.form_data
    WHERE visit_date::date >= CURRENT_DATE - INTERVAL '21 days'
    AND column_name IN ('9733','9731','9732','9730')
    GROUP BY
        form_id, formid, visit_date, visit_timestamp, visit_length,
        time_in, time_out, store_id, store_number, visitor_name, visitor_username, visitor_role
),
-- Employee Trends
employee_trends AS (
  SELECT *,
  COUNT(visit_date) OVER (PARTITION BY visitor_username ORDER BY visit_date RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW) as employee_visits_7_days,
  AVG(visit_length) OVER (
            PARTITION BY visitor_username
            ORDER BY visit_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        ) AS employee_avg_daily_7d,
        -- Count unique stores visited by the current employee in the last 7 days
        COUNT(store_id) OVER (
            PARTITION BY visitor_username
            ORDER BY visit_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        ) AS employee_stores_7d,
  COUNT(visit_date) OVER (PARTITION BY visitor_username ORDER BY visit_date RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW) as employee_visits_14_days,
   AVG(visit_length) OVER (
            PARTITION BY visitor_username
            ORDER BY visit_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        ) AS employee_avg_daily_14d,
        COUNT(store_id) OVER (
            PARTITION BY visitor_username
            ORDER BY visit_date
            RANGE BETWEEN INTERVAL '13 days' PRECEDING AND CURRENT ROW
        ) AS employee_stores_14d,
  COUNT(visit_date) OVER (PARTITION BY visitor_username ORDER BY visit_date RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW) as employee_visits_21_days,
     AVG(visit_length) OVER (
            PARTITION BY visitor_username
            ORDER BY visit_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        ) AS employee_avg_daily_21d,
        COUNT(store_id) OVER (
            PARTITION BY visitor_username
            ORDER BY visit_date
            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
        ) AS employee_stores_21d,
        -- Calculate the percentage change in unique stores visited (7 days vs 21 days)
        CASE
            WHEN COUNT(store_id) OVER (
                PARTITION BY visitor_username
                ORDER BY visit_date
                RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
            ) = 0 THEN NULL -- Avoid division by zero
            ELSE
                (
                    (
                        COUNT(store_id) OVER (
                            PARTITION BY visitor_username
                            ORDER BY visit_date
                            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
                        ) -
                        COUNT(store_id) OVER (
                            PARTITION BY visitor_username
                            ORDER BY visit_date
                            RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
                        )
                    )::NUMERIC /
                    COUNT(store_id) OVER (
                        PARTITION BY visitor_username
                        ORDER BY visit_date
                        RANGE BETWEEN INTERVAL '20 days' PRECEDING AND CURRENT ROW
                    )
                ) * 100
        END AS stores_visited_7_vs_21_day_trend_pct
  FROM visit_data
),
-- Weekly statistics for variance calculations
weekly_stats AS (
    SELECT
        -- Week 1 (most recent 7 days)
        SUM(in_week_1) AS week_1_total_visits,
        COUNT(DISTINCT CASE WHEN in_week_1 = 1 THEN store_id END) AS week_1_unique_stores,
        ROUND(SUM(in_week_1)::numeric / 7, 2) AS week_1_avg_daily_visits,

        -- Week 2 (days 8-14)
        SUM(in_week_2) AS week_2_total_visits,
        COUNT(DISTINCT CASE WHEN in_week_2 = 1 THEN store_id END) AS week_2_unique_stores,
        ROUND(SUM(in_week_2)::numeric / 7, 2) AS week_2_avg_daily_visits,

        -- Week 3 (days 15-21)
        SUM(in_week_3) AS week_3_total_visits,
        COUNT(DISTINCT CASE WHEN in_week_3 = 1 THEN store_id END) AS week_3_unique_stores,
        ROUND(SUM(in_week_3)::numeric / 7, 2) AS week_3_avg_daily_visits

    FROM visit_data
),
-- Store visit counts by week for median calculations
store_visit_counts_by_week AS (
    SELECT
        store_id,
        SUM(in_week_1) AS week_1_visits,
        SUM(in_week_2) AS week_2_visits,
        SUM(in_week_3) AS week_3_visits
    FROM visit_data
    GROUP BY store_id
),
-- Median calculations by week
weekly_medians AS (
    SELECT
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY week_1_visits) AS week_1_median_visits_per_store,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY week_2_visits) AS week_2_median_visits_per_store,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY week_3_visits) AS week_3_median_visits_per_store
    FROM store_visit_counts_by_week
    WHERE week_1_visits > 0 OR week_2_visits > 0 OR week_3_visits > 0
),
-- Calculate summary statistics
summary_stats AS (
    SELECT
        -- Total visits by period
        SUM(in_7_days) AS total_visits_7_days,
        SUM(in_14_days) AS total_visits_14_days,
        SUM(in_21_days) AS total_visits_21_days,

        -- Unique stores by period
        COUNT(DISTINCT CASE WHEN in_7_days = 1 THEN vd.store_id END) AS stores_visited_7_days,
        COUNT(DISTINCT CASE WHEN in_14_days = 1 THEN vd.store_id END) AS stores_visited_14_days,
        COUNT(DISTINCT CASE WHEN in_21_days = 1 THEN vd.store_id END) AS stores_visited_21_days,

        -- Visit averages per day
        ROUND(SUM(in_7_days)::numeric / 7, 2) AS avg_daily_visits_7_days,
        ROUND(SUM(in_14_days)::numeric / 14, 2) AS avg_daily_visits_14_days,
        ROUND(SUM(in_21_days)::numeric / 21, 2) AS avg_daily_visits_21_days,

        -- Visit medians (visits per store)
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY store_visit_counts_7.visit_count
        ) AS median_visits_per_store_7_days,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY store_visit_counts_14.visit_count
        ) AS median_visits_per_store_14_days,
        PERCENTILE_CONT(0.5) WITHIN GROUP (
            ORDER BY store_visit_counts_21.visit_count
        ) AS median_visits_per_store_21_days

    FROM visit_data vd
    LEFT JOIN (
        SELECT store_id, COUNT(*) as visit_count
        FROM visit_data WHERE in_7_days = 1 GROUP BY store_id
    ) store_visit_counts_7 ON vd.store_id = store_visit_counts_7.store_id
    LEFT JOIN (
        SELECT store_id, COUNT(*) as visit_count
        FROM visit_data WHERE in_14_days = 1 GROUP BY store_id
    ) store_visit_counts_14 ON vd.store_id = store_visit_counts_14.store_id
    LEFT JOIN (
        SELECT store_id, COUNT(*) as visit_count
        FROM visit_data WHERE in_21_days = 1 GROUP BY store_id
    ) store_visit_counts_21 ON vd.store_id = store_visit_counts_21.store_id
),
-- Week-over-week variance calculations
variance_stats AS (
    SELECT
        ws.*,
        wm.*,

        -- Week-over-week variance for total visits
        CASE
            WHEN ws.week_2_total_visits > 0 THEN
                ROUND(((ws.week_1_total_visits - ws.week_2_total_visits)::numeric / ws.week_2_total_visits::numeric * 100), 2)
            ELSE NULL
        END AS week_1_vs_week_2_total_visits_variance_pct,

        CASE
            WHEN ws.week_3_total_visits > 0 THEN
                ROUND(((ws.week_2_total_visits - ws.week_3_total_visits)::numeric / ws.week_3_total_visits::numeric * 100), 2)
            ELSE NULL
        END AS week_2_vs_week_3_total_visits_variance_pct,

        -- Week-over-week variance for average daily visits
        CASE
            WHEN ws.week_2_avg_daily_visits > 0 THEN
                ROUND(((ws.week_1_avg_daily_visits - ws.week_2_avg_daily_visits) / ws.week_2_avg_daily_visits * 100)::numeric, 2)
            ELSE NULL
        END AS week_1_vs_week_2_avg_daily_variance_pct,

        CASE
            WHEN ws.week_3_avg_daily_visits > 0 THEN
                ROUND(((ws.week_2_avg_daily_visits - ws.week_3_avg_daily_visits) / ws.week_3_avg_daily_visits * 100)::numeric, 2)
            ELSE NULL
        END AS week_2_vs_week_3_avg_daily_variance_pct,

        -- Week-over-week variance for median visits per store
        CASE
            WHEN wm.week_2_median_visits_per_store > 0 THEN
                ROUND(((wm.week_1_median_visits_per_store - wm.week_2_median_visits_per_store) / wm.week_2_median_visits_per_store * 100)::numeric, 2)
            ELSE NULL
        END AS week_1_vs_week_2_median_variance_pct,

        CASE
            WHEN wm.week_3_median_visits_per_store > 0 THEN
                ROUND(((wm.week_2_median_visits_per_store - wm.week_3_median_visits_per_store) / wm.week_3_median_visits_per_store * 100)::numeric, 2)
            ELSE NULL
        END AS week_2_vs_week_3_median_variance_pct,

        -- Week-over-week variance for unique stores
        CASE
            WHEN ws.week_2_unique_stores > 0 THEN
                ROUND(((ws.week_1_unique_stores - ws.week_2_unique_stores)::numeric / ws.week_2_unique_stores::numeric * 100), 2)
            ELSE NULL
        END AS week_1_vs_week_2_unique_stores_variance_pct,

        CASE
            WHEN ws.week_3_unique_stores > 0 THEN
                ROUND(((ws.week_2_unique_stores - ws.week_3_unique_stores)::numeric / ws.week_3_unique_stores::numeric * 100), 2)
            ELSE NULL
        END AS week_2_vs_week_3_unique_stores_variance_pct

    FROM weekly_stats ws
    CROSS JOIN weekly_medians wm
)
-- Final result set
SELECT
    vd.*,
    ss.total_visits_7_days,
    ss.total_visits_14_days,
    ss.total_visits_21_days,
    ss.stores_visited_7_days,
    ss.stores_visited_14_days,
    ss.stores_visited_21_days,
    ss.avg_daily_visits_7_days,
    ss.avg_daily_visits_14_days,
    ss.avg_daily_visits_21_days,
    ss.median_visits_per_store_7_days,
    ss.median_visits_per_store_14_days,
    ss.median_visits_per_store_21_days,
    vd.employee_visits_7_days,
    vd.employee_avg_daily_7d,
    vd.employee_stores_7d,
    vd.employee_visits_14_days,
    vd.employee_avg_daily_14d,
    vd.employee_stores_14d,
    vd.employee_visits_21_days,
    vd.employee_avg_daily_21d,
    vd.employee_stores_21d,
    -- Weekly breakdown
    vs.week_1_total_visits,
    vs.week_2_total_visits,
    vs.week_3_total_visits,
    vs.week_1_unique_stores,
    vs.week_2_unique_stores,
    vs.week_3_unique_stores,
    vs.week_1_avg_daily_visits,
    vs.week_2_avg_daily_visits,
    vs.week_3_avg_daily_visits,
    vs.week_1_median_visits_per_store,
    vs.week_2_median_visits_per_store,
    vs.week_3_median_visits_per_store,

    -- Week-over-week variance percentages
    vs.week_1_vs_week_2_total_visits_variance_pct,
    vs.week_2_vs_week_3_total_visits_variance_pct,
    vs.week_1_vs_week_2_avg_daily_variance_pct,
    vs.week_2_vs_week_3_avg_daily_variance_pct,
    vs.week_1_vs_week_2_median_variance_pct,
    vs.week_2_vs_week_3_median_variance_pct,
    vs.week_1_vs_week_2_unique_stores_variance_pct,
    vs.week_2_vs_week_3_unique_stores_variance_pct,
    --- ranking
    -- Employee performance ranking (by 7-day visits)
    RANK() OVER (ORDER BY employee_visits_7_days DESC) AS employee_7day_visits_rank,
    RANK() OVER (ORDER BY employee_visits_14_days DESC) AS employee_14day_visits_rank,
    RANK() OVER (ORDER BY employee_visits_21_days DESC) AS employee_21day_visits_rank,
    vd.stores_visited_7_vs_21_day_trend_pct
FROM employee_trends vd
CROSS JOIN summary_stats ss
CROSS JOIN variance_stats vs
ORDER BY vd.visit_timestamp ASC;
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
        # tools=tools,
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
    prompt = textwrap.dedent("""
Analyze store visit performance using the pre-calculated metrics across three time horizons: 7 days (1 week), 14 days (2 weeks), and 21 days (3 weeks).
Provide insights on trends, performance, and actionable recommendations.

do a detailed report including:
1. **Executive Summary:**
Use the pre-calculated metrics to summarize the store visit performance:

- Average visit length (avg_daily_visits_7_days) and time spent per store for the past 7 days and average of the past 2 weeks (avg_daily_visits_14_days).
- Total number of visits and stores visited in the past 7 days (total_visits_7_days, stores_visited_7_days).
- Percent of unique store visits to total visits (stores_visited_7_vs_21_day_trend_pct).
- average and total duration per Rep for the past 7 days (employee_avg_daily_7d, employee_visits_7_days).
- Average duration of visits (average of visit_length)
- Median duration of the visits (median_visits_per_store_7_days).
- Compare the average visit length to the past 2 weeks (avg_daily_visits_14_days).
- How average and median duration of visits compares to the past 2 weeks weekly averages.

2. **Visit Content Analysis**
Use the calculated metrics to analyze visit content:

Extract and analyze the four key questions (column_names: '9730', '9731', '9732', '9733'):
- Question 9730 (Key Wins): Summarize positive outcomes and successes
- Question 9731 (Challenges/Opportunities): Identify recurring issues and improvement areas
- Question 9732 (Next Visit Focus): Analyze follow-up priorities and action items
- Question 9733 (Competitive Landscape): Evaluate market positioning and visibility concerns
for each of 4 questions for the past 7 days always return the following:
    - **Top Phrases:** Meaningful Phrase Extraction, use n-gram analysis to extract key phrases from responses that appear frequently
    - **Themes:** Identify business-relevant terms like product names, competitor names, specific issues, store features, customer behaviors
    - **Theme clustering**: Group similar concepts together (e.g., "low foot traffic" + "fewer customers" = "Customer Volume Issues")
    - **Sentiment:** Perform sentiment analysis (positive/negative/neutral classification) (e.g 327 positive, 54 negative, 367 neutral)
    - **Sentiment Trend comparison:** Compare sentiment patterns to 14-day and 21-day periods if data available
    - **Sample Comments:** Put a sample comment for each question, with a positive, negative, and neutral comment
    - **Insights:** Identify actionable insights

3. **Employee Performance Deep Dive**
Use the calculated metrics to analyze employee performance:

- Top Performers: Use employee_7day_visits_rank to identify leaders and high performers with employee_21day_visits_rank.
- Reps with most visits and least visits.
- Productivity Analysis: Compare employee_avg_daily_7d across reps
- Store Coverage: Analyze employee_stores_7d for territory management effectiveness
- Trend Identification: Use variance columns to identify improving/declining performance.
- Identify reps with significant changes in stores visited (stores_visited_7_vs_21_day_trend_pct)

4. **Store Performance Analysis**
Use the calculated metrics to analyze store performance:

- High-Traffic Stores: Group by store_id and sum visits across periods
- Coverage Gaps: Identify stores with declining visit frequency
- Time Investment: Analyze time_spent_minutes by store to identify efficiency patterns

5. **Trend Analysis & Patterns**
Use the calculated metrics to identify trends and patterns:

- Growth/Decline Patterns: Interpret percentage changes in variance columns
- Seasonal/Weekly Patterns: Analyze week_1_total_visits vs week_2_total_visits vs week_3_total_visits
- Efficiency Trends: Compare time spent vs visits completed ratios
- Outlier Detection: Identify unusual patterns in rankings and variance metrics

6. **Actionable Recommendations**
Use the insights to provide actionable recommendations:

- Performance Optimization: Target stores and reps with declining variance percentages
- Resource Allocation: Recommendations based on visit frequency and efficiency data
- Training Needs: Identify reps with concerning ranking trends
- Store Prioritization: Focus areas based on visit patterns and sentiment analysis
- Variance Interpretation: Positive variance = improvement, negative = decline
- Ranking Context: Lower rank numbers = better performance (1 = best)
- Efficiency Focus: Balance visit quantity with quality (time spent and outcomes)

7. **Exporting and Reporting**

Export the analysis as a PDF report using the pdf_print_tool and as a podcast.
""")
    answer, response = asyncio.run(
        agent.invoke(prompt)
    )
    print(response.output)
