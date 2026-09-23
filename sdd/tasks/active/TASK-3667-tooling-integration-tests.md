# TASK-3667: Integration tests: persist → reload → built toolkit; datasources in memory; override isolation

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3653, TASK-3655, TASK-3657, TASK-3660, TASK-3662
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests; AC1, AC8, AC9. Proves the pieces fit: a Studio PUT followed by an
agent rebuild yields a toolkit instantiated with the persisted params (DB and YAML), datasources
live only in memory, and one user's override never leaks into another user's session.

---

## Scope

- `test_studio_toolkit_persist_reload_roundtrip` (DB agent; fake DB row + fake vault; rebuild via
  `BotManager._build_database_bot` with a minimal bot class).
- `test_yaml_agent_toolkit_persist_roundtrip` (tmp AGENTS_DIR; `update_agent_tooling`; factory rebuild).
- `test_dataset_manager_datasources_in_memory` (2 datasources replayed; mocked `add_*`; nothing written except the spec).
- `test_user_override_session_isolation` (two sessions, one override).
- Everything offline: monkeypatch vault functions, DocumentDB service, network toolkits (use a fake toolkit
  registered via a patched `_resolve_spec_class` / `discover_from_registry`).

**NOT in scope**: production code changes — if a test exposes a bug, fix it in the owning task's file and record it in the Completion Note.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` | CREATE | End-to-end tests with fake vault + tmp AGENTS_DIR |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.spec import ToolkitSpec, normalize_tooling  # TASK-3645
from parrot.handlers.studio.tooling_store import AgentToolingStore  # TASK-3659
from parrot.handlers.agent import AgentTalk  # verified: handlers/agent.py
from parrot.registry.registry import AgentRegistry, BotConfig  # verified: registry.py:224
from parrot.manager.manager import BotManager  # verified: tests/test_tools_list_route.py imports it
```

### Existing Signatures to Use
```python
# see TASK-3653 (_build_database_bot), TASK-3654/3655 (apply_tooling_specs in configure),
# TASK-3657 (update_agent_tooling), TASK-3659 (AgentToolingStore), TASK-3662 (_apply_user_toolkit_overrides)
```

### Does NOT Exist
- ~~network access in tests~~ — every external dependency is faked.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/studio/test_tooling_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

Reuse helper patterns from test_tooling_store.py / test_agenttalk_toolkit_overrides.py; do not import private helpers across test files — copy small fakes.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Shared fakes in the file (vault dict, fake toolkit, fake BotModel row) — *why*: offline, deterministic.
2. One test per scenario — *why*: maps 1:1 to spec §4 Integration Tests.

### `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` (CREATE — skeleton)
```python
"""FEAT-593 integration tests — offline, fakes only."""
import pytest

# FILL IN: fakes — vault dict (store/retrieve/delete patched in tooling_store + tools.spec modules),
#   _EchoKit(AbstractToolkit) with (prefix, token) ctor, patch ToolInterface._resolve_spec_class → _EchoKit


@pytest.mark.asyncio
async def test_studio_toolkit_persist_reload_roundtrip():
    # FILL IN: store.put_toolkit on a fake DB row → rebuild via _build_database_bot with a minimal
    #   AbstractBot subclass → await configure pieces → assert _EchoKit instance has prefix + hydrated token
    ...


@pytest.mark.asyncio
async def test_yaml_agent_toolkit_persist_roundtrip(tmp_path, monkeypatch):
    ...


@pytest.mark.asyncio
async def test_dataset_manager_datasources_in_memory():
    ...


@pytest.mark.asyncio
async def test_user_override_session_isolation():
    ...

### FILL IN checklist
- [ ] Four scenario bodies; bounded by AC1 / AC8 / AC9

---

## Acceptance Criteria

- [ ] All four tests pass offline.
- [ ] Any production fix made here is noted in the Completion Note.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py -q`

---

## Test Specification

```python
# see blueprint
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
