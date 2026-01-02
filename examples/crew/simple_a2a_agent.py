#!/usr/bin/env python3
"""
Simple A2A Agent Server Example

This script shows the minimal pattern for creating an A2A agent server
with aiohttp and API key authentication.

Usage:
    python simple_a2a_agent.py
"""
import asyncio
import secrets
from aiohttp import web

from parrot.bots.agent import BasicAgent
from parrot.a2a import A2AServer


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

PORT = 8081
LLM_MODEL = "google:gemini-2.5-flash"


def generate_api_key() -> str:
    """Generate a secure API key."""
    return f"a2a-{secrets.token_urlsafe(32)}"


def create_api_key_middleware(api_key: str):
    """Create middleware for API key authentication."""
    @web.middleware
    async def api_key_auth(request: web.Request, handler):
        # Skip auth for discovery and health endpoints
        if request.path in ["/.well-known/agent.json", "/health"]:
            return await handler(request)

        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == api_key:
                return await handler(request)

        # Check X-API-Key header
        x_api_key = request.headers.get("X-API-Key", "")
        if x_api_key == api_key:
            return await handler(request)

        return web.json_response(
            {"error": {"code": "Unauthorized", "message": "Invalid or missing API key"}},
            status=401
        )
    return api_key_auth


# ─────────────────────────────────────────────────────────────────────────────
# Agent Definition
# ─────────────────────────────────────────────────────────────────────────────

class SimpleAgent(BasicAgent):
    """A simple agent with basic capabilities."""

    def __init__(self, **kwargs):
        super().__init__(
            name="SimpleAgent",
            role="General Assistant",
            goal="Help users with various tasks",
            description="A simple AI assistant agent exposed via A2A protocol.",
            **kwargs
        )

    async def configure(self, app=None):
        """Configure the agent with tools."""
        await super().configure(app)

        # Add your tools here, for example:
        # from parrot.tools.databasequery import DatabaseQueryTool
        # self.tool_manager.register_tool(DatabaseQueryTool())

        self.logger.info(
            f"Agent configured with {len(self.tool_manager.list_tools())} tools"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Server Setup
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    """Main entry point."""
    # Generate API key
    api_key = generate_api_key()

    # Create middleware
    middleware = create_api_key_middleware(api_key)

    # Create aiohttp app
    app = web.Application(middlewares=[middleware])

    # Create and configure agent
    agent = SimpleAgent(llm=LLM_MODEL)
    await agent.configure(app)

    # Create A2A server wrapper
    a2a_server = A2AServer(
        agent,
        version="1.0.0",
        tags=["general", "assistant"]
    )

    # Setup A2A routes
    a2a_server.setup(
        app,
        url=f"http://localhost:{PORT}"
    )

    # Add health endpoint
    async def health_handler(request):
        return web.json_response({
            "status": "healthy",
            "agent": agent.name,
            "port": PORT
        })
    app.router.add_get("/health", health_handler)

    # Start server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print("=" * 60)
    print("   Simple A2A Agent Server")
    print("=" * 60)
    print(f"\n🚀 Server running on http://0.0.0.0:{PORT}")
    print(f"📋 Discovery: http://localhost:{PORT}/.well-known/agent.json")
    print(f"❤️  Health:    http://localhost:{PORT}/health")
    print(f"\n🔑 API Key: {api_key}")
    print("\nPress Ctrl+C to stop.")
    print("=" * 60)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
