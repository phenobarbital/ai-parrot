# TASK-2602: `AgentMCPMount` — per-agent Streamable HTTP endpoints

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2600, TASK-2601
**Assigned-to**: unassigned

---

## Context

Implements the endpoint half of spec §3 **Module 2**. Builds one
`StreamableHttpMCPServer` per exposed agent at `/mcp/agents/{name}`, using the exact
parent-app mount pattern `A2AServer.setup()` already proves (`a2a/server.py:231`).

Spec §2 Overview #2 (topology) and OQ5 (agent reload) both land here.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py` with `AgentMCPMount`.
- For each configured agent, build a `StreamableHttpMCPServer` and register its routes into
  the existing `web.Application` at `{base_path}/{name}`.
- Register into each server: the agent's **exposure set** (TASK-2600) **plus** the agent's
  own tools, minus internal plumbing (follow `A2AServer._INTERNAL_TOOL_NAMES`).
- Implement the optional aggregate `/mcp` endpoint publishing `{agent}__{tool}` names.
  **Both name forms must resolve to the same canonical PBAC resource**
  `mcp:agent:{name}:tool:{tool}` — the aggregate is naming sugar, never its own
  authorization path. Expose a resolver helper for TASK-2605 to consume.
- **OQ5**: hold agents **by name** and resolve through `BotManager.get_bots()` per call.
  Never cache the agent object — `reload_agent()` cleans up the old instance. Rebuild the
  exposure set when the resolved instance changes.
- Reject at mount time: an agent name containing `__`; a `base_path` that collides with an
  existing transport.
- Wire the mount into `BotManager.setup()`.
- Unit tests.

