#!/usr/bin/env python3
"""
A2A Secure Server Demo - Multiple agents with JWT authentication.

This script demonstrates:
- Running multiple A2A agents on different ports
- JWT-based authentication for secure communication
- Skill-based routing and access control
- Health monitoring and metrics

Usage:
    # Start servers (run in separate terminals or use --all)
    python a2a_server.py --agent analyst --port 8081
    python a2a_server.py --agent support --port 8082
    python a2a_server.py --all  # Starts both agents

    # Or with custom JWT secret
    python a2a_server.py --all --jwt-secret "my-production-secret"

"""
from typing import Any, Dict, Optional
import sys
import uuid
from datetime import datetime, timezone
import json
import argparse
import asyncio
from aiohttp import web
from parrot.a2a import (
    A2AServer,
    JWTAuthenticator,
    InMemoryCredentialProvider,
    AgentConfig
)
from parrot.a2a.security import (
    A2ASecurityMiddleware,
    SecurityPolicy,
    CallerIdentity,
)

# Define our demo agents
AGENT_CONFIGS = {
    "analyst": AgentConfig(
        name="DataAnalyst",
        description="Analyzes data and provides insights",
        port=8081,
        skills=[
            {
                "id": "analyze_data",
                "name": "Analyze Data",
                "description": "Analyze datasets and provide statistical insights",
                "tags": ["analysis", "statistics"],
            },
            {
                "id": "generate_report",
                "name": "Generate Report",
                "description": "Generate formatted reports from data",
                "tags": ["reports", "documents"],
            },
        ],
        system_prompt="You are a data analyst. Analyze data and provide insights.",
    ),
    "support": AgentConfig(
        name="CustomerSupport",
        description="Handles customer inquiries and support tickets",
        port=8082,
        skills=[
            {
                "id": "answer_question",
                "name": "Answer Question",
                "description": "Answer customer questions",
                "tags": ["support", "qa"],
            },
            {
                "id": "create_ticket",
                "name": "Create Ticket",
                "description": "Create a support ticket",
                "tags": ["support", "tickets"],
            },
        ],
        system_prompt="You are a customer support agent. Help customers with their inquiries.",
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Simple A2A Server Implementation
# ─────────────────────────────────────────────────────────────────────────────

class SimpleA2AServer:
    """
    Simplified A2A server for demo purposes.

    In production, use parrot.a2a.A2AServer which integrates
    with full agent capabilities.
    """

    def __init__(
        self,
        config: AgentConfig,
        jwt_auth: JWTAuthenticator,
        credentials: InMemoryCredentialProvider,
    ):
        self.config = config
        self.jwt_auth = jwt_auth
        self.credentials = credentials
        self._tasks: Dict[str, Dict] = {}
        self._request_count = 0

    def get_agent_card(self) -> Dict[str, Any]:
        """Generate A2A AgentCard."""
        return {
            "name": self.config.name,
            "description": self.config.description,
            "version": "1.0.0",
            "url": f"http://localhost:{self.config.port}",
            "protocolVersion": "0.3",
            "skills": self.config.skills,
            "capabilities": {
                "streaming": True,
                "stateTransitionHistory": False,
            },
        }

    async def handle_discovery(self, request: web.Request) -> web.Response:
        """Handle /.well-known/agent.json"""
        return web.json_response(self.get_agent_card())

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle /health"""
        return web.json_response({
            "status": "healthy",
            "agent": self.config.name,
            "uptime": "running",
            "requests_served": self._request_count,
        })

    async def handle_message(self, request: web.Request) -> web.Response:
        """Handle POST /a2a/message/send"""
        self._request_count += 1

        # Get caller identity from middleware
        identity: Optional[CallerIdentity] = request.get("a2a_identity")

        try:
            data = await request.json()
            message = data.get("message", {})
            parts = message.get("parts", [])

            # Extract text from parts
            text = ""
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    break

            if not text and isinstance(message, str):
                text = message

            # Generate response based on agent type
            response_text = self._generate_response(text, identity)

            # Create task response
            task_id = str(uuid.uuid4())
            task = {
                "id": task_id,
                "contextId": message.get("contextId", str(uuid.uuid4())),
                "status": {
                    "state": "completed",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                "artifacts": [
                    {
                        "parts": [{"type": "text", "text": response_text}],
                        "index": 0,
                    }
                ],
            }

            self._tasks[task_id] = task

            print(f"[{self.config.name}] Processed message from {identity.agent_name if identity else 'anonymous'}")

            return web.json_response(task)

        except Exception as e:
            return web.json_response(
                {"error": {"code": "ProcessingError", "message": str(e)}},
                status=500,
            )

    async def handle_stream(self, request: web.Request) -> web.StreamResponse:
        """Handle POST /a2a/message/stream (SSE)"""
        self._request_count += 1
        identity: Optional[CallerIdentity] = request.get("a2a_identity")

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        try:
            data = await request.json()
            message = data.get("message", {})
            parts = message.get("parts", [])

            text = ""
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    break

            # Generate response
            response_text = self._generate_response(text, identity)

            # Stream in chunks
            task_id = str(uuid.uuid4())
            words = response_text.split()

            for i, word in enumerate(words):
                chunk = word + " "
                event = {
                    "artifactUpdate": {
                        "taskId": task_id,
                        "artifact": {
                            "parts": [{"type": "text", "text": chunk}],
                            "index": 0,
                            "append": True,
                        },
                    }
                }
                await response.write(f"data: {json.dumps(event)}\n\n".encode())
                await asyncio.sleep(0.05)  # Simulate streaming delay

            # Send completion
            completion = {
                "statusUpdate": {
                    "taskId": task_id,
                    "final": True,
                    "status": {"state": "completed"},
                }
            }
            await response.write(f"data: {json.dumps(completion)}\n\n".encode())

        except Exception as e:
            error_event = {
                "statusUpdate": {
                    "final": True,
                    "status": {
                        "state": "failed",
                        "message": {"parts": [{"type": "text", "text": str(e)}]},
                    },
                }
            }
            await response.write(f"data: {json.dumps(error_event)}\n\n".encode())

        return response

    async def handle_invoke_skill(self, request: web.Request) -> web.Response:
        """Handle POST /a2a/skill/invoke"""
        self._request_count += 1
        identity: Optional[CallerIdentity] = request.get("a2a_identity")

        try:
            data = await request.json()
            skill_id = data.get("skill_id")
            params = data.get("params", {})

            # Check permission
            if identity and not identity.can_invoke_skill(skill_id):
                return web.json_response(
                    {"error": f"Permission denied for skill: {skill_id}"},
                    status=403,
                )

            # Find skill
            skill = None
            for s in self.config.skills:
                if s["id"] == skill_id:
                    skill = s
                    break

            if not skill:
                return web.json_response(
                    {"error": f"Skill not found: {skill_id}"},
                    status=404,
                )

            # Execute skill (mock)
            result = {
                "skill_id": skill_id,
                "status": "completed",
                "result": f"Executed {skill['name']} with params: {params}",
                "executed_by": self.config.name,
            }

            print(
                f"[{self.config.name}] Skill '{skill_id}' invoked by {identity.agent_name if identity else 'anonymous'}"
            )

            return web.json_response(result)

        except Exception as e:
            return web.json_response(
                {"error": str(e)},
                status=500,
            )

    async def handle_stats(self, request: web.Request) -> web.Response:
        """Handle GET /a2a/stats"""
        return web.json_response({
            "agent": self.config.name,
            "requests_served": self._request_count,
            "tasks_count": len(self._tasks),
            "skills": [s["id"] for s in self.config.skills],
        })

    def _generate_response(
        self,
        text: str,
        identity: Optional[CallerIdentity],
    ) -> str:
        """Generate a mock response based on agent type."""
        caller = identity.agent_name if identity else "anonymous"

        if self.config.name == "DataAnalyst":
            return (
                f"[DataAnalyst] Analyzing your request: '{text[:50]}...'\n\n"
                f"📊 Analysis Results:\n"
                f"- Data points processed: {len(text.split())}\n"
                f"- Sentiment: Neutral\n"
                f"- Key topics: data, analysis, insights\n"
                f"- Confidence: 85%\n\n"
                f"Requested by: {caller}"
            )
        elif self.config.name == "CustomerSupport":
            return (
                f"[CustomerSupport] Thank you for contacting us!\n\n"
                f"Regarding your inquiry: '{text[:50]}...'\n\n"
                f"🎫 Ticket #CS-{uuid.uuid4().hex[:8].upper()} created.\n"
                f"We'll get back to you within 24 hours.\n\n"
                f"Caller: {caller}"
            )
        else:
            return f"[{self.config.name}] Processed: {text}"

    def create_app(self) -> web.Application:
        """Create aiohttp application with routes."""
        # Create security middleware
        middleware = A2ASecurityMiddleware(
            jwt_authenticator=self.jwt_auth,
            credential_provider=self.credentials,
            default_policy=SecurityPolicy(require_auth=True),
        )

        app = web.Application(middlewares=[middleware.middleware])

        # Routes
        app.router.add_get("/.well-known/agent.json", self.handle_discovery)
        app.router.add_get("/health", self.handle_health)
        app.router.add_post("/a2a/message/send", self.handle_message)
        app.router.add_post("/a2a/message/stream", self.handle_stream)
        app.router.add_post("/a2a/skill/invoke", self.handle_invoke_skill)
        app.router.add_get("/a2a/stats", self.handle_stats)

        return app

async def run_server(
    agent_name: str,
    jwt_secret: str,
    credentials: InMemoryCredentialProvider,
) -> None:
    """Run a single A2A agent server."""
    if agent_name not in AGENT_CONFIGS:
        print(f"Unknown agent: {agent_name}")
        print(f"Available agents: {list(AGENT_CONFIGS.keys())}")
        return

    config = AGENT_CONFIGS[agent_name]

    # Create JWT authenticator (shared secret)
    jwt_auth = JWTAuthenticator(
        secret_key=jwt_secret,
        issuer="a2a-demo",
        default_expiry=3600,
    )

    # Create server
    server = SimpleA2AServer(config, jwt_auth, credentials)
    app = server.create_app()

    # Run
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()

    print(f"🚀 {config.name} running on http://localhost:{config.port}")
    print(f"   Discovery: http://localhost:{config.port}/.well-known/agent.json")
    print(f"   Health:    http://localhost:{config.port}/health")
    print(f"   Skills:    {[s['id'] for s in config.skills]}")

    return runner


async def run_all_servers(jwt_secret: str) -> None:
    """Run all configured agent servers."""
    # Shared credential provider
    credentials = InMemoryCredentialProvider()

    # Register known clients
    client_creds = await credentials.register_agent(
        "DemoClient",
        permissions=["skill:*"],
        roles=["user"],
    )
    print("\n📋 Registered client 'DemoClient'")
    print(f"   API Key: {client_creds['api_key'][:20]}...")

    # Create JWT auth for generating demo tokens
    jwt_auth = JWTAuthenticator(
        secret_key=jwt_secret,
        issuer="a2a-demo",
    )
    demo_token = jwt_auth.create_token(
        agent_name="DemoClient",
        permissions=["skill:*"],
        roles=["user"],
        expires_in=86400,  # 24 hours
    )
    print(f"   JWT Token: {demo_token[:50]}...")

    # Save credentials for client demo
    creds_file = "/tmp/a2a_demo_credentials.json"
    with open(creds_file, "w") as f:
        json.dump({
            "api_key": client_creds["api_key"],
            "jwt_token": demo_token,
            "jwt_secret": jwt_secret,
            "agents": {
                name: {
                    "url": f"http://localhost:{cfg.port}",
                    "name": cfg.name,
                }
                for name, cfg in AGENT_CONFIGS.items()
            },
        }, f, indent=2)
    print(f"\n💾 Credentials saved to: {creds_file}")

    # Start all servers
    runners = []
    for agent_name in AGENT_CONFIGS:
        runner = await run_server(agent_name, jwt_secret, credentials)
        if runner:
            runners.append(runner)

    print("\n✅ All agents started! Press Ctrl+C to stop.\n")
    print("=" * 60)

    # Wait forever
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        for runner in runners:
            await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(
        description="A2A Secure Server Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start all agents
  python a2a_server_demo.py --all

  # Start specific agent
  python a2a_server_demo.py --agent analyst --port 8081

  # Custom JWT secret
  python a2a_server_demo.py --all --jwt-secret "my-secret-key"
        """,
    )

    parser.add_argument(
        "--agent",
        choices=list(AGENT_CONFIGS.keys()),
        help="Agent to start",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Override port for agent",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Start all agents",
    )
    parser.add_argument(
        "--jwt-secret",
        default="a2a-demo-secret-key-change-in-production",
        help="JWT secret key",
    )

    args = parser.parse_args()

    if not args.all and not args.agent:
        parser.print_help()
        print("\nError: Specify --all or --agent")
        sys.exit(1)

    # Override port if specified
    if args.port and args.agent:
        AGENT_CONFIGS[args.agent].port = args.port

    print("=" * 60)
    print("       A2A Secure Server Demo")
    print("=" * 60)
    print(f"JWT Secret: {args.jwt_secret[:20]}...")
    print()

    try:
        if args.all:
            asyncio.run(run_all_servers(args.jwt_secret))
        else:
            credentials = InMemoryCredentialProvider()
            asyncio.run(run_server(args.agent, args.jwt_secret, credentials))
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")


if __name__ == "__main__":
    main()
