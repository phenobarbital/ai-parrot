# TASK-4750: M13 — discovery seam: `kind`/`endpoint`/`contract_categories` on `AgentRegistry`, `BotMetadata`, `BotConfig`

**Feature**: FEAT-746 — Squawk: typed binary inter-agent protocol
**Spec**: `sdd/specs/inter-agent-protocol.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 (U2, S10 mitigation, AC13): one registry answers "who serves X". `BotConfig`/`BotMetadata` gain `kind: local | a2a | squawk` (`AgentKind` str-enum), `endpoint`, `contract_categories`; a validator makes `class_name`/`module` optional for remote kinds and `endpoint` mandatory for them; `AgentRegistry.find_by_kind()` / `find_serving(category)`; `get_instance()` refuses remote kinds with `RemoteAgentNotInstantiable`. `BotMetadata.__post_init__` currently requires a class/callable factory — remote entries carry a `None` factory, so the check is relaxed for `kind != local`. `A2AMeshDiscovery` is untouched. FEAT-747 reads `kind` via `getattr` until this merges.

---

## Scope

- `registry.py`: `AgentKind`, `RemoteAgentNotInstantiable`; fields on `BotMetadata` (+ `__post_init__` relaxation) and `BotConfig` (+ `model_validator`); `find_by_kind`, `find_serving`; the refusal at the top of `AgentRegistry.get_instance`; a `register_remote(config: BotConfig) -> BotMetadata` helper so YAML `kind: squawk` entries register without a factory (hook it where `discover_config_agents`/`load_agent_definition_file` build `BotMetadata` — read :733-781 and :964-1052 first).
- `registry/__init__.py`: export `AgentKind`, `RemoteAgentNotInstantiable`.
- Tests: `packages/ai-parrot/tests/registry/test_remote_kind.py`.

**NOT in scope**: `A2AMeshDiscovery`, `RegisteredAgent`, Roost's `find_capability` (FEAT-747), any YAML files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | kinds, fields, validators, finders, refusal |
| `packages/ai-parrot/src/parrot/registry/__init__.py` | MODIFY | exports |
| `packages/ai-parrot/tests/registry/test_remote_kind.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import AgentRegistry, BotConfig, BotMetadata   # verified: packages/ai-parrot/src/parrot/registry/__init__.py:2
from pydantic import BaseModel, Field, model_validator   # registry.py:31 imports BaseModel, Field — add model_validator there
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
from dataclasses import dataclass, field, asdict, is_dataclass   # line 20
from typing import Dict, Iterable, List, Literal, Type, Set, Union, Optional, Any, Protocol   # line 14
@dataclass
class BotMetadata:                           # line 50
    name: str; factory: Union[Type[AbstractBot], AgentFactory]; module_path: str; file_path: Path; singleton: bool = False; tags; priority; at_startup; dependencies; startup_config; bot_config; events_block; _instance; _lock   # lines 59-72
    def __post_init__(self):                 # line 73 — raises ValueError unless factory is an AbstractBot subclass or callable (:76-80)
class BotConfig(BaseModel):                  # line 227
    name: str; class_name: str; module: str; enabled: bool = True; origin: Literal["repo","factory"] = "repo"; ...   # lines 230-255
class AgentRegistry:                         # line 258
    async def get_instance(self, name: str, request: Optional[web.Request] = None, **kwargs) -> Optional[AbstractBot]   # line 659 (2nd occurrence of `    async def get_instance(`; the 1st is BotMetadata.get_instance at :85)
    def list_agents(self) -> List[BotMetadata]   # line 1421
    def discover_config_agents(...)          # line 733     def load_agent_definition_file(...)   # line 964
