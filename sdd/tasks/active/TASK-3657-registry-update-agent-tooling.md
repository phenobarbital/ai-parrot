# TASK-3657: AgentRegistry.update_agent_tooling(): in-place atomic YAML rewrite

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3656
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, design research S10, AC5. Editing a registry agent must rewrite THE file it
was loaded from (`metadata.file_path`) — `create_agent_definition` derives the path from
category+name and could fork or move the definition.

---

## Scope

- Add `AgentRegistry.update_agent_tooling(name, *, toolkits=None, mcp_servers=None) -> Path`.
- Guards (→ `PermissionError` with a human message): no metadata → `KeyError`; `bot_config is None`;
  suffix not `.yaml/.yml`; `file_path.resolve()` not under `AGENTS_DIR.resolve()`; filename !=
  `f"{name.lower()}.yaml"` (or `.yml`).
- Load YAML (`yaml.safe_load`), replace only `agent.toolkits` and/or `agent.mcp_servers` (spec
  dumps with `exclude_defaults=True`), write to a temp file in the same dir, `os.replace`.
- Refresh `metadata.bot_config` (`toolkits` / `mcp_servers` fields) so a reload sees the change.

**NOT in scope**: HTTP handler (TASK-3659/3660).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/registry/registry.py` | MODIFY | Add update_agent_tooling() |
| `packages/ai-parrot/tests/registry/test_update_agent_tooling.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
import os, tempfile  # stdlib
import yaml  # already used by registry.py for definitions (verify the import name at the top of the file)
from ..conf import AGENTS_DIR  # verified: registry.py:35
from ..tools.spec import AgentMCPServerSpec, ToolkitSpec  # created by TASK-3645
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/registry/registry.py
@dataclass(slots=True)
class BotMetadata: name; factory; module_path; file_path: Path; ...; bot_config: Optional[Any] = None  # :46-64
class AgentRegistry:
    def get_metadata(self, name: str) -> Optional[BotMetadata]: ...  # :648
    def load_agent_definition_file(self, yaml_file: Path) -> bool:  # :979 — BotMetadata(file_path=yaml_file, bot_config=config) at :1052
    def create_agent_definition(self, config: BotConfig, category: str = "general") -> Path:  # :1069 ← insert new method after it
# Containment precedent: Path(file_path).resolve().is_relative_to(AGENTS_DIR.resolve())  (handlers/studio/agents.py:417)
```

### Does NOT Exist
- ~~`AgentRegistry.update_agent_tooling`~~ — this task creates it.
- ~~`BotMetadata.category`~~ — no category stored; always use `file_path`.

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
      "path": "packages/ai-parrot/tests/registry/test_update_agent_tooling.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#AgentRegistry.get_metadata",
    "sym:packages/ai-parrot/src/parrot/registry/registry.py#BotMetadata"
  ]
}
```

---

## Implementation Notes

Preserve every other YAML key verbatim (load → mutate two keys → dump with `sort_keys=False`).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Implement guards first — *why*: AC5 read-only semantics.
2. Atomic write with tempfile + os.replace — *why*: S10.
3. Refresh metadata.bot_config — *why*: `reload_agent` rebuilds from metadata.
4. Tests on tmp AGENTS_DIR.

### `packages/ai-parrot/src/parrot/registry/registry.py` (MODIFY)
```python
# FILL IN: insert right after the end of `create_agent_definition` (verified: registry.py:1069..end of method)
    def update_agent_tooling(
        self,
        name: str,
        *,
        toolkits: list[ToolkitSpec] | None = None,
        mcp_servers: list[AgentMCPServerSpec] | None = None,
    ) -> Path:
        """Rewrite ``agent.toolkits`` / ``agent.mcp_servers`` of the agent's own YAML in place (FEAT-593).

        Raises:
            KeyError: unknown agent.
            PermissionError: not an editable YAML definition under ``AGENTS_DIR`` named ``{name}.yaml``.
        """
        meta = self.get_metadata(name)
        if meta is None:
            raise KeyError(name)
        path = Path(meta.file_path).resolve() if meta.file_path else None
        # FILL IN: guards → PermissionError("<reason>") for: bot_config None, path None, suffix not in
        #   {".yaml", ".yml"}, not path.is_relative_to(AGENTS_DIR.resolve()), path.stem != name.lower()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        agent = data.setdefault("agent", {})
        if toolkits is not None:
            agent["toolkits"] = [t.model_dump(exclude_defaults=True) for t in toolkits]
        if mcp_servers is not None:
            agent["mcp_servers"] = [m.model_dump(exclude_defaults=True) for m in mcp_servers]
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        # FILL IN: refresh meta.bot_config.toolkits / .mcp_servers (BotConfig is a pydantic model:
        #   meta.bot_config = meta.bot_config.model_copy(update={...}))
        self.logger.info("Updated tooling for agent '%s' in %s", name, path)
        return path
```
**Why**: toolkits dumped as dicts (not bare strings) is fine — `BotConfig.toolkits` accepts both
after TASK-3656.

### FILL IN checklist
- [ ] Guard conditions + messages; bounded by AC5 / spec §3 M6 skeleton
- [ ] metadata refresh; bounded by BotConfig being a pydantic model
- [ ] Confirm the yaml module import used by registry.py

---

## Acceptance Criteria

- [ ] Rewrites the exact file; other keys (model, system_prompt, tags…) unchanged.
- [ ] Refuses (PermissionError) a `.py` agent, YAML outside AGENTS_DIR, misnamed YAML (AC5).
- [ ] No temp files left behind on success or failure.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/registry/test_update_agent_tooling.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/registry/test_update_agent_tooling.py
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from parrot.registry import registry as registry_module
from parrot.registry.registry import AgentRegistry, BotConfig
from parrot.tools.spec import ToolkitSpec


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(registry_module, "AGENTS_DIR", tmp_path)
    f = tmp_path / "agents" / "general" / "demo.yaml"
    f.parent.mkdir(parents=True)
    f.write_text(yaml.safe_dump({"agent": {"name": "demo", "toolkits": [], "tags": ["x"]}, "model": {"provider": "p"}}))
    reg = AgentRegistry.__new__(AgentRegistry)
    reg.logger = SimpleNamespace(info=lambda *a, **k: None)
    cfg = BotConfig(name="demo", class_name="C", module="m")
    reg.get_metadata = lambda name: SimpleNamespace(file_path=f, bot_config=cfg) if name == "demo" else None
    return reg, f


def test_rewrites_in_place(setup):
    reg, f = setup
    reg.update_agent_tooling("demo", toolkits=[ToolkitSpec(slug="jira", params={"a": 1})])
    data = yaml.safe_load(f.read_text())
    assert data["agent"]["toolkits"][0]["slug"] == "jira" and data["model"] == {"provider": "p"}
    assert not list(f.parent.glob(".*.tmp"))


def test_refuses_outside_agents_dir(setup, tmp_path):
    reg, _ = setup
    outside = tmp_path.parent / "demo.yaml"
    reg.get_metadata = lambda name: SimpleNamespace(file_path=outside, bot_config=object())
    with pytest.raises(PermissionError):
        reg.update_agent_tooling("demo", toolkits=[])
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
