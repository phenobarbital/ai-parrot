# TASK-311 — EpisodicMemoryMixin for AbstractBot

**Feature**: FEAT-045 (Episodic Memory Store v2)
**Spec**: `sdd/specs/episodicmemorystore.spec.md`
**Status**: pending
**Priority**: high
**Effort**: L
**Depends on**: TASK-304, TASK-309, TASK-310
**Parallel**: false
**Parallelism notes**: Integrates with AbstractBot, imports store (TASK-309) and tools (TASK-310). Modifies the bot's ask() flow.

---

## Objective

Create `EpisodicMemoryMixin` that hooks into `AbstractBot` to automatically record episodes after tool calls and conversations, and inject episodic context (warnings, preferences, room context) into the system prompt before LLM calls.

## Files to Create/Modify

- `parrot/memory/episodic/mixin.py` — new file
- `parrot/memory/episodic/__init__.py` — update with all final exports
- `parrot/memory/__init__.py` — add episodic subpackage exports

## Implementation Details

### EpisodicMemoryMixin

Per brainstorm section 5.1:

```python
class EpisodicMemoryMixin:
    """Mixin for AbstractBot that adds automatic episodic memory.

    Hooks into the ask() flow to:
    1. Inject episodic context (warnings, preferences) into system prompt (pre-LLM)
    2. Record significant tool executions as episodes (post-tool)
    3. Record conversation outcomes as episodes (post-ask)
    """

    # Configuration (override in subclass or via kwargs)
    enable_episodic_memory: bool = True
    episodic_backend: str = "pgvector"       # "pgvector" | "faiss"
    episodic_dsn: str | None = None          # For PgVector
    episodic_schema: str = "parrot_memory"
    episodic_reflection_enabled: bool = True
    episodic_inject_warnings: bool = True
    episodic_max_warnings: int = 3
    episodic_trivial_tools: set[str] = {"get_time", "get_date"}
```

### _configure_episodic_memory()

Called during bot `configure()`:
1. Resolve backend (PgVector or FAISS) based on `episodic_backend`.
2. Create `EpisodicMemoryStore` with appropriate backend, embedding provider, reflection engine.
3. If Redis is available, create `EpisodeRedisCache`.
4. Optionally register `EpisodicMemoryToolkit` with the bot's `ToolManager`.
5. Store as `self._episodic_store`.

### _build_episodic_context(query, user_id, room_id) -> str

Per brainstorm section 5.1:
1. Build `MemoryNamespace` from bot's agent_id + provided user_id/room_id.
2. If `episodic_inject_warnings`: get failure warnings relevant to query.
3. If `user_id`: get user preferences.
4. If `room_id`: get room context (last 5 episodes).
5. Assemble and return formatted context string.

Returns empty string if no relevant episodic context found.

### _record_post_tool(tool_name, tool_args, tool_result, user_query, user_id, session_id, room_id)

Per brainstorm section 5.1:
1. Skip if `tool_name` in `episodic_trivial_tools`.
2. Build namespace with all available dimensions.
3. Call `store.record_tool_episode(namespace, ...)`.
4. Fire-and-forget (use `asyncio.create_task` to avoid blocking).

### _record_post_ask(query, response, user_id, session_id, room_id)

1. Evaluate if the conversation is significant enough to record (not trivial greetings).
2. Build namespace.
3. Record as QUERY_RESOLUTION or DECISION category.
4. Fire-and-forget.

### Integration Pattern

The mixin does NOT modify `AbstractBot.ask()` directly. Instead, it provides hooks that concrete bot implementations (Chatbot, Agent) call at the appropriate points:

```python
# In Agent.ask() or Chatbot.ask():
if hasattr(self, '_build_episodic_context'):
    episodic_context = await self._build_episodic_context(query, user_id, room_id)
    if episodic_context:
        system_prompt += f"\n\n{episodic_context}"
```

The mixin is opt-in — bots that don't inherit it are unaffected.

## Acceptance Criteria

- [ ] `_configure_episodic_memory()` creates store with correct backend based on config.
- [ ] `_build_episodic_context()` returns formatted text with warnings + preferences + room context.
- [ ] `_build_episodic_context()` returns empty string when no relevant context exists.
- [ ] `_record_post_tool()` skips trivial tools and records significant ones.
- [ ] `_record_post_tool()` is fire-and-forget (does not block ask flow).
- [ ] `_record_post_ask()` records significant conversations.
- [ ] Mixin is opt-in and does not break bots that don't use it.
- [ ] `parrot/memory/episodic/__init__.py` exports all public classes.
- [ ] `parrot/memory/__init__.py` updated with episodic exports.
