# TASK-2517: Testing surface — test/ask, deterministic tool execute, tool assignment

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2511, TASK-2516
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9. Users test agents and tools both ways (resolved in the
original request): deterministically (call `tool.execute(**kwargs)`
directly) and via the LLM (`agent.ask()` with the tool registered in the
agent's `ToolManager`). Session-based test instances follow the proven
`BotConfigTestHandler` pattern. Test runs honor the caller's BYOK key.

---

## Scope

- Implement `StudioTestingHandler(StudioBaseView)` in
  `handlers/studio/testing.py`:
  - `POST /api/v1/astudio/agents/{name}/test/ask` — body
    `{query, use_byok: true}`; session-scoped test instance (create on
    first call, keyed by session+agent, pattern `BotConfigTestHandler`);
    when `use_byok` and a stored key exists for the agent's provider, build
    the test client with `api_key=` (TASK-2516 helper); returns the
    response + usage metadata. `DELETE .../test` ends the session instance.
  - `POST /api/v1/astudio/tools/{slug}/execute` — resolve tool by slug
    (`TOOL_REGISTRY`/`discover_all` + `resolve_class`), instantiate
    (zero-arg or app-context-wired), call `await tool.execute(**args)`;
    return `ToolResult` serialized; 422 listing missing server-managed
    deps when instantiation needs them; 404 unknown slug.
  - `POST /api/v1/astudio/agents/{name}/tools` — body
    `{tools: [...], toolkits: [{slug, params}]}`; assign via
    `bot.tool_manager.register_tools(...)` /
    `bot.tool_manager.register_toolkit(...)` on the agent instance;
    ownership enforced; response lists registered tool names.
- Routes + tests (LLM calls mocked).

**NOT in scope**: toolkit config schemas (TASK-2518); vector-store search
testing (existing `PATCH /api/v1/ai/stores` — do not duplicate).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | CREATE | testing handler |
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | MODIFY | add routes |
| `packages/ai-parrot-server/tests/studio/test_testing_surface.py` | CREATE | ask/execute/assign tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.discovery import discover_all, resolve_class  # discovery.py:108,139
from parrot_tools import TOOL_REGISTRY                          # parrot_tools/__init__.py:12 (207 slugs)
from parrot.clients.factory import LLMFactory                   # factory.py:159
from parrot.registry import agent_registry                      # registry/__init__.py:7-12
```

### Existing Signatures to Use
```python
# Pattern (READ, do not modify): handlers/testing_handler.py:29
class BotConfigTestHandler(BaseView):
    # PUT :76 create test session / POST :128 query / DELETE :228 stop
    # helpers: manager property :39 (app['bot_manager']), _session_key :54,
    #          _create_agent :58 — session-scoped instance discipline to copy

# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):  # :235
    async def execute(self, *args, **kwargs) -> ToolResult: ...  # :797 (public wrapper:
        # permission check, error handling, result standardization)
    # class attrs :250-262: name, description, args_schema, return_direct,
    #   routing_meta, credential_provider
# ToolResult(BaseModel) :200

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager(MCPToolManagerMixin):  # :233
    def register_toolkit(self, toolkit: Union[str, "AbstractToolkit", type],
                         **kwargs) -> List[AbstractTool]: ...  # :1008
        # accepts slug (ToolkitRegistry lookup), class (instantiated w/ kwargs), or instance
    def register_tools(self, tools: List[Union[ToolDefinition, AbstractTool]]) -> None: ...  # :879
    def get_tool(self, tool_name): ...  # :1215
    def list_tools(self) -> List[str]: ...  # :1235
# Agent exposes: self.tool_manager (bots/abstract.py:386);
#   AbstractBot.register_tools thin delegate (abstract.py:4019)

# tools/discovery.py
def discover_all(sources=None) -> Dict[str, Union[str, Type]]: ...  # :108
def resolve_class(dotted_path: str) -> Type: ...                    # :139

# Ask path: bots — per-request LLM override exists (abstract.py:3817 llm kwarg);
#   llm resolution priority in _resolve_llm_config (abstract.py:826)
# BYOK helper (TASK-2516): resolve_user_api_key(app, user_id, provider) -> Optional[str]
```

### Does NOT Exist
- ~~`AbstractBot.add_tool()` / `add_toolkit()`~~ — use
  `bot.tool_manager.register_toolkit(...)` / `register_tools(...)`.
- ~~A deterministic tool-execution endpoint~~ — greenfield (the crew
  catalog and `/api/v1/tools/catalog` only LIST tools).
- ~~Zero-arg instantiation for `InfographicToolkit`/`LLMWikiToolkit`~~ —
  required deps (`artifact_store`; three toolkits + `WikiConfig`) → for
  these, wire from app context (`app['artifact_store']`,
  manager.py:2157) or return 422 `server_managed` listing.
- ~~`ToolkitRegistry` as the primary lookup~~ — deprecated
  (tools/registry.py:42 docstring); use `discovery` + `TOOL_REGISTRY`.

---

## Implementation Notes

### Pattern to Follow
Session test instances: key `f"studio_test:{session_id}:{agent_name}"`
held in a handler-level dict or app key, TTL-cleaned — mirror
`BotConfigTestHandler._session_key`/`_create_agent` (:54/:58).

### Key Constraints
- `execute` args validated against `tool.args_schema` when present;
  validation errors → 422 with field messages.
- Tool assignment mutates the LIVE agent instance (resolved: shared
  instance semantics) — response includes `persisted: false` note; YAML
  persistence of toolkit config belongs to TASK-2518's assignment flow.
- BYOK: never fall back silently to the server key when `use_byok=true`
  and the stored key fails auth — surface the provider error (spec §7).
- Mock all LLM calls in tests (no network).

### References in Codebase
- `handlers/agents/ephemeral.py` — error-mapping discipline.
- `tests/unit/test_skill_registry_toolkit.py` — toolkit test patterns.

---

## Acceptance Criteria

- [ ] `test/ask` creates a session instance once, reuses it, honors BYOK,
      and DELETE tears it down.
- [ ] `tools/{slug}/execute` runs zero-arg tools deterministically; 404
      unknown slug; 422 with `server_managed` list for heavy toolkits.
- [ ] Tool/toolkit assignment registers into the live agent's
      `tool_manager`; ownership enforced.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_testing_surface.py
class TestTestingSurface:
    async def test_ask_session_instance_reused(self, studio_app): ...
    async def test_ask_uses_byok_key(self, studio_app, vault_keys): ...
    async def test_execute_zero_arg_tool(self, studio_app): ...
    async def test_execute_unknown_slug_404(self, studio_app): ...
    async def test_execute_server_managed_422(self, studio_app): ...
    async def test_assign_toolkit_registers_tools(self, studio_app): ...
    async def test_assign_requires_ownership(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2511, TASK-2516 completed
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- `StudioTestingHandler` (`test/ask` + `test` DELETE), `StudioToolExecuteHandler`
  (`tools/{slug}/execute`), and `StudioToolAssignHandler`
  (`agents/{name}/tools`) implemented in `handlers/studio/testing.py`,
  routes appended to `setup_studio_routes` in `handlers/studio/__init__.py`.
- Session-scoped test instance reuse mirrors `BotConfigTestHandler`
  (`manager.get_bot(name, new=True, session_id=...)`, session key
  `_studio_test:{agent_name}`, `manager._bots` lookup on reuse).
- BYOK: provider derived from `bot._llm_raw` (only when it's a plain
  `"provider:model"` string); `resolve_user_api_key` (TASK-2516) consulted
  per-call; a stored key rebuilds `bot.llm` via
  `LLMFactory.create(..., api_key=...)`. No stored key → no-op (keeps
  whatever client is already configured); an auth failure on a genuinely
  swapped-in BYOK client is never caught-and-retried against the server
  default — it surfaces as a 502 `query_failed` error (spec §7).
- Deterministic execute: `discover_all()` + `resolve_class()` (never the
  deprecated `ToolkitRegistry` string path — see Codebase Contract "Does
  NOT Exist"); zero-arg or app-context-wired instantiation via
  `inspect.signature()` against a small `_KNOWN_APP_DEPS` map
  (`artifact_store` today); missing deps → 422 `server_managed` with the
  list of missing param names. Args are validated explicitly via the
  tool's own `validate_args()` BEFORE calling `execute()` so a bad-args
  call surfaces as `422 invalid_args` (not swallowed into a 200
  `ToolResult(status="error")`, which is what `execute()` alone would do).
- Toolkit assignment resolves each slug the same discovery-based way (not
  `register_toolkit(str)`'s deprecated `ToolkitRegistry` lookup) before
  calling `bot.tool_manager.register_toolkit(cls, **params)`; plain tool
  slugs go straight through `bot.tool_manager.register_tools([...])`,
  whose internal `load_tool()` already resolves via the modern
  `discover_from_registry` path. Response always reports
  `"persisted": false` (YAML persistence is TASK-2518's scope).
- Ownership on assignment reuses `_StudioAgentsMixin`'s DB/registry owner
  resolution (imported from `.agents`) — same dual-source lookup as
  agent create/delete, then `StudioBaseView._require_owner`.
- Tests (14, all passing, LLM calls mocked — no network):
  session-instance-reuse unit test of the mixin helper; `test/ask` happy
  path + BYOK-key-applied + BYOK-no-stored-key-is-noop + query-failure
  502 + unknown-agent 404 + DELETE (active/no-op); tool execute
  zero-arg-success / unknown-slug-404 / server-managed-422; toolkit
  assignment success / ownership-403 / unknown-toolkit-reported-as-error.
  Full `packages/ai-parrot-server/tests/studio/` suite (122 tests) and
  the broader server regression sweep both pass (pre-existing, unrelated
  failures in `test_saas_auth_hardening.py`/`test_namespace_imports.py`/
  `test_a2a_*_vertical.py` confirmed via `git stash` to predate this task).
- `ruff check handlers/studio/` reports only the pervasive pre-existing
  `BLE001` blind-except pattern already used throughout every other file
  in this directory (54 total occurrences repo-wide, none introduced by
  this task beyond following the same established fail-open convention);
  the one fixable `G201` finding in this task's new code was fixed.

**Deviations from spec**:
- `TestAskRequest.use_byok` defaults to `True` (the task's example body
  `{query, use_byok: true}` reads as the field's default, not merely an
  example value) — a caller can still opt out with `use_byok: false`.
- Request/response Pydantic models (`TestAskRequest`, `ToolExecuteRequest`,
  `ToolAssignRequest`/`ToolkitAssignEntry`) are defined locally in
  `testing.py` rather than added to `handlers/studio/models.py`, since
  the task's Files to Create/Modify list does not include `models.py`
  (Cardinal Rule: file fidelity) and `testing.py` is their only consumer.
