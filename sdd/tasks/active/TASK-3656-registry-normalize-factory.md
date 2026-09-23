# TASK-3656: Registry: widen BotConfig.toolkits, normalize in factory, drop dead loops, round-trip specs

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3645
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, design research S1, AC13. The factory reads only `config.tools.toolkits`
(dead `pass` loop, :942-950) and `config.tools.mcp_servers` (:933-939); the top-level
`toolkits` / `mcp_servers` that `create_agent_definition` writes (:1125-1126) are never read.

---

## Scope

- `BotConfig.toolkits: List[Union[str, ToolkitSpec]]`.
- In the factory (`async def factory(**kwargs)`, :858): after `tools_list` is built, call
  `normalize_tooling(tools_list, list(config.toolkits) + list(config.tools.toolkits if config.tools else []),
  list(config.mcp_servers) + list(config.tools.mcp_servers if config.tools else []))`; set
  `merged_args["tools"] = tooling.tools + tooling.toolkits` and
  `merged_args["agent_mcp_servers"] = tooling.mcp_servers`.
- Delete the post-init MCP loop (:932-939) and the dead toolkit loop (:941-950) — MCP now goes
  through `apply_tooling_specs` (TASK-3654/3655).
- `create_agent_definition`: write toolkits as `[t if isinstance(t, str) else t.model_dump(exclude_defaults=True) for t in config.toolkits]`.
- Tests: YAML-shaped BotConfig with top-level toolkits dicts + mcp_servers reaches the
  constructed bot's kwargs; round-trip lossless.

**NOT in scope**: `update_agent_tooling` (TASK-3657).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | BotConfig.toolkits type; factory normalization; remove dead loops; create_agent_definition dump |
| `packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.spec import ToolkitSpec, normalize_tooling  # created by TASK-3645 (use relative `from ..tools.spec import ...` inside registry.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
from ..mcp import MCPServerConfig  # :32
class BotConfig(BaseModel):  # :224
    tools: Optional[ToolConfig] = Field(default=None)             # :236
    toolkits: List[str] = Field(default_factory=list)             # :237 ← anchor
    mcp_servers: List[Dict[str, Any]] = Field(default_factory=list)  # :238
# create_agent_factory → async def factory(**kwargs) -> AbstractBot:   # :858
#   tools_list built from config.tools.tools (:893-905); `            merged_args["tools"] = tools_list` (:907) ← anchor
#   bot = agent_class(**merged_args)  (:925)
#   `            if config.tools and config.tools.mcp_servers:` (:933) … loop to :939   ← delete
#   `            # Handle Toolkits` (:942) … `pass` loop to :950                           ← delete
class AgentRegistry:
    def create_agent_definition(self, config: BotConfig, category: str = "general") -> Path:  # :1069
        #   "toolkits": list(config.toolkits),   (:1125) ← anchor
        #   "mcp_servers": config.mcp_servers,   (:1126)
# packages/ai-parrot/src/parrot/models/basic.py
class ToolConfig(BaseModel): tools; mcp_servers: List[Dict]; toolkits: List[str]  # :33-37 (unchanged)
```

### Does NOT Exist
- ~~a working toolkit loader in the factory~~ — the loop is `pass`; delete it.
- ~~`BotConfig.datasets`~~ — datasets are `dataset_manager` toolkit params.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/registry/registry.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotConfig",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.create_agent_definition",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ToolConfig"
  ]
}
```

---

## Implementation Notes

- A second, older factory at registry.py:90-135 (`BotMetadata.get_instance`) forwards
  `merged_kwargs["toolkits"]` — leave it; it serves `startup_config` instantiation and is out of scope,
  but confirm it does not break once `toolkits` items can be dicts/specs (it only forwards them).
- MCP dicts in YAML may carry raw `headers`/`auth_config`: `normalize_tooling` keeps them in
  `params` (legacy repo YAML); Studio-written YAML has them vaulted.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Widen the field — *why*: YAML entries become `str | {slug, params, user_overridable}`.
2. Normalize in the factory; delete both post-init loops — *why*: one path (S1).
3. Serialize specs in `create_agent_definition` — *why*: lossless round-trip.
4. Tests.

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY — BotConfig)
```python
# occurrences: 1 (verified: grep -c '    toolkits: List\[str\] = Field(default_factory=list)' registry.py)
# REPLACE (verified: registry.py:237):
    toolkits: List[Union[str, ToolkitSpec]] = Field(default_factory=list)  # FEAT-593: str | spec
```

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY — factory)
```python
# occurrences: 1 (verified: grep -c '            merged_args\["tools"\] = tools_list' registry.py)
# REPLACE `            merged_args["tools"] = tools_list` (verified: registry.py:907) with:
            tooling = normalize_tooling(
                tools_list,
                list(config.toolkits) + list(config.tools.toolkits if config.tools else []),
                list(config.mcp_servers) + list(config.tools.mcp_servers if config.tools else []),
            )
            merged_args["tools"] = tooling.tools + tooling.toolkits
            merged_args["agent_mcp_servers"] = tooling.mcp_servers

# DELETE the block starting at `            # Handle MCP Servers from ToolConfig` /
#   `            if config.tools and config.tools.mcp_servers:` (verified: registry.py:932-939)
#   and the block starting at `            # Handle Toolkits` (verified: registry.py:941-950).
```

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY — writer)
```python
# occurrences: 1 (verified: grep -c '            "toolkits": list(config.toolkits),' registry.py)
# REPLACE (verified: registry.py:1125):
            "toolkits": [t if isinstance(t, str) else t.model_dump(exclude_defaults=True) for t in config.toolkits],
```
Add `from ..tools.spec import ToolkitSpec, normalize_tooling` to the imports (check for cycles —
`parrot.tools.spec` imports only pydantic + `parrot.security.vault_utils`) and `Union` if missing.

### FILL IN checklist
- [ ] Verify `MCPServerConfig` import is still used after deleting the loop; drop it if unused (ruff F401)
- [ ] Verify `Union` is imported in registry.py

---

## Acceptance Criteria

- [ ] A BotConfig with top-level `toolkits: [{"slug": "jira", "params": {...}}]` and `mcp_servers: [...]` yields a bot constructed with a ToolkitSpec in `tools` and specs in `agent_mcp_servers` (AC13).
- [ ] No `pass` toolkit loop / post-init MCP loop remains.
- [ ] `create_agent_definition` → `load_agent_definition_file` round-trips a dict toolkit entry losslessly.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_registry_tooling_normalize.py
import pytest
from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.tools.spec import ToolkitSpec


def test_botconfig_accepts_specs():
    cfg = BotConfig(name="a", class_name="BasicAgent", module="parrot.bots.agent",
                    toolkits=["weather", {"slug": "jira", "params": {"default_project": "T"}}])
    assert isinstance(cfg.toolkits[1], ToolkitSpec)


@pytest.mark.asyncio
async def test_factory_passes_specs(monkeypatch):
    # FILL IN: build the factory for a BotConfig whose class records its kwargs (monkeypatch the class
    #   resolution in create_agent_factory — read registry.py:840-860), await factory(), assert
    #   kwargs["tools"] contains a ToolkitSpec and kwargs["agent_mcp_servers"] has one spec
    ...


def test_create_agent_definition_roundtrip(tmp_path, monkeypatch):
    # FILL IN: monkeypatch parrot.registry.registry.AGENTS_DIR → tmp_path; write + reload; compare toolkits
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
