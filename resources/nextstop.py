from aiohttp import web
from parrot.handlers.abstract import AbstractAgentHandler


class NextStopAgent(AbstractAgentHandler):
    """
    NextStopAgent is an abstract agent handler that extends the AbstractAgentHandler.
    It provides a framework for implementing specific agent functionalities.
    """

    def __init__(self, *args, **kwargs):
        self.agent_name = "NextStopAgent"
        self.base_route: str = '/api/v1/agents/nextstop'
        self.additional_routes = [
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
        super().__init__(*args, **kwargs)

    @staticmethod
    async def on_startup(app: web.Application) -> None:
        """Start the application."""
        print(f"Starting NextStop Agent application: {app}")

    @staticmethod
    async def on_shutdown(app: web.Application) -> None:
        """Stop the application."""
        print(f"Stopping NextStop Agent application: {app}")


    @staticmethod
    async def on_cleanup(app: web.Application) -> None:
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
