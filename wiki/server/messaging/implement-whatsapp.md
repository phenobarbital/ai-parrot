---
title: "WhatsApp Integration Implementation Summary"
---

# WhatsApp Integration - Implementation Summary

## 📋 Executive Summary

I have implemented a complete WhatsApp integration for AI-Parrot that lets you:

1. **Send messages** from agents using `WhatsAppTool`
2. **Receive messages** as commands using `WhatsAppHook`
3. **Generate a QR code** for web authentication (no Facebook App needed)
4. **Integrate** easily with your existing `AutonomousOrchestrator`

## 🏗️ Implemented Architecture

```
┌─────────────────────────────────────────────────────────┐
│  AI-Parrot (Python/aiohttp)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ WhatsAppTool │  │ WhatsAppHook │  │ Orchestrator │  │
│  │ (Send)       │  │ (Receive)    │  │ Hook         │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │ HTTP              │ Redis            │         │
└─────────┼───────────────────┼──────────────────┼─────────┘
          │                   │                  │
          ▼                   ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│  WhatsApp Bridge (Go/whatsmeow)                         │
│  • Persistent session management (SQLite)               │
│  • QR authentication (web + terminal)                   │
│  • WebSocket for real-time QR                           │
│  • HTTP API for sending messages                        │
│  • Redis Pub/Sub for incoming messages                  │
└─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│  WhatsApp (using the official protocol)                 │
└─────────────────────────────────────────────────────────┘
```

## 📁 Files Created

### 1. **Go Infrastructure (WhatsApp Bridge)**
```
services/whatsapp-bridge/
├── main.go              # Complete bridge implementation
├── go.mod               # Go dependencies
├── Dockerfile           # Multi-stage Docker image
└── README.md
```

**Bridge features:**
- ✅ QR authentication with a web interface
- ✅ Persistent session in SQLite
- ✅ WebSocket for real-time updates
- ✅ REST API for sending messages
- ✅ Redis Pub/Sub for incoming messages
- ✅ Support for text, images, videos, documents
- ✅ Health check endpoint
- ✅ Group handling

### 2. **Python Integration (AI-Parrot)**

```
parrot/
├── tools/messaging/
│   └── whatsapp.py      # WhatsAppTool - Send messages
├── hooks/
│   └── whatsapp.py      # WhatsAppHook & WhatsAppOrchestratorHook
└── conf/
    └── whatsapp.py      # Configuration

examples/
└── whatsapp_integration.py  # 5 complete examples
```

**Python features:**
- ✅ `WhatsAppTool`: Tool for sending messages from agents
- ✅ `WhatsAppHook`: Hook for receiving messages (similar to webhooks)
- ✅ `WhatsAppOrchestratorHook`: Multi-agent router
- ✅ Filtering by phone number
- ✅ Filtering by group
- ✅ Configurable command prefixes
- ✅ Optional auto-reply
- ✅ Custom callbacks

### 3. **Build & Deploy**

```
Makefile                 # Make commands for install/build/run
docker-compose.yml       # Full stack (Redis + Bridge + AI-Parrot)
scripts/
└── whatsapp-quickstart.sh  # Quick start script
```

### 4. **Documentation**

```
docs/
└── WHATSAPP.md          # Complete usage guide
```

## 🚀 Installation and Usage

### Option 1: Local

```bash
# 1. Install Go
make install-go

# 2. Build the bridge
make build-whatsapp-bridge

# 3. Run
make run-whatsapp-bridge

# 4. Authenticate
# Open http://localhost:8765/qr
# Scan the QR code with WhatsApp
```

### Option 2: Docker (Recommended)

```bash
# Everything in one command
docker-compose up -d

# View logs and get the QR code
docker-compose logs -f whatsapp-bridge

# Or visit http://localhost:8765/qr
```

### Option 3: Quick Script

```bash
./scripts/whatsapp-quickstart.sh
# Choose option 1 (local) or 2 (Docker)
```

## 💡 Implemented Use Cases

### 1. **Agent that sends messages**

```python
from parrot.tools.messaging.whatsapp import WhatsAppTool

agent.tool_manager.add_tool(WhatsAppTool())

# The agent can now:
await agent.ask("Envía un WhatsApp a +14155552671 diciendo que el reporte está listo")
```

### 2. **Agent that receives commands via WhatsApp**

```python
from parrot.hooks.whatsapp import WhatsAppHook

hook = WhatsAppHook(
    agent=my_agent,
    allowed_phones=["14155552671"],  # Only this number
    command_prefix="!",  # Requires ! at the start
    auto_reply=True
)
await hook.start()

# Now send from WhatsApp:
# "!analiza las ventas de Q4"
```

### 3. **Multi-Agent Router over WhatsApp**

```python
from parrot.hooks.whatsapp import WhatsAppOrchestratorHook

hook = WhatsAppOrchestratorHook(orchestrator, default_agent)

# Routing by keywords
hook.register_route("sales", sales_agent, keywords=["precio", "compra"])
hook.register_route("soporte", support_agent, keywords=["ayuda", "error"])

# Routing by phone (VIP)
hook.register_route("vip", vip_agent, phones=["14155551234"])

await hook.start()
```

