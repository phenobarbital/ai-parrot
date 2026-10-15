# TASK-4354: BasicAgent.setup_mcp_servers

**Feature**: FEAT-680 — BasicAgent.setup_mcp_servers (registry MCP config was silently ignored)
**Spec**: `sdd/specs/tests-test-basic-agent-new-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §2/§3 Module 1. Resolves ledger issue:7c3f2e6ed5be.
`BotMetadata.get_instance` only applies `mcp_servers` config when the instance has
`setup_mcp_servers`; `BasicAgent` lacks it, so the config is silently dropped and
`test_setup_mcp_servers` fails with `AttributeError`.
`test_agent_real_integration` already passes on `dev` — no change.

---

## Scope

- Add `async def setup_mcp_servers(self, configurations: Optional[List[MCPServerConfig]] = None) -> None`
  to `BasicAgent`, right after `add_mcp_server`, mirroring `VoiceBot.setup_mcp_servers`
  (per-config try/except, info log on success, error log with `exc_info=True` on failure).
- Tests: failure isolation (first config raises, second still added) and `None` no-op.

**NOT in scope**: `registry.py`, `VoiceBot`, `MCPEnabledMixin`, `test_agent_real_integration`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/agent.py` | MODIFY | add `setup_mcp_servers` |
| `packages/ai-parrot/tests/test_basic_agent_new.py` | MODIFY | new regression cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.agent import BasicAgent   # tests import it inside the mock_agent_deps fixture
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/agent.py:1024
async def add_mcp_server(self, config: MCPServerConfig) -> List[str]
# packages/ai-parrot/src/parrot/bots/voice.py:496 (reference implementation)
async def setup_mcp_servers(self, configurations: Optional[List[MCPServerConfig]] = None) -> None
# packages/ai-parrot/src/parrot/registry/registry.py:175
if server_configs and hasattr(instance, "setup_mcp_servers"): await instance.setup_mcp_servers(server_configs)
```

### Does NOT Exist
- `BasicAgent.setup_mcp_servers` (before this task)
- `MCPEnabledMixin` in `BasicAgent`'s MRO

---

## Acceptance Criteria
- [ ] `BasicAgent.setup_mcp_servers` exists and calls `add_mcp_server` per config.
- [ ] A raising config does not stop later configs; `None` is a no-op.
- [ ] `test_basic_agent_new.py` passes.

## Validation Commands
```bash
pytest packages/ai-parrot/tests/test_basic_agent_new.py -q
```

## Test Specification
`test_setup_mcp_servers` (existing), `test_setup_mcp_servers_isolates_failures`,
`test_setup_mcp_servers_none_is_noop`.

## Agent Instructions
Implement exactly the scope above, run the validation command, commit only the two files.

## Completion Note
