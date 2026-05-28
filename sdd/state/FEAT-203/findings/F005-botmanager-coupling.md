---
id: F005
query: "BotManager coupling to handlers and server infrastructure"
type: read
---

## Finding: BotManager is the central server orchestrator

**File**: parrot/manager/manager.py (lines 90-2116)

### Direct handler imports (~25 classes):
ChatHandler, BotHandler, AgentTalk, IntegrationsHandler, InfographicTalk,
DataAnalystHandler, AgentFactoryHandler, PrintPDFHandler, DatasetManagerHandler,
DatabaseDriversHandler/Formats/Intents/Roles/Schemas, ChatInteractionHandler,
ChatbotHandler, BotConfigHandler, BotConfigTestHandler, DashboardHandler,
DashboardTabHandler, UserAgentHandler, EphemeralUserAgentHandler, ToolCatalogHandler,
StreamHandler, CrewHandler, CrewExecutionHandler, setup_credentials_routes,
setup_mcp_helper_routes, HITLResponseHandler, setup_web_hitl

### Route registration in setup() (lines 1334-1585):
- 200+ lines of app.router.add_view() calls
- Registers on_startup, on_shutdown, on_cleanup hooks

### Startup sequence (lines 1680-1727):
1. setup_pbac(app) → app['abac']
2. BotManager.setup(app) → registers routes + hooks
3. AgentRegistry.setup(app) → reads app['abac']
4. BotManager.on_startup(app) → loads bots, crews, integrations

### Impact:
BotManager STAYS in core per user instruction. But its setup() method is 100%
server infrastructure. Solution: split setup() into core logic (bot loading) and
server logic (route registration) that's lazy-imported from satellite.
