---
id: F004
query: "parrot/services, parrot/scheduler, parrot/autonomous structure"
type: read
---

## Finding: Three server-side modules

### parrot/services/ (~15 files)
- AgentService — task queue + worker pool + Redis listener + delivery router + heartbeat
- WhatsApp bridge — REST API handlers
- O365 remote auth, identity mapping, vault token sync — utility services
- services/mcp/ — ParrotMCPServer, SimpleMCPServer (aiohttp-integrated MCP servers)
- **Deps**: ..bots.abstract, ..manager (BotManager), ..notifications, ..conf, ..interfaces.o365

### parrot/scheduler/ (3 files, __init__.py = 1740 lines)
- AgentSchedulerManager — wraps APScheduler, DB-persisted schedules
- Decorators: @schedule, @schedule_daily_report, @schedule_weekly_report
- **CRITICAL**: Decorators used by bots in core (github_reviewer, jira_specialist)
- **Deps**: ..manager, ..registry, ..notifications, ..conf, ..models.responses
- **Tight coupling**: app.py instantiates with bot_manager=self.bot_manager

### parrot/autonomous/ (~15 files)
- AutonomousOrchestrator — event bus, hooks, execution modes
- Transport: filesystem-based (inbox/feed/reservation)
- Deploy: installer, templates
- CLI: parrot-fs entry point
- **Deps**: core.events, core.hooks, manager (TYPE_CHECKING), registry (TYPE_CHECKING)
