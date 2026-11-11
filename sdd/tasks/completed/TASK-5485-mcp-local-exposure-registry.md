# TASK-5485: Exposure declaration in the agent registry

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-877 lets an agent be served as a local stdio MCP server, but only when its
declaration opts in (spec G3, decision `opt-in-exposure`). Both declaration paths — a
YAML definition under `AGENTS_DIR/agents/` and `@register_agent` — must land in ONE
field, `BotConfig.mcp_local`, which every later task reads. This task implements spec
§3 **Module 1**. It also extracts a sync `load_modules_sync()` so the (sync)
`AgentToolkit` constructor can run decorator discovery without an event loop.

---

## Scope

- Add the Pydantic model `MCPLocalExposure` (`enabled: bool = True`,
  `allow: Optional[List[str]] = None`, `extra="forbid"`) directly above `BotConfig`.
- Add `BotConfig.mcp_local: Optional[MCPLocalExposure]` plus a `field_validator`
  (`mode="before"`) coercing `True` → `{}` and `False`/`None` → `None`.
- Map the YAML top-level `mcp_local:` section in `load_agent_definition_file` (same
  place `prompt:` is mapped).
- Emit `mcp_local` in `create_agent_definition` (`model_dump(exclude_none=True)`,
  omitted when `None`) so the FEAT-467 round-trip stays lossless.
- Add an explicit `mcp_local=` keyword to `register_bot_decorator` and pass it into the
  `BotConfig` it builds.
- Extract the loop of `async def load_modules` into a public sync
  `load_modules_sync() -> int`; `load_modules` returns `self.load_modules_sync()`.
- Write `packages/ai-parrot/tests/registry/test_mcp_local_exposure.py`.

**NOT in scope**: the own-class method rule, agent resolution, `AgentToolkit`
(TASK-5487..5489); exporting `MCPLocalExposure` from `parrot/registry/__init__.py`
(consumers import it from `parrot.registry.registry`); any change to `agents.yaml`
handling beyond what the new `BotConfig` field gives for free.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | `MCPLocalExposure`, `BotConfig.mcp_local`, YAML read/write, decorator keyword, `load_modules_sync` |
| `packages/ai-parrot/tests/registry/test_mcp_local_exposure.py` | CREATE | Unit tests for Module 1 |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11). Line numbers unchanged since
> the spec's verification commit.

### Verified Imports
```python
from parrot.registry.registry import AgentRegistry, BotConfig, AgentKind   # verified: registry.py:302,256,55
from parrot.bots.agent import Agent                                        # verified: bots/agent.py:1576
from pydantic import BaseModel, Field, model_validator                     # verified: registry.py:36 (this task adds ConfigDict, field_validator)
# registry.py already has: from __future__ import annotations (line 9);
# from typing import TYPE_CHECKING, Dict, Iterable, List, Literal, Type, Set, Union, Optional, Any, Protocol (line 16)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class BotConfig(BaseModel):                                   # line 256
    name: str                                                  # line 259
    class_name: Optional[str] = None                           # line 260
    module: Optional[str] = None                               # line 261
    prompt: Optional[PromptConfig] = Field(default=None)       # line 273
    @model_validator(mode="after")                             # line 289
    def _kind_requirements(self) -> "BotConfig":               # line 290
    roost: Optional[RoostAgentConfig] = Field(default=None)    # line 299 (declared AFTER the validator)

class AgentRegistry:                                           # line 302
    def __init__(self, agents_dir: Optional[Path] = None, *, extra_agent_dirs=None)  # line 341; creates agents_dir/__init__.py and agents_dir/agents.yaml
    def get_metadata(self, name: str) -> Optional[BotMetadata]  # line 695
    def load_agent_definition_file(self, yaml_file: Path) -> bool  # line 1025
        #   bot_config_data = agent_def.copy()                         (line 1067)
        #   if "prompt" in content:                                    (line 1082)
        #       bot_config_data["prompt"] = PromptConfig(**content["prompt"])   (line 1083)
        #   # Create BotConfig                                         (line 1085)
        #   config = BotConfig(**bot_config_data)                      (line 1086)
    def create_agent_definition(self, config: BotConfig, category: str = "general") -> Path  # line 1121
        #   if config.prompt:                                          (line 1210)
        #       data["prompt"] = config.prompt.model_dump(exclude_none=True)   (line 1211)
        #   with open(file_path, "w") as f: yaml.dump(data, f)         (lines 1213-1214)
    def _load_modules_from_directory(self, directory: Path) -> int  # line 1362 (sync)
    async def load_modules(self) -> int                        # line 1382; body lines 1388-1395, no awaits
    def register_bot_decorator(self, *, name=None, priority=0, dependencies=None, singleton=False,
                               at_startup=False, startup_config=None, tags=None,
                               roost: Optional[RoostAgentConfig] = None, **kwargs)  # line 1397
        #   _bot_config = BotConfig(... priority=priority, roost=roost, )   (lines 1459-1473)
        #   self.register(..., bot_config=_bot_config, roost=roost, **kwargs)  (lines 1476-1488)
```

