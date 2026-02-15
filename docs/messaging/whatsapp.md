# WhatsApp Integration for AI-Parrot

Complete WhatsApp integration using **whatsmeow** (Go) bridge with Python hooks for autonomous agents.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      AI-Parrot Application                   │
│  ┌────────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │ WhatsAppTool   │  │WhatsAppHook │  │ Orchestrator    │  │
│  │ (Send msgs)    │  │ (Receive)   │  │ Hook            │  │
│  └────────┬───────┘  └──────┬──────┘  └────────┬────────┘  │
│           │ HTTP             │ Redis             │          │
└───────────┼──────────────────┼───────────────────┼──────────┘
            │                  │                   │
            ▼                  ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    WhatsApp Bridge (Go)                      │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                     whatsmeow                         │   │
│  │  - Session Management                                 │   │
│  │  - QR Authentication                                  │   │
│  │  - Message Routing                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────┐                        │
│  │      SQLite (Sessions)          │                        │
│  └─────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│                      WhatsApp Servers                        │
└─────────────────────────────────────────────────────────────┘
```

## 📦 Components

### 1. WhatsApp Bridge (Go)
- **Location**: `services/whatsapp-bridge/`
- **Technology**: Go 1.22 + whatsmeow
- **Purpose**: Handles WhatsApp protocol, authentication, and message delivery
- **Endpoints**:
  - `GET /health` - Health check
  - `POST /send` - Send message
  - `GET /qr` - QR code page
  - `GET /qr.png` - QR code image
  - `WS /ws` - WebSocket for QR updates

### 2. WhatsAppTool (Python)
- **Location**: `parrot/tools/messaging/whatsapp.py`
- **Purpose**: Send WhatsApp messages from agents
- **Usage**: Add to agent's tool manager

### 3. WhatsAppHook (Python)
- **Location**: `parrot/hooks/whatsapp.py`
- **Purpose**: Receive WhatsApp messages for autonomous agents
- **Features**:
  - Phone number filtering
  - Command prefix support
  - Auto-reply
  - Custom callbacks

### 4. WhatsAppOrchestratorHook (Python)
- **Location**: `parrot/hooks/whatsapp.py`
- **Purpose**: Route messages to different agents based on keywords/phone
- **Features**:
  - Keyword-based routing
  - Phone-based routing
  - Multi-agent support

## 🚀 Quick Start

### Installation

```bash
# 1. Install Go
make install-go

# 2. Build WhatsApp Bridge
make build-whatsapp-bridge

# 3. Install Python dependencies
uv sync
```

### Running Locally

```bash
# Terminal 1: Start Redis
docker run -p 6379:6379 redis:alpine

# Terminal 2: Start WhatsApp Bridge
make run-whatsapp-bridge

# Terminal 3: Authenticate with QR
# Open http://localhost:8765/qr in browser
# Scan QR code with WhatsApp

# Terminal 4: Run your agent
python examples/whatsapp_integration.py 2
```

### Running with Docker Compose

```bash
# Start entire stack
docker-compose up -d

# View logs
docker-compose logs -f whatsapp-bridge

# Authenticate
# Visit http://localhost:8765/qr
# Scan QR code with WhatsApp

# Stop
docker-compose down
```

## 📖 Usage Examples

### Example 1: Agent That Sends Messages

```python
from parrot.bots.agent import BasicAgent
from parrot.tools.messaging.whatsapp import WhatsAppTool
from parrot.tools.manager import ToolManager

agent = BasicAgent(name="Assistant", llm="google:gemini-2.0-flash-exp")

# Add WhatsApp tool
tool_manager = ToolManager()
tool_manager.add_tool(WhatsAppTool())
agent.tool_manager = tool_manager

await agent.configure()

# Agent can now send WhatsApp messages
response = await agent.ask(
    "Send a WhatsApp to +14155552671 saying the report is ready"
)
```

### Example 2: Agent That Receives Commands

```python
from parrot.bots.agent import BasicAgent
from parrot.hooks.whatsapp import WhatsAppHook

agent = BasicAgent(name="Assistant", llm="google:gemini-2.0-flash-exp")
await agent.configure()

