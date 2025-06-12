import asyncio
import pandas as pd
from navconfig import BASE_DIR
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
from parrot.llms.openai import OpenAILLM
from parrot.bots.data import PandasAgent


vertex = VertexLLM(
    # model="gemini-2.0-flash",
    model="gemini-1.5-pro",
    preset="analytical",
    use_chat=True
)

vertex_pro = VertexLLM(
    model="gemini-2.5-pro-preview-05-06",
    preset="concise",
    use_chat=True
)

gemma = GroqLLM(
    model="gemma2-9b-it",
    preset="concise",
    max_tokens=1024
)

groq = GroqLLM(
    model="mistral-saba-24b",
    preset="analytical",
    max_tokens=2048,
    use_chat=True
)

openai = OpenAILLM(
    model="gpt-4.1",
    temperature=0.1,
    preset="concise",
    max_tokens=2048,
    use_chat=True
)

claude = AnthropicLLM(
    model="claude-3-5-sonnet-20240620",
    temperature=0,
    use_tools=True
)

backstory = """
You have a pandas DataFrame with financial projections, it is the projected revenue by projectfor the end of the month, with slight variations day after day. every day is only corrections over the projected revenue at end of month.
columns:
- description (str): business division
- project (str): project name
- revenue (float): projected revenue at end of month
- budget (float): budgeted revenue at end of month
- percent_to_budget (float): percentage of revenue compared to budget
- ebitda (float):  earnings before interest, taxes, depreciation, and amortization
- budget_ebitda (float): budgeted ebitda
- margin (float): profit margin
- budget_margin (float): percentage to budget
- budgeted_margin (float): budgeted profit margin (percentage)
- projection_date (date): date of the projection

IMPORTANT:
- The data is not cumulative, every day it is the projected revenue at end of month, only work with the last projected revenue for each project.
"""

async def get_agent(llm):
    data = await PandasAgent.gen_data(agent_name='RevenueAgent', query="troc_revenue_projections")
    agent = PandasAgent(
        name='RevenueAgent',
        llm=llm,
        df=data,
        backstory=backstory
    )
    await agent.configure()
    return agent


if __name__ == '__main__':
    agent = asyncio.run(get_agent(openai))
    prompt = f"""
    Generate a business-style narrative for CEO and CFO of the company based on the Revenue projections provided in the Pandas DataFrame, considering the above description.
    Use the last projected revenue for each project, not cumulative data.
    Ensure the narrative is directly relevant to business decision-making, oriented for CEO and CFO of the company.

    The narrative should include the following sections:

    1.  **Executive Summary:** Provide a brief overview of the key findings and insights derived from the data analysis.
    2. **Detailed Analysis:** Identify the top-5 projects by total reveneue, and provide a detailed analysis of each project, including:
    - Project name
    - Total revenue
    - day-over-day change in total revenue
    - Total cost
    - Profit margin
    - Key insights and recommendations for each project
    - since data is daily, compare performance against budget, highlighting any significant deviations (percent_to_budget) and their implications.
    - EBITDA margin
    - Revenue growth rate compared to previous periods.
    - Any other relevant metrics that can help leadership understand the project's financial health and performance.
    3. **Comparative Analysis:** Compare the performance of the top-5 projects against each other, highlighting strengths and weaknesses.
    4.  **Key Trends:** Identify and describe the most significant trends observed in the data. Provide specific examples and supporting data points, projects with highest EBITDA margins, projects where revenue most closely matches budget (smallest absolute percent_to_budget), 3-day moving average, etc.
    5.  **Outliers:** Highlight any significant outliers or anomalies in the data. Explain their potential impact on the overall analysis.
    6.  **Potential Risks:** Based on the trends and outliers, identify potential risks or challenges that leadership should be aware of.
    7.  **Recommendations:** Provide actionable recommendations for leadership based on the analysis, addressing the identified trends and risks.
    8. **Summarize overall trends:** is revenue running above or below budget on average, and how is profitability trending over the period?
    9. **Conclusion:** Summarize the key takeaways from the analysis and their implications for the business.

    And the end, exports the detailed analysis as a PDF file using pdf_print_tool and generate a summary as a podcast using the podcast_generator_tool
    """
    prompt = """
🧠 Revised Executive Summary Section
Begin with a concise, insights-packed overview that helps leadership quickly grasp the financial pulse of the business. This section should highlight:
Use the last projected revenue for each project, not cumulative data.
Ensure the narrative is directly relevant to business decision-making, oriented for CEO and CFO of the company.

📊 Performance Highlights
Top Revenue and EBITDA Leaders: Name the highest performing projects by total revenue and EBITDA margin.

MTD Trend vs Budget:

Show Month-to-Date (MTD) performance for Revenue and EBITDA, compared to budget.

Highlight % variance and whether the trend is improving or worsening.

Include a sparkline or trendline if visuals are part of the output.

Revenue Contribution by Program:
Show each project’s % contribution to total monthly revenue.
Identify top contributors and underperformers.

Week-over-Week Change:
- Report overall financial change compared to last week.

Include program-level deltas, especially for key initiatives.
Color code or flag major swings (+/-) for fast scanning.

🚦 Quick Signals
Create a Table:

Use simple indicators (✔️, ⚠️, ❌) to flag:
- Above-budget performance
- Margin concerns
- Projects exceeding growth expectations
- Areas needing attention
- Any red flags or risks
- Always return the project names when enumerate them.
- Any significant deviations from budget or expectations
- Any projects with significant day-over-day changes in revenue



IMPORTANT:
- Use the complete version with quick signals table, revenue contribution, and week-over-week changes to export as a PDF file using pdf_print_tool
- Use a concise summary to generate a podcast using the podcast_generator_tool.
"""
    # prompt = """what is the total projected revenue for all projects."""

    answer, response = asyncio.run(
        agent.invoke(prompt)
    )
    print(response.output)
