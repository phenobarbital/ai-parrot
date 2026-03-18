# Matrix Multi-Agent Crew Guide

## AI-Parrot — FEAT-044

**Version**: 1.6.0
**Module**: `parrot.integrations.matrix.crew`

---

## Table of Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Configuration Reference](#3-configuration-reference)
4. [Architecture Deep Dive](#4-architecture-deep-dive)
5. [Agent Setup](#5-agent-setup)
6. [Running the Crew](#6-running-the-crew)
7. [Advanced Usage](#7-advanced-usage)
8. [Production Deployment](#8-production-deployment)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Overview

### What is a Matrix Multi-Agent Crew?

A **Matrix multi-agent crew** is a collection of AI agents that collaborate in one or more Matrix rooms. Each agent:

- Has its own **virtual Matrix identity** (MXID) via the Application Service (AS) protocol.
- Can participate in a **shared general room** where users route messages to agents using `@mention`.
- Can optionally have a **dedicated private room** for direct, unrouted conversations.
- Reports its availability status (ready / busy / offline) on a **pinned status board** maintained by a coordinator bot.

This pattern mirrors the Telegram crew implementation (`parrot.integrations.telegram.crew`) but is adapted for Matrix's specific protocol features: Application Service virtual users, `m.replace` edit-based streaming, and room state events.

### Architecture Diagram

```
                     ┌────────────────────────────────────────┐
                     │         MatrixCrewTransport            │
                     │   (top-level orchestrator, lifecycle)   │
                     └──────────────────┬─────────────────────┘
                                        │
           ┌────────────────────────────┼─────────────────────────┐
           │                            │                         │
           ▼                            ▼                         ▼
┌─────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│  MatrixCoordinator  │   │  MatrixCrewRegistry  │   │  MatrixCrewConfig    │
│  (pinned status     │   │  (agent tracking,    │   │  (YAML config,       │
│   board, lifecycle  │   │   status, lookup)    │   │   per-agent entries) │
│   hooks)            │   │                      │   │                      │
└─────────────────────┘   └──────────────────────┘   └──────────────────────┘
           │                            │
           │              ┌─────────────┼─────────────┐
           │              │             │             │
           ▼              ▼             ▼             ▼
┌─────────────────────────────┐  ┌──────────┐  ┌──────────┐
│  MatrixCrewAgentWrapper     │  │ Wrapper2 │  │ WrapperN │
│  (per-agent: mention route, │  │          │  │          │
│   typing, status notify,    │  └──────────┘  └──────────┘
│   response chunking)        │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────┐
│                    MatrixAppService                          │
│  (virtual MXIDs, HTTP push, event routing from homeserver)  │
└─────────────────────────────────────────────────────────────┘
           │
    ┌──────┴──────┐
    ▼             ▼
┌────────┐   ┌────────┐
│ Agent  │   │ Agent  │   ... (dedicated rooms)
│ Room 1 │   │ Room 2 │
└────────┘   └────────┘
    └────┬────┘
         ▼
   ┌──────────┐
   │ General  │   (shared room — all agents + coordinator)
   │  Room    │
   └──────────┘
```

### Comparison with Telegram Crew

| Feature | Telegram Crew | Matrix Crew |
|---------|---------------|-------------|
| Per-agent identity | Separate bot tokens | Virtual MXIDs via AppService |
| Message routing | @username mention | @localpart mention or HTML pill |
| Status board | Pinned message (edited) | Pinned message (edited via m.replace) |
| Typing indicator | `sendChatAction` | `m.typing` via intent |
| Streaming | Message + edit | Edit-based (m.replace) |
| Config | YAML with env vars | YAML with env vars |
| Room model | Single group + private chats | General room + dedicated rooms |

---

## 2. Prerequisites

### 2.1 Matrix Homeserver

You need a running Matrix homeserver. We recommend **Synapse** (reference implementation):

```bash
# Install Synapse
pip install matrix-synapse

# Generate a basic config
python -m synapse.app.homeserver \
    --server-name example.com \
    --config-path /etc/synapse/homeserver.yaml \
    --generate-config \
    --report-stats=no
```

For a quick local development setup using Docker:

```bash
docker run -d \
  --name synapse \
  -p 8008:8008 \
  -v /data/synapse:/data \
  -e SYNAPSE_SERVER_NAME=localhost \
  -e SYNAPSE_REPORT_STATS=no \
  matrixdotorg/synapse:latest
```

### 2.2 Generating the Application Service Registration

The AS registration file tells Synapse how to route events to your crew. Generate it using AI-Parrot's registration utility:

```bash
# From your project root
python -m parrot.integrations.matrix.registration \
    --server-name example.com \
    --bot-localpart parrot-coordinator \
    --namespace-prefix "parrot-" \
    --output registration.yaml
```

This generates a file like:

```yaml
id: ai-parrot
url: http://localhost:8449   # AS HTTP listener — must be reachable by Synapse
as_token: <randomly-generated>
hs_token: <randomly-generated>
sender_localpart: parrot-coordinator
namespaces:
  users:
    - exclusive: true
      regex: "@parrot-.*:example.com"
  rooms: []
  aliases: []
```

**Save the `as_token` and `hs_token`** — you will need them in your `.env` or environment variables.

### 2.3 Registering the AS with Synapse

Add the registration file path to Synapse's `homeserver.yaml`:

```yaml
# homeserver.yaml
app_service_config_files:
  - /path/to/registration.yaml
```

Restart Synapse:

```bash
systemctl restart matrix-synapse
# or
docker restart synapse
```

### 2.4 Creating Rooms

Create the required rooms and note their IDs (format: `!<opaque>:<server>`):

```bash
# Using the Matrix Python SDK or curl
# General room — all agents will join this
curl -X POST \
  -H "Authorization: Bearer <coordinator_access_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "AI-Parrot Crew", "preset": "public_chat"}' \
  https://matrix.example.com/_matrix/client/v3/createRoom

# Agent dedicated rooms (one per agent with a dedicated room)
curl -X POST \
  -H "Authorization: Bearer <coordinator_access_token>" \
  -d '{"name": "Financial Analyst Room", "preset": "private_chat"}' \
  https://matrix.example.com/_matrix/client/v3/createRoom
```

Note the `room_id` from each response — you'll need them in the YAML config.

### 2.5 Environment Variables

Set the following before starting the crew:

| Variable | Description | Example |
|----------|-------------|---------|
| `MATRIX_HOMESERVER_URL` | Homeserver HTTP URL | `https://matrix.example.com` |
| `MATRIX_SERVER_NAME` | Server domain | `example.com` |
| `MATRIX_AS_TOKEN` | AS token from registration.yaml | `abc123...` |
| `MATRIX_HS_TOKEN` | HS token from registration.yaml | `xyz789...` |
| `MATRIX_GENERAL_ROOM_ID` | General room ID | `!abc:example.com` |
| `MATRIX_ANALYST_ROOM_ID` | Analyst's room ID | `!def:example.com` |
| `MATRIX_RESEARCHER_ROOM_ID` | Researcher's room ID | `!ghi:example.com` |

---

## 3. Configuration Reference

### 3.1 Root Config (`MatrixCrewConfig`)

```yaml
# matrix_crew.yaml
homeserver_url: "${MATRIX_HOMESERVER_URL}"   # Required
server_name: "${MATRIX_SERVER_NAME}"          # Required
as_token: "${MATRIX_AS_TOKEN}"                # Required
hs_token: "${MATRIX_HS_TOKEN}"                # Required
bot_mxid: "@parrot-coordinator:${MATRIX_SERVER_NAME}"  # Required
general_room_id: "${MATRIX_GENERAL_ROOM_ID}"  # Required
appservice_port: 8449                          # Default: 8449
pinned_registry: true                          # Default: true
typing_indicator: true                         # Default: true
streaming: false                               # Default: true
max_message_length: 4096                       # Default: 4096
unaddressed_agent: "general-assistant"         # Default: null (ignore)

agents:
  <agent_name>:
    <agent fields>
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `homeserver_url` | str | ✅ | — | Full URL of the Matrix homeserver |
| `server_name` | str | ✅ | — | Server domain (e.g. `example.com`) |
| `as_token` | str | ✅ | — | Application Service token |
| `hs_token` | str | ✅ | — | Homeserver token |
| `bot_mxid` | str | ✅ | — | Full MXID of the coordinator bot |
| `general_room_id` | str | ✅ | — | Shared room ID for all agents |
| `agents` | dict | ✅ | `{}` | Map of `agent_name → MatrixCrewAgentEntry` |
| `appservice_port` | int | ❌ | `8449` | HTTP port for the AS listener |
| `pinned_registry` | bool | ❌ | `true` | Pin status board in general room |
| `typing_indicator` | bool | ❌ | `true` | Show typing while processing |
| `streaming` | bool | ❌ | `true` | Use edit-based streaming |
| `unaddressed_agent` | str/null | ❌ | `null` | Default agent for unmentioned messages |
| `max_message_length` | int | ❌ | `4096` | Max chars per message before chunking |

### 3.2 Per-Agent Config (`MatrixCrewAgentEntry`)

```yaml
agents:
  analyst:                            # Internal name (used in routing)
    chatbot_id: "finance-analyst"     # Required — BotManager lookup key
    display_name: "Financial Analyst" # Required — shown in Matrix
    mxid_localpart: "analyst"         # Required — virtual MXID localpart
    avatar_url: null                  # Optional — mxc:// avatar URL
    dedicated_room_id: "!room:server" # Optional — private room ID
    skills:
      - "Stock analysis"              # Shown in status board
    tags:
      - "finance"                     # Routing tags (future use)
    file_types:
      - "image/png"                   # Accepted file MIME types
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `chatbot_id` | str | ✅ | BotManager key to resolve the agent |
| `display_name` | str | ✅ | Human-readable name in Matrix |
| `mxid_localpart` | str | ✅ | Localpart of the virtual MXID |
| `avatar_url` | str/null | ❌ | `mxc://` URL for the agent's avatar |
| `dedicated_room_id` | str/null | ❌ | Agent's private room ID |
| `skills` | list[str] | ❌ | Shown in the pinned status board |
| `tags` | list[str] | ❌ | Classification tags for routing |
| `file_types` | list[str] | ❌ | Accepted file MIME types |

### 3.3 Environment Variable Substitution

All string values in the YAML support `${ENV_VAR}` substitution:

```yaml
as_token: "${MATRIX_AS_TOKEN}"
general_room_id: "!${ROOM_LOCAL_ID}:${MATRIX_SERVER_NAME}"
```

Missing variables log a warning and are replaced with an empty string.

### 3.4 Example Configurations

#### Minimal (2 agents, no dedicated rooms)

```yaml
homeserver_url: "https://matrix.example.com"
server_name: "example.com"
as_token: "${MATRIX_AS_TOKEN}"
hs_token: "${MATRIX_HS_TOKEN}"
bot_mxid: "@coordinator:example.com"
general_room_id: "!general:example.com"
agents:
  assistant:
    chatbot_id: "general-bot"
    display_name: "Assistant"
    mxid_localpart: "assistant"
```

#### Full (3 agents with dedicated rooms + streaming)

See `matrix_crew.yaml` in this directory.

#### Large crew (5+ agents)

```yaml
homeserver_url: "https://matrix.example.com"
server_name: "example.com"
as_token: "${MATRIX_AS_TOKEN}"
hs_token: "${MATRIX_HS_TOKEN}"
bot_mxid: "@coordinator:example.com"
general_room_id: "!general:example.com"
unaddressed_agent: "orchestrator"
agents:
  analyst:
    chatbot_id: "finance-analyst"
    display_name: "Financial Analyst"
    mxid_localpart: "analyst"
    dedicated_room_id: "!analyst:example.com"
    skills: ["Stocks", "P/E ratios"]
  researcher:
    chatbot_id: "web-researcher"
    display_name: "Researcher"
    mxid_localpart: "researcher"
    dedicated_room_id: "!researcher:example.com"
    skills: ["Web search", "Summarization"]
  coder:
    chatbot_id: "code-assistant"
    display_name: "Code Assistant"
    mxid_localpart: "coder"
    dedicated_room_id: "!coder:example.com"
    skills: ["Python", "JavaScript", "SQL"]
  writer:
    chatbot_id: "content-writer"
    display_name: "Content Writer"
    mxid_localpart: "writer"
    skills: ["Blog posts", "Documentation"]
  orchestrator:
    chatbot_id: "orchestrator-bot"
    display_name: "Orchestrator"
    mxid_localpart: "orchestrator"
    skills: ["Task routing", "Planning"]
```

---

## 4. Architecture Deep Dive

### 4.1 Room Topology

```
┌─────────────────────────────────────────────────────────┐
│                    GENERAL ROOM                          │
│  Members: @coordinator, @analyst, @researcher, @assistant│
│  Pinned: Status Board (updated by coordinator)          │
│  Routing: @mention → specific agent                     │
│  Fallback: unaddressed messages → @assistant (default)  │
└─────────────────────────────────────────────────────────┘

┌──────────────┐  ┌──────────────┐
│  ANALYST ROOM│  │RESEARCHER ROOM│
│  Members:    │  │  Members:    │
│   @analyst   │  │   @researcher│
│   (+ users)  │  │   (+ users)  │
│  Direct chat │  │  Direct chat │
└──────────────┘  └──────────────┘
```

### 4.2 Message Flow — Shared Room with @mention

```
1. User sends: "@analyst What is AAPL's P/E ratio?"
2. Matrix homeserver pushes event to AS HTTP listener (port 8449)
3. MatrixAppService._handle_event() receives the m.room.message
4. MatrixCrewTransport.on_room_message() is called
5. Sender is NOT a virtual agent MXID → proceed
6. Room is NOT a dedicated room → proceed to mention check
7. parse_mention("@analyst ...", "example.com") → "analyst"
8. "analyst" matches config.agents["analyst"].mxid_localpart
9. MatrixCrewAgentWrapper("analyst").handle_message() is called:
   a. registry.update_status("analyst", "busy", "@analyst What is AAPL...")
   b. coordinator.on_status_change("analyst") → status board refresh
   c. asyncio.create_task(_send_typing(room_id))
   d. agent = BotManager.get_bot("finance-analyst")
   e. response = await agent.ask("@analyst What is AAPL's P/E ratio?")
   f. appservice.send_as_agent("analyst", room_id, response)
   g. registry.update_status("analyst", "ready")
   h. coordinator.on_status_change("analyst") → status board refresh
   i. typing_task.cancel()
```

### 4.3 Message Flow — Dedicated Room

```
1. User sends message in @analyst's dedicated room (no @mention needed)
2. Homeserver → MatrixAppService (HTTP push)
3. MatrixCrewTransport.on_room_message()
4. room_id in _room_to_agent → agent_name = "analyst"
5. MatrixCrewAgentWrapper("analyst").handle_message()
   (same as above, steps a–i)
```

### 4.4 Status Board Lifecycle

```
1. transport.start() → coordinator.start()
2. coordinator renders status board from registry.all_agents()
3. coordinator.client.send_text(general_room_id, board_text) → event_id
4. coordinator sets m.room.pinned_events with [event_id]
5. On any agent status change:
   a. registry.update_status() is called
   b. coordinator.on_status_change() is called
   c. coordinator.refresh_status_board() is called (rate-limited: min 0.5s)
   d. coordinator.client.edit_message(event_id, new_board_text)
6. transport.stop() → coordinator.stop() → sends shutdown notice
```

### 4.5 Virtual MXID Registration

The AS protocol allows the coordinator bot to create and control "virtual" Matrix users. The namespace is defined in `registration.yaml`:

```yaml
namespaces:
  users:
    - exclusive: true
      regex: "@parrot-.*:example.com"
```

For each agent, `MatrixAppService.register_agent()`:
1. Gets the `IntentAPI` for the agent's MXID via `appservice.intent.user(mxid)`.
2. Calls `intent.ensure_registered()` — creates the virtual user if it doesn't exist.
3. Sets the display name via `intent.set_displayname()`.

The AS then manages sending messages, setting typing state, and joining rooms for each virtual user.

---

## 5. Agent Setup

### 5.1 Defining Agents in BotManager

Each agent entry in the YAML references a `chatbot_id` that must be registered in `BotManager` before the crew starts:

```python
# In your main script or agent configuration

from parrot.manager import BotManager
from parrot.clients.openai import OpenAIClient
from parrot.bots.agent import Agent

# Create the LLM client
openai_client = OpenAIClient(model="gpt-4o")

# Create and register the financial analyst
analyst = Agent(
    name="finance-analyst",
    client=openai_client,
    system_prompt=(
        "You are a financial analyst specializing in equity research. "
        "Provide data-driven, concise analysis of stocks and markets."
    ),
)
BotManager.register("finance-analyst", analyst)

# Create and register the researcher
researcher = Agent(
    name="web-researcher",
    client=openai_client,
    system_prompt=(
        "You are a research assistant. Find and summarize information accurately. "
        "Always cite your sources when possible."
    ),
)
BotManager.register("web-researcher", researcher)

# Create and register the general assistant
general = Agent(
    name="general-bot",
    client=openai_client,
    system_prompt="You are a helpful general-purpose assistant.",
)
BotManager.register("general-bot", general)
```

For agents defined in `agents.yaml`, they are auto-loaded when BotManager initializes. The `chatbot_id` in the YAML must match the agent's name in `agents.yaml`.

### 5.2 Configuring Skills and Tags

**Skills** appear in the status board and help users know what each agent can do:

```yaml
agents:
  analyst:
    skills:
      - "Stock analysis and P/E ratios"
      - "Financial statement review"
      - "Market trend analysis"
```

The status board renders as:
```
[ready] @analyst -- Financial Analyst | Skills: Stock analysis and P/E ratios, ...
```

**Tags** are metadata for future routing features (regex-based routing, topic detection):

```yaml
agents:
  analyst:
    tags:
      - "finance"
      - "stocks"
      - "markets"
```

### 5.3 Setting Up Dedicated Rooms

Each agent can have a `dedicated_room_id` — a private Matrix room where all messages are routed to that agent without needing an `@mention`.

To create and configure a dedicated room:

```bash
# 1. Create the room (using Element or curl)
# 2. Note the room ID (!abc:example.com)
# 3. Set in config:
```

```yaml
agents:
  analyst:
    dedicated_room_id: "!analyst-room-id:example.com"
```

The crew will automatically:
- Join the coordinator bot to the room.
- Join the agent's virtual user to the room.
- Route all incoming messages in that room to that agent.

### 5.4 Avatar Configuration

Set a custom avatar for each agent using a `mxc://` URI (a Matrix Content Repository URL):

```yaml
agents:
  analyst:
    avatar_url: "mxc://example.com/AbCdEfGhIjKlMnOpQrStUv"
```

To upload an avatar to the Matrix media repository:

```python
import aiohttp

async def upload_avatar(homeserver: str, access_token: str, image_path: str) -> str:
    """Upload an image and return its mxc:// URI."""
    async with aiohttp.ClientSession() as session:
        with open(image_path, "rb") as f:
            data = f.read()
        response = await session.post(
            f"{homeserver}/_matrix/media/v3/upload",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "image/png",
            },
            data=data,
        )
        result = await response.json()
        return result["content_uri"]  # e.g. "mxc://example.com/AbCd..."
```

---

## 6. Running the Crew

### 6.1 Starting the Example Script

```bash
# Set environment variables
export MATRIX_HOMESERVER_URL=https://matrix.example.com
export MATRIX_SERVER_NAME=example.com
export MATRIX_AS_TOKEN=<your-as-token>
export MATRIX_HS_TOKEN=<your-hs-token>
export MATRIX_GENERAL_ROOM_ID=!general-room:example.com
export MATRIX_ANALYST_ROOM_ID=!analyst-room:example.com
export MATRIX_RESEARCHER_ROOM_ID=!researcher-room:example.com

# Run
cd examples/matrix_crew
python matrix_crew_example.py --config matrix_crew.yaml --log-level INFO
```

### 6.2 Programmatic Usage

```python
import asyncio
from parrot.integrations.matrix.crew import MatrixCrewTransport

async def main() -> None:
    async with MatrixCrewTransport.from_yaml("matrix_crew.yaml") as transport:
        print("Crew running!")
        await asyncio.sleep(3600)  # run for 1 hour

asyncio.run(main())
```

### 6.3 Verifying Agents are Online

When the crew starts successfully:
1. The coordinator bot posts a status board in the general room (pinned message).
2. All agents appear as members of the general room.
3. The status board shows all agents as `[ready]`.

Expected status board:
```
AI-Parrot Crew -- Agent Status

[ready] @analyst -- Financial Analyst | Skills: Stock analysis and P/E ratios, ...
[ready] @researcher -- Research Assistant | Skills: Web search and summarization, ...
[ready] @assistant -- General Assistant | Skills: General Q&A, Task routing

Last updated: 2026-03-11 14:32 UTC
```

### 6.4 Testing @mention Routing

In the general room:

```
You: @analyst what is AAPL's current P/E ratio?
analyst: AAPL's P/E ratio is currently approximately 28x trailing earnings...

You: @researcher find me recent papers on transformer architecture improvements
researcher: I found several recent papers on transformer improvements...

You: what time is it?
assistant: I'm sorry, I don't have real-time data, but I can help you with...
```

### 6.5 Testing Dedicated Room Conversations

In the analyst's dedicated room:
```
You: Can you explain what free cash flow yield means?
analyst: Free cash flow yield is a financial ratio that compares a company's...
```

No `@mention` is needed in the dedicated room.

### 6.6 Monitoring Logs

The crew logs to the root logger. Key log messages:

```
INFO  Matrix crew transport started — 3 agents online
INFO  Registered virtual user @analyst:example.com for agent 'analyst'
INFO  Agent 'analyst' joined room !general:example.com
INFO  Status board posted in !general:example.com (event: $abc123)
INFO  Agent 'analyst' handling message in !general from @user:example.com
DEBUG Agent 'analyst' status → busy (task: @analyst what is AAPL...)
DEBUG Status board refreshed
DEBUG Agent 'analyst' status → ready (task: None)
```

---

## 7. Advanced Usage

### 7.1 Adding New Agents to a Running Crew

Currently, adding agents requires restarting the crew. To minimize downtime:

```python
# Stop the crew gracefully
await transport.stop()

# Add new agent to config (programmatically or edit YAML)
transport._config.agents["data-scientist"] = MatrixCrewAgentEntry(
    chatbot_id="data-science-bot",
    display_name="Data Scientist",
    mxid_localpart="datascientist",
    skills=["Data analysis", "Machine learning"],
)

# Restart
await transport.start()
```

### 7.2 Custom Routing Logic

The default routing (dedicated room → @mention → default agent) can be extended by subclassing `MatrixCrewTransport`:

```python
from parrot.integrations.matrix.crew import MatrixCrewTransport, MatrixCrewConfig

class CustomCrewTransport(MatrixCrewTransport):
    """Custom transport with tag-based routing."""

    async def on_room_message(
        self, room_id: str, sender: str, body: str, event_id
    ) -> None:
        # Intercept messages containing finance keywords
        finance_keywords = ["stock", "market", "P/E", "earnings", "dividend"]
        if any(kw.lower() in body.lower() for kw in finance_keywords):
            wrapper = self._wrappers.get("analyst")
            if wrapper and room_id == self._config.general_room_id:
                await wrapper.handle_message(room_id, sender, body, str(event_id))
                return

        # Fall back to default routing
        await super().on_room_message(room_id, sender, body, event_id)
```

### 7.3 Inter-Agent Communication via A2A Transport

Agents within the crew can communicate with each other using `MatrixA2ATransport`:

```python
from parrot.integrations.matrix.crew import MatrixCrewTransport
from parrot.integrations.matrix import MatrixA2ATransport

# Each agent wrapper can send tasks to other agents
async def research_and_analyze(transport: MatrixCrewTransport) -> None:
    # Researcher agent delegates to analyst via A2A
    a2a = MatrixA2ATransport(
        client=transport._appservice.bot_intent,
        source_agent_id="web-researcher",
    )
    result = await a2a.send_task(
        target_agent_id="finance-analyst",
        task="Analyze the financial impact of AI adoption in tech companies",
        room_id="!inter-agent:example.com",
    )
    print(f"Analysis result: {result}")
```

### 7.4 Integrating with AgentCrew for Complex Workflows

`MatrixCrewTransport` operates at the chat-protocol level. For complex multi-step workflows, combine it with `AgentCrew`:

```python
from parrot.bots.orchestration.crew import AgentCrew
from parrot.integrations.matrix.crew import MatrixCrewTransport, MatrixCrewAgentWrapper

class EnhancedAgentWrapper(MatrixCrewAgentWrapper):
    """Agent wrapper that uses AgentCrew for complex queries."""

    def __init__(self, *args, crew: AgentCrew, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._crew = crew

    async def handle_message(
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        # For complex queries, run the full crew
        if "analyze" in body.lower() and len(body) > 100:
            result = await self._crew.run_sequential(body)
            # Send result instead of delegating to single agent
            await self._appservice.send_as_agent(
                self._agent_name, room_id, result.final_output
            )
        else:
            # Simple query — use default routing
            await super().handle_message(room_id, sender, body, event_id)
```

### 7.5 Hooks Integration

`MatrixCrewTransport` is compatible with AI-Parrot's hooks system. Attach listeners for logging or analytics:

```python
from parrot.core.hooks import HookRegistry, HookEvent

# Register a hook that fires on every crew message
@HookRegistry.on("matrix_crew.message_received")
async def log_crew_message(event: HookEvent) -> None:
    print(f"Agent {event.data['agent_name']} received: {event.data['body'][:50]}")
```

### 7.6 File Handling

For agents configured with `file_types`, implement file handling in a subclass:

```python
class FileAwareWrapper(MatrixCrewAgentWrapper):
    """Agent wrapper that handles file attachments."""

    async def handle_message(
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        # Check if this was a file event (passed via body or custom logic)
        if body.startswith("[FILE]"):
            # Extract file URL and process
            await self._process_file(room_id, body)
        else:
            await super().handle_message(room_id, sender, body, event_id)

    async def _process_file(self, room_id: str, file_info: str) -> None:
        """Download and process a Matrix file attachment."""
        # Implementation: download from MXC, call agent with file content
        ...
```

---

## 8. Production Deployment

### 8.1 Reverse Proxy Setup (nginx)

The AppService HTTP listener (port 8449) must be reachable by the Matrix homeserver. In production, use nginx as a reverse proxy:

```nginx
# /etc/nginx/sites-available/matrix-appservice
server {
    listen 443 ssl;
    server_name appservice.example.com;

    ssl_certificate /etc/letsencrypt/live/appservice.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/appservice.example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8449;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
    }
}
```

Update `registration.yaml` to use the HTTPS URL:

```yaml
url: https://appservice.example.com
```

### 8.2 TLS Configuration

Always use TLS in production. The homeserver communicates with the AS over HTTPS, and the AS receives push events from the homeserver.

```yaml
# registration.yaml (Synapse reads this)
url: https://appservice.example.com   # Use HTTPS!
```

### 8.3 Systemd Service

Run the crew as a systemd service for automatic restart and log management:

```ini
# /etc/systemd/system/matrix-crew.service
[Unit]
Description=AI-Parrot Matrix Multi-Agent Crew
After=network.target matrix-synapse.service
Requires=matrix-synapse.service

[Service]
Type=simple
User=aiparrot
WorkingDirectory=/opt/aiparrot/examples/matrix_crew
EnvironmentFile=/opt/aiparrot/.env
ExecStart=/opt/aiparrot/.venv/bin/python matrix_crew_example.py \
    --config matrix_crew.yaml \
    --log-level INFO
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=matrix-crew

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable matrix-crew
systemctl start matrix-crew
journalctl -u matrix-crew -f
```

### 8.4 Docker Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv pip install -e ".[matrix]" --system

COPY . .

CMD ["python", "examples/matrix_crew/matrix_crew_example.py", \
     "--config", "examples/matrix_crew/matrix_crew.yaml"]
```

```yaml
# docker-compose.yaml
version: "3.8"
services:
  matrix-crew:
    build: .
    restart: unless-stopped
    ports:
      - "8449:8449"
    environment:
      - MATRIX_HOMESERVER_URL=${MATRIX_HOMESERVER_URL}
      - MATRIX_SERVER_NAME=${MATRIX_SERVER_NAME}
      - MATRIX_AS_TOKEN=${MATRIX_AS_TOKEN}
      - MATRIX_HS_TOKEN=${MATRIX_HS_TOKEN}
      - MATRIX_GENERAL_ROOM_ID=${MATRIX_GENERAL_ROOM_ID}
      - MATRIX_ANALYST_ROOM_ID=${MATRIX_ANALYST_ROOM_ID}
      - MATRIX_RESEARCHER_ROOM_ID=${MATRIX_RESEARCHER_ROOM_ID}
    volumes:
      - ./logs:/app/logs
    networks:
      - matrix-network

networks:
  matrix-network:
    external: true
```

### 8.5 Monitoring and Alerting

**Prometheus metrics** (via a custom exporter):

```python
from prometheus_client import Gauge, Counter

crew_agents_ready = Gauge(
    "matrix_crew_agents_ready",
    "Number of agents in ready state"
)
crew_messages_total = Counter(
    "matrix_crew_messages_total",
    "Total messages processed by the crew",
    ["agent_name"]
)
```

**Health check endpoint** (add to your aiohttp server):

```python
from aiohttp import web

async def health_check(request: web.Request) -> web.Response:
    """Health check for the Matrix crew."""
    registry = request.app["matrix_crew"]._registry
    agents = await registry.all_agents()
    all_ready = all(a.status in ("ready", "busy") for a in agents)
    status = 200 if all_ready else 503
    return web.json_response(
        {
            "status": "ok" if all_ready else "degraded",
            "agents": [
                {"name": a.agent_name, "status": a.status}
                for a in agents
            ],
        },
        status=status,
    )
```

### 8.6 Scaling Considerations

- **Single homeserver**: All agents must be on the same homeserver (federation is not supported).
- **N agents**: The crew scales linearly. Each additional agent adds one virtual MXID and one `MatrixCrewAgentWrapper` coroutine.
- **Large crews (10+ agents)**: Consider collapsing idle agents in the status board to reduce clutter. The registry's `all_agents()` method can be filtered to show only active agents.
- **Message volume**: The AS HTTP listener handles all incoming events. For high-volume rooms, consider adding a message queue between the AS and the agent wrappers.

### 8.7 Backup and Recovery

- **AS tokens**: Store `as_token` and `hs_token` in a secrets manager (HashiCorp Vault, AWS Secrets Manager). Do not commit them to version control.
- **Registration file**: Back up `registration.yaml` — losing it means re-registering the AS with the homeserver and potentially losing virtual user history.
- **Room IDs**: Store room IDs in a configuration store (not just environment variables) so they survive homeserver restarts.

---

## 9. Troubleshooting

### 9.1 Agents Not Appearing in Matrix Room

**Symptom**: After starting the crew, virtual agents are not visible as members.

**Cause**: The AS is not registered with the homeserver, or the namespace regex doesn't match the agent MXIDs.

**Fix**:
1. Verify `registration.yaml` is listed in Synapse's `homeserver.yaml`:
   ```yaml
   app_service_config_files:
     - /path/to/registration.yaml
   ```
2. Restart Synapse after modifying `homeserver.yaml`.
3. Check the namespace regex matches your agent MXIDs:
   ```yaml
   namespaces:
     users:
       - exclusive: true
         regex: "@parrot-.*:example.com"  # Must match @analyst:example.com etc.
   ```
4. Verify the AS HTTP listener is reachable from the homeserver:
   ```bash
   curl -H "Authorization: Bearer <hs_token>" http://localhost:8449/health
   ```

### 9.2 "Agent not found in BotManager" Error

**Symptom**: Log shows `RuntimeError: Agent 'finance-analyst' not found in BotManager`.

**Cause**: The `chatbot_id` in the YAML doesn't match any registered agent.

**Fix**:
1. Verify the agent is registered before starting the crew:
   ```python
   from parrot.manager import BotManager
   agents = BotManager.list_bots()
   print(agents)  # Should include "finance-analyst"
   ```
2. If using `agents.yaml`, verify the agent name matches the `chatbot_id` in the crew YAML.

### 9.3 Status Board Not Updating

**Symptom**: The pinned status board shows stale data.

**Cause**: Rate limiting is preventing updates, or the coordinator can't edit the pinned message.

**Fix**:
1. Check the coordinator's `_rate_limit_interval` (default: 0.5s). For testing, set it to 0.
2. Verify the coordinator bot has permission to edit messages and send state events in the general room.
3. Check logs for `Failed to refresh status board` errors.

### 9.4 Messages Not Being Routed

**Symptom**: Sending `@analyst question` in the general room gets no response.

**Cause**: The mention is not being parsed correctly, or the routing logic doesn't match.

**Fix**:
1. Test mention parsing directly:
   ```python
   from parrot.integrations.matrix.crew.mention import parse_mention
   result = parse_mention("@analyst what is AAPL?", "example.com")
   print(result)  # Should be "analyst"
   ```
2. Verify the `mxid_localpart` in the agent config matches what you're @mentioning:
   ```yaml
   agents:
     analyst:
       mxid_localpart: "analyst"  # @analyst mentions route here
   ```
3. Enable DEBUG logging and look for "No routing match" messages.

### 9.5 Typing Indicator Not Showing

**Symptom**: The typing indicator (`...`) doesn't appear while the agent is processing.

**Cause**: The virtual agent's intent doesn't have permission to send `m.typing` in the room, or the `typing_indicator` config is set to false.

**Fix**:
1. Verify `typing_indicator: true` in the YAML config.
2. Check that the agent's virtual user has joined the room.
3. The `m.typing` event may require specific homeserver permissions — check Synapse logs.

### 9.6 Debug Logging

Enable detailed logging for the Matrix crew:

```python
import logging

# Show all crew module logs
logging.getLogger("parrot.integrations.matrix").setLevel(logging.DEBUG)
logging.getLogger("parrot.integrations.matrix.crew").setLevel(logging.DEBUG)

# Show mautrix (AS) protocol logs
logging.getLogger("mautrix").setLevel(logging.DEBUG)
```

Or via the CLI:
```bash
python matrix_crew_example.py --config matrix_crew.yaml --log-level DEBUG
```

### 9.7 Common Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: mautrix` | mautrix not installed | `uv pip install 'ai-parrot[matrix]'` |
| `ConnectionRefusedError` on start | Homeserver not reachable | Check `homeserver_url` and network |
| `401 Unauthorized` | Wrong AS token | Verify `as_token` matches `registration.yaml` |
| `403 Forbidden` | Bot not in room | Ensure coordinator was invited to the room |
| `ValidationError: homeserver_url` | Missing env var | Set `MATRIX_HOMESERVER_URL` |
| `FileNotFoundError: matrix_crew.yaml` | Config file not found | Run from correct directory or use `--config` |

---

## API Reference

### MatrixCrewTransport

The top-level orchestrator. Use this class to start and stop the crew.

```python
class MatrixCrewTransport:
    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewTransport": ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_room_message(self, room_id, sender, body, event_id) -> None: ...
    async def __aenter__(self) -> "MatrixCrewTransport": ...
    async def __aexit__(self, *exc) -> None: ...
```

### MatrixCrewRegistry

Thread-safe registry for tracking agent status.

```python
class MatrixCrewRegistry:
    async def register(self, card: MatrixAgentCard) -> None: ...
    async def unregister(self, agent_name: str) -> None: ...
    async def update_status(self, agent_name, status, current_task=None) -> None: ...
    async def get(self, agent_name: str) -> MatrixAgentCard | None: ...
    async def get_by_mxid(self, mxid: str) -> MatrixAgentCard | None: ...
    async def all_agents(self) -> list[MatrixAgentCard]: ...
```

### MatrixAgentCard

Pydantic model representing an agent's identity and runtime status.

```python
class MatrixAgentCard(BaseModel):
    agent_name: str
    display_name: str
    mxid: str           # @localpart:server
    status: str         # ready | busy | offline
    current_task: str | None
    skills: list[str]
    joined_at: datetime | None
    last_seen: datetime | None

    def to_status_line(self) -> str: ...
```

### Mention Utilities

```python
def parse_mention(body: str, server_name: str) -> str | None: ...
def format_reply(agent_mxid: str, display_name: str, text: str) -> str: ...
def build_pill(mxid: str, display_name: str) -> str: ...
```

---

## 10. Testing the Crew

### 10.1 Running Unit Tests

```bash
# From the repo root
source .venv/bin/activate
pytest tests/test_matrix_crew.py -v

# With coverage
pytest tests/test_matrix_crew.py -v --cov=parrot.integrations.matrix.crew \
    --cov-report=term-missing
```

### 10.2 Test Structure Overview

The test suite (`tests/test_matrix_crew.py`) covers 35 test cases:

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestMatrixCrewConfig` | 5 | Config loading, defaults, validation, YAML + env vars |
| `TestMentionParsing` | 7 | Plain text, pill HTML, no mention, wrong server |
| `TestMatrixCrewRegistry` | 6 | CRUD, concurrent access, MXID lookup |
| `TestAgentCardStatusLine` | 3 | Ready, busy (with task), offline rendering |
| `TestMatrixCoordinator` | 4 | Start/pin, refresh, rate limit, stop notice |
| `TestMatrixCrewAgentWrapper` | 4 | Chunk text: short, long, paragraph boundary, exact |
| `TestMessageRouting` | 6 | Dedicated room, @mention, default agent, self-ignore, coordinator refresh, lifecycle |

### 10.3 Writing Custom Tests

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.integrations.matrix.crew.registry import MatrixAgentCard, MatrixCrewRegistry
from parrot.integrations.matrix.crew.mention import parse_mention


@pytest.mark.asyncio
async def test_my_custom_routing() -> None:
    """Test custom routing logic."""
    registry = MatrixCrewRegistry()
    card = MatrixAgentCard(
        agent_name="analyst",
        display_name="Financial Analyst",
        mxid="@analyst:example.com",
    )
    await registry.register(card)

    # Test that a mention resolves correctly
    localpart = parse_mention("@analyst AAPL question", "example.com")
    assert localpart == "analyst"

    # Verify the agent exists in the registry
    agent = await registry.get("analyst")
    assert agent is not None
    assert agent.status == "ready"
```

### 10.4 Mock AppService Pattern

All integration tests use a mock `MatrixAppService` to avoid needing a real homeserver:

```python
@pytest.fixture
def mock_appservice():
    """Full mock of MatrixAppService for integration tests."""
    appservice = MagicMock()

    # Intent that virtual agents use for sending messages
    mock_intent = AsyncMock()
    mock_intent.send_text = AsyncMock(return_value="$event001")
    mock_intent.set_typing = AsyncMock()
    mock_intent.ensure_joined = AsyncMock()
    mock_intent.send_message = AsyncMock(return_value="$event002")

    appservice._get_intent = MagicMock(return_value=mock_intent)
    appservice.bot_intent = mock_intent
    appservice.send_as_agent = AsyncMock(return_value="$event003")
    appservice.send_as_bot = AsyncMock(return_value="$event004")
    appservice.register_agent = AsyncMock(
        side_effect=lambda name, _: f"@{name}:example.com"
    )
    appservice.ensure_agent_in_room = AsyncMock()
    appservice.set_event_callback = MagicMock()
    appservice.start = AsyncMock()
    appservice.stop = AsyncMock()

    return appservice
```

---

## 11. Security Considerations

### 11.1 Token Management

**Never** commit AS tokens to version control. Use environment variables or a secrets manager:

```bash
# Using HashiCorp Vault
export MATRIX_AS_TOKEN=$(vault kv get -field=as_token secret/matrix-crew)
export MATRIX_HS_TOKEN=$(vault kv get -field=hs_token secret/matrix-crew)

# Using AWS Secrets Manager
export MATRIX_AS_TOKEN=$(aws secretsmanager get-secret-value \
    --secret-id matrix-crew/as-token --query SecretString --output text)
```

### 11.2 AS Namespace Isolation

The Application Service namespace should be as restrictive as possible:

```yaml
# registration.yaml — GOOD: restrictive namespace
namespaces:
  users:
    - exclusive: true
      regex: "@_parrot_[a-z]+:example\\.com"  # Only specific localparts
```

```yaml
# registration.yaml — BAD: overly broad namespace
namespaces:
  users:
    - exclusive: true
      regex: ".*"  # This would claim ALL users!
```

### 11.3 Rate Limiting

Matrix homeservers impose rate limits on:
- Message sending (typically 50/min per user)
- State event updates
- Typing notifications

The crew's rate-limited status board (`rate_limit_interval=0.5`) helps avoid hitting limits. For high-traffic deployments, consider increasing this interval.

### 11.4 Input Validation

Messages from Matrix clients are passed directly to `agent.ask()`. Implement input validation to prevent prompt injection:

```python
class SafeCrewAgentWrapper(MatrixCrewAgentWrapper):
    """Agent wrapper with basic input sanitization."""

    MAX_INPUT_LENGTH = 2000
    BLOCKED_PATTERNS = ["<script>", "system prompt:", "ignore previous"]

    async def handle_message(
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        # Truncate oversized inputs
        if len(body) > self.MAX_INPUT_LENGTH:
            body = body[:self.MAX_INPUT_LENGTH] + "... [truncated]"

        # Block suspicious patterns
        body_lower = body.lower()
        for pattern in self.BLOCKED_PATTERNS:
            if pattern in body_lower:
                self.logger.warning(
                    "Blocked suspicious message from %s: %s", sender, pattern
                )
                return

        await super().handle_message(room_id, sender, body, event_id)
```

### 11.5 Access Control

By default, any Matrix user in the room can interact with agents. To restrict access:

```python
class AccessControlledTransport(MatrixCrewTransport):
    """Transport that restricts which users can interact with agents."""

    ALLOWED_USERS = {"@alice:example.com", "@bob:example.com"}

    async def on_room_message(
        self, room_id: str, sender: str, body: str, event_id
    ) -> None:
        if sender not in self.ALLOWED_USERS:
            self.logger.debug("Ignoring message from unauthorized user %s", sender)
            return
        await super().on_room_message(room_id, sender, body, event_id)
```

---

## 12. Performance Tuning

### 12.1 Response Chunking

For agents that produce long responses, tuning `max_message_length` affects user experience:

| Value | Effect |
|-------|--------|
| `1000` | More, shorter messages — better for mobile clients |
| `4096` | Fewer, longer messages — default |
| `8192` | Very long messages — may truncate in some clients |

The chunking algorithm prefers:
1. Paragraph breaks (`\n\n`)
2. Line breaks (`\n`)
3. Sentence endings (`. `)
4. Hard character limit as fallback

### 12.2 Typing Indicator Timing

The typing indicator background task sends `m.typing` every 10 seconds. For slow agents (>30s response time), increase the interval:

```python
class SlowAgentWrapper(MatrixCrewAgentWrapper):
    """Wrapper for slow agents with extended typing interval."""

    async def _send_typing(self, room_id: str) -> None:
        try:
            intent = self._appservice._get_intent(self._mxid)
            from mautrix.types import RoomID
            while True:
                await intent.set_typing(RoomID(room_id), timeout=60000)  # 60s
                await asyncio.sleep(45)  # Refresh every 45s
        except asyncio.CancelledError:
            await intent.set_typing(RoomID(room_id), typing=False)
```

### 12.3 Concurrent Message Processing

By default, each `handle_message()` call is awaited sequentially per agent. To allow concurrent processing for the same agent (e.g., different rooms):

```python
class ConcurrentAgentWrapper(MatrixCrewAgentWrapper):
    """Wrapper that handles multiple messages concurrently."""

    def __init__(self, *args, max_concurrent: int = 3, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def handle_message(
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        async with self._semaphore:
            await super().handle_message(room_id, sender, body, event_id)
```

### 12.4 Registry Performance

The `MatrixCrewRegistry` uses `asyncio.Lock` for thread safety. For very large crews (50+ agents), consider using a read-write lock to allow concurrent reads:

```python
import asyncio

class HighPerformanceRegistry(MatrixCrewRegistry):
    """Registry optimized for high-read, low-write scenarios."""

    def __init__(self) -> None:
        super().__init__()
        self._read_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._readers = 0

    async def get(self, agent_name: str):
        # Allow concurrent reads
        async with self._read_lock:
            self._readers += 1
        try:
            return self._agents.get(agent_name)
        finally:
            async with self._read_lock:
                self._readers -= 1
```

---

## 13. Migration Guide

### 13.1 Migrating from Single-Agent Matrix Integration

If you're currently using `MatrixClientWrapper` for a single agent and want to migrate to the crew model:

**Before** (single agent):
```python
from parrot.integrations.matrix import MatrixClientWrapper

client = MatrixClientWrapper(
    homeserver="https://matrix.example.com",
    mxid="@mybot:example.com",
    access_token="<token>",
)
await client.connect()
# ... manual event handling
```

**After** (crew with one agent):
```yaml
# matrix_crew.yaml
homeserver_url: "https://matrix.example.com"
server_name: "example.com"
as_token: "${MATRIX_AS_TOKEN}"
hs_token: "${MATRIX_HS_TOKEN}"
bot_mxid: "@coordinator:example.com"
general_room_id: "!myroom:example.com"
agents:
  mybot:
    chatbot_id: "my-agent"
    display_name: "My Bot"
    mxid_localpart: "mybot"
```

```python
from parrot.integrations.matrix.crew import MatrixCrewTransport

async with MatrixCrewTransport.from_yaml("matrix_crew.yaml") as crew:
    await asyncio.sleep(float("inf"))
```

### 13.2 Migrating from Telegram Crew

The Matrix crew mirrors the Telegram crew structure. Key differences:

| Telegram | Matrix | Notes |
|----------|--------|-------|
| `TelegramCrewConfig` | `MatrixCrewConfig` | Very similar structure |
| `CrewAgentEntry.bot_token` | `MatrixCrewAgentEntry.mxid_localpart` | Different auth model |
| `CrewAgentEntry.username` | `MatrixCrewAgentEntry.mxid_localpart` | Same concept |
| `CrewRegistry` | `MatrixCrewRegistry` | Same interface |
| `CoordinatorBot` | `MatrixCoordinator` | Same concept |
| `TelegramCrewTransport` | `MatrixCrewTransport` | Same interface |

---

*Generated by AI-Parrot SDD — FEAT-044: Matrix Multi-Agent Crew Integration*
*Version 1.6.0 — 2026-03-11*
