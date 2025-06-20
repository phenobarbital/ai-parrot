from datetime import datetime
import textwrap
from aiohttp import web
from datamodel import BaseModel, Field
from parrot.handlers.abstract import AbstractAgentHandler
from parrot.tools.weather import OpenWeather
from parrot.tools import PythonREPLTool
from .tools import StoreInfo


class NextStopResponse(BaseModel):
    """
    NextStopResponse is a model that defines the structure of the response
    for the NextStop agent.
    """
    # session_id: str = Field(..., description="Unique identifier for the session")
    data: str = Field(..., description="Data returned by the agent")
    status: str = Field(default="success", description="Status of the response")
    output: str = Field(required=False)
    store_id: str = Field(required=False, description="ID of the store associated with the session")
    created_at: datetime = Field(default=datetime.now())
    podcast_path: str = Field(required=False, description="Path to the podcast associated with the session")
    pdf_path: str = Field(required=False, description="Path to the PDF associated with the session")


class NextStopAgent(AbstractAgentHandler):
    """
    NextStopAgent is an abstract agent handler that extends the AbstractAgentHandler.
    It provides a framework for implementing specific agent functionalities.
    """
    agent_name = "NextStopAgent"
    additional_routes: dict = [
        {
            "method": "GET",
            "path": "/api/v1/agents/nextstop/results/{sid}",
            "handler": "get_results"
        },
        {
            "method": "GET",
            "path": "/api/v1/agents/nextstop/status",
            "handler": "get_agent_status"
        }
    ]

    def __init__(self, *args, **kwargs):
        self.agent_name = "NextStopAgent"
        self.base_route: str = '/api/v1/agents/nextstop'
        super().__init__(*args, **kwargs)


    async def _nextstop_agent(self) -> None:
        tools = [
            OpenWeather(request='weather'),
            PythonREPLTool(),
        ] + StoreInfo().get_tools()
        backstory = """
Users can find store information, such as store hours, locations, and services.
The agent can also provide weather updates and perform basic Python code execution.
It is designed to assist users in planning their visits to stores by providing relevant information.
The agent can answer questions about store locations, hours of operation, and available services.
It can also provide weather updates for the store's location, helping users plan their visits accordingly.
The agent can execute Python code snippets to perform calculations or data processing tasks.
        """
        self.app['nextstop_agent'] = await self.create_agent(
            tools=tools,
            backstory=backstory,
        )
        print(
            f"Agent {self._agent}:{self.agent_name} initialized with tools: {', '.join(tool.name for tool in tools)}"
        )

    async def on_startup(self, app: web.Application) -> None:
        """Start the application."""
        self._agent = await self._nextstop_agent()

    async def on_shutdown(self, app: web.Application) -> None:
        """Stop the application."""
        self._agent = None

    async def get_results(self, request: web.Request) -> web.Response:
        """Return the results of the agent."""
        sid = request.match_info.get('sid', None)
        if not sid:
            return web.json_response({"error": "Session ID is required"}, status=400)
        # Placeholder for actual results retrieval logic
        results = {"session_id": sid, "data": "Sample results data"}
        return web.json_response(results)

    async def get_agent_status(self, request: web.Request) -> web.Response:
        """Return the status of the agent."""
        # Placeholder for actual status retrieval logic
        status = {"agent_name": self.agent_name, "status": "running"}
        return web.json_response(status)

    async def get(self) -> web.Response:
        """Handle GET requests."""
        return web.json_response({"message": "NextStopAgent is running"})

    async def post(self) -> web.Response:
        """Handle POST requests."""
        data = await self.request.json()
        # Get Store ID if Provided:
        store_id = data.get('store_id', None)
        if not store_id:
            return web.json_response(
                {"error": "Store ID is required"}, status=400
            )
        response = await self._nextstop_report(store_id)
        # Placeholder for actual processing logic
        if not response:
            return web.json_response({"error": "No data found"}, status=404)
        # Return the response data
        return self.json_response(
            response,
            status=200,
        )

    async def _nextstop_report(self, store_id: str) -> NextStopResponse:
        """Generate a report for the NextStop agent."""
        agent = self.request.app['nextstop_agent']
        if not agent:
            raise web.HTTPInternalServerError(
                reason="NextStop agent is not initialized"
            )
        # Create the list of prompts sections:
        sections = []
        executive = f"""
Store ID: {store_id}
Using dataframe returned by get_visit_info, Generate a detailed, comprehensive store visit performance report using the pre-calculated metrics provided in the DataFrame.

Analyze store visit performance across three time horizons: 7 days (1 week), 14 days (2 weeks), and 21 days (3 weeks).

## 1. Executive Summary
- **Average Visit Length (7 Days):** avg_daily_visits_7_days
- **Average Visit Length Comparison (14 Days):** avg_daily_visits_14_days
- **Average Visit Length Comparison (21 Days):** avg_daily_visits_21_days
- **Variance in Average Visit Length (7 Days vs 14 Days):** compare avg_daily_visits_7_days vs avg_daily_visits_14_days
- **Total Visits (7 Days):** total_visits_7_days
- **Total Visits (14 Days):** total_visits_14_days
- **Variance in Average Visit Length (7 Days vs 14 Days):** compare avg_daily_visits_14_days vs avg_daily_visits_21_days
- **Total Unique Stores Visited (7 Days):** stores_visited_7_days
- **Average Duration of Visits:** average visit_length
- **Median Duration of Visits (7 Days):** median_visits_per_store_7_days
- **Median Duration Comparison (14 Days):** median_visits_per_store_14_days

## 2. Basic Store Information
- **Store ID:** store_id
- **Store Name:** store_name
- **Store Address:** store_address
- **Current Weather:** Uses `openweather_tool` to get current weather information for the store's location.
- **Foot Traffic:** Use `get_foot_traffic` to get foot traffic data for the store.

## 3. **Summary of Insights:**
- **Key Findings:** Summarize the most impactful insights from the analysis.
- **Critical Challenges:** Highlight major issues identified in the visits.
- **Opportunities for Improvement:** Areas where performance can be enhanced.
- **Next Steps:** Outline immediate actions based on findings.
- **Recommended actions:** Provide specific recommendations for improving store visit performance.

IMPORTANT INSTRUCTIONS:
- Strictly follow this markdown format without exception.
- Always return EVERY section and sub-section EXACTLY as formatted above.
- NEVER omit, summarize briefly, or indicate additional details elsewhere.
- NEVER reference external tables or bullet lists or say "see table below." Always provide tables or lists explicitly inline.
- Use the provided DataFrame metrics directly in your analysis.
- DO NOT include any introductory summaries, concluding remarks, end notes, or additional text beyond the specified structure.
- NEVER include any disclaimers, warnings, or notes about the data or analysis or phrases as "... from the provided DataFrame".
        """
        _, response, result = await agent.invoke(executive)
        print('RESPONSE > ', response)
        print('RESULT > ', result)
        sections.append(response.output.strip())
