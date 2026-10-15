---
type: feature
base_branch: dev
feature_id: FEAT-680
projects: [ai-parrot]
tags: [basic-agent, mcp, registry, tests]
---

# Feature Specification: BasicAgent.setup_mcp_servers (registry MCP config was silently ignored)

**Feature ID**: FEAT-680
**Date**: 2026-10-15
**Author**: Claude (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:7c3f2e6ed5be (discovered from spec:FEAT-591).

---

## 1. Motivation & Business Requirements

### Problem Statement

The ledger issue reported two pre-existing failures in
`packages/ai-parrot/tests/test_basic_agent_new.py`:

1. `test_setup_mcp_servers` — fails with
   `AttributeError: 'BasicAgent' object has no attribute 'setup_mcp_servers'`.
   This is a real product defect, not a stale test: `BotMetadata.get_instance()`
   (`packages/ai-parrot/src/parrot/registry/registry.py:175`) applies an agent's
   `mcp_servers` configuration only `if hasattr(instance, "setup_mcp_servers")`.
   `BasicAgent` (and therefore `Agent`) exposes `add_mcp_server` but not
   `setup_mcp_servers`, so every registry-built BasicAgent/Agent silently drops
   its configured MCP servers — no error, no log. Only `VoiceBot`
   (`bots/voice.py:496`) and `MCPEnabledMixin` (`mcp/integration.py:1834`)
   implement it.
2. `test_agent_real_integration` — passes when run alone, fails when the whole
   module runs: the module-scoped `mock_agent_deps_module` fixture keeps
   `parrot.clients.google` mocked in `sys.modules` until the module ends, so the
   "real" test receives the mocked `GoogleGenAIClient`. Fix: move it, unchanged,
   to its own module `test_basic_agent_integration.py`.

### Goals
- `BasicAgent.setup_mcp_servers(configurations)` exists, registers each config via
  `self.add_mcp_server(config)`, and logs success/failure per server without
  aborting the remaining servers (same contract as `VoiceBot.setup_mcp_servers`).
- `None` / empty list is a no-op.
- `test_basic_agent_new.py` passes in full.

### Non-Goals
- No change to `registry.py`, `VoiceBot`, `MCPEnabledMixin` or `ToolManager`.
- No change to the body of `test_agent_real_integration` (only its module).

---

## 2. Architectural Design

Add an async method next to `add_mcp_server` in the "MCP Server Management Methods"
section of `BasicAgent`:

```python
async def setup_mcp_servers(self, configurations: Optional[List[MCPServerConfig]] = None) -> None:
    for config in configurations or []:
        try:
            tools = await self.add_mcp_server(config)
            self.logger.info(...)
        except Exception as e:
            self.logger.error(..., exc_info=True)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotMetadata.get_instance` (`registry/registry.py:175`) | caller | `await instance.setup_mcp_servers(server_configs)` |
| `BasicAgent.add_mcp_server` (`bots/agent.py:1024`) | callee | returns `List[str]`, already swallows+logs its own errors |

---

## 3. Module Breakdown

### Module 1: BasicAgent.setup_mcp_servers
- **Path**: `packages/ai-parrot/src/parrot/bots/agent.py`,
  `packages/ai-parrot/tests/test_basic_agent_new.py`,
  `packages/ai-parrot/tests/test_basic_agent_integration.py` (new)
- **Responsibility**: add the method; extend tests with a failure-isolation case
  (one config raising does not stop the next) and a `None` no-op case.

---

## 4. Test Specification

`pytest packages/ai-parrot/tests/test_basic_agent_new.py` passes (the existing
`test_setup_mcp_servers` plus new cases for failure isolation and `None`).

---

## 5. Acceptance Criteria
- [ ] `BasicAgent` (and `Agent`) has `setup_mcp_servers`; registry `mcp_servers` config now reaches `add_mcp_server`.
- [ ] One failing server does not prevent the others from being added.
- [ ] `setup_mcp_servers(None)` / `([])` is a no-op.
- [ ] `test_basic_agent_new.py` passes.

---

## 6. Codebase Contract
- `packages/ai-parrot/src/parrot/bots/agent.py:40` — `class BasicAgent(Chatbot, NotificationMixin)`
- `packages/ai-parrot/src/parrot/bots/agent.py:1024` — `async def add_mcp_server(self, config: MCPServerConfig) -> List[str]`
- `packages/ai-parrot/src/parrot/bots/voice.py:496` — reference implementation `VoiceBot.setup_mcp_servers`
- `packages/ai-parrot/src/parrot/registry/registry.py:175` — `hasattr(instance, "setup_mcp_servers")` caller

## 7. Open Questions
None.
