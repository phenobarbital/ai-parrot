#!/usr/bin/env python3
"""
A2A Secure Server Demo - Multiple agents with JWT authentication.

This script demonstrates:
- Running multiple A2A agents on different ports
- JWT-based authentication for secure communication
- Skill-based routing and access control
- Health monitoring and metrics

Requirements:
    The A2A *server* layer (``A2AServer``) and the security primitives used
    here (``JWTAuthenticator``, ``InMemoryCredentialProvider``,
    ``A2ASecurityMiddleware``, ``SecurityPolicy``, ``CallerIdentity``) now live
    in the ``ai-parrot-server`` satellite package — only the A2A client,
    models, mesh, router and orchestrator stay in core ``ai-parrot``.

        pip install ai-parrot-server   # or: pip install ai-parrot[server]

    Import paths are unchanged: ``parrot.a2a`` lazily resolves the server-side
    classes from ``parrot.a2a.server`` / ``parrot.a2a.security`` and raises a
    helpful error if ``ai-parrot-server`` is not installed.

Usage:
    # Start servers (run in separate terminals or use --all)
    python a2a_server.py --agent analyst --port 8081
    python a2a_server.py --agent support --port 8082
    python a2a_server.py --all  # Starts both agents

    # Or with custom JWT secret
    python a2a_server.py --all --jwt-secret "my-production-secret"

"""

from typing import Any, Dict, Optional
import os
import sys
import uuid
from datetime import datetime, timezone
import json
import argparse
import asyncio
from aiohttp import web

# Core A2A models ship with ai-parrot itself.
from parrot.a2a import AgentConfig

