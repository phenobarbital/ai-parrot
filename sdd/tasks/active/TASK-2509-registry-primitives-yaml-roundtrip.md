# TASK-2509: Registry primitives + lossless YAML round-trip

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 — deliberately TASK #1 (resolved in brainstorm): every
Studio persist path depends on `AgentRegistry.create_agent_definition`
writing YAML that `load_agent_definitions` can read back **without loss**.
Today it silently drops `toolkits`, `prompt`, `vector_store`, `tags`,
`policies`, `mcp_servers`, `priority`, `at_startup`, `config`. The Studio
also needs a per-agent `unregister(name)` primitive (today only
`delete_factory_agent` and test-only `clear_registry` exist) and
replace-safe re-registration for the reload flow (TASK-2510).

---

## Scope

- Fix `AgentRegistry.create_agent_definition` to serialize the FULL
  `BotConfig` (all fields listed above) into the `agent:`-keyed YAML
  format that `load_agent_definitions` consumes.
- Ensure `load_agent_definitions` maps every serialized field back onto
  `BotConfig` (extend its parsing where a field was never read because it
  was never written — e.g. `toolkits`, `vector_store`, `policies`).
- Add `AgentRegistry.unregister(self, name: str) -> bool` — removes the
  `BotMetadata` entry and its cached `_instance`; returns False for
  unknown names; never raises for missing entries.
- Make `register(..., replace=True)` drop the stale `BotMetadata._instance`
  of the entry it replaces (so reload cannot serve a zombie instance).
- Write round-trip + unregister unit tests.

**NOT in scope**: `BotManager.reload_agent` (TASK-2510); any HTTP handler;
changes to `delete_factory_agent` semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | round-trip fix, `unregister`, replace-safe register |
| `packages/ai-parrot/tests/registry/test_yaml_roundtrip.py` | CREATE | round-trip equality matrix |
| `packages/ai-parrot/tests/registry/test_unregister.py` | CREATE | unregister + replace-instance-drop tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.registry import agent_registry, register_agent   # registry/__init__.py:7-12
from parrot.registry.registry import AgentRegistry, BotConfig  # registry.py:252,222
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
class BotConfig(BaseModel):  # :222
    name: str; class_name: str; module: str; enabled: bool = True
    origin: Literal["repo", "factory"] = "repo"
    config: Dict[str, Any]; tools: Optional[ToolConfig]; toolkits: List[str]
    mcp_servers: List[Dict[str, Any]]; model: Optional[ModelConfig]
    system_prompt: Optional[Union[str, Dict]]; prompt: Optional[PromptConfig]
    vector_store: Optional[StoreConfig]; tags: Optional[Set[str]]
    singleton: bool = False; at_startup: bool = False
    startup_config: Dict[str, Any]; priority: int = 0
    policies: Optional[List["PolicyRuleConfig"]]

class AgentRegistry:  # :252
    def register(self, name, factory, *, singleton=False, tags=None,
                 priority=0, dependencies=None, replace=False, at_startup=False,
                 startup_config=None, bot_config=None, **kwargs) -> None: ...  # :522
    def load_agent_definitions(self, definitions_dir: Optional[Path] = None) -> int: ...  # :962
        # default AGENTS_DIR/'agents' (:967); rglob("*.yaml"); requires `agent:` key;
        # maps top-level model:/tools:/system_prompt:/prompt:/events:
    def create_agent_definition(self, config: BotConfig,
                                category: str = "general") -> Path: ...  # :1053
        # writes AGENTS_DIR/agents/<category>/<name>.yaml; yaml.dump at :1086
    def delete_factory_agent(self, name: str) -> tuple[bool, str]: ...  # :1090
    def clear_registry(self) -> None: ...  # :1350 (test-only)
# BotMetadata dataclass :43 — fields incl. bot_config, file_path, _instance;
#   async get_instance :79
# AGENTS_DIR: packages/ai-parrot/src/parrot/conf.py:175
```

### Does NOT Exist
- ~~`AgentRegistry.unregister(name)`~~ — THIS task creates it.
- ~~A loader for `AGENTS_DIR/<name>/config.yaml`~~ — canonical format is
  the `agent:`-keyed YAML of `load_agent_definitions`; do not invent a
  second format.
- ~~`agents/agents/` directory in the repo~~ — created on first write.
- ~~`BotConfig.save()` / `.to_yaml()`~~ — serialization lives in
  `create_agent_definition`, not on the model.

---

## Implementation Notes

### Pattern to Follow
The existing writer builds a `data = {"agent": {...}}` dict then optional
top-level `model`/`tools`/`system_prompt` keys (registry.py:1057-1087).
Extend that dict-building symmetrically with the reader in
`load_agent_definitions` (:962-1050) so the two stay one format. Prefer
`config.model_dump(exclude_none=True)` per-section over ad-hoc field
picking.

### Key Constraints
- Round-trip test is the definition of done:
  `BotConfig → create_agent_definition → load_agent_definitions` must yield
  an equal `BotConfig` for a fully-populated fixture.
- Keep backward compatibility: YAMLs written by the OLD writer must still
  load (all new keys optional on read).
- `unregister` must also work for instances added via `register_instance`.
- Google-style docstrings, type hints, `self.logger`.

### References in Codebase
- `packages/ai-parrot/tests/test_agent_definitions.py` — existing
  definition-loading tests to extend/mirror.
- `packages/ai-parrot/src/parrot/bots/factory/tools/finalize.py:31` —
  caller of `create_agent_definition` that must keep working.

---

## Acceptance Criteria

- [ ] Fully-populated `BotConfig` round-trips losslessly (all 9 previously
      dropped fields survive).
- [ ] Old-format YAML files still load.
- [ ] `unregister` removes metadata + cached instance; returns False on
      unknown name.
- [ ] `register(replace=True)` drops the replaced entry's `_instance`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/registry/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/registry/`

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_yaml_roundtrip.py
import pytest
from parrot.registry.registry import AgentRegistry, BotConfig

@pytest.fixture
def full_config() -> BotConfig:
    """BotConfig with every optional field populated."""

def test_roundtrip_lossless(tmp_path, full_config):
    reg = AgentRegistry(agents_dir=tmp_path)
    path = reg.create_agent_definition(full_config, category="general")
    assert path.exists()
    count = reg.load_agent_definitions(path.parent)
    assert count == 1
    meta = reg.get_metadata(full_config.name)
    assert meta.bot_config.toolkits == full_config.toolkits
    assert meta.bot_config.vector_store == full_config.vector_store
    # ... assert remaining previously-dropped fields

def test_old_format_still_loads(tmp_path):
    """YAML lacking the new keys loads with defaults."""

# packages/ai-parrot/tests/registry/test_unregister.py
def test_unregister_removes_entry_and_instance(): ...
def test_unregister_unknown_returns_false(): ...
def test_register_replace_drops_stale_instance(): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