**NOT in scope**: metadata resources (TASK-2603), identity/PBAC/audit (TASK-2604/5/6),
job handles (TASK-2607), PRM (TASK-2608), the Redis store (TASK-2609).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/agent_mount.py` | CREATE | `AgentMCPMount` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Wire the mount in `setup()` |
| `packages/ai-parrot-server/tests/mcp/test_agent_mount.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31 (post PR #1274). **The brainstorm's line numbers
> are stale — these are the merged ones.**

### Verified Imports
```python
from aiohttp import web
from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.transports.streamable_http import StreamableHttpMCPServer
from parrot.mcp.transports.base import RemoteMCPServerBase
from parrot.mcp.agent_tools import AgentMethodTool, build_exposure_set   # TASK-2600
from parrot.mcp.config import AgentMCPMountConfig                        # TASK-2601
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/transports/streamable_http.py
class StreamableHttpMCPServer(HttpMCPServer):                 # :250   (brainstorm said :125 — WRONG)
    def __init__(self, ...)                                   # :259
    self._sessions: dict[str, McpStreamSession]               # :265
    def _register_routes(self, router, base_route) -> None    # :286   POST/GET/DELETE + /info
    async def _handle_info(self, request)                     # :311
    async def _guard(self, request)                           # :530   centralized auth
    async def _handle_streamable_post(self, request)          # :582
    async def _handle_streamable_get(self, request)           # :892
    async def _handle_streamable_delete(self, request)        # :1035
class StreamBuffer:                                           # :144   (renamed from SessionEventStore)
class McpStreamSession:                                       # :184

# packages/ai-parrot-server/src/parrot/mcp/transports/http.py
class HttpMCPServer(OAuthRoutesMixin, RemoteMCPServerBase):   # :22
    def __init__(self, config: MCPServerConfig,
                 parent_app: Optional[web.Application] = None)  # :25
    def _register_routes(self, router, base_route: str) -> None # :94

# packages/ai-parrot-server/src/parrot/mcp/transports/base.py
class RemoteMCPServerBase(_CoreMCPServerBase):                # :18
    def register_tool(self, tool: AbstractTool)               # :65   applies allowed/blocked filter

# packages/ai-parrot-server/src/parrot/a2a/server.py  — MOUNT PATTERN TO COPY
class A2AServer:                                              # :86
    def setup(self, ...)                                      # :231  registers routes on the app
    _INTERNAL_TOOL_NAMES = frozenset({"to_json"})             # :398
    def _build_skills_from_tools(self) -> List[AgentSkill]    # :400  walks agent.tool_manager

# packages/ai-parrot-server/src/parrot/manager/manager.py
async def reload_agent(self, name: str) -> ReloadResult       # :856   swaps _bots[name], cleans up old
def get_bots(self) -> Dict[str, AbstractBot]                  # :1146
def setup(self, app: web.Application) -> web.Application      # :1965  SYNCHRONOUS

# packages/ai-parrot-server/src/parrot/mcp/parrot_server.py
def _check_base_path_conflicts(self) -> None                  # :121   called at :164
```

### Does NOT Exist
- ~~`AgentMCPMount`, `MCPAgentMount`~~ — you are creating `AgentMCPMount`.
- ~~`StreamableHttpMCPServer.register_agent()`~~ — no such method; register tools individually.
- ~~`SessionEventStore`~~ — **removed by PR #1274**; it is now `StreamBuffer` at `:144`.
- ~~`BotManager.setup()` being async~~ — it is **synchronous** (`:1965`).
- ~~Per-principal `tools/list`~~ — `handle_tools_list(params)` (`server_base.py:100`) takes
  no principal. TASK-2605 adds filtering; do not assume it exists yet.

---

## Implementation Notes

### Pattern to Follow
Mirror `A2AServer.setup()` — build the server, then register routes into the parent app:

```python
class AgentMCPMount:
    def __init__(self, bot_manager, config: AgentMCPMountConfig):
        self._bots = bot_manager        # by NAME, never a cached agent object (OQ5)
        self._config = config
        self._servers: dict[str, StreamableHttpMCPServer] = {}

    def setup(self, app: web.Application) -> web.Application:
        for name in self._config.agents:
            if "__" in name:
                raise ValueError(f"agent name {name!r} contains the aggregate separator '__'")
            server = StreamableHttpMCPServer(cfg, parent_app=app)
            self._register_agent_tools(server, name)
            server._register_routes(app.router, f"{self._config.base_path}/{name}")
            self._servers[name] = server
        return app

    def _resolve(self, name):
        return self._bots.get_bots()[name]     # per call — reload-safe
```

### Key Constraints
- **OQ5**: never hold the agent object across calls. `reload_agent()` `_safe_cleanup()`s
  the old instance, so a cached reference serves a closed agent.
- Canonical resource string is `mcp:agent:{name}:tool:{tool}` for **both** the per-agent
  and aggregate name forms. Expose it as a helper; TASK-2605 enforces on it.
- The mount's `base_path` must not collide — see `_check_base_path_conflicts` (`:121`).
- Filter internal plumbing tools the way `A2AServer` does (`_INTERNAL_TOOL_NAMES`).
- G11: do not alter the tool-level `ParrotMCPServer` behavior.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/a2a/server.py:231` — the mount pattern
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py:164` — base_path guard usage

---

## Acceptance Criteria

- [ ] `/mcp/agents/{name}` (POST/GET/DELETE + `/info`) is registered per configured agent
- [ ] Both the exposure set and the agent's own tools are registered; internal plumbing is excluded
- [ ] The aggregate endpoint publishes `{agent}__{tool}` when enabled
- [ ] Per-agent and aggregate names resolve to the **same** `mcp:agent:{name}:tool:{tool}`
- [ ] An agent name containing `__` is rejected at mount time
- [ ] A `base_path` collision is rejected
- [ ] **OQ5**: after `reload_agent()`, the mount serves the new instance
- [ ] `BotManager.setup()` wires the mount; the tool-level server still works (G11)
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_agent_mount.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/mcp/agent_mount.py`

---

## Test Specification

```python
class TestAgentMCPMount:
    def test_creates_per_agent_endpoint(self, app, bot_manager):
        AgentMCPMount(bot_manager, cfg).setup(app)
        paths = {r.resource.canonical for r in app.router.routes()}
        assert any("/mcp/agents/finance" in p for p in paths)

    def test_registers_exposure_set_and_own_tools(self, mount):
        names = set(mount._servers["finance"].tools)
        assert "forecast" in names            # decorated method
        assert "to_json" not in names         # internal plumbing excluded

    def test_aggregate_prefix(self, app, bot_manager):
        AgentMCPMount(bot_manager, cfg_agg).setup(app)
        assert "finance__forecast" in mount._servers["__aggregate__"].tools

    def test_both_forms_same_pbac_resource(self, mount):
        assert mount.canonical_resource("finance", "forecast") == \
               mount.canonical_resource_from_aggregate("finance__forecast")

    def test_rejects_separator_in_agent_name(self, app, bot_manager):
        with pytest.raises(ValueError, match="__"):
            AgentMCPMount(bot_manager, cfg_bad_name).setup(app)

    async def test_mount_resolves_agent_by_name_per_call(self, mount, bot_manager):
        """OQ5 — a reloaded agent must be picked up, not a stale cached object."""
        old = bot_manager.get_bots()["finance"]
        await bot_manager.reload_agent("finance")
        assert mount._resolve("finance") is not old

    def test_no_regression_tool_level_server(self, app):
        """G11 — the existing tool-level MCP server still mounts and responds."""
```

---

## Agent Instructions

1. **Read the spec** — §2 Overview #2, §3 Module 2, OQ5 in §8.
2. **Check dependencies** — TASK-2600 and TASK-2601 in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — the streamable line numbers changed in PR #1274.
4. **Update status** → `"in-progress"`.
5. **Implement** per scope. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