#         # Generate Visit context per-question:
#         questions = {
#             "9730": "Key Wins",
#             "9731": "Challenges/Opportunities",
#             "9732": "Next Visit Focus",
#             "9733": "Competitive Landscape"
#         }
#         visit_content =  []
#         for column_name, question_title in questions.items():
#             col = f"q_{column_name}_data"
#             q = f"""
# You are given column called `{col}`.  Each cell is a plain string containing the answer text you must analyze.
# You must analyze the content of this column and provide a detailed, structured analysis for each question. Follow the exact format below without exception.

# ### Question {column_name}: {question_title}
# - **Top Phrases:**
#     - Meaningful Phrase Extraction, extract key phrases from responses that appear frequently.
# - **Themes:**
#     - Identify business-relevant terms like product names, competitor names, specific issues, store features, customer behaviors
# - **Sentiment Counts:**
#   - Positive: X, Negative: Y, Neutral: Z
# - **Sentiment Trend Comparison:**
#   - 14 Days: Positive X, Negative Y, Neutral Z
#   - 21 Days: Positive X, Negative Y, Neutral Z
# - **Sample Comments:** (add the store_id where the comment was found)
#   - Positive: Select a distinct comment clearly reflecting positive sentiment.
#   - Negative: Select a distinct comment clearly reflecting negative sentiment.
#   - Neutral: Select a distinct comment clearly reflecting neutral sentiment.
# - **Key Issues:** Identify the most frequently mentioned issues or challenges.
# - **Insights:** Identify actionable insights: data-driven findings that provide a clear understanding of the visit content and can inform business decisions.
#   - Actionable Insight 1
#   - Actionable Insight 2

# **Do NOT** aggregate multiple questions together. **Do NOT** summarize across questions. **Do NOT** omit any of the seven bullets above.

# IMPORTANT INSTRUCTIONS:
# - Always return EVERY section and sub-section EXACTLY as formatted above.
# - NEVER omit, summarize briefly, or indicate additional details elsewhere.
# - Use the provided DataFrame metrics directly in your analysis.
# - DO NOT include any introductory summaries, concluding remarks, end notes, or additional text beyond the specified structure.
# - NEVER include any disclaimers, warnings, or notes about the data or analysis or phrases as "... from the provided DataFrame".
#             """
#             _, response = await self._agent.invoke(q)
#             print('RESPONSE > ', response)
#             visit_content.append(response.output.strip())
#         # Join the visit content into a single string
#         ct = "\n\n".join(visit_content)
#         content = f"""## 2. Visit Content Analysis (7 Days)
#         {ct}
#         """
#         print('content > ')
#         print(content)
#         sections.append(content)
        # Insights:
        # Join all sections into a single report
        report = "\n\n".join(sections)
        # Create the response object
        response_data = NextStopResponse(
            data=report,
            status="success",
            created_at=datetime.now(),
            store_id=store_id,
            output=report
        )
        return response_data
