# TASK-578: DatabaseAgent — Unified Agent with Multi-Toolkit Support

**Feature**: sqlagent-repair
**Spec**: `sdd/specs/sqlagent-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-568, TASK-569, TASK-570, TASK-571, TASK-576, TASK-577
**Assigned-to**: unassigned

---

## Context

Implements spec Module 11. This is the capstone task — rewriting the current 3,071-line `AbstractDBAgent` into a thin `DatabaseAgent` that orchestrates toolkits, cache manager, router, and response formatting. The agent owns: LLM interaction, system prompt generation, conversation memory, response formatting via `DatabaseResponse`, and three-tier role resolution.

---

## Scope

- Create `parrot/bots/database/agent.py` with `DatabaseAgent(AbstractBot)`:
  - Constructor accepts: `name`, `toolkits: List[DatabaseToolkit]`, `default_user_role`, `vector_store`, `redis_url`, `system_prompt_template`, `**kwargs`
  - `configure()`: create `CacheManager`, assign partitions to toolkits, start all toolkits, register toolkit tools with `ToolManager`, register databases with router
  - `ask()` with three-tier role resolution:
    1. Explicit `user_role=` param (highest priority)
    2. Router-inferred from `QueryIntent`
    3. `default_user_role` fallback
  - Hybrid database routing: explicit `database=` param > LLM-inferred via tool calls
  - System prompt dynamically built from registered toolkits' capabilities
  - Response formatting via existing `DatabaseResponse` model with `OutputComponent` flags
  - Conversation memory integration via existing `AbstractBot` infrastructure
  - Error recovery: delegate to toolkit's retry handler
- Port response formatting logic from current `abstract.py`:
  - `_format_response()` (line ~2419)
  - `_format_as_text()` (line ~2323)
  - `_extract_performance_metrics()` (line ~2541)
- Write unit tests with mock toolkits

**NOT in scope**: Modifying `AbstractBot`, modifying toolkit implementations, deleting old code (that's TASK-579).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/database/agent.py` | CREATE | DatabaseAgent implementation |
| `parrot/bots/database/prompts.py` | MODIFY | Update system prompt template for multi-toolkit support |
| `tests/unit/test_database_agent.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Bot infrastructure
from parrot.bots.abstract import AbstractBot  # parrot/bots/abstract.py:92

# Toolkits (TASK-569-575 outputs)
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.database.toolkits.sql import SQLToolkit
from parrot.bots.database.toolkits.postgres import PostgresToolkit

# Cache (TASK-568 output)
from parrot.bots.database.cache import CacheManager, CachePartition, CachePartitionConfig

# Router (TASK-576 output)
from parrot.bots.database.router import SchemaQueryRouter

# Models
from parrot.bots.database.models import (
    UserRole, OutputComponent, OutputFormat, QueryIntent,
    RouteDecision, DatabaseResponse, TableMetadata,
    QueryExecutionResponse, get_default_components,
    ROLE_COMPONENT_DEFAULTS, INTENT_COMPONENT_MAPPING
)

# Retry (TASK-577 output)
from parrot.bots.database.retries import QueryRetryConfig

# AI-Parrot core
from parrot.models import AIMessage, CompletionUsage
from parrot.tools.manager import ToolManager
from parrot.memory import ConversationTurn

# Prompts
from parrot.bots.database.prompts import DB_AGENT_PROMPT
```

### Existing Signatures to Use
```python
# parrot/bots/abstract.py:92
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, ToolInterface, VectorInterface, ABC):
    system_prompt_template = BASIC_SYSTEM_PROMPT      # line 113
    _prompt_builder: Optional[PromptBuilder] = None   # line 115
    # Has: configure(app), _llm, tool_manager, logger, etc.

# parrot/tools/manager.py:587
# ToolManager.register_toolkit(toolkit) — registers all tools from a toolkit

# parrot/bots/database/abstract.py:454 — REFERENCE for ask() signature
# async def ask(self, query, context, user_role=UserRole.DATA_ANALYST, ...) -> AIMessage:

# parrot/bots/database/abstract.py:277 — REFERENCE for create_system_prompt()
# async def create_system_prompt(self, user_context, context, vector_context,
#     conversation_context, metadata_context, vector_metadata, route, **kwargs) -> str:

# parrot/bots/database/abstract.py:2419 — REFERENCE for _format_response()
# async def _format_response(self, query, db_response, ...) -> AIMessage:
```

