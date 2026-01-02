#!/usr/bin/env python3
"""
A2A Secure Client Demo - Communicate with A2A agents using JWT authentication.

This script demonstrates:
- Using SecureA2AClient from parrot.a2a.security
- JWT and API key authentication
- Sending messages and invoking skills
- Streaming responses
- Interactive mode

Usage:
    # First, start the servers:
    python a2a_server_demo.py --all

    # Then run the client:
    python a2a_client_demo.py                    # Interactive mode
    python a2a_client_demo.py --discover         # Discover all agents
    python a2a_client_demo.py --ask "Hello!"     # Send message
    python a2a_client_demo.py --agent analyst --ask "Analyze sales data"
    python a2a_client_demo.py --skill analyze_data --params '{"data": "test"}'

Requirements:
    pip install aiohttp pyjwt
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional

# Add parent to path for local development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─────────────────────────────────────────────────────────────────────────────
# Import from parrot.a2a.security
# For standalone demo, we import from the local security module
# In production: from parrot.a2a.security import SecureA2AClient, AuthScheme
# ─────────────────────────────────────────────────────────────────────────────

try:
    # Try importing from installed parrot package
    from parrot.a2a.security import (
        SecureA2AClient,
        AuthScheme,
        JWTAuthenticator,
    )
    USING_PARROT = True
except ImportError:
    # Fallback: import from local security.py file (for standalone demo)
    try:
        from security import (
            SecureA2AClient,
            AuthScheme,
            JWTAuthenticator,
        )
        USING_PARROT = False
        print("ℹ️  Using local security.py (parrot package not installed)")
    except ImportError:
        print("❌ Error: Cannot import security module.")
        print("   Either install parrot or ensure security.py is in the same directory.")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_AGENTS = {
    "analyst": "http://localhost:8081",
    "support": "http://localhost:8082",
}

CREDENTIALS_FILE = "/tmp/a2a_demo_credentials.json"


def load_credentials() -> Dict[str, Any]:
    """Load credentials from the server demo."""
    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# Helper wrapper for easier agent info access
# ─────────────────────────────────────────────────────────────────────────────

class A2AClientSession:
    """
    Wrapper around SecureA2AClient for demo convenience.

    Provides easy access to agent info and common operations.
    """

    def __init__(
        self,
        url: str,
        *,
        jwt_token: Optional[str] = None,
        api_key: Optional[str] = None,
        jwt_secret: Optional[str] = None,
        agent_name: str = "DemoClient",
    ):
        """
        Initialize client session.

        Args:
            url: Agent URL
            jwt_token: Pre-generated JWT token
            api_key: API key for authentication
            jwt_secret: JWT secret for auto-generating tokens
            agent_name: Name for JWT claims
        """
        self.url = url
        self._jwt_token = jwt_token
        self._api_key = api_key
        self._jwt_secret = jwt_secret
        self._agent_name = agent_name
        self._client: Optional[SecureA2AClient] = None
        self._a2a_client = None  # The underlying A2AClient
        self._agent_card: Optional[Dict] = None

    def _create_client(self) -> SecureA2AClient:
        """Create SecureA2AClient with appropriate auth."""
        if self._jwt_token:
            return SecureA2AClient(
                self.url,
                auth_scheme=AuthScheme.BEARER,
                token=self._jwt_token,
            )
        elif self._api_key:
            return SecureA2AClient(
                self.url,
                auth_scheme=AuthScheme.API_KEY,
                api_key=self._api_key,
            )
        elif self._jwt_secret:
            # Create JWT authenticator for auto token generation
            jwt_auth = JWTAuthenticator(
                secret_key=self._jwt_secret,
                issuer="a2a-demo",
            )
            return SecureA2AClient(
                self.url,
                auth_scheme=AuthScheme.BEARER,
                jwt_authenticator=jwt_auth,
                agent_name=self._agent_name,
                permissions=["skill:*"],
            )
        else:
            # No auth - will likely fail on protected endpoints
            return SecureA2AClient(
                self.url,
                auth_scheme=AuthScheme.NONE,
            )

    async def connect(self) -> "A2AClientSession":
        """Connect to the agent."""
        self._client = self._create_client()
        self._a2a_client = await self._client.connect()
        self._agent_card = self._a2a_client.agent_card
        return self

    async def disconnect(self) -> None:
        """Disconnect from the agent."""
        if self._client:
            await self._client.disconnect()
            self._client = None
            self._a2a_client = None

    async def __aenter__(self) -> "A2AClientSession":
        return await self.connect()

    async def __aexit__(self, *args):
        await self.disconnect()

    @property
    def agent_name(self) -> str:
        """Get connected agent name."""
        if self._agent_card:
            return self._agent_card.name if hasattr(self._agent_card, 'name') else self._agent_card.get("name", "Unknown")
        return "Not connected"

    @property
    def agent_card(self) -> Optional[Dict]:
        """Get agent card."""
        if self._agent_card:
            # Handle both object and dict
            if hasattr(self._agent_card, 'to_dict'):
                return self._agent_card.to_dict() if hasattr(self._agent_card, 'to_dict') else vars(self._agent_card)
            return self._agent_card if isinstance(self._agent_card, dict) else None
        return None

    @property
    def skills(self):
        """Get agent skills."""
        if self._agent_card:
            if hasattr(self._agent_card, 'skills'):
                return self._agent_card.skills
            elif isinstance(self._agent_card, dict):
                return self._agent_card.get("skills", [])
        return []

    async def health(self) -> Dict[str, Any]:
        """Check agent health."""
        if self._a2a_client and hasattr(self._a2a_client, '_session'):
            url = f"{self.url}/health"
            async with self._a2a_client._session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()
        return {"status": "unknown"}

    async def send_message(self, content: str, **kwargs) -> Any:
        """Send a message to the agent."""
        return await self._client.send_message(content, **kwargs)

    async def stream_message(self, content: str, **kwargs):
        """Stream a message response."""
        async for chunk in self._client.stream_message(content, **kwargs):
            yield chunk

    async def invoke_skill(self, skill_id: str, params: Optional[Dict] = None, **kwargs) -> Any:
        """Invoke a skill on the agent."""
        return await self._client.invoke_skill(skill_id, params, **kwargs)

    async def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        if self._a2a_client and hasattr(self._a2a_client, '_session'):
            url = f"{self.url}/a2a/stats"
            async with self._a2a_client._session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Demo Functions
# ─────────────────────────────────────────────────────────────────────────────

async def discover_agents(
    agents: Dict[str, str],
    jwt_token: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_secret: Optional[str] = None,
) -> None:
    """Discover all configured agents."""
    print("\n🔍 Discovering A2A Agents...\n")

    for name, url in agents.items():
        try:
            async with A2AClientSession(
                url,
                jwt_token=jwt_token,
                api_key=api_key,
                jwt_secret=jwt_secret,
            ) as client:
                card = client.agent_card
                health = await client.health()

                agent_name = card.get("name", name) if card else name
                print(f"✅ {agent_name} ({url})")
                print(f"   Description: {card.get('description', 'N/A') if card else 'N/A'}")
                print(f"   Version: {card.get('version', 'N/A') if card else 'N/A'}")
                print(f"   Status: {health.get('status', 'unknown')}")

                skills = card.get("skills", []) if card else []
                if skills:
                    print(f"   Skills:")
                    for skill in skills:
                        skill_id = skill.get("id", skill.id if hasattr(skill, 'id') else "?")
                        skill_desc = skill.get("description", "") if isinstance(skill, dict) else getattr(skill, 'description', '')
                        print(f"      - {skill_id}: {skill_desc}")
                print()

        except PermissionError as e:
            print(f"🔒 {name} ({url}): {e}")
        except Exception as e:
            print(f"❌ {name} ({url}): {e}")


async def send_message(
    url: str,
    message: str,
    jwt_token: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_secret: Optional[str] = None,
    stream: bool = False,
) -> None:
    """Send a message to an agent."""
    try:
        async with A2AClientSession(
            url,
            jwt_token=jwt_token,
            api_key=api_key,
            jwt_secret=jwt_secret,
        ) as client:
            print(f"\n📤 Sending to {client.agent_name}...")
            print(f"   Message: {message[:50]}{'...' if len(message) > 50 else ''}")
            print()

            if stream:
                print("📥 Response (streaming):")
                print("-" * 40)
                async for chunk in client.stream_message(message):
                    print(chunk, end="", flush=True)
                print("\n" + "-" * 40)
            else:
                result = await client.send_message(message)

                print("📥 Response:")
                print("-" * 40)

                # Extract text from result
                if hasattr(result, 'artifacts'):
                    artifacts = result.artifacts
                elif isinstance(result, dict):
                    artifacts = result.get("artifacts", [])
                else:
                    artifacts = []

                for artifact in artifacts:
                    parts = artifact.get("parts", []) if isinstance(artifact, dict) else getattr(artifact, 'parts', [])
                    for part in parts:
                        if isinstance(part, dict) and part.get("type") == "text":
                            print(part.get("text", ""))
                        elif hasattr(part, 'text'):
                            print(part.text or "")

                print("-" * 40)

                task_id = result.get("id") if isinstance(result, dict) else getattr(result, 'id', None)
                status = result.get("status", {}) if isinstance(result, dict) else getattr(result, 'status', {})
                state = status.get("state") if isinstance(status, dict) else getattr(status, 'state', None)

                print(f"\nTask ID: {task_id}")
                print(f"Status: {state}")

    except PermissionError as e:
        print(f"🔒 Authentication Error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def invoke_skill(
    url: str,
    skill_id: str,
    params: Dict[str, Any],
    jwt_token: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_secret: Optional[str] = None,
) -> None:
    """Invoke a skill on an agent."""
    try:
        async with A2AClientSession(
            url,
            jwt_token=jwt_token,
            api_key=api_key,
            jwt_secret=jwt_secret,
        ) as client:
            print(f"\n⚡ Invoking skill '{skill_id}' on {client.agent_name}...")
            print(f"   Params: {json.dumps(params)}")
            print()

            result = await client.invoke_skill(skill_id, params)

            print("📥 Result:")
            print("-" * 40)
            if isinstance(result, dict):
                print(json.dumps(result, indent=2))
            else:
                print(result)
            print("-" * 40)

    except PermissionError as e:
        print(f"🔒 Permission Error: {e}")
    except ValueError as e:
        print(f"❌ Not Found: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")


async def interactive_mode(
    agents: Dict[str, str],
    jwt_token: Optional[str] = None,
    api_key: Optional[str] = None,
    jwt_secret: Optional[str] = None,
) -> None:
    """Run interactive client mode."""
    print("\n🎮 Interactive A2A Client")
    print("=" * 60)
    print("Using: SecureA2AClient from parrot.a2a.security")
    print("=" * 60)
    print("Commands:")
    print("  /agents           - List available agents")
    print("  /use <agent>      - Select agent (analyst, support)")
    print("  /skills           - List skills of current agent")
    print("  /skill <id> [json]- Invoke a skill")
    print("  /stream <msg>     - Send message with streaming")
    print("  /stats            - Show agent stats")
    print("  /quit             - Exit")
    print()
    print("Or just type a message to send to the current agent.")
    print("=" * 60)

    current_agent = "analyst"
    current_url = agents.get(current_agent, "http://localhost:8081")

    print(f"\n📍 Current agent: {current_agent} ({current_url})")

    while True:
        try:
            user_input = input("\n> ").strip()

            if not user_input:
                continue

            # Commands
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=2)
                cmd = parts[0].lower()

                if cmd == "/quit" or cmd == "/exit":
                    print("👋 Goodbye!")
                    break

                elif cmd == "/agents":
                    print("\nAvailable agents:")
                    for name, url in agents.items():
                        marker = "→" if name == current_agent else " "
                        print(f"  {marker} {name}: {url}")

                elif cmd == "/use":
                    if len(parts) < 2:
                        print("Usage: /use <agent_name>")
                        continue

                    agent_name = parts[1].lower()
                    if agent_name in agents:
                        current_agent = agent_name
                        current_url = agents[agent_name]
                        print(f"📍 Switched to: {current_agent} ({current_url})")
                    else:
                        print(f"Unknown agent: {agent_name}")
                        print(f"Available: {list(agents.keys())}")

                elif cmd == "/skills":
                    async with A2AClientSession(
                        current_url,
                        jwt_token=jwt_token,
                        api_key=api_key,
                        jwt_secret=jwt_secret,
                    ) as client:
                        print(f"\nSkills for {client.agent_name}:")
                        for skill in client.skills:
                            if isinstance(skill, dict):
                                print(f"  • {skill['id']}: {skill.get('description', '')}")
                            else:
                                print(f"  • {skill.id}: {getattr(skill, 'description', '')}")

                elif cmd == "/skill":
                    if len(parts) < 2:
                        print("Usage: /skill <skill_id> [params_json]")
                        continue

                    skill_id = parts[1]
                    params = {}
                    if len(parts) > 2:
                        try:
                            params = json.loads(parts[2])
                        except json.JSONDecodeError:
                            print("Invalid JSON for params")
                            continue

                    await invoke_skill(
                        current_url, skill_id, params,
                        jwt_token=jwt_token,
                        api_key=api_key,
                        jwt_secret=jwt_secret,
                    )

                elif cmd == "/stream":
                    if len(parts) < 2:
                        print("Usage: /stream <message>")
                        continue

                    message = " ".join(parts[1:])
                    await send_message(
                        current_url, message,
                        jwt_token=jwt_token,
                        api_key=api_key,
                        jwt_secret=jwt_secret,
                        stream=True,
                    )

                elif cmd == "/stats":
                    async with A2AClientSession(
                        current_url,
                        jwt_token=jwt_token,
                        api_key=api_key,
                        jwt_secret=jwt_secret,
                    ) as client:
                        stats = await client.get_stats()
                        print(f"\n📊 Stats for {client.agent_name}:")
                        print(json.dumps(stats, indent=2))

                elif cmd == "/help":
                    print("\nCommands: /agents, /use, /skills, /skill, /stream, /stats, /quit")

                else:
                    print(f"Unknown command: {cmd}")
                    print("Type /help for available commands")

            else:
                # Send message
                await send_message(
                    current_url, user_input,
                    jwt_token=jwt_token,
                    api_key=api_key,
                    jwt_secret=jwt_secret,
                )

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            break
        except Exception as e:
            print(f"Error: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Test Without Auth (should fail)
# ─────────────────────────────────────────────────────────────────────────────

async def test_without_auth(url: str) -> None:
    """Test that requests without auth are rejected."""
    print("\n🔐 Testing authentication requirement...")
    print(f"   Target: {url}")

    try:
        # Create client without any auth
        client = SecureA2AClient(
            url,
            auth_scheme=AuthScheme.NONE,
        )

        a2a_client = await client.connect()

        # Try to send message (should fail on protected endpoint)
        await client.send_message("Hello")
        print("❌ Request succeeded without auth (unexpected!)")

        await client.disconnect()

    except PermissionError:
        print("✅ Request correctly rejected without authentication")
    except Exception as e:
        error_msg = str(e).lower()
        if "401" in error_msg or "unauthorized" in error_msg or "authentication" in error_msg:
            print("✅ Request correctly rejected (401 Unauthorized)")
        else:
            print(f"⚠️  Error (may still be auth-related): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="A2A Secure Client Demo (using SecureA2AClient)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python a2a_client_demo.py

  # Discover all agents
  python a2a_client_demo.py --discover

  # Send message to specific agent
  python a2a_client_demo.py --agent analyst --ask "Analyze this data"

  # Stream response
  python a2a_client_demo.py --agent support --ask "I need help" --stream

  # Invoke skill
  python a2a_client_demo.py --agent analyst --skill analyze_data --params '{"source": "db"}'

  # Test auth requirement
  python a2a_client_demo.py --test-auth

  # Use custom token
  python a2a_client_demo.py --token "eyJhbGciOiJIUzI1NiIs..." --ask "Hello"
        """,
    )

    parser.add_argument(
        "--agent",
        choices=["analyst", "support"],
        default="analyst",
        help="Agent to communicate with",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover all available agents",
    )
    parser.add_argument(
        "--ask",
        metavar="MESSAGE",
        help="Send a message",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Use streaming for response",
    )
    parser.add_argument(
        "--skill",
        metavar="SKILL_ID",
        help="Invoke a skill",
    )
    parser.add_argument(
        "--params",
        metavar="JSON",
        default="{}",
        help="JSON parameters for skill",
    )
    parser.add_argument(
        "--token",
        metavar="JWT",
        help="JWT token for authentication",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="API key for authentication",
    )
    parser.add_argument(
        "--test-auth",
        action="store_true",
        help="Test that authentication is required",
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run interactive mode",
    )

    args = parser.parse_args()

    # Load credentials from server demo
    creds = load_credentials()

    # Get authentication credentials
    jwt_token = args.token or creds.get("jwt_token")
    api_key = args.api_key or creds.get("api_key")
    jwt_secret = creds.get("jwt_secret")  # For auto-generation

    # Get agent URLs
    agents = creds.get("agents", {})
    if not agents:
        agents = {k: v for k, v in DEFAULT_AGENTS.items()}
    else:
        agents = {k: v["url"] for k, v in agents.items()}

    print("=" * 60)
    print("       A2A Secure Client Demo")
    print("       Using: SecureA2AClient from parrot.a2a.security")
    print("=" * 60)

    if jwt_token:
        print(f"🔑 Auth: JWT token ({jwt_token[:30]}...)")
    elif api_key:
        print(f"🔑 Auth: API key ({api_key[:20]}...)")
    elif jwt_secret:
        print(f"🔑 Auth: Auto-generate JWT (secret available)")
    else:
        print("⚠️  No credentials found!")
        print("   Run 'python a2a_server_demo.py --all' first to generate credentials")
        if not args.test_auth:
            print()

    # Execute command
    try:
        if args.test_auth:
            url = agents.get(args.agent, DEFAULT_AGENTS[args.agent])
            asyncio.run(test_without_auth(url))

        elif args.discover:
            asyncio.run(discover_agents(
                agents,
                jwt_token=jwt_token,
                api_key=api_key,
                jwt_secret=jwt_secret,
            ))

        elif args.skill:
            url = agents.get(args.agent, DEFAULT_AGENTS[args.agent])
            params = json.loads(args.params)
            asyncio.run(invoke_skill(
                url, args.skill, params,
                jwt_token=jwt_token,
                api_key=api_key,
                jwt_secret=jwt_secret,
            ))

        elif args.ask:
            url = agents.get(args.agent, DEFAULT_AGENTS[args.agent])
            asyncio.run(send_message(
                url, args.ask,
                jwt_token=jwt_token,
                api_key=api_key,
                jwt_secret=jwt_secret,
                stream=args.stream,
            ))

        else:
            # Default: interactive mode
            asyncio.run(interactive_mode(
                agents,
                jwt_token=jwt_token,
                api_key=api_key,
                jwt_secret=jwt_secret,
            ))

    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")


if __name__ == "__main__":
    main()