# Server-side + security layer ship with the ai-parrot-server satellite package.
# (`parrot.a2a` re-exports these lazily, but importing from the canonical
#  `parrot.a2a.security` module makes the ai-parrot-server dependency explicit.)
from parrot.a2a.security import (
    JWTAuthenticator,
    InMemoryCredentialProvider,
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


class _PublicPaths:
    """Membership test for request paths that bypass authentication.

    The A2ASecurityMiddleware exempts a path when ``path in skip_paths``. A plain
    set only matches exact paths, so unknown requests fall through to a ``401``.
    Discovery clients like Copilot Studio *fuzz* many AgentCard filenames
    (``agent-card.json``, ``agent.json``, ``agentCard.json``, ``agent_card.json``,
    …) under both ``/.well-known/`` and ``/a2a/.well-known/``. We treat *any*
    well-known path as public so those probes get a clean ``200``/``404`` from
    the router instead of a misleading ``401`` from the auth layer.
    """

    def __init__(self, exact):
        self._exact = set(exact)

    def __contains__(self, path: str) -> bool:
        if path in self._exact:
            return True
        # Any RFC 8615 well-known discovery path is public (exact `/.well-known`
        # or anything beneath a `/.well-known/` segment).
        return path.endswith("/.well-known") or "/.well-known/" in path


class SimpleA2AServer:
    """
    Simplified A2A server for demo purposes.

    In production, use ``parrot.a2a.A2AServer`` (shipped by the
    ``ai-parrot-server`` package), which wraps a real AI-Parrot agent and
    integrates with full agent capabilities.
    """

    def __init__(
        self,
        config: AgentConfig,
        jwt_auth: JWTAuthenticator,
        credentials: InMemoryCredentialProvider,
        public_url: Optional[str] = None,
    ):
        self.config = config
        self.jwt_auth = jwt_auth
        self.credentials = credentials
        # Public origin advertised in the AgentCard. When the server is exposed
        # through a tunnel/reverse-proxy (e.g. ngrok/cloudflared), set this to
        # the public origin so remote agents discover a reachable address
        # instead of localhost. Falls back to the local loopback address.
        self.public_url = (public_url or f"http://localhost:{self.config.port}").rstrip("/")
        # A2A service base URL. Clients derive operation endpoints from it
        # (e.g. `{a2a_url}/message/send`), so it MUST include the `/a2a` prefix
        # under which the operation routes are mounted — otherwise Copilot would
        # POST to `{origin}/message/send`, which doesn't exist.
        self.a2a_url = f"{self.public_url}/a2a"
        self._tasks: Dict[str, Dict] = {}
        self._request_count = 0

    def get_agent_card(self) -> Dict[str, Any]:
        """Generate an A2A AgentCard that strict consumers accept.

        The field set includes both the legacy v0.3 transport fields
        (``url``/``preferredTransport``) and the current ``supportedInterfaces``
        declaration so strict consumers can negotiate the JSON-RPC endpoint
        without rejecting the card as an unknown/old shape.

        We deliberately do NOT emit non-spec fields (e.g. a skill ``inputSchema``)
        or ``null`` placeholders, which can trip strict validators.
        """
        return {
            "protocolVersion": "0.3",
            "name": self.config.name,
            "description": self.config.description,
            "version": "1.0.0",
            # Base URL of the A2A service. Clients POST JSON-RPC calls here, so
            # it must include the `/a2a` prefix where the RPC route is mounted.
            "url": self.a2a_url,
            "supportedInterfaces": [
                {
                    "url": self.a2a_url,
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "0.3",
                }
            ],
            # REQUIRED by the spec / Copilot's parser. We expose the JSON-RPC
            # transport (POST {url}); see `handle_rpc`.
            "preferredTransport": "JSONRPC",
            "capabilities": {
                # streaming disabled → Copilot uses the simple `message/send`
                # call instead of SSE `message/stream`, keeping the demo simple.
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": False,
            },
            "defaultInputModes": ["text/plain", "application/json"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "description": s["description"],
                    "tags": s.get("tags", []),
                    "examples": s.get("examples", []),
                }
                for s in self.config.skills
            ],
        }

    async def handle_discovery(self, request: web.Request) -> web.Response:
        """Serve the AgentCard (A2A discovery).

        Reachable at the common A2A well-known AgentCard filenames, both under
        ``/a2a/.well-known/`` and at the root ``/.well-known/`` location.
        """
        return web.json_response(self.get_agent_card())

    @staticmethod
    def _rpc_error(req_id: Any, code: int, message: str) -> web.Response:
        """Build a JSON-RPC 2.0 error response."""
        return web.json_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

    async def handle_rpc(self, request: web.Request) -> web.Response:
        """Handle the A2A JSON-RPC transport at ``POST {url}`` (i.e. ``/a2a``).

        Implements the ``message/send`` (and ``message/stream``, answered
        non-streamed) methods of the A2A protocol so clients like Copilot Studio
        can invoke the agent. The AgentCard advertises ``preferredTransport:
        JSONRPC`` and ``url: .../a2a``, so this is where calls land.
        """
        self._request_count += 1
        identity: Optional[CallerIdentity] = request.get("a2a_identity")

        try:
            data = await request.json()
        except Exception:
            return self._rpc_error(None, -32700, "Parse error")

        req_id = data.get("id")
        method = data.get("method")
        params = data.get("params") or {}

        if method not in ("message/send", "message/stream"):
            return self._rpc_error(req_id, -32601, f"Method not found: {method}")

        message = params.get("message", {})
        parts = message.get("parts", [])
        text = ""
        for part in parts:
            # A2A uses the "kind" discriminator; tolerate legacy "type".
            if part.get("kind") == "text" or part.get("type") == "text":
                text = part.get("text", "")
                break

        response_text = self._generate_response(text, identity)

        # Return an A2A Message object as the JSON-RPC result.
        result: Dict[str, Any] = {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": response_text}],
        }
        if context_id := message.get("contextId"):
            result["contextId"] = context_id

        print(f"[{self.config.name}] RPC {method} from " f"{identity.agent_name if identity else 'anonymous'}")
        return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": result})

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle /health"""
        return web.json_response(
            {
                "status": "healthy",
                "agent": self.config.name,
                "uptime": "running",
                "requests_served": self._request_count,
            }
        )

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
            skill = next((s for s in self.config.skills if s["id"] == skill_id), None)

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
        return web.json_response(
            {
                "agent": self.config.name,
                "requests_served": self._request_count,
                "tasks_count": len(self._tasks),
                "skills": [s["id"] for s in self.config.skills],
            }
        )

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
        # Create security middleware.
        # Discovery (AgentCard) and health endpoints must stay public so
        # clients like Copilot can fetch the card before authenticating —
        # otherwise the middleware would answer them with 401.
        middleware = A2ASecurityMiddleware(
            jwt_authenticator=self.jwt_auth,
            credential_provider=self.credentials,
            default_policy=SecurityPolicy(require_auth=True),
            skip_paths=[
                # Agent base path: Copilot Studio probes `GET /a2a` to fetch
                # the card before it has any credentials, so it must be public.
                "/a2a",
                "/health",
                "/ready",
            ],
        )
        # Make *every* well-known discovery path public (any card filename, at
        # the root or under /a2a) so Copilot's AgentCard fuzzing never gets a
        # misleading 401 on an unknown variant — only real operation endpoints
        # (message/send, skill/invoke, stats) stay authenticated.
        middleware._skip_paths = _PublicPaths(middleware._skip_paths)

        app = web.Application(middlewares=[middleware.middleware])

        # Discovery (AgentCard) routes.
        # The current A2A spec names the card `agent-card.json`; Copilot Studio
        # also probes several legacy/case variants. Serve all observed variants
        # to keep discovery deterministic instead of depending on probe order.
        for prefix in ("/a2a/.well-known", "/.well-known"):
            for filename in (
                "agent-card.json",
                "agent.json",
                "agentcard.json",
                "agentCard.json",
                "agent_card.json",
            ):
                app.router.add_get(f"{prefix}/{filename}", self.handle_discovery)
        # Copilot Studio fetches the AgentCard from the agent base path itself.
        app.router.add_get("/a2a", self.handle_discovery)
        # A2A JSON-RPC transport: clients POST message/send here (card's `url`).
        app.router.add_post("/a2a", self.handle_rpc)
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
    public_url: Optional[str] = None,
) -> None:
    """Run a single A2A agent server.

    Args:
        agent_name: Key into ``AGENT_CONFIGS``.
        jwt_secret: Shared secret for the JWT authenticator.
        credentials: Shared credential provider.
        public_url: Public origin to advertise in the AgentCard (e.g. the
            ngrok URL). Defaults to ``http://localhost:<port>``.
    """
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
    server = SimpleA2AServer(config, jwt_auth, credentials, public_url=public_url)
    app = server.create_app()

    # Run
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", config.port)
    await site.start()

    # Local bind address vs. the public origin advertised in the AgentCard.
    local = f"http://localhost:{config.port}"
    public = server.public_url

    print(f"🚀 {config.name} running on {local}")
    if public != local:
        print(f"   Public:    {public}  (advertised in AgentCard)")
        print(f"   Discovery: {public}/a2a/.well-known/agent-card.json")
    else:
        print(f"   Discovery: {local}/a2a/.well-known/agent-card.json")
    print(f"   Health:    {local}/health")
    print(f"   Skills:    {[s['id'] for s in config.skills]}")

    return runner


async def _serve_forever(runners: list) -> None:
    """Keep the given AppRunners alive until cancelled, then clean them up."""
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        for runner in runners:
            await runner.cleanup()


async def run_single_server(
    agent_name: str,
    jwt_secret: str,
    public_url: Optional[str] = None,
) -> None:
    """Run one A2A agent server and block until interrupted.

    ``run_server`` only *starts* the server and returns its AppRunner; without
    a wait loop the event loop would exit immediately and the process would die
    right after printing the banner. This wrapper keeps it alive.
    """
    credentials = InMemoryCredentialProvider()
    runner = await run_server(
        agent_name,
        jwt_secret,
        credentials,
        public_url=public_url,
    )
    if not runner:
        return

    print("\n✅ Agent started! Press Ctrl+C to stop.\n")
    print("=" * 60)

    await _serve_forever([runner])


async def run_all_servers(
    jwt_secret: str,
    public_urls: Optional[Dict[str, str]] = None,
) -> None:
    """Run all configured agent servers.

    Args:
        jwt_secret: Shared secret for the JWT authenticator.
        public_urls: Optional mapping of ``agent_name -> public origin`` to
            advertise in each AgentCard (e.g. when fronted by ngrok).
    """
    public_urls = public_urls or {}
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
        json.dump(
            {
                "api_key": client_creds["api_key"],
                "jwt_token": demo_token,
                "jwt_secret": jwt_secret,
                "agents": {
                    name: {
                        "url": public_urls.get(name, f"http://localhost:{cfg.port}"),
                        "name": cfg.name,
                    }
                    for name, cfg in AGENT_CONFIGS.items()
                },
            },
            f,
            indent=2,
        )
    print(f"\n💾 Credentials saved to: {creds_file}")

    # Start all servers
    runners = []
    for agent_name in AGENT_CONFIGS:
        runner = await run_server(
            agent_name,
            jwt_secret,
            credentials,
            public_url=public_urls.get(agent_name),
        )
        if runner:
            runners.append(runner)

    print("\n✅ All agents started! Press Ctrl+C to stop.\n")
    print("=" * 60)

    await _serve_forever(runners)


def main():
    parser = argparse.ArgumentParser(
        description="A2A Secure Server Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start all agents
  python a2a_server.py --all

  # Start specific agent
  python a2a_server.py --agent analyst --port 8081

  # Custom JWT secret
  python a2a_server.py --all --jwt-secret "my-secret-key"

  # Expose the support agent through ngrok (advertise the public URL):
  #   ngrok http 8082
  python a2a_server.py --agent support --port 8082 \\
      --public-url https://eminent-kiwi-trusty.ngrok-free.app
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
    parser.add_argument(
        "--public-url",
        default=os.getenv("A2A_PUBLIC_URL"),
        help=(
            "Public origin advertised in the AgentCard when the server is "
            "exposed through a tunnel/reverse-proxy (e.g. an ngrok URL like "
            "https://eminent-kiwi-trusty.ngrok-free.app). Defaults to the "
            "A2A_PUBLIC_URL env var, or http://localhost:<port>."
        ),
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
            # In --all mode a single public URL is ambiguous (multiple ports),
            # so map it to the targeted agent if one was named, else skip.
            public_urls = {args.agent: args.public_url} if args.public_url and args.agent else {}
            asyncio.run(run_all_servers(args.jwt_secret, public_urls=public_urls))
        else:
            asyncio.run(
                run_single_server(
                    args.agent,
                    args.jwt_secret,
                    public_url=args.public_url,
                )
            )
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")


if __name__ == "__main__":
    main()
