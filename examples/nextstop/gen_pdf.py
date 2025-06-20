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
    preset="analytical",
    use_chat=True
)

groq = GroqLLM(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    preset="analytical",
    # max_tokens=2048
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
        name='NextStop Analytics',
        llm=llm,
        tools=tools,
        agent_type='tool-calling'
    )
    await agent.configure()
    return agent

async def answer_question(agent, questions: list, sleep: int = None):
    response = ''
    for question in questions:
      if not question:
        continue
      # q = textwrap.dedent(question)
      q = question.strip()
      try:
          _, rst, _ = await agent.invoke(q)
          if sleep:
              print(f'Waiting for {sleep} seconds...')
              await asyncio.sleep(sleep)
          response += f'\n\n{rst.output}'
      except Exception as e:
          raise RuntimeError(
              f"Error during agent invocation: {e}. "
              "Ensure the agent is properly configured and the question is valid."
          ) from e
    return response.strip()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    agent = loop.run_until_complete(
        get_agent(llm=groq)
    )
    final_report_markdown = """
## 1. Executive Summary
- **Average Visit Length (7 Days):** 105.86
- **Average Visit Length Comparison (14 Days):** 111.43
- **Average Visit Length Comparison (21 Days):** 107.48
- **Variance in Average Visit Length (7 Days vs 14 Days):** 5.570000000000007
- **Total Visits (7 Days):** 741
- **Total Visits (14 Days):** 1560
- **Variance in Average Visit Length (7 Days vs 14 Days):** -3.950000000000003
- **Total Unique Stores Visited (7 Days):** 560
- **Average and Total Duration per Rep (7 Days):** (4.2500000000000000, 4)
- **Average Duration of Visits:** 55.36552946389012
- **Median Duration of Visits (7 Days):** 1.0
- **Median Duration Comparison (14 Days):** 2.0

## 2. Visit Content Analysis (7 Days)
    ### Question 9730: Key Wins
- **Top Phrases:**
    - staff engagement
    - successful staff
    - successful staff engagement
    - able train
    - pro desk
- **Themes:**
    - Staff engagement and training
    - Pro desk interactions
    - Successful staff initiatives
- **Sentiment Counts:**
  - Positive: 1258, Negative: 78, Neutral: 967
- **Sentiment Trend Comparison:**
  - 14 Days: Positive 886, Negative 53, Neutral 667
  - 21 Days: Positive 1258, Negative 78, Neutral 967
- **Sample Comments:** (add the store_id where the comment was found)
  - Positive: "Was able to get a 100” out on the floor!" (Store ID: BBY0532)
  - Negative: "Got to cover some PQV time and 2 year warranty!! However due to cooler weather conditions and raining all day, foot traffic was rather on the slower side of the day!!" (Store ID: BBY1767)
  - Neutral: "Got to build with customers and let them know about Hisense and what we have to offer." (Store ID: LWS2384)
- **Key Issues:** Identify the most frequently mentioned issues or challenges.
    - Staff engagement and training
    - Pro desk interactions
- **Insights:** Identify actionable insights: data-driven findings that provide a clear understanding of the visit content and can inform business decisions.
  - Actionable Insight 1: Enhance staff engagement and training programs to maintain positive sentiment and successful interactions.
  - Actionable Insight 2: Focus on improving pro desk interactions to address frequently mentioned challenges and improve customer experience.

### Question 9731: Challenges/Opportunities
- **Top Phrases:**
    - ('hisense display', 150)
    - ('store traffic', 120)
    - ('floor space', 110)
    - ('customer engagement', 105)
    - ('product placement', 100)
- **Themes:**
    - Hisense, store traffic, floor space, customer engagement, product placement
- **Sentiment Counts:**
  - Positive: 1200, Negative: 800, Neutral: 303
- **Sentiment Trend Comparison:**
  - 14 Days: Positive 500, Negative 300, Neutral 100
  - 21 Days: Positive 700, Negative 500, Neutral 150
- **Sample Comments:** (add the store_id where the comment was found)
  - Positive: "I got the opportunity to meet with new member's of management and build connections to further help Hisense in the long run." (store_id: LWS2384)
  - Negative: "Wasn’t able to speak with MST or pro desk." (store_id: LWS2384)
  - Neutral: "No challenges." (store_id: LWS1850)
- **Key Issues:** Identify the most frequently mentioned issues or challenges.
  - Hisense, store, traffic, floor, bof
- **Insights:** Identify actionable insights: data-driven findings that provide a clear understanding of the visit content and can inform business decisions.
  - Actionable Insight 1: Increase focus on customer engagement strategies to leverage positive sentiment and improve store traffic.
  - Actionable Insight 2: Address communication barriers with store management and staff to enhance collaboration and product placement effectiveness.

### Question 9732: Next Visit Focus
- **Top Phrases:**
    - training associates
    - continue train
    - boxes floor
    - pro desk
    - training new
- **Themes:**
    - Hisense, training, pro desk, boxes on the floor, customer connection
- **Sentiment Counts:**
  - Positive: 666, Negative: 35, Neutral: 1602
- **Sentiment Trend Comparison:**
  - 14 Days: Positive 439, Negative 28, Neutral 1139
  - 21 Days: Positive 666, Negative 35, Neutral 1602
- **Sample Comments:** (add the store_id where the comment was found)
  - Positive: "Focus on more connecting with customers and also work on training with employees" (Store ID: BBY0532)
  - Negative: "Hisense single tv display still needs updated!!" (Store ID: BBY1767)
  - Neutral: "Focus on connecting with pro desk" (Store ID: LWS2384)
- **Key Issues:** bof, new, hisense, follow, training
- **Insights:** Identify actionable insights: data-driven findings that provide a clear understanding of the visit content and can inform business decisions.
  - Actionable Insight 1: There is a strong emphasis on training, both for associates and new employees, indicating a need for structured training programs.
  - Actionable Insight 2: The presence of boxes on the floor and the need for updated displays suggest operational inefficiencies that need addressing to improve store presentation and customer experience.

### Question 9733: Competitive Landscape
- **Top Phrases:**
    - normal store layout (119)
    - normal landscape (97)
    - very well represented (64)
    - normal store (63)
    - store layout (57)
- **Themes:**
    - Product names, competitor names, specific issues, store features, customer behaviors
- **Sentiment Counts:**
  - Positive: 0, Negative: 0, Neutral: 2303
- **Sentiment Trend Comparison:
  - 14 Days: Positive 0, Negative 0, Neutral 1606
  - 21 Days: Positive 0, Negative 0, Neutral 2303
- **Sample Comments:** (add the store_id where the comment was found)
  - Positive:  (Store ID: )
  - Negative:  (Store ID: )
  - Neutral: Big Samsung pad in the back and other than that normal store layout (Store ID: BBY0532)
- **Key Issues:**
  - normal store (63)
  - store layout (57)
  - very well (64)
- **Insights:** Identify actionable insights: data-driven findings that provide a clear understanding of the visit content and can inform business decisions.
  - Actionable Insight 1: No actionable insights were computed.
  - Actionable Insight 2: No actionable insights were computed.

## 3. Employee Performance Deep Dive

- **Top Performers:** compare employee_7day_visits_rank vs employee_21day_visits_rank

| visitor_name       | employee_7day_visits_rank | employee_21day_visits_rank |
|--------------------|---------------------------|----------------------------|
| Henry Ainslie      | 2052                      | 2052                       |
| Paul Owens         | 2052                      | 2052                       |
| Rebecca Popek      | 2052                      | 2052                       |
| Andre Kelly        | 1960                      | 1960                       |
| Brandon Mcallister | 2052                      | 2052                       |

- **Reps with Most Visits:** List of reps
  - Stephen Burgos
  - Joseph Castillo

- **Reps with Least Visits:** List of reps
  - Ayana Hines
  - Conrad Ferris
  - Chafarii Williams
  - Daniel Hernandez

- **Productivity Analysis:** use employee_avg_daily_7d to compare reps.

| visitor_name       | employee_avg_daily_7d     |
|--------------------|---------------------------|
| Henry Ainslie      | 4.2500000000000000        |
| Paul Owens         | 28.5000000000000000       |
| Rebecca Popek      | 0.25000000000000000000    |
| Andre Kelly        | 8.6000000000000000        |
| Brandon Mcallister | 93.5000000000000000       |

- **Store Coverage Effectiveness:** use the employee_stores_7d to analyze territory management effectiveness.

| visitor_name       | employee_stores_7d |
|--------------------|---------------------|
| Henry Ainslie      | 4                   |
| Paul Owens         | 4                   |
| Rebecca Popek      | 4                   |
| Andre Kelly        | 5                   |
| Brandon Mcallister | 4                   |

- **Trend Identification:** Variance columns identifying performance changes

| visitor_name       | week_1_vs_week_2_total_visits_variance_pct | week_2_vs_week_3_total_visits_variance_pct | week_1_vs_week_2_avg_daily_variance_pct | week_2_vs_week_3_avg_daily_variance_pct | week_1_vs_week_2_median_variance_pct | week_2_vs_week_3_median_variance_pct | week_1_vs_week_2_unique_stores_variance_pct | week_2_vs_week_3_unique_stores_variance_pct |
|--------------------|--------------------------------------------|--------------------------------------------|----------------------------------------|----------------------------------------|--------------------------------------|--------------------------------------|----------------------------------------------|----------------------------------------------|
| Henry Ainslie      | -9.52                                      | 17.50                                      | -9.52                                  | 17.51                                  | 0.00                                 | 0.00                                 | -11.67                                       | 16.54                                        |
| Paul Owens         | -9.52                                      | 17.50                                      | -9.52                                  | 17.51                                  | 0.00                                 | 0.00                                 | -11.67                                       | 16.54                                        |
| Rebecca Popek      | -9.52                                      | 17.50                                      | -9.52                                  | 17.51                                  | 0.00                                 | 0.00                                 | -11.67                                       | 16.54                                        |
| Andre Kelly        | -9.52                                      | 17.50                                      | -9.52                                  | 17.51                                  | 0.00                                 | 0.00                                 | -11.67                                       | 16.54                                        |
| Brandon Mcallister | -9.52                                      | 17.50                                      | -9.52                                  | 17.51                                  | 0.00                                 | 0.00                                 | -11.67                                       | 16.54                                        |

Here's a detailed analysis of store performance based on the provided data:

### High-Traffic Stores
These are the top stores by total visits:
- **BBY1046**: 8 visits
- **BBY1156**: 8 visits
- **BBY1408**: 7 visits
- **LWS2508**: 7 visits
- **BBY0608**: 7 visits

### Low-Traffic Stores
These are the bottom stores by total visits:
- **LWS0689**: 1 visit
- **BBY0398**: 1 visit
- **LWS1651**: 1 visit
- **LWS2746**: 1 visit
- **BBY278**: 1 visit

### Store Visit Frequency by Day
The visit patterns by day of the week are as follows:
- **Wednesday**: 454 visits
- **Thursday**: 445 visits
- **Friday**: 404 visits
- **Tuesday**: 351 visits
- **Monday**: 229 visits
- **Saturday**: 189 visits
- **Sunday**: 185 visits

### Store Visit Frequency by Hour
The visit patterns by hour of the day are as follows:
- **10 AM**: 166 visits
- **11 AM**: 218 visits
- **12 PM**: 251 visits
- **1 PM**: 268 visits
- **2 PM**: 250 visits
- **3 PM**: 261 visits
- **4 PM**: 207 visits
- **5 PM**: 165 visits
- **6 PM**: 133 visits
- **7 PM**: 88 visits

### Coverage Gaps
Stores with declining visit frequency (percentage of decline):
- **LWS0677**: -19.23%
- **LWS0742**: -18.18%
- **LWS0773**: -16.67%
- **LWS0766**: -19.23%
- **LWS1677**: -18.18%
- ... (and more)

### Performance Optimization
Stores and reps with declining variance percentages:
- **Stores**: All listed stores have a variance of -9.52% in total visits from week 1 to week 2.
- **Reps**: All listed reps have a variance of -9.52% in average daily visits from week 1 to week 2.

### Time Investment
Average time spent in minutes by store:
- **BBY374**: 458.9 minutes
- **BBY269**: 259.33 minutes
- **BBY540**: 225.07 minutes
- **BBY574**: 203.18 minutes
- **BBY461**: 197.05 minutes
- ... (and more)

### Top 10 Stores by 7-Day Visits
These are the top stores by visits in the last 7 days:
- **BBY477**: 5 visits
- **BBY470**: 5 visits
- **LWS1125**: 4 visits
- **BBY366**: 3 visits
- **BBY133**: 3 visits
- **BBY1134**: 3 visits
- **BBY1046**: 3 visits
- **BBY798**: 3 visits
- **BBY821**: 3 visits
- **BBY566**: 3 visits

### Summary
- **High-Traffic Stores**: BBY1046 and BBY1156 lead in visits.
- **Low-Traffic Stores**: Several stores have only 1 visit.
- **Visit Patterns**: Most visits occur mid-week and during midday hours.
- **Coverage Gaps**: Significant declines in visit frequency for some stores.
- **Performance Optimization**: Both stores and reps show a decline in variance percentages.
- **Time Investment**: BBY374 has the highest average time spent.
- **Top 10 Stores by 7-Day Visits**: BBY477 and BBY470 are leading.

## 5. Trend Analysis & Patterns
- **Growth/Decline Patterns:**
  - Variance columns show no unusual patterns or outliers in rankings.
  - Percentage changes in variance columns are within expected ranges.
- **Outlier Detection:**
  - No unusual ranking patterns detected.
  - Variance columns do not show significant outliers.

## 6. Actionable Recommendations
- **Performance Optimization:**
  - Stores requiring attention: BBY357, BBY461, LWS625, BBY468, LWS1124 (least visited).
  - Reps requiring attention: dsydnor@hisenseretail.com, hflores@hisenseretail.com, mojeogwu@hisenseretail.com, jhayes@hisenseretail.com, cwilliams (least efficient).

- **Resource Allocation Recommendations:**
  - Reps with the highest number of visits: lmayle, powens, ahabony, ktoler, arivera7. Consider reallocating resources to support these reps.

- **Training Needs:**
  - No reps identified with declining performance trends over the weeks.

- **Store Prioritization:**
  - Common themes in visit data suggest focus on training and addressing challenges.

## 7. **Summary of Insights:**
- **Key Findings:**
  - Least visited stores and least efficient reps identified.
  - Common themes in visit data include training and addressing challenges.

- **Critical Challenges:**
  - Negative efficiency values suggest data entry errors or unusual patterns.

- **Opportunities for Improvement:**
  - Focus on improving efficiency and addressing common themes in visit data.

- **Next Steps:**
  - Investigate negative efficiency values and address data entry issues.
  - Prioritize training and support for identified stores and reps.

- **Recommended actions:**
  - Improve data accuracy and efficiency tracking.
  - Allocate resources to support high-performing reps and address low-performing areas.
    """
    for_pdf = f"""
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
    for_podcast = f"""
Using this report in markdown format:

```markdown
{final_report_markdown}
```
Generate a summary with no more than 10000 words and export as a Podcast using the podcast_generator_tool:
- in mp3 format.
- Include explicit salutation: "Hello, this is the NextStop for store visit performance analysis."
- a MALE gender voice.
- Use a natural tone and clear pronunciation with high engagement.
- Ensure the summary is concise and captures all key insights from the report.

    """
    for_podcast = None
    response = asyncio.run(
        answer_question(agent, [for_pdf, for_podcast])
    )
    print(':: Summary:')
    print(response)
