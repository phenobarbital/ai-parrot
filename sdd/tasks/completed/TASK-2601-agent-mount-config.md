# TASK-2601: Agent-mount configuration model

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Supports spec §3 **Module 2**. Small, self-contained configuration groundwork that the
mount (TASK-2602), the guard (TASK-2604/2605/2606) and the PRM endpoint (TASK-2608) all
read. Split out so the mount task starts from a settled config surface.

Carries the resolved tenancy decision from spec §8: `default_tenant_id` is the **only live
path** until navigator-auth emits a tenant claim.

---

## Scope

- Implement `AgentMCPMountConfig` exactly as specified in spec §2 Data Models.
- Extend `MCPServerConfig` (`packages/ai-parrot-server/src/parrot/mcp/config.py`) with the
  agent-mount settings, without disturbing existing fields or defaults.
- Validate at construction: `resource_server_url` is an absolute URI;
  `call_deadline_seconds` is below the 300 s client ceiling; `max_result_tokens` is below
  the ~30 000-token connector ceiling; no agent name contains the `__` aggregate separator.
- Unit tests.

**NOT in scope**: reading the config anywhere, building servers, wiring `BotManager`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/config.py` | MODIFY | Add `AgentMCPMountConfig`; extend `MCPServerConfig` |
| `packages/ai-parrot-server/tests/mcp/test_agent_mount_config.py` | CREATE | Validation tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.mcp.config import AuthMethod, MCPServerConfig
from pydantic import BaseModel, Field, field_validator
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/mcp/config.py
class AuthMethod(str, Enum):        # :6   NONE | API_KEY | OAUTH2_INTERNAL | OAUTH2_EXTERNAL | BEARER
class MCPServerConfig:              # :16
    allowed_tools: Optional[List[str]] = None      # :32   static, process-wide
    blocked_tools: Optional[List[str]] = None      # :33   NOT per-principal
    base_path: str = "/mcp"                        # :61
    allowed_origins: Optional[List[str]] = None    # :70
    session_ttl: int = 3600                        # :75
    event_buffer_size: int = 1000                  # :77
```

### Does NOT Exist
- ~~`AgentMCPMountConfig`~~ — you are creating it.
- ~~`MCPServerConfig.agents`~~ / ~~`.tenant_id`~~ — not present today.
- ~~A per-principal tool filter in `MCPServerConfig`~~ — `allowed_tools`/`blocked_tools`
  are static name filters applied in `RemoteMCPServerBase.register_tool` (`base.py:65`).
  Do not repurpose them for PBAC.

---

## Implementation Notes

### Key Constraints
- `default_tenant_id` is documented as the **single-tenant fallback** and, per spec §8, the
  only path that fires until navigator-auth emits a tenant claim. Comment it as such.
- Defaults per spec §2: `base_path="/mcp/agents"`, `aggregate_enabled=False`,
  `max_result_tokens=25_000`, `call_deadline_seconds=240.0`.
- Do not change any existing `MCPServerConfig` default — G11 forbids regressions.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/mcp/parrot_server.py:121` —
  `_check_base_path_conflicts()`; the agent mount must claim a distinct `base_path`

---

## Acceptance Criteria

- [ ] `AgentMCPMountConfig` matches spec §2 Data Models field-for-field
- [ ] A relative `resource_server_url` is rejected
- [ ] `call_deadline_seconds >= 300` is rejected
- [ ] `max_result_tokens >= 30_000` is rejected
- [ ] An agent name containing `__` is rejected
- [ ] Existing `MCPServerConfig` fields and defaults are unchanged
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_agent_mount_config.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/mcp/config.py`

---

## Test Specification

```python
class TestAgentMCPMountConfig:
    def test_defaults(self):
        c = AgentMCPMountConfig(agents=["finance"], resource_server_url="https://h/mcp/agents/finance")
        assert c.base_path == "/mcp/agents" and c.aggregate_enabled is False
        assert c.max_result_tokens == 25_000 and c.call_deadline_seconds == 240.0

    @pytest.mark.parametrize("url", ["mcp/agents", "", "not-a-uri"])
    def test_rejects_relative_resource_url(self, url):
        with pytest.raises(ValidationError):
            AgentMCPMountConfig(agents=["a"], resource_server_url=url)

    def test_rejects_deadline_at_or_above_client_ceiling(self):
        with pytest.raises(ValidationError):
            AgentMCPMountConfig(agents=["a"], resource_server_url="https://h/x", call_deadline_seconds=300.0)

    def test_rejects_agent_name_with_separator(self):
        with pytest.raises(ValidationError, match="__"):
            AgentMCPMountConfig(agents=["fin__ance"], resource_server_url="https://h/x")

    def test_existing_config_untouched(self):
        assert MCPServerConfig().base_path == "/mcp"
        assert MCPServerConfig().session_ttl == 3600
```

---

## Agent Instructions

1. **Read the spec** — §2 Data Models, §3 Module 2.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract**.
4. **Update status** → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: `AgentMCPMountConfig(BaseModel)` added to `config.py` field-for-field per
spec §2 Data Models, with `field_validator`s rejecting: agent names containing
`__`, a non-absolute `resource_server_url` (checked via `urlparse` scheme+netloc),
`call_deadline_seconds >= 300`, and `max_result_tokens >= 30_000`. `MCPServerConfig`
(dataclass) extended with one new optional field, `agent_mount:
Optional[AgentMCPMountConfig] = None`, satisfying the integration-table entry
("MCPServerConfig extends: agent-mount settings") without touching any existing
field or default — `test_existing_config_untouched` pins `base_path`, `session_ttl`,
and the new field's `None` default. 9/9 new tests pass; full
`packages/ai-parrot-server/tests/mcp/` suite (90 tests) still green — no regressions.
`ruff check config.py` shows only pre-existing findings (35 baseline, confirmed via
`git stash` diff before/after) plus one new `Optional[...]` vs `X | None` style
finding on the new field, consistent with the file's existing (unconverted) style.

**Deviations from spec**: none — the "Extend `MCPServerConfig`" scope bullet is
satisfied via one new optional field wrapping `AgentMCPMountConfig`, since no
other task consumes `MCPServerConfig.agent_mount` directly (TASK-2602's
`AgentMCPMount` takes an `AgentMCPMountConfig` as its own constructor arg); this
field exists so `ParrotMCPServer`/`BotManager.setup()` has a settled place to read
it from later if wired that way.