# Setup WhatsApp hook
hook = WhatsAppHook(
    agent=agent,
    allowed_phones=["14155552671"],  # Only this number
    command_prefix="!",  # Messages must start with !
    auto_reply=True
)

await hook.start()

# Now send WhatsApp messages like:
# "!analyze sales data for Q4"
# "!generate monthly report"
```

### Example 3: Multi-Agent Router

```python
from parrot.hooks.whatsapp import WhatsAppOrchestratorHook

# Create specialized agents
sales_agent = BasicAgent(name="Sales", llm="...")
support_agent = BasicAgent(name="Support", llm="...")

await sales_agent.configure()
await support_agent.configure()

# Setup orchestrator
hook = WhatsAppOrchestratorHook(
    orchestrator=orchestrator,
    default_agent=general_agent
)

# Route by keywords
hook.register_route(
    "sales",
    agent=sales_agent,
    keywords=["quote", "pricing", "buy"]
)

hook.register_route(
    "support",
    agent=support_agent,
    keywords=["help", "issue", "problem"]
)

# Route by phone (VIP customer)
hook.register_route(
    "vip",
    agent=sales_agent,
    phones=["14155551234"]
)

await hook.start()
```

### Example 4: Integration with Existing Orchestrator

```python
# If you already have webhooks, MQTT, RabbitMQ hooks...
from parrot.bots.orchestration.agent import OrchestratorAgent

orchestrator = OrchestratorAgent(...)

# Just add WhatsApp as another input channel
whatsapp_hook = WhatsAppHook(
    agent=orchestrator,
    command_prefix="/",
    auto_reply=True
)

await whatsapp_hook.start()

# Now your orchestrator receives commands from:
# - WhatsApp
# - Webhooks
# - MQTT
# - RabbitMQ
# All using the same agent logic!
```

## ⚙️ Configuration

### Environment Variables

```bash
# WhatsApp Bridge
WHATSAPP_BRIDGE_ENABLED=true
WHATSAPP_BRIDGE_URL=http://localhost:8765
REDIS_SERVICES_URL=redis://localhost:6379

# Optional: Security
WHATSAPP_ALLOWED_PHONES=14155552671,34612345678
WHATSAPP_ALLOWED_GROUPS=MyGroup,AnotherGroup
WHATSAPP_COMMAND_PREFIX=!
```

### In `parrot/conf.py`

```python
from navconfig import config

WHATSAPP_BRIDGE_ENABLED = config.get('WHATSAPP_BRIDGE_ENABLED', fallback=True)
WHATSAPP_BRIDGE_URL = config.get('WHATSAPP_BRIDGE_URL', fallback='http://localhost:8765')
WHATSAPP_ALLOWED_PHONES = config.get('WHATSAPP_ALLOWED_PHONES', fallback=None)
```

## 🔒 Authentication

### First Time Setup

1. **Start Bridge**:
   ```bash
   make run-whatsapp-bridge
   ```

2. **Open QR Page**:
   ```
   http://localhost:8765/qr
   ```

3. **Scan with WhatsApp**:
   - Open WhatsApp on your phone
   - Go to Settings → Linked Devices
   - Scan the QR code

4. **Session Persists**:
   - Session saved to `data/whatsapp.db`
   - No need to re-scan on restart

### Production Deployment

- Mount `data/whatsapp/` as persistent volume
- Session survives container restarts
- Re-authentication only needed if:
  - Database is deleted
  - WhatsApp unlinks device
  - After long inactivity

## 📊 Message Flow

### Incoming Messages (WhatsApp → Agent)

```
User sends WhatsApp message
        ↓
WhatsApp Bridge (whatsmeow)
        ↓
Redis pub/sub (channel: whatsapp:messages)
        ↓
WhatsAppHook (Python)
        ↓
Agent processes message
        ↓
Agent generates response
        ↓
WhatsAppTool sends reply
        ↓
WhatsApp Bridge
        ↓
User receives response
```

### Outgoing Messages (Agent → WhatsApp)

```
Agent decides to send message
        ↓