```

### Does NOT Exist
- ~~`BotMetadata.kind` / `BotConfig.endpoint`~~ — added here.
- ~~`AgentRegistry.register_a2a_agent`~~ — that is `ToolManager.register_a2a_agent` (manager.py:2302), unrelated.
- ~~`A2AMeshDiscovery` reading `AgentRegistry`~~ — none; stays independent.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/registry/registry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/registry/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/registry/test_remote_kind.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotMetadata",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_instance"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `AgentKind(str, Enum)` so `metadata.kind == "squawk"` keeps working for FEAT-747's `getattr(..., "kind", "local")` reads.
- `BotMetadata.factory` becomes `Optional[...]`; `__post_init__`: `if self.kind == AgentKind.LOCAL: <existing check>` else require `endpoint`.
- `BotConfig` validator: local ⇒ `class_name` and `module` required; remote ⇒ `endpoint` required.
- `get_instance` refusal is the FIRST statement after metadata lookup; `RemoteAgentNotInstantiable(ValueError)` message names the kind and endpoint.
- `find_serving(category)` matches exact category names in `contract_categories` (prefix matching is Roost's job).
- Run the existing registry tests listed in Validation Commands — `test_yaml_roundtrip.py` must keep passing (lossless YAML: new fields are optional with defaults).

### References in Codebase
- `packages/ai-parrot/tests/registry/test_unregister.py`, `test_yaml_roundtrip.py` — test idioms.

---

## Implementation Blueprint

### Steps (in order)
1. Enum + exception near the top of `registry.py` (after imports) — *why*: referenced by both models.
2. `BotMetadata` fields + `__post_init__` — *why*: remote entries have no factory.
3. `BotConfig` fields + validator — *why*: YAML `kind: squawk` entries omit class/module.
4. `AgentRegistry` finders + refusal + `register_remote` — *why*: U2 "one registry answers who serves X".
5. Exports; tests.

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY — block 1)
```python
# occurrences: 1 (verified: grep -c 'class BotMetadata:' packages/ai-parrot/src/parrot/registry/registry.py)
# BEFORE `@dataclass` / `class BotMetadata:` (registry.py:49-50) insert:
class AgentKind(str, Enum):   # add `from enum import Enum` to the imports block (registry.py:9-21)
    """Where an agent runs: in-process, behind the A2A client, or behind a Squawk endpoint (FEAT-746 U2)."""

    LOCAL = "local"
    A2A = "a2a"
    SQUAWK = "squawk"


class RemoteAgentNotInstantiable(ValueError):
    """get_instance() on a remote-kind registry entry; resolve it through the protocol client instead."""
```
```python
# Inside BotMetadata (registry.py:59-72) — make `factory: Optional[Union[Type[AbstractBot], AgentFactory]] = None` is NOT allowed (non-default after default);
# keep `factory` positional but accept None: `factory: Union[Type[AbstractBot], AgentFactory, None]`, and append after `events_block` (:71):
    kind: AgentKind = AgentKind.LOCAL
    endpoint: Optional[str] = None
    contract_categories: List[str] = field(default_factory=list)
# In __post_init__ (:73-83) wrap the existing factory check:
    if self.kind == AgentKind.LOCAL:
        <existing is_class/is_factory check, unchanged>
    elif not self.endpoint:
        raise ValueError(f"Remote bot {self.name} (kind={self.kind.value}) requires an endpoint")
```

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY — block 2, BotConfig)
```python
# occurrences: 1 (verified: grep -c 'class BotConfig(BaseModel):' packages/ai-parrot/src/parrot/registry/registry.py)
# Change `class_name: str` → `class_name: Optional[str] = None` and `module: str` → `module: Optional[str] = None` (registry.py:231-232), append after `policies` (:255):
    kind: AgentKind = AgentKind.LOCAL
    endpoint: Optional[str] = None
    contract_categories: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _kind_requirements(self) -> "BotConfig":
        # FILL IN: LOCAL ⇒ class_name and module required; else endpoint required — ValueError with the field name
        return self
```

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY — block 3, AgentRegistry)
```python
# occurrences: 2 (verified: grep -c '    async def get_instance(' packages/ai-parrot/src/parrot/registry/registry.py) — FILL IN: disambiguate: attach to the occurrence
# inside `class AgentRegistry` whose signature continues `self, name: str, request: Optional[web.Request] = None, **kwargs,` (registry.py:659-664), NOT BotMetadata.get_instance (:85).
# Right after the metadata lookup inside AgentRegistry.get_instance add:
        if metadata.kind != AgentKind.LOCAL:
            raise RemoteAgentNotInstantiable(f"{name} is a {metadata.kind.value} agent at {metadata.endpoint}; use the protocol client")
