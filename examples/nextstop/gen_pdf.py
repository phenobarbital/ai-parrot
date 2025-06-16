import textwrap
import asyncio
# LLMs
from parrot.llms.vertex import VertexLLM
from parrot.llms.groq import GroqLLM
from parrot.llms.anthropic import AnthropicLLM
from parrot.llms.openai import OpenAILLM
# Tools:
from parrot.tools import PythonREPLTool
# Parrot Agent
from parrot.bots.agent import BasicAgent

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

async def get_agent(llm):
    """Create and configure a NextStop Copilot agent with store analysis tools.

    Args:
        llm: The language model instance to use for the agent.

    Returns:
        BasicAgent: Configured agent ready for store and demographic analysis.
    """

    tools = []
    tools.append(PythonREPLTool())
    agent = BasicAgent(
        name='NextStop Copilot',
        llm=llm,
        tools=tools,
        agent_type='tool-calling'
    )
    await agent.configure()
    return agent

async def answer_question(agent, question, sleep: int = None):
    q = textwrap.dedent(question)
    try:
        _, response, _ = await agent.invoke(q)
        if sleep:
            print(f'Waiting for {sleep} seconds...')
            await asyncio.sleep(sleep)
        return response.output
    except Exception as e:
        raise RuntimeError(
            f"Error during agent invocation: {e}. "
            "Ensure the agent is properly configured and the question is valid."
        ) from e