### Does NOT Exist
- ~~`DatabaseAgent`~~ — does not exist yet (this task creates it)
- ~~`AbstractBot.register_toolkit()`~~ — no such method; use `ToolManager.register_toolkit()`
- ~~`AbstractBot.ask()`~~ — AbstractBot does not have `ask()`; that's on AbstractDBAgent
- ~~`AbstractToolkit.get_database_type()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow
```python
class DatabaseAgent(AbstractBot):
    """Unified database agent with multi-toolkit support."""
    _default_temperature: float = 0.0
    max_tokens: int = 8192

    def __init__(self, name="DatabaseAgent", toolkits=None,
                 default_user_role=UserRole.DATA_ANALYST,
                 vector_store=None, redis_url=None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.toolkits = toolkits or []
        self.default_user_role = default_user_role
        self.cache_manager = CacheManager(redis_url=redis_url, vector_store=vector_store)
        # Router created with first toolkit's schema info
        self.query_router = None  # Set during configure()

    async def configure(self, app=None):
        await super().configure(app)
        # 1. Create cache partitions for each toolkit
        # 2. Start all toolkits
        # 3. Register toolkit tools with ToolManager
        # 4. Build router with database identifiers
        ...

    async def ask(self, query, user_role=None, database=None, ...) -> AIMessage:
        # 1. Resolve role: explicit > inferred > default
        # 2. Route query (intent + database selection)
        # 3. Build system prompt with toolkit capabilities
        # 4. Call LLM with toolkit tools available
        # 5. Format response with DatabaseResponse
        ...
```

### Key Constraints
- Agent must NOT contain any database-specific logic (that lives in toolkits)
- System prompt must list all available toolkit tools with their database context
- Tool naming: prefix toolkit tools with database identifier to avoid collisions
- Response formatting logic can be ported from `abstract.py:2323-2515` but simplified
- Must work with a single toolkit (most common case) and multiple toolkits

### References in Codebase
- `parrot/bots/database/abstract.py` — current agent implementation (3,071 lines) to slim down from
- `parrot/bots/database/prompts.py` — system prompt templates
- `parrot/bots/abstract.py` — AbstractBot base class

---

## Acceptance Criteria

- [ ] `DatabaseAgent` inherits from `AbstractBot`
- [ ] Works with single toolkit: configure, ask, get response
- [ ] Works with multiple toolkits: routes to correct toolkit
- [ ] Three-tier role resolution works: explicit > inferred > default
- [ ] System prompt dynamically built from registered toolkits
- [ ] Response formatting uses `DatabaseResponse` with appropriate `OutputComponent`s
- [ ] All tests pass: `pytest tests/unit/test_database_agent.py -v`
- [ ] Imports work: `from parrot.bots.database.agent import DatabaseAgent`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import UserRole, OutputComponent


class MockToolkit:
    """Minimal mock toolkit for agent testing."""
    database_type = "postgresql"
    allowed_schemas = ["public"]
    primary_schema = "public"

    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    def get_tools(self):
        return []


class TestDatabaseAgent:
    def test_default_role(self):
        agent = DatabaseAgent(
            toolkits=[MockToolkit()],
            default_user_role=UserRole.DATABASE_ADMIN
        )
        assert agent.default_user_role == UserRole.DATABASE_ADMIN

    def test_single_toolkit(self):
        agent = DatabaseAgent(toolkits=[MockToolkit()])
        assert len(agent.toolkits) == 1

    def test_multi_toolkit(self):
        agent = DatabaseAgent(toolkits=[MockToolkit(), MockToolkit()])
        assert len(agent.toolkits) == 2
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/sqlagent-repair.spec.md` (Module 11)
2. **Check ALL dependencies** — TASK-568 through TASK-577 (except 572-575 which are optional non-SQL toolkits)
3. **Read `parrot/bots/database/abstract.py`** thoroughly — identify which methods move to agent vs which were moved to toolkits
4. **Read `parrot/bots/abstract.py`** — understand AbstractBot's interface
5. **Key decision**: the agent should be THIN — delegate all database logic to toolkits
6. **Implement**, test, move to completed, update index

---

## Completion Note

*(Agent fills this in when done)*