### Does NOT Exist
- ~~`MCPLocalExposure`~~, ~~`BotConfig.mcp_local`~~, ~~`AgentRegistry.load_modules_sync`~~ — created by this task.
- ~~`parrot.registry.MCPLocalExposure`~~ — not exported from the package `__init__`; import from `parrot.registry.registry`.
- ~~`AgentRegistry.discover()`~~ — there is no single discovery entry point.
- ~~`register_agent` bound to an isolated registry~~ — `parrot.registry.register_agent` is
  `agent_registry.register_bot_decorator` (the GLOBAL registry). Tests must call
  `<isolated_registry>.register_bot_decorator(...)` directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/registry/registry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/registry/test_mcp_local_exposure.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_agent_definition_file",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.create_agent_definition",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.load_modules",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.register_bot_decorator",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry._load_modules_from_directory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `registry.py` uses `from __future__ import annotations`: define `MCPLocalExposure`
  **before** `BotConfig` so Pydantic resolves `Optional[MCPLocalExposure]` at class creation.
- Never change existing field order semantics or validators; only add.
- The YAML reader passes the RAW value (`true`, `false`, a mapping) to `BotConfig`; the
  field validator does the coercion — one coercion point for YAML, `agents.yaml` and
  the decorator.
- `load_modules` behaviour (log line, return value) must stay byte-for-byte the same.

### References in Codebase
- `registry.py:1082-1083` — the `prompt:` mapping to mirror.
- `registry.py:1210-1211` — the `prompt` writer to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the pydantic import — *why*: the new model needs `ConfigDict` and the coercion needs `field_validator`.
2. Insert `MCPLocalExposure` above `class BotConfig` — *why*: forward refs under `from __future__ import annotations` must resolve at class creation.
3. Add the `mcp_local` field after `prompt` and the `_coerce_mcp_local` validator above `_kind_requirements` — *why*: one coercion point for every declaration path (spec §2 "Declaring").
4. Map `mcp_local` in the YAML reader and emit it in the writer — *why*: AC-13 round-trip.
5. Add the decorator keyword and pass it into `_bot_config` — *why*: the Python opt-in path (G3).
6. Extract `load_modules_sync` — *why*: `AgentToolkit.__init__` (TASK-5488) is sync and runs inside an already-running loop in `mcp-local`.
7. Write the tests, run the Validation Commands.

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY) — imports
```python
# occurrences: 1 (verified: grep -c 'from pydantic import BaseModel, Field, model_validator' registry.py)
# REPLACE line 36 `from pydantic import BaseModel, Field, model_validator` with:
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

### `registry.py` (MODIFY) — the model
```python
# occurrences: 1 (verified: grep -c 'class BotConfig(BaseModel):' registry.py)
# BEFORE — insert above `class BotConfig(BaseModel):` (verified: registry.py:256), with two blank lines around it
class MCPLocalExposure(BaseModel):
    """Opt-in declaration that an agent may be served as a local stdio MCP server (FEAT-877).

    Attributes:
        enabled: When False the agent is treated as undeclared.
        allow: Method names to expose. None exposes every own-class method; an entry
            that is not an own-class public async method is an error at install and at
            serve time (raised by parrot.mcp.agent_toolkit).
    """

    enabled: bool = True
    allow: Optional[List[str]] = None

    model_config = ConfigDict(extra="forbid")
```

### `registry.py` (MODIFY) — field and validator
```python
# occurrences: 1 (verified: grep -c '    prompt: Optional\[PromptConfig\] = Field(default=None)' registry.py)
# AFTER — insert below `    prompt: Optional[PromptConfig] = Field(default=None)` (verified: registry.py:273)
    mcp_local: Optional[MCPLocalExposure] = Field(default=None)  # FEAT-877: True → MCPLocalExposure()