# occurrences: 1 (verified: grep -c '    def list_agents(self) -> List\[BotMetadata\]:' registry.py) — AFTER the list_agents method body add:
    def find_by_kind(self, kind: AgentKind) -> List[BotMetadata]:
        """Registered entries of one kind, sorted by name."""
        return [m for m in self.list_agents() if m.kind == kind]

    def find_serving(self, category: str) -> List[BotMetadata]:
        """Remote entries advertising `category` in contract_categories (exact match)."""
        return [m for m in self.list_agents() if m.kind != AgentKind.LOCAL and category in m.contract_categories]

    def register_remote(self, config: BotConfig) -> BotMetadata:
        """Register a kind != local entry (no factory); used by YAML discovery for `kind: squawk|a2a` entries."""
        # FILL IN: build BotMetadata(name=config.name, factory=None, module_path="", file_path=Path("remote"), tags=config.tags, kind=config.kind,
        #          endpoint=config.endpoint, contract_categories=list(config.contract_categories), bot_config=config) and store it the same way register() does
        #          (read register() :526-584 for the dict + events it touches) — bounded by: never instantiates
        raise NotImplementedError
```
Also route YAML discovery: in `discover_config_agents` (:733) and `load_agent_definition_file` (:964), when `config.kind != AgentKind.LOCAL` call `register_remote(config)` and skip the factory path — *FILL IN* after reading those methods.

### `packages/ai-parrot/src/parrot/registry/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .registry import AgentRegistry, BotConfig, BotMetadata' packages/ai-parrot/src/parrot/registry/__init__.py)
# REPLACE line 2 with:
from .registry import AgentKind, AgentRegistry, BotConfig, BotMetadata, RemoteAgentNotInstantiable
# and add "AgentKind", "RemoteAgentNotInstantiable" to __all__
```

### FILL IN checklist
- [ ] `BotConfig._kind_requirements`; bounded by Key Constraints
- [ ] `AgentRegistry.register_remote` + YAML discovery routing; bounded by "never instantiates", `register()`'s storage layout
- [ ] get_instance anchor disambiguation (2 occurrences)

---

## Acceptance Criteria

- [ ] `BotConfig(name="hr", kind="squawk", endpoint="squawk://hr:7470", contract_categories=["hr.reports"])` validates without `class_name`; `BotConfig(name="x")` (local) still requires `class_name`/`module`
- [ ] `register_remote` + `find_serving("hr.reports")` returns the entry; `find_by_kind(AgentKind.SQUAWK)` too; `await registry.get_instance("hr")` raises `RemoteAgentNotInstantiable` (AC13)
- [ ] Existing `test_unregister.py`, `test_yaml_roundtrip.py`, `test_registry_tooling_normalize.py` still pass
- [ ] ruff clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/registry/test_remote_kind.py -q`
- `pytest packages/ai-parrot/tests/registry/test_unregister.py -q`
- `pytest packages/ai-parrot/tests/registry/test_yaml_roundtrip.py -q`
- `pytest packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_remote_kind.py
import pytest
from parrot.registry import AgentKind, AgentRegistry, BotConfig, RemoteAgentNotInstantiable

def test_remote_config_needs_endpoint():
    with pytest.raises(ValueError):
        BotConfig(name="hr", kind="squawk")
    cfg = BotConfig(name="hr", kind="squawk", endpoint="squawk://hr:7470", contract_categories=["hr.reports"])
    assert cfg.kind is AgentKind.SQUAWK and cfg.class_name is None

async def test_register_remote_and_refuse_instance(tmp_path):
    reg = AgentRegistry(agents_dir=tmp_path)   # FILL IN: constructor kwargs per registry.py:297-328
    cfg = BotConfig(name="hr", kind="squawk", endpoint="squawk://hr:7470", contract_categories=["hr.reports"])
    reg.register_remote(cfg)
    assert [m.name for m in reg.find_serving("hr.reports")] == ["hr"]
    with pytest.raises(RemoteAgentNotInstantiable):
        await reg.get_instance("hr")
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug inter-agent-protocol --feature-id FEAT-746`)
2. **Read the spec** §3 M13, §7 "Discovery conflation", §9 S10
3. **Check dependencies** — none
4. **Verify the Codebase Contract** (re-grep every anchor; `get_instance` has 2 occurrences)
5. **Update status** → `"in-progress"`, commit only the index
6. **Implement**
7. **Verify** — Validation Commands (all four)
8. **Commit** — only the listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4750 inter-agent-protocol verified`
10. **Completion Note**

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
