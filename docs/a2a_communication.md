# A2A Secure Communication Demo

This demo showcases secure Agent-to-Agent (A2A) communication with JWT authentication,
using `SecureA2AClient` from `parrot.a2a.security`.

## Quick Start

### 1. Install Dependencies

```bash
pip install aiohttp pyjwt
```

### 2. Start the Servers

In Terminal 1:
```bash
python a2a_server_demo.py --all
```

This starts two agents:
- **DataAnalyst** on `http://localhost:8081`
- **CustomerSupport** on `http://localhost:8082`

Output:
```
============================================================
       A2A Secure Server Demo
============================================================
JWT Secret: a2a-demo-secret-key-c...

📋 Registered client 'DemoClient'
   API Key: a2a_abc123...
   JWT Token: eyJhbGciOiJIUzI1NiIs...

💾 Credentials saved to: /tmp/a2a_demo_credentials.json

🚀 DataAnalyst running on http://localhost:8081
   Discovery: http://localhost:8081/.well-known/agent.json
   Skills:    ['analyze_data', 'generate_report']

🚀 CustomerSupport running on http://localhost:8082
   Discovery: http://localhost:8082/.well-known/agent.json
   Skills:    ['answer_question', 'create_ticket']

✅ All agents started! Press Ctrl+C to stop.
```

### 3. Run the Client

In Terminal 2:
```bash
# Interactive mode (default)
python a2a_client_demo.py

# Or send a single message
python a2a_client_demo.py --ask "Analyze my sales data"

# Or discover all agents
python a2a_client_demo.py --discover
```

---

## Key Feature: Using SecureA2AClient

The client demo uses `SecureA2AClient` from `parrot.a2a.security`:

```python
from parrot.a2a.security import SecureA2AClient, AuthScheme, JWTAuthenticator

# With pre-generated JWT token
client = SecureA2AClient(
    "http://localhost:8081",
    auth_scheme=AuthScheme.BEARER,
    token="eyJhbGciOiJIUzI1NiIs...",
)

# With API key
client = SecureA2AClient(
    "http://localhost:8081",
    auth_scheme=AuthScheme.API_KEY,
    api_key="a2a_abc123...",
)

# With auto-generated JWT (provides authenticator)
jwt_auth = JWTAuthenticator(secret_key="your-secret", issuer="a2a-demo")
client = SecureA2AClient(
    "http://localhost:8081",
    auth_scheme=AuthScheme.BEARER,
    jwt_authenticator=jwt_auth,
    agent_name="MyAgent",
    permissions=["skill:*"],
)

# Connect and use
async with client:
    task = await client.send_message("Hello!")

    async for chunk in client.stream_message("Analyze this"):
        print(chunk, end="")
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      Client                                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              SecureA2AClient                          │  │
│  │  - JWT Token or API Key                               │  │
│  │  - Auto-adds Authorization header                     │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────┬───────────────────────────────────┘
                         │ HTTPS + JWT
                         ▼
┌────────────────────────────────────────────────────────────┐
│                 A2ASecurityMiddleware                       │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐  │
│  │ JWT Validator  │  │  API Key Check │  │ Permission   │  │
│  │                │  │                │  │   Check      │  │
│  └────────────────┘  └────────────────┘  └──────────────┘  │
└────────────────────────┬───────────────────────────────────┘
                         │ Authenticated
                         ▼
┌────────────────────────────────────────────────────────────┐
│                    A2A Agents                               │
│  ┌─────────────────┐        ┌─────────────────┐            │
│  │  DataAnalyst    │        │ CustomerSupport │            │
│  │  :8081          │        │  :8082          │            │
│  │                 │        │                 │            │
│  │  Skills:        │        │  Skills:        │            │
│  │  - analyze_data │        │  - answer_question           │
│  │  - gen_report   │        │  - create_ticket │           │
│  └─────────────────┘        └─────────────────┘            │
└────────────────────────────────────────────────────────────┘
```

---

## Server Commands

```bash
# Start all agents
python a2a_server_demo.py --all

# Start specific agent
python a2a_server_demo.py --agent analyst --port 8081
python a2a_server_demo.py --agent support --port 8082

# Custom JWT secret (production)
python a2a_server_demo.py --all --jwt-secret "my-super-secret-key"
```

---

## Client Commands

### Interactive Mode

```bash
python a2a_client_demo.py
```

Interactive commands:
- `/agents` - List available agents
- `/use analyst` - Switch to analyst agent
- `/skills` - List current agent's skills
- `/skill analyze_data {"source": "db"}` - Invoke skill
- `/stream Hello!` - Stream response
- `/stats` - Show agent statistics
- `/quit` - Exit

### Command Line Mode