WhatsAppTool.execute()
        ↓
HTTP POST to /send
        ↓
WhatsApp Bridge
        ↓
whatsmeow sends message
        ↓
User receives message
```

## 🛠️ Development

### Project Structure

```
ai-parrot/
├── services/
│   └── whatsapp-bridge/
│       ├── main.go              # Bridge implementation
│       ├── go.mod
│       ├── go.sum
│       └── Dockerfile
├── parrot/
│   ├── tools/
│   │   └── messaging/
│   │       └── whatsapp.py      # WhatsAppTool
│   ├── hooks/
│   │   └── whatsapp.py          # Hooks for receiving
│   └── conf/
│       └── whatsapp.py          # Configuration
├── examples/
│   └── whatsapp_integration.py  # Usage examples
├── data/
│   └── whatsapp/
│       └── whatsapp.db          # Session storage
├── Makefile                      # Build commands
└── docker-compose.yml            # Stack definition
```

### Testing Locally

```bash
# Build and run
make build-whatsapp-bridge
make run-whatsapp-bridge

# Send test message
curl -X POST http://localhost:8765/send \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "14155552671",
    "message": "Test from AI-Parrot!"
  }'

# Check health
curl http://localhost:8765/health
```

### Debugging

```bash
# Check bridge logs
docker-compose logs -f whatsapp-bridge

# Check if authenticated
curl http://localhost:8765/health | jq

# Monitor Redis messages
redis-cli
> SUBSCRIBE whatsapp:messages

# Test tool directly
python -c "
import asyncio
from parrot.tools.messaging.whatsapp import WhatsAppTool

async def test():
    tool = WhatsAppTool()
    result = await tool.execute(
        phone='14155552671',
        message='Test!'
    )
    print(result)

asyncio.run(test())
"
```

## 🔧 Troubleshooting

### "Bridge is not available"
- Check bridge is running: `curl http://localhost:8765/health`
- Check Redis is running: `redis-cli ping`
- Verify `WHATSAPP_BRIDGE_URL` in config

### "WhatsApp not connected"
- Check bridge logs for errors
- Re-authenticate by scanning QR: http://localhost:8765/qr
- Verify session database exists: `ls data/whatsapp/whatsapp.db`

### Messages not being received
- Check Redis pub/sub: `redis-cli SUBSCRIBE whatsapp:messages`
- Verify `WhatsAppHook` is running
- Check allowed_phones configuration
- Verify command_prefix matches

### Bridge won't start
- Verify Go is installed: `go version`
- Check dependencies: `cd services/whatsapp-bridge && go mod download`
- Review build logs: `make build-whatsapp-bridge 2>&1 | tee build.log`

## 🚢 Production Deployment

### Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: whatsapp-bridge
spec:
  replicas: 1  # Must be 1 for session management
  selector:
    matchLabels:
      app: whatsapp-bridge
  template:
    metadata:
      labels:
        app: whatsapp-bridge
    spec:
      containers:
      - name: bridge
        image: ai-parrot/whatsapp-bridge:latest
        ports:
        - containerPort: 8765
        env:
        - name: REDIS_URL
          value: "redis://redis-service:6379"
        volumeMounts:
        - name: session-data
          mountPath: /data
      volumes:
      - name: session-data
        persistentVolumeClaim:
          claimName: whatsapp-session-pvc
```

### Docker Swarm

```yaml
version: '3.8'
services:
  whatsapp-bridge:
    image: ai-parrot/whatsapp-bridge:latest
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == manager
    volumes:
      - whatsapp-data:/data
    environment:
      - REDIS_URL=redis://redis:6379
volumes:
  whatsapp-data:
```

## 📚 Additional Resources

- [whatsmeow Documentation](https://github.com/tulir/whatsmeow)
- [AI-Parrot Documentation](../README.md)
- [AutonomousOrchestrator Guide](../parrot/bots/orchestration/README.md)

## 🤝 Contributing

1. Test changes locally first
2. Ensure both Go and Python tests pass
3. Update examples if adding features
4. Document new configuration options

## 📄 License

Same as AI-Parrot (check main LICENSE file)