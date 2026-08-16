# TASK-2210: AgentServiceConfig — YAML config + agent target resolution

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Data Models" and Module 2. Defines how a daemon is configured
(YAML or CLI flags) and how the `module:attr` agent target is resolved into
a live agent instance.

---

## Scope

- Implement `config.py` in `parrot/integrations/agentd/`:
  - Pydantic v2 models exactly as spec §2: `SchedulerConfig`,
    `AgentTargetConfig`, `AgentServiceConfig` (fields: name, agent, socket,
    scheduler, exposed_methods, log_level, max_line_bytes=10MB,
    shutdown_grace=30.0).
  - `AgentServiceConfig.from_yaml(path) -> AgentServiceConfig` and
    `from_target(target, name, **overrides)` (CLI path without YAML).
  - `default_socket_path(name) -> Path`: `$XDG_RUNTIME_DIR/parrot/<name>.sock`,
    fallback `/tmp/parrot-<uid>/<name>.sock`.
  - `async resolve_agent(cfg: AgentTargetConfig) -> Any`: import
    `module:attr`; class → instantiate with kwargs; callable → call
    (await result if coroutine); if resolved object has an async
    `configure` attribute → await `configure()`. Clear errors for bad
    paths/attrs (raise `AgentTargetError`).
- Unit tests: YAML load + defaults + validation errors; socket default with
  and without `XDG_RUNTIME_DIR`; target-resolution matrix (class / instance /
  sync factory / async factory / missing module / missing attr).

**NOT in scope**: daemon lifecycle (TASK-2212), CLI flags parsing (TASK-2216).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | CREATE | Models + loaders + target resolution |
| `packages/ai-parrot-integrations/tests/agentd/test_config.py` | CREATE | Unit tests |
| `packages/ai-parrot-integrations/tests/agentd/fakes.py` | CREATE | `EchoAgent` + factories used across agentd tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field, field_validator  # pydantic v2 (core dep)
import yaml    # PyYAML — already a transitive/core dependency (used by AgentRegistry config)
import importlib, inspect, os
from pathlib import Path
```

### Existing Signatures to Use
```python
# Bots expose async configure() — resolve_agent must call it when present:
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    async def configure(self, app=None) -> None   # verified in console-cli-agents brainstorm; re-verify line before use
```

### Does NOT Exist
- ~~`parrot.integrations.agentd.config`~~ — created by this task.
- ~~a repo-wide "load yaml config" helper for integrations~~ — none exists; implement locally.
- ~~`AgentServiceConfig` anywhere else~~ — do not import from ai-parrot core.

---

## Implementation Notes

### Key Constraints
- `EchoAgent` fake: minimal duck-typed agent — `async ask(question, **kw) -> AIMessage-like`, `async ask_stream(question, **kw)` async generator, `async configure()`, `get_available_tools() -> list[str]`, `get_tools_count()`, `has_tools()`. Used by every later integration test — keep it dependency-free (do NOT subclass AbstractBot; duck typing is enough and avoids LLM config).
- Validation: `name` must be slug-safe (it becomes a filename); reject path separators.
- No aiohttp imports.

### References in Codebase
- Spec §2 "Data Models" — authoritative field list.
- `packages/ai-parrot/src/parrot/cli/loaders.py:70` (`StandaloneAgentLoader.load`) — precedent for agent instantiation/configure flow.

---

## Acceptance Criteria

- [ ] YAML from spec §3 example loads; missing fields get defaults.
- [ ] `resolve_agent` matrix passes (class/instance/sync factory/async factory/bad module/bad attr).
- [ ] Socket default honours `XDG_RUNTIME_DIR`, falls back to `/tmp/parrot-<uid>/`.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_config.py -v`
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_config.py
import pytest
from parrot.integrations.agentd.config import (
    AgentServiceConfig, resolve_agent, default_socket_path, AgentTargetError,
)

class TestConfig:
    def test_yaml_roundtrip(self, tmp_path): ...
    def test_defaults(self): ...
    def test_bad_name_rejected(self): ...

@pytest.mark.asyncio
class TestResolveAgent:
    async def test_class_target(self): ...
    async def test_async_factory_target(self): ...
    async def test_missing_attr_raises(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **deps**: none; 3. **verify contract** (esp. AbstractBot.configure line);
4. index → in-progress; 5. implement; 6. verify criteria; 7. move to completed/; 8. index → done; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-16
**Notes**: Implemented `config.py` with `SchedulerConfig`, `AgentTargetConfig`,
`AgentServiceConfig` (fields exactly per spec §2: name, agent, socket,
scheduler, exposed_methods, log_level, max_line_bytes=10MB,
shutdown_grace=30.0), `AgentServiceConfig.from_yaml()`/`.from_target()`,
`default_socket_path()` (XDG_RUNTIME_DIR with `/tmp/parrot-<uid>/` fallback),
and `resolve_agent()` covering class / instance / sync-factory /
async-factory targets plus `AgentTargetError` for bad module/attr/shape.
`resolve_agent()` awaits `configure()` only when it is an async function
(`inspect.iscoroutinefunction`), matching `AbstractBot.configure(app=None)`.
`name` validation rejects empty strings and path separators (`/`, `\`).

Added `tests/agentd/fakes.py` with a dependency-free, duck-typed `EchoAgent`
(ask/ask_stream/configure/get_available_tools/get_tools_count/has_tools) plus
`make_echo_agent`/`make_echo_agent_async` factories and a module-level
`echo_instance` — used to exercise every branch of the target-resolution
matrix, and available for later agentd tasks per the spec's fixture note
(`tests.agentd.fakes:EchoAgent`).

25 tests pass (14 new in `test_config.py`, 11 pre-existing in
`test_protocol.py` unaffected). `ruff check` clean after auto-fix (quoted
forward-ref return types, unused noqa directives, import ordering).

**Deviations from spec**: none.
