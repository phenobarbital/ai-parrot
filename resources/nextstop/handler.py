from datetime import datetime
from aiohttp import web
from datamodel import BaseModel, Field
from parrot.handlers.abstract import AbstractAgentHandler
from parrot.tools.weather import OpenWeather
from parrot.tools import PythonREPLTool

class NextStopResponse(BaseModel):
    """
    NextStopResponse is a model that defines the structure of the response
    for the NextStop agent.
    """
    session_id: str = Field(..., description="Unique identifier for the session")
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

    async def on_startup(self, app: web.Application) -> None:
        """Start the application."""
        print(f"Starting NextStop Agent application: {app}")

    async def on_shutdown(self, app: web.Application) -> None:
        """Stop the application."""
        print(f"Stopping NextStop Agent application: {app}")

    async def on_cleanup(self, app: web.Application) -> None:
        """Cleanup the application."""
        print(f"Cleaning up NextStop Agent application: {app}")

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
        # Placeholder for actual processing logic
        return web.json_response({"message": "Data received", "data": data})