# occurrences of `    @model_validator(mode="after")` may be > 1 — disambiguate with the next line:
# BEFORE — insert above the 2-line block
#     @model_validator(mode="after")
#     def _kind_requirements(self) -> "BotConfig":        (verified: registry.py:289-290)
    @field_validator("mcp_local", mode="before")
    @classmethod
    def _coerce_mcp_local(cls, value: Any) -> Any:
        """Coerce the `mcp_local` declaration (FEAT-877).

        True → {} (enabled, no allowlist); False/None → None; anything else unchanged.
        """
        # FILL IN: return {} for `value is True`, None for `value is False or value is None`,
        #   else `value` unchanged — bounded by spec §2 "Declaring" (use identity checks so
        #   1/0 are not coerced; Pydantic then validates mappings against extra="forbid").
```

### `registry.py` (MODIFY) — YAML reader
```python
# occurrences: 1 (verified: grep -c '        # Create BotConfig' registry.py)
# BEFORE — insert above `        # Create BotConfig` (verified: registry.py:1085), after the `prompt` mapping
        # Map 'mcp_local' section (FEAT-877): raw value, coerced by BotConfig._coerce_mcp_local
        if "mcp_local" in content:
            bot_config_data["mcp_local"] = content["mcp_local"]
```

### `registry.py` (MODIFY) — YAML writer
```python
# occurrences: 1 (verified: grep -c '            data\["prompt"\] = config.prompt.model_dump(exclude_none=True)' registry.py)
# AFTER — insert below `            data["prompt"] = config.prompt.model_dump(exclude_none=True)` (verified: registry.py:1211)

        if config.mcp_local is not None:
            data["mcp_local"] = config.mcp_local.model_dump(exclude_none=True)
```

### `registry.py` (MODIFY) — sync module discovery
```python
# occurrences: 1 (verified: grep -c '    async def load_modules(self) -> int:' registry.py)
# REPLACE the whole `async def load_modules` method (verified: registry.py:1382-1395) with:
    def load_modules_sync(self) -> int:
        """Import every ``*.py`` in every discovery directory (sync).

        This triggers any ``@register_agent`` decorators in those modules.

        Returns:
            Number of modules imported.
        """
        total_imported = 0
        for directory in self._discovery_paths:
            total_imported += self._load_modules_from_directory(directory)

        self.logger.info(
            f"Discovered (decorator) agent modules: {total_imported} across {len(self._discovery_paths)} directories"
        )
        return total_imported

    async def load_modules(self) -> int:
        """
        Dynamically import all Python modules from every discovery directory.

        This triggers any decorators in those modules to register agents.
        """
        return self.load_modules_sync()
```

### `registry.py` (MODIFY) — decorator keyword
```python
# `        roost: Optional[RoostAgentConfig] = None,` occurs 2 times (lines 583, 1407) — use 3-line context:
# REPLACE (verified: registry.py:1406-1408)
#         tags: Optional[Iterable[str]] = None,
#         roost: Optional[RoostAgentConfig] = None,
#         **kwargs,
# WITH
        tags: Optional[Iterable[str]] = None,
        roost: Optional[RoostAgentConfig] = None,
        mcp_local: Union[bool, Dict[str, Any], MCPLocalExposure, None] = None,
        **kwargs,

# Add to the decorator docstring Args: `mcp_local: FEAT-877 opt-in to local stdio MCP exposure
#   (True, a mapping with `enabled`/`allow`, or an MCPLocalExposure).`

# `                roost=roost,` occurs 2 times (lines 1472, 1486) — use 3-line context:
# REPLACE (verified: registry.py:1471-1473 — the `_bot_config = BotConfig(` call)
#                 priority=priority,
#                 roost=roost,
#             )
# WITH
                priority=priority,
                roost=roost,
                mcp_local=mcp_local,
            )