### 4. **Integration with the existing AutonomousOrchestrator**

```python
# If you already have webhooks, MQTT, RabbitMQ...
from parrot.hooks.whatsapp import WhatsAppHook

# Just add WhatsApp as another channel:
whatsapp_hook = WhatsAppHook(
    agent=orchestrator,
    command_prefix="/",
    auto_reply=True
)
await whatsapp_hook.start()

# Now the orchestrator receives commands from:
# - WhatsApp ✅
# - Webhooks ✅
# - MQTT ✅
# - RabbitMQ ✅
```

## 🔧 Configuration

### Environment Variables

```bash
# .env
WHATSAPP_BRIDGE_ENABLED=true
WHATSAPP_BRIDGE_URL=http://localhost:8765
REDIS_SERVICES_URL=redis://localhost:6379

# Security (optional)
WHATSAPP_ALLOWED_PHONES=14155552671,34612345678
WHATSAPP_ALLOWED_GROUPS=MiGrupo,OtroGrupo
WHATSAPP_COMMAND_PREFIX=!
```

### In `parrot/conf/__init__.py`

Add this snippet (it is already in `parrot/conf/whatsapp_config_snippet.py`):

```python
# WhatsApp Bridge Configuration
WHATSAPP_BRIDGE_ENABLED = config.getboolean('WHATSAPP_BRIDGE_ENABLED', fallback=True)
WHATSAPP_BRIDGE_URL = config.get('WHATSAPP_BRIDGE_URL', fallback='http://localhost:8765')
# ... (see the full file)
```

## 🎯 Advantages of this Implementation

### vs. wacli (OpenClaw)
- ✅ **Same authentication flow** (simple QR)
- ✅ **Native integration** in Python with your architecture
- ✅ **Bidirectional** from the start
- ✅ **Scalable** (multiple AI-Parrot instances, a single bridge)

### vs. pywa (Facebook API)
- ✅ **No Facebook App** needed
- ✅ **No approval** required
- ✅ **Setup in minutes** vs. days/weeks
- ✅ **Free** (no API limits)

### vs. whatsapp-web.py (Selenium)
- ✅ **Faster** (no browser needed)
- ✅ **More robust** (whatsmeow is very stable)
- ✅ **Fewer resources** (Go is more efficient)
- ✅ **Better for production**

## 📊 Message Flow

### Incoming Message (WhatsApp → Agent)

```
User sends a WhatsApp message
        ↓
WhatsApp Bridge (whatsmeow)
        ↓
Redis Pub/Sub (channel: whatsapp:messages)
        ↓
WhatsAppHook (Python)
        ↓
Agent.ask() processes the message
        ↓
Agent generates a response
        ↓
WhatsAppTool sends the response
        ↓
Bridge → WhatsApp
        ↓
User receives the response
```

### Outgoing Message (Agent → WhatsApp)

```
Agent decides to send a message
        ↓
WhatsAppTool.execute(phone, message)
        ↓
HTTP POST to /send
        ↓
WhatsApp Bridge
        ↓
whatsmeow sends
        ↓
User receives
```

## 🔐 Authentication

1. **First time**: Scan the QR code at http://localhost:8765/qr
2. **Session saved** in `data/whatsapp/whatsapp.db`
3. **No re-scan required** on restart
4. **Persistent** even in Docker (with a mounted volume)

## 🐛 Troubleshooting

### Bridge does not connect
```bash
# View logs
docker-compose logs -f whatsapp-bridge

# Or if running locally
./bin/whatsapp-bridge
```

### Messages do not reach the agent
```bash
# Check Redis Pub/Sub
redis-cli SUBSCRIBE whatsapp:messages

# Check that the hook is running
# (this log should appear: "WhatsApp hook started for agent 'X'")
```

### QR code does not appear
```bash
# Check that the bridge is running
curl http://localhost:8765/health

# It should respond with:
# {"success":true,"data":{"connected":false,"authenticated":false,"logged_in":false}}
```

## 📝 Next Steps

1. **Review the code** in the generated files
2. **Test locally** with `make run-whatsapp-bridge`
3. **Authenticate** by scanning the QR code
4. **Run the examples** in `examples/whatsapp_integration.py`
5. **Integrate** with your existing agents

## 📚 Files to Review

1. `docs/WHATSAPP.md` - Complete documentation
2. `examples/whatsapp_integration.py` - 5 usage examples
3. `services/whatsapp-bridge/main.go` - Bridge implementation
4. `parrot/tools/messaging/whatsapp.py` - Tool for sending
5. `parrot/hooks/whatsapp.py` - Hooks for receiving
6. `Makefile` - Build/install commands
7. `docker-compose.yml` - Full stack

## 🎉 Ready to Use!

```bash
# Fastest option:
./scripts/whatsapp-quickstart.sh

# Or manually:
make install-go
make build-whatsapp-bridge
make run-whatsapp-bridge

# Then:
# 1. Open http://localhost:8765/qr
# 2. Scan the QR code with WhatsApp
# 3. Run your agents
```

---

**Questions?** See `docs/WHATSAPP.md` for more details.