```bash
# Discover agents
python a2a_client_demo.py --discover

# Send message
python a2a_client_demo.py --ask "Hello, how are you?"

# Send to specific agent
python a2a_client_demo.py --agent support --ask "I need help"

# Stream response
python a2a_client_demo.py --ask "Tell me a story" --stream

# Invoke skill
python a2a_client_demo.py --skill analyze_data --params '{"source": "sales"}'

# Test authentication requirement
python a2a_client_demo.py --test-auth
```

---

## Authentication Flow

### JWT Authentication

```
1. Server generates JWT for registered clients
2. Client includes JWT in Authorization header
3. Server validates JWT signature and expiration
4. Server extracts permissions from JWT claims
5. Server checks skill-level permissions

Request:
  POST /a2a/message/send
  Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
  Content-Type: application/json

  {"message": {"parts": [{"type": "text", "text": "Hello"}]}}
```

### API Key Authentication

```
Request:
  POST /a2a/message/send
  X-API-Key: a2a_abc123...
  Content-Type: application/json

  {"message": {"parts": [{"type": "text", "text": "Hello"}]}}
```

---

## Endpoints

Each agent exposes:

| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /.well-known/agent.json` | ❌ No | Agent discovery (AgentCard) |
| `GET /health` | ❌ No | Health check |
| `POST /a2a/message/send` | ✅ Yes | Send message |
| `POST /a2a/message/stream` | ✅ Yes | Stream response (SSE) |
| `POST /a2a/skill/invoke` | ✅ Yes | Invoke specific skill |
| `GET /a2a/stats` | ✅ Yes | Agent statistics |

---

## Security Features

### Implemented

- ✅ JWT token authentication (HS256)
- ✅ API key authentication
- ✅ Permission-based authorization
- ✅ Skill-level access control
- ✅ Token expiration validation
- ✅ Public endpoints for discovery/health

### Future (in parrot.a2a.security)

- 🔄 mTLS (mutual TLS)
- 🔄 HMAC request signing
- 🔄 OAuth2 integration
- 🔄 Rate limiting
- 🔄 IP whitelisting
- 🔄 Redis credential store
- 🔄 Vault integration

---

## Example Session

```
$ python a2a_client_demo.py

============================================================
       A2A Secure Client Demo
============================================================
🔑 Using JWT token: eyJhbGciOiJIUzI1NiIsInR5cCI6...

🎮 Interactive A2A Client
============================================================
Commands:
  /agents           - List available agents
  /use <agent>      - Select agent (analyst, support)
  /skills           - List skills of current agent
  ...

📍 Current agent: analyst (http://localhost:8081)

> Analyze my quarterly sales data

📤 Sending to DataAnalyst...
   Message: Analyze my quarterly sales data

📥 Response:
----------------------------------------
[DataAnalyst] Analyzing your request: 'Analyze my quarterly sales data'...

📊 Analysis Results:
- Data points processed: 5
- Sentiment: Neutral
- Key topics: data, analysis, insights
- Confidence: 85%

Requested by: DemoClient
----------------------------------------

Task ID: 8f3a2b1c-...
Status: completed

> /use support
📍 Switched to: support (http://localhost:8082)

> I can't log into my account

📤 Sending to CustomerSupport...

📥 Response:
----------------------------------------
[CustomerSupport] Thank you for contacting us!

Regarding your inquiry: 'I can't log into my account'...

🎫 Ticket #CS-A1B2C3D4 created.
We'll get back to you within 24 hours.

Caller: DemoClient
----------------------------------------

> /quit
👋 Goodbye!
```

---

## Production Notes

1. **JWT Secret**: Use a strong, random secret in production
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **HTTPS**: Always use HTTPS in production

3. **Credential Storage**: Use Redis or Vault instead of in-memory

4. **Token Expiry**: Configure appropriate expiry times

5. **Logging**: Enable structured logging for audit trails

---

## Files

| File | Lines | Description |
|------|-------|-------------|
| `a2a_server_demo.py` | ~830 | Server with JWT auth middleware |
| `a2a_client_demo.py` | ~720 | Interactive secure client |
| `security.py` | ~2000 | Full security module (parrot.a2a) |

---

## Integration with AI-Parrot

In a real AI-Parrot project:

```python
from parrot.bots import BasicAgent
from parrot.a2a import (
    A2AServer,
    A2ASecurityMiddleware,
    JWTAuthenticator,
    InMemoryCredentialProvider,
    SecureA2AClient,
)

# Create agent
agent = BasicAgent(name="MyBot", llm="claude:claude-sonnet-4-20250514")
await agent.configure()

# Setup security
jwt_auth = JWTAuthenticator(secret_key="...", issuer="my-network")
credentials = InMemoryCredentialProvider()
await credentials.register_agent("TrustedClient", permissions=["skill:*"])

middleware = A2ASecurityMiddleware(
    jwt_authenticator=jwt_auth,
    credential_provider=credentials,
)

# Expose as secure A2A service
app = web.Application(middlewares=[middleware.middleware])
a2a = A2AServer(agent)
a2a.setup(app)

# Run
web.run_app(app, port=8080)
```