```
**Why**: the keyword is explicit (not `**kwargs`) so it never leaks into `self.register(**kwargs)`;
the `BotConfig` validator coerces it exactly like the YAML value.

### `packages/ai-parrot/tests/registry/test_mcp_local_exposure.py` (CREATE)
```python
"""FEAT-877 Module 1 — `mcp_local` exposure declaration in the registry."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from parrot.bots.agent import Agent
from parrot.registry.registry import AgentRegistry, BotConfig, MCPLocalExposure


@pytest.fixture
def isolated_registry(tmp_path: Path) -> AgentRegistry:
    """An AgentRegistry rooted in tmp_path — never the global registry."""
    return AgentRegistry(agents_dir=tmp_path / "agents")


def _write_definition(registry: AgentRegistry, body: dict) -> Path:
    path = registry.agents_dir / "agents" / "general" / f"{body['agent']['name']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def _agent(name: str = "finance") -> dict:
    return {"name": name, "class_name": "BasicAgent", "module": "parrot.bots.agent"}


def test_yaml_mcp_local_true_coerces(isolated_registry: AgentRegistry) -> None:
    path = _write_definition(isolated_registry, {"agent": _agent(), "mcp_local": True})
    assert isolated_registry.load_agent_definition_file(path)
    assert isolated_registry.get_metadata("finance").bot_config.mcp_local == MCPLocalExposure()


def test_yaml_mcp_local_allow(isolated_registry: AgentRegistry) -> None:
    # FILL IN: top-level `mcp_local: {allow: [forecast]}` → MCPLocalExposure(allow=["forecast"])
    ...


@pytest.mark.parametrize("value", [None, False])
def test_yaml_mcp_local_absent_or_false(isolated_registry: AgentRegistry, value: object) -> None:
    # FILL IN: value None → omit the key entirely; False → `mcp_local: false`; both → bot_config.mcp_local is None
    ...


def test_yaml_mcp_local_unknown_key_rejected(isolated_registry: AgentRegistry) -> None:
    # FILL IN: `mcp_local: {allow: [x], expose: true}` → pytest.raises(ValueError) from load_agent_definition_file
    ...


def test_decorator_mcp_local_kwarg(isolated_registry: AgentRegistry) -> None:
    @isolated_registry.register_bot_decorator(name="finance", mcp_local={"allow": ["forecast"]})
    class FinanceAgent(Agent):
        async def forecast(self, months: int) -> dict:
            """Forecast."""
            return {"months": months}

    # FILL IN: assert get_metadata("finance").bot_config.mcp_local == MCPLocalExposure(allow=["forecast"]);
    #   also register a second class with mcp_local=True and one without the keyword (→ None)


def test_definition_roundtrip_keeps_mcp_local(isolated_registry: AgentRegistry) -> None:
    # FILL IN: BotConfig(name=..., class_name="BasicAgent", module="parrot.bots.agent", mcp_local={"allow": ["forecast"]})
    #   → create_agent_definition(cfg) → load_agent_definition_file(path) → equal mcp_local;
    #   and a BotConfig without mcp_local writes a YAML whose top level has no "mcp_local" key (AC-13)
    ...


async def test_load_modules_sync_matches_async(isolated_registry: AgentRegistry) -> None:
    # FILL IN: write one trivial module (no registration) into isolated_registry.agents_dir;
    #   assert isolated_registry.load_modules_sync() == await isolated_registry.load_modules() == 1
    ...
```

### FILL IN checklist
- [ ] `BotConfig._coerce_mcp_local` — identity-based coercion; bounded by spec §2 "Declaring".
- [ ] every `...` test body above — bounded by spec §4 Module 1 rows and AC-13.
- [ ] decorator docstring line for `mcp_local`.

---

## Acceptance Criteria

- [ ] `mcp_local: true` / `{allow: [...]}` / absent / `false` behave per spec §2; unknown keys are rejected.
- [ ] `@register_agent(mcp_local=...)` lands in `bot_config.mcp_local`.
- [ ] `create_agent_definition` → reload keeps `mcp_local`; it is omitted when `None` (AC-13).
- [ ] `load_modules()` returns the same count as `load_modules_sync()` and logs the same line.
- [ ] Existing registry round-trip and definition tests stay green.
- [ ] `ruff check packages/ai-parrot/src/parrot/registry/registry.py packages/ai-parrot/tests/registry/test_mcp_local_exposure.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/registry/test_mcp_local_exposure.py -q`
- `pytest packages/ai-parrot/tests/registry/test_yaml_roundtrip.py -q`
- `pytest packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py -q`
- `pytest packages/ai-parrot/tests/registry/test_remote_kind.py -q`
- `pytest packages/ai-parrot/tests/test_agent_definitions.py -q`

---

## Test Specification

See the CREATE block above: one test per spec §4 Module 1 row
(`test_yaml_mcp_local_true_coerces`, `test_yaml_mcp_local_allow`,
`test_yaml_mcp_local_absent_or_false`, `test_yaml_mcp_local_unknown_key_rejected`,
`test_decorator_mcp_local_kwarg`, `test_definition_roundtrip_keeps_mcp_local`,
`test_load_modules_sync_matches_async`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5485 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-5485
- Feature: agent-local-mcp
- Implementation SHA: 371e2855073c6c37cc921371c86fe253ea5ef438
- Closed at (UTC): 2026-11-11T00:14:24+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 2 · Duration: 440s · Tokens: n/a |
