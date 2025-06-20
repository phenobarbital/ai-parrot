from datetime import datetime
import textwrap
from aiohttp import web
from datamodel import BaseModel, Field
from parrot.llms.vertex import VertexLLM
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
        vertex = VertexLLM(
            model="gemini-2.5-pro",
            preset="analytical",
            use_chat=True
        )
        self.app['nextstop_agent'] = await self.create_agent(
            llm=vertex,
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
- **Average Visit Length (7 Days):** use the avg_daily_visits_7_days
- **Average Visit Length Comparison (14 Days):** use the avg_daily_visits_14_days
- **Average Visit Length Comparison (21 Days):** use the avg_daily_visits_21_days
- **Variance in Average Visit Length (7 Days vs 14 Days):** compare columns avg_daily_visits_7_days vs avg_daily_visits_14_days
- **Total Visits (7 Days):** use the total_visits_7_days
- **Total Visits (14 Days):** use the total_visits_14_days
- **Variance in Average Visit Length (7 Days vs 14 Days):** compare avg_daily_visits_14_days vs avg_daily_visits_21_days
- **Total Unique Stores Visited (7 Days):** use the stores_visited_7_days
- **Average Duration of Visits:** use the average visit_length
- **Median Duration of Visits (7 Days):** use the median_visits_per_store_7_days
- **Median Duration Comparison (14 Days):** use the median_visits_per_store_14_days

## 2. Basic Store Information
- **Store ID:** store_id
- **Store Name:** store_name
- **Store Address:** store_address
- **Current Weather:** Uses `openweather_tool` to get current weather information for the store's location.
- **Foot Traffic:** Use `get_foot_traffic` to get foot traffic data for the store, for every day of the week and average of daily foot traffic.

## 3. Visit Performance Metrics
For every column_name ["9730", "9731", "9732", "9733"] on `visit_data` column, provide the following metrics:
### Question `column_name`
- **Top Phrases:** Extract key phrases from responses that appear frequently.
- **Sentiment Counts:**
    - Positive: X, Negative: Y, Neutral: Z
- **Key Issues:** Identify the most frequently mentioned issues or challenges.

## 4. **Summary of Insights:**
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
        try:
            _, response, _ = await agent.invoke(executive)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        sections.append(response.output.strip())
        # Join all sections into a single report
        final_report = "\n\n".join(sections)
        # Use the joined report to generate a PDF and a Podcast:
        for_pdf = f"""
        Using this report in markdown format:

        ```markdown
        {final_report}
        ```
        - Export this COMPLETE markdown report using the pdf_print_tool.
        - Export as a Podcast using the podcast_generator_tool:
            - in mp3 format.
            - Include explicit salutation: "Hello, this is the NextStop for store visit performance analysis."
            - a MALE gender voice.
            - Use a natural tone and clear pronunciation with high engagement.
            - Ensure the summary is concise and captures all key insights from the report.
        IMPORTANT INSTRUCTIONS:
        - Always return EVERY section and sub-section EXACTLY as formatted above.
        - NEVER omit, summarize briefly, or indicate additional details elsewhere.
        - The PDF must contain the ENTIRE content above exactly as generated here.
        """
        try:
            _, response, result = await agent.invoke(for_pdf)
        except Exception as e:
            print(f"Error invoking agent: {e}")
            raise RuntimeError(
                f"Failed to generate report due to an error in the agent invocation: {e}"
            )
        print(':: RESULT > ', result)
        # Create the response object
        response_data = NextStopResponse(
            data=final_report,
            status="success",
            created_at=datetime.now(),
            store_id=store_id,
            output=result.get('output', ''),
        )
        return response_data
