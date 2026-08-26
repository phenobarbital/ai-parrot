# Matrix Swarm Sample — Multi-Provider Agent Demo

A runnable, self-contained example of a 4-agent swarm using different LLM providers (OpenAI, Anthropic, Google Gemini, NVIDIA) collaborating via a local Matrix homeserver.

**Goal**: Go from `git clone` to running agents on Matrix in < 10 minutes.

## Overview

This sample demonstrates:
- **4 specialized agents** with different LLM providers and roles
- **Multi-LLM vendor-agnostic architecture** — seamless switching between OpenAI, Anthropic, Google, and NVIDIA
- **Collaborative sessions** — agents ask each other questions via private tunnels
- **Swarm answer policies** — channels with different routing rules (swarm vs. mention-only)
- **Local Matrix dev stack** — a complete Synapse homeserver with Postgres, Element Web, and bridges in Docker Compose

## Prerequisites

- **Docker + Docker Compose** (≥24.0) — for the Matrix homeserver stack
- **Python 3.11+** — for the demo script and AI-Parrot
- **`uv` package manager** (or `pip`) — for dependency installation
- **API Keys** for all 4 LLM providers:
  - [OpenAI](https://platform.openai.com/api-keys) — gpt-4o
  - [Anthropic](https://console.anthropic.com/keys) — claude-sonnet-4-20250514
  - [Google GenAI](https://ai.google.dev/) — gemini-2.5-flash
  - [NVIDIA API](https://docs.nvidia.com/nim/llama-2/) — meta/llama-3.3-70b-instruct
- **Network access** — ports 8008 (Synapse), 8080 (Element), 8449 (appservice) must be available

## Quick Start

### 1. Install AI-Parrot and Dependencies

From the repo root:
```bash
uv pip install -e ".[all]"
```

Or with pip:
```bash
pip install -e ".[all]"
```

### 2. Bootstrap the Matrix Stack

Run the automated setup script (one-time only):
```bash
cd ../../  # back to repo root
bash scripts/matrix/bootstrap.sh
```

This generates:
- `registration.yaml` — appservice registration file
- Application Service token
- Homeserver token
- Creates initial Matrix rooms

**Alternative**: use the Makefile from `examples/matrix_swarm/`:
```bash
make -C examples/matrix_swarm setup
```

### 3. Start the Matrix Homeserver

```bash
docker compose -f docker-compose.matrix.yml up -d
```

This starts:
- **Synapse** (homeserver, port 8008)
- **Postgres** (database)
- **Element Web** (client UI, port 8080)
- **Bridges** (Signal, Slack, Discord — optional)

**Alternative**:
```bash
make -C examples/matrix_swarm start
```

Wait for services to be healthy:
```bash
docker compose -f docker-compose.matrix.yml logs -f synapse
```

You'll see: `INFO synapse.server: Synapse v... starting`

### 4. Configure Environment Variables

Copy the template and edit with your API keys and Matrix tokens:
```bash
cd examples/matrix_swarm
cp .env.example .env
```

Open `.env` and fill in:
- **Matrix Tokens** (from bootstrap output):
  - `MATRIX_AS_TOKEN`
  - `MATRIX_HS_TOKEN`
  - `MATRIX_GENERAL_ROOM_ID`
- **LLM API Keys**:
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `GOOGLE_API_KEY`
  - `NVIDIA_API_KEY`

### 5. Run the Demo

```bash
python swarm_demo.py
```

You'll see logs like:
```
2026-08-26 14:32:10 [INFO] __main__: Loading agents from agents.yaml
2026-08-26 14:32:10 [INFO] __main__: Found 4 agent(s)
2026-08-26 14:32:10 [INFO] __main__: Creating agent web-researcher (llm=openai:gpt-4o, tools=WikiToolkit,WorkingMemoryToolkit)
2026-08-26 14:32:10 [INFO] __main__: ✓ Registered agent web-researcher
...
2026-08-26 14:32:12 [INFO] __main__: Matrix swarm is running. Press Ctrl+C to stop.
```

### 6. Interact with Agents

Open **Element Web** in your browser:
```
http://localhost:8080
```

- **Username**: `@parrot-admin:parrot.local` (or any user you created)
- **Password**: Set during bootstrap

Join the **#general** room and send a message:
```
What are the top AI trends this year?
```

All 4 agents will collaborate:
1. **Researcher** (OpenAI) gathers recent info
2. **Analyst** (Anthropic) analyzes trends
3. **Writer** (Google) drafts insights
4. **Synthesizer** (NVIDIA) produces a final summary

## Architecture

```
┌─────────────────────────────────────────┐
│          Element Web (Matrix UI)         │
│        http://localhost:8080            │
└──────────────────┬──────────────────────┘
                   │ Messages
                   ▼
┌─────────────────────────────────────────┐
│       Synapse Homeserver (8008)          │
│    Channels, Rooms, Permissions          │
└──────────────────┬──────────────────────┘
                   │ Matrix Rooms
          ┌────────┴───────────┐
          ▼                    ▼
┌──────────────────┐  ┌───────────────────┐
│  MatrixCrew      │  │  Private Tunnels  │
│  Transport       │  │  (agent-to-agent) │
└────────┬─────────┘  └──────────────────┘
         │
    ┌────┴──────────────────────┬────────────────────────┐
    ▼                           ▼                        ▼
┌─────────────┐         ┌────────────────┐     ┌──────────────┐
│  Web        │         │  Financial     │     │  Report      │
│  Researcher │         │  Analyst       │     │  Writer      │
│  OpenAI     │         │  Anthropic     │     │  Google      │
│  gpt-4o     │         │  claude-sonnet │     │  gemini-2.5  │
└─────────────┘         └────────────────┘     └──────────────┘

    ┌────────────────┐
    │  Synthesizer   │
    │  NVIDIA        │
    │  llama-70b     │
    └────────────────┘
```

## Agent Profiles

| Agent | Chatbot ID | LLM Provider | Models | Tools | Role |
|-------|----------|---------|--------|-------|------|
| **Researcher** | `web-researcher` | OpenAI | gpt-4o | WikiToolkit, WorkingMemoryToolkit | Searches & compiles research |
| **Analyst** | `financial-analyst` | Anthropic | claude-sonnet-4-20250514 | WikiToolkit, WorkingMemoryToolkit | Analyzes trends & metrics |
| **Writer** | `report-writer` | Google | gemini-2.5-flash | *(none — pure LLM)* | Synthesizes findings into prose |
| **Synthesizer** | `synthesis-agent` | NVIDIA | meta/llama-3.3-70b-instruct | *(none — pure LLM)* | Integrates perspectives & concludes |

## Environment Variables

| Variable | Source | Example | Purpose |
|----------|--------|---------|---------|
| `MATRIX_AS_TOKEN` | `scripts/matrix/bootstrap.sh` output | `syt_...` | Appservice token for Matrix auth |
| `MATRIX_HS_TOKEN` | `scripts/matrix/bootstrap.sh` output | `hs_token_...` | Homeserver token for verification |
| `MATRIX_GENERAL_ROOM_ID` | `scripts/matrix/bootstrap.sh` output or Element | `!abcd1234:parrot.local` | Room ID of general/swarm channel |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/api-keys) | `sk-proj-...` | OpenAI API key (gpt-4o) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/keys) | `sk-ant-...` | Anthropic API key (Claude) |
| `GOOGLE_API_KEY` | [ai.google.dev](https://ai.google.dev/) | `AIzaSy...` | Google GenAI API key (Gemini) |
| `NVIDIA_API_KEY` | [NVIDIA docs](https://docs.nvidia.com/nim/llama-2/) | `nvapi-...` | NVIDIA NIM API key (Llama) |

## Makefile Targets

Convenience commands for lifecycle management:

```bash
# One-time setup (bootstraps Matrix homeserver)
make -C examples/matrix_swarm setup

# Start the Matrix stack (Synapse + Postgres + Element)
make -C examples/matrix_swarm start

# Stop the Matrix stack (services remain, volumes preserved)
make -C examples/matrix_swarm stop

# Tail logs from all services
make -C examples/matrix_swarm logs

# Run the swarm demo (requires .env configured)
make -C examples/matrix_swarm demo

# Stop and completely remove containers + volumes (full cleanup)
make -C examples/matrix_swarm clean
```

## Troubleshooting

### "Port 8008 already in use"
Another service is using the Synapse port. Either stop it or change the port in `docker-compose.matrix.yml`:
```bash
netstat -tlnp | grep 8008
kill <PID>
```

### "API key is invalid" (OpenAI, Anthropic, etc.)
Check that your `.env` file is correctly populated with valid API keys. Test one:
```bash
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('OPENAI_API_KEY' in os.environ and 'Set!')"
```

### "Matrix homeserver is not running"
Verify services are up:
```bash
docker compose -f docker-compose.matrix.yml ps
```

If Synapse is down, restart:
```bash
docker compose -f docker-compose.matrix.yml up synapse -d
```

### "Room not found" or agents not responding
Ensure:
1. `MATRIX_GENERAL_ROOM_ID` is correct (find in Element → room settings → Advanced → Room ID)
2. All agent chatbot_ids in `swarm_config.yaml` match `agents.yaml`
3. Agents are successfully registered (check logs: `grep "Registered agent"`)

### "docker compose: command not found"
Install Docker Compose v2 (bundled with Docker Desktop ≥4.0):
```bash
docker compose version
```

Or use legacy syntax:
```bash
docker-compose -f docker-compose.matrix.yml up -d
```

## See Also

- **[MATRIX_CREW_GUIDE.md](../matrix_crew/MATRIX_CREW_GUIDE.md)** — comprehensive guide to the Matrix integration (FEAT-463)
- **[docker-compose.matrix.yml](../../docker-compose.matrix.yml)** — full service definitions and network configuration
- **[scripts/matrix/bootstrap.sh](../../scripts/matrix/bootstrap.sh)** — setup script source
- **[FEAT-463 spec](../../sdd/specs/matrix-agents-swarm.spec.md)** — core swarm module architecture
- **[AI-Parrot docs](../../docs/)** — full framework documentation

## Contributing

Found a bug or want to extend the sample? PRs welcome!

**Development workflow**:
1. Fork and create a feature branch
2. Test with `make -C examples/matrix_swarm setup start`
3. Update agents.yaml or swarm_config.yaml as needed
4. Run `make demo` and verify in Element
5. Submit a PR

---

**Happy swarming! 🤖**
