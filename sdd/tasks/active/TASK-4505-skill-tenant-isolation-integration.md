# TASK-4505: Tenant isolation integration tests

**Feature**: FEAT-707 — Per-Tenant Skills for `SkillRegistryMixin`
**Spec**: `sdd/specs/per-tenant-skills.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4496, TASK-4503
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests and design-research S10. Unit tests prove each
piece; this task proves the property the feature exists for: one singleton
agent serving two tenants concurrently never mixes their skills — not in
`<available_skills>`, not in `/trigger` activation, not in `load_skill` /
`read_skill_asset`, not mid-stream. It runs the real `BaseBot.ask` binding
(TASK-4496) against the fully wired mixin (TASK-4503).

---

## Scope

- Create `packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py` with the six scenarios of spec §4 Integration Tests.
- Use a fake LLM client (no network; never `real_llm`) that records the system prompt and can emit one tool call.

**NOT in scope**: any production-code change. If a scenario fails because of a production bug, record it in the Completion Note, mark the task `done-with-issues`, and open a ledger issue (`wikitoolkit ledger open --discovered-from spec:FEAT-707 ...`) — do not fix it here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py` | CREATE | integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.skills.mixin import SkillRegistryMixin                    # verified: skills/mixin.py:27
from parrot.skills.tenancy import current_skill_tenant                # TASK-4494
from parrot.utils.helpers import RequestContext                       # verified: utils/helpers.py:7
```

### Existing Signatures to Use
```python
# BaseBot.ask(question, ..., ctx=None, ..., tenant: Optional[str] = None, **kwargs) -> AIMessage   (TASK-4496)
# SkillRegistryMixin: tenant_based, tenant_id, current_skill_view(), _configure_skill_file_registry()  (TASK-4499/4503)
# packages/ai-parrot/tests/integration/test_skill_system.py — existing end-to-end skill test: reuse its bot/LLM scaffolding
# packages/ai-parrot/tests/integration/conftest.py — existing integration fixtures
```

### Does NOT Exist
- ~~A ready-made "two tenant" fixture~~ — build it here (spec §4 Test Data `agent_tree`).
- ~~`real_llm` usage~~ — forbidden in the Validation Contract.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/skills/mixin.py#SkillRegistryMixin"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Read `test_skill_system.py` and `integration/conftest.py`; reuse their bot + fake-client scaffolding — *why*: avoids a second, divergent harness.
2. Build the `agent_tree` fixture per spec §4 (global + pokemon + epson, a composite pokemon skill with an asset, a `global_only` global skill).
3. Write the six scenarios; use `asyncio.gather` for concurrency and an `asyncio.Event` barrier so both requests are in flight at once.

### `packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py` (CREATE)
```python
"""FEAT-707 — tenant isolation on a singleton agent (TASK-4505)."""
import asyncio
from pathlib import Path

import pytest

# FILL IN: imports for the bot class / fake client reused from test_skill_system.py

# FILL IN: fixture agent_tree(tmp_path) — spec §4 Test Data
# FILL IN: fixture tenant_bot(agent_tree) — tenant_based=True, configured once, shared by both requests

async def test_two_tenants_concurrent_on_singleton(tenant_bot) -> None:
    """AC-V1/AC-V3: each concurrent ask sees only its own view (prompt block + list_skill_commands)."""
    # FILL IN: barrier in the fake client so both asks overlap; assert no epson skill text in the pokemon
    #          prompt and vice versa; assert /revenue resolves to each tenant's file


async def test_trigger_isolation_concurrent(tenant_bot) -> None:
    """AC-A1: concurrent '/revenue ...' asks each render only their own skill body."""
    # FILL IN


async def test_fixed_tenant_instance(agent_tree) -> None:
    """Class attribute tenant_id='pokemon' → pokemon view without a kwarg."""
    # FILL IN


async def test_global_only_end_to_end(tenant_bot, caplog) -> None:
    """AC-V4: tenant shadow of a global_only skill dropped, ERROR logged, global served."""
    # FILL IN


async def test_read_skill_asset_tenant_composite(tenant_bot) -> None:
    """AC-V1: assets come from the tenant composite skill only."""
    # FILL IN


async def test_ask_stream_mid_stream_tool_sees_tenant(tenant_bot) -> None:
    """AC-V3: a tool invoked during ask_stream reads the bound tenant."""
    # FILL IN
```

### FILL IN checklist
- [ ] scaffolding reuse
- [ ] fixtures
- [ ] six scenarios — bounded by AC-V1, AC-V3, AC-V4, AC-A1

---

## Acceptance Criteria

- [ ] All six scenarios pass deterministically (run the file 3× in a row).
- [ ] `test_skill_system.py` still passes unmodified.

## Validation Commands

- `pytest packages/ai-parrot/tests/integration/test_skill_tenant_isolation.py -q`
- `pytest packages/ai-parrot/tests/integration/test_skill_system.py -q`

---

## Test Specification

See the CREATE block.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug per-tenant-skills --feature-id FEAT-707`).
2. **Read the spec** §4 Integration Tests and Test Data.
3. **Check dependencies**: TASK-4496 and TASK-4503 `done`.
4. **Verify the Codebase Contract**.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint.
7. **Validate** with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit code** — only the listed file.
9. **Close** with `scripts/sdd/close_task.sh TASK-4505 per-tenant-skills verified` (or `partial` per Scope).
10. **Fill in the Completion Note** and commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
