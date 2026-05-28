---
id: F001
query: "parrot/handlers directory structure and dependencies"
type: read
---

## Finding: parrot/handlers/ (~59 Python files)

Entirely server-side HTTP infrastructure. Sub-packages: agents/, crew/, database/,
jobs/, models/, scraping/, stores/.

**Key classes**: AgentTalk, ChatHandler, BotHandler, ChatbotHandler, StreamHandler,
CrewHandler, VectorStoreHandler, DashboardHandler, etc.

**External deps**: aiohttp (BaseView), asyncdb, pandas, pydantic, redis, navigator/navigator-auth

**Cross-deps FROM handlers**:
- parrot.bots.abstract.AbstractBot
- parrot.tools.manager.ToolManager
- parrot.mcp.integration.MCPServerConfig
- parrot.memory.RedisConversation
- parrot.registry.registry.BotConfig
- parrot.clients.factory.LLMFactory
- parrot.auth.oauth2.*

**Cross-deps TO handlers** (who imports from parrot.handlers):
- parrot.manager.manager (BotManager) — imports ~25 handler classes for route registration
- parrot.mcp.oauth → parrot.handlers.vault_utils
- parrot.auth.oauth2_base → parrot.handlers.vault_utils
- parrot.agents.demo → parrot.handlers.web_hitl

**vault_utils/credentials_utils**: Used by mcp.oauth and auth.oauth2_base — needs
to stay accessible in core if handlers move to satellite.