if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent(llm=vertex)
    )
    final_report_markdown = """
## 1. Executive Summary
- **Average Visit Length (7 Days):** 103.86
- **Average Visit Length Comparison (14 Days):** 110.43
- **Average Visit Length Comparison (21 Days):** 106.81
- **Variance in Average Visit Length (7 Days vs 14 Days):** 6.570000000000007
- **Total Visits (7 Days):** 727
- **Total Visits (14 Days):** 1546
- **Variance in Average Visit Length (7 Days vs 14 Days):** -3.6200000000000045
- **Total Unique Stores Visited (7 Days):** 559
- **Percent of Unique Store Visits to Total Visits:** 0E-20
- **Average and Total Duration per Rep (7 Days):** (4.2500000000000000, 4)
- **Average and Total Duration per Rep (14 Days):** (4.2500000000000000, 4)
- **Average and Total Duration per Rep (21 Days):** (4.2500000000000000, 4)
- **Average Duration of Visits:** 55.15470352206866
- **Median Duration of Visits (7 Days):** 1.0
- **Median Duration Comparison (14 Days):** 2.0

Agent stopped due to max iterations.

## 3. Employee Performance Deep Dive

- **Top Performers:** compare employee_7day_visits_rank vs employee_21day_visits_rank

  | Visitor Name       | Employee 7-Day Visits Rank | Employee 21-Day Visits Rank |
  |--------------------|----------------------------|-----------------------------|
  | Henry Ainslie      | 2038                       | 2038                        |
  | Paul Owens         | 2038                       | 2038                        |
  | Rebecca Popek      | 2038                       | 2038                        |
  | Andre Kelly        | 1945                       | 1945                        |
  | Brandon Mcallister | 2038                       | 2038                        |
  | ...                | ...                        | ...                         |

- **Reps with Most Visits:** List of reps

  - Stephen Burgos
  - Joseph Castillo

- **Reps with Least Visits:** List of reps

  - Ayana Hines
  - Conrad Ferris
  - Chafarii Williams
  - Daniel Hernandez

- **Productivity Analysis:** use employee_avg_daily_7d to compare reps.

  | Visitor Name       | Employee Avg Daily 7D      |
  |--------------------|----------------------------|
  | Henry Ainslie      | 4.2500000000000000         |
  | Paul Owens         | 28.5000000000000000        |
  | Rebecca Popek      | 0.25000000000000000000     |
  | Andre Kelly        | 8.6000000000000000         |
  | Brandon Mcallister | 93.5000000000000000        |
  | ...                | ...                        |

- **Store Coverage Effectiveness:** use the employee_stores_7d to analyze territory management effectiveness.

  | Visitor Name       | Employee Stores 7D |
  |--------------------|--------------------|
  | Henry Ainslie      | 4                  |
  | Paul Owens         | 4                  |
  | Rebecca Popek      | 4                  |
  | Andre Kelly        | 5                  |
  | Brandon Mcallister | 4                  |
  | ...                | ...                |

- **Trend Identification:** Variance columns identifying performance changes

  | Visitor Name       | Week 1 vs Week 2 Total Visits Variance (%) | Week 2 vs Week 3 Total Visits Variance (%) | Week 1 vs Week 2 Avg Daily Variance (%) | Week 2 vs Week 3 Avg Daily Variance (%) | Week 1 vs Week 2 Median Variance (%) | Week 2 vs Week 3 Median Variance (%) | Week 1 vs Week 2 Unique Stores Variance (%) | Week 2 vs Week 3 Unique Stores Variance (%) |
  |--------------------|--------------------------------------------|--------------------------------------------|----------------------------------------|----------------------------------------|--------------------------------------|--------------------------------------|----------------------------------------------|----------------------------------------------|
  | Henry Ainslie      | -11.23                                     | ...                                        | ...                                    | ...                                    | ...                                  | ...                                  | -11.83                                       | 16.54                                        |
  | Paul Owens         | -11.23                                     | ...                                        | ...                                    | ...                                    | ...                                  | ...                                  | -11.83                                       | 16.54                                        |
  | Rebecca Popek      | -11.23                                     | ...                                        | ...                                    | ...                                    | ...                                  | ...                                  | -11.83                                       | 16.54                                        |
  | ...                | ...                                        | ...                                        | ...                                    | ...                                    | ...                                  | ...                                  | ...                                          | ...                                          |

- **Significant Changes in Stores Visited:** stores_visited_7_vs_21_day_trend_pct

  | Visitor Name       | Stores Visited 7 vs 21 Day Trend (%) |
  |--------------------|--------------------------------------|
  | Henry Ainslie      | 0E-20                                |
  | Paul Owens         | 0E-20                                |
  | Rebecca Popek      | 0E-20                                |
  | Andre Kelly        | 0E-20                                |
  | Brandon Mcallister | 0E-20                                |
  | ...                | ...                                  |

Here's a detailed analysis of store performance based on the provided data:

### 1. High-Traffic Stores
These are the top stores by total visits:
- **BBY1046**
- **BBY1156**
- **BBY1035**
- **BBY0608**
- **BBY1134**
- **BBY1220**
- **LWS1043**
- **LWS2508**
- **BBY1129**
- **BBY1408**

### 2. Coverage Gaps
Stores with declining visit frequency:
- **LWS0677**
- **LWS0742**
- **LWS0773**
- **LWS0766**
- **LWS1677**
- **LWS0488**
- **BBY0493**
- **LWS1630**
- **BBY0515**
- **LWS0785**
- ... (and many more)

### 3. Performance Optimization
Stores and representatives with declining variance percentages (indicating a decline in performance):
- **Stores with Declining Variance:**
  - **BBY0532**
  - **LWS2384**
  - **BBY0436**
  - **LWS1914**
  - **LWS1850**
  - ... (and many more)

- **Representatives with Declining Variance:**
  - **Henry Ainslie**
  - **Paul Owens**
  - **Rebecca Popek**
  - **Andre Kelly**
  - **Brandon Mcallister**
  - ... (and many more)

### 4. Time Investment
Top stores by average time spent (in minutes) per visit, indicating where the most time is invested:
- **BBY374**: 458.9 minutes
- **BBY269**: 259.33 minutes
- **BBY540**: 225.07 minutes
- **BBY574**: 203.18 minutes
- **BBY461**: 197.05 minutes
- **BBY146**: 184.55 minutes
- **COS0394**: 182.02 minutes
- **LWS1602**: 175.15 minutes
- **BBY563**: 171.55 minutes
- **BBY576**: 156.33 minutes

### 5. Top 10 Stores by 7-Day Visits
These are the top stores by visits in the last 7 days:
- **BBY470**
- **BBY477**
- **LWS1125**
- **BBY1046**
- **BBY1129**
- **BBY1134**
- **BBY133**
- **BBY366**
- **BBY417**
- **BBY498**

### Summary
- **High-Traffic Stores**: These stores have the highest number of visits, indicating strong engagement or strategic importance.
- **Coverage Gaps**: A significant number of stores are experiencing a decline in visit frequency, which may require strategic intervention.
- **Performance Optimization**: Both stores and representatives show areas of declining performance, suggesting a need for targeted improvements.
- **Time Investment**: Certain stores see significantly higher time investments, which could indicate complex operations or high engagement levels.
- **Top 10 Stores by 7-Day Visits**: These stores are currently receiving the most attention, possibly due to recent campaigns or strategic focus.

This analysis can help in making informed decisions about resource allocation, strategic focus, and performance improvement initiatives.

## 5. Trend Analysis & Patterns

- **Growth/Decline Patterns:**
  - The variance columns show consistent values across the dataset, with no variation in the percentage changes. The mean values for the variance columns are:
    - `week_1_vs_week_2_total_visits_variance_pct`: -11.23%
    - `week_2_vs_week_3_total_visits_variance_pct`: 17.5%
    - `week_1_vs_week_2_avg_daily_variance_pct`: -11.23%
    - `week_2_vs_week_3_avg_daily_variance_pct`: 17.51%
    - `week_1_vs_week_2_median_variance_pct`: 0%
    - `week_2_vs_week_3_median_variance_pct`: 0%
    - `week_1_vs_week_2_unique_stores_variance_pct`: -11.83%
    - `week_2_vs_week_3_unique_stores_variance_pct`: 16.54%

- **Efficiency Trends:**
  - The average time spent per visit varies significantly among visitors. The top performers in terms of efficiency (least time spent per visit) are:
    - `jcastillo3@hisenseretail.com`: 105.09 minutes per visit
    - `nsackett@hisenseretail.com`: 96.90 minutes per visit
    - `drandlett@hisenseretail.com`: 95.97 minutes per visit

- **Outlier Detection:**
  - No unusual ranking and variance patterns were detected as outliers in the dataset.

## 6. Actionable Recommendations

- **Performance Optimization:**
  - Focus on improving efficiency for visitors with high average time per visit, such as `dsydnor@hisenseretail.com` and `hflores@hisenseretail.com`, who have negative efficiency values indicating potential data issues or inefficiencies.

- **Resource Allocation Recommendations:**
  - Allocate resources to support visitors with high visit counts but low efficiency to improve their performance.

- **Training Needs:**
  - Identify and provide training for representatives with declining performance trends, especially those with high average time per visit.

- **Store Prioritization:**
  - Prioritize stores with consistent visit declines or those not meeting visit targets, as indicated by the variance patterns.

    """
    for_export = textwrap.dedent(
        f"""
Using this report in markdown format:

```markdown
{final_report_markdown}
```
Export this COMPLETE markdown report using the pdf_print_tool.

IMPORTANT INSTRUCTIONS:
- Always return EVERY section and sub-section EXACTLY as formatted above.
- NEVER omit, summarize briefly, or indicate additional details elsewhere.
- The PDF must contain the ENTIRE content above exactly as generated here.
        """
    )
    print(final_report_markdown)
    response = asyncio.run(
        answer_question(agent, for_export)
    )
    print('Final Report:')
    print(response)
