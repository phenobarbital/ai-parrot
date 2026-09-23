# TASK-3653: BotManager._build_database_bot: pass normalized tools= and agent_mcp_servers=

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3645, TASK-3652
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem Statement + §3 Module 4, AC13, design research S1. The DB load path passes
`available_tools=bot_model.tools` (manager.py:515) — a kwarg `AbstractBot` never consumes, so DB
agents never register their `tools` column today. This task passes the normalized list as `tools=`.
**Behaviour change**: DB agents will now actually get their tools (call out in the PR; `tools_enabled`
is unchanged).

---

## Scope

- In `_build_database_bot`, compute `tooling = normalize_tooling(bot_model.tools,
  mcp_servers=getattr(bot_model, "mcp_servers", None) or [], toolkit_config=getattr(bot_model, "toolkit_config", None) or {})`
  before `class_name(...)`.
- Replace `available_tools=bot_model.tools,` with `tools=tooling.tools + tooling.toolkits,` and
  add `agent_mcp_servers=tooling.mcp_servers,`.
- Test with a fake bot class capturing kwargs.

**NOT in scope**: consuming `agent_mcp_servers` (TASK-3655) or ToolkitSpec entries (TASK-3654) —
until those land, specs in `tools` are logged as unknown by `_initialize_tools`, which is harmless.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Replace available_tools= with tools= + agent_mcp_servers= |
| `packages/ai-parrot-server/tests/manager/test_build_database_bot_tools.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.spec import normalize_tooling  # created by TASK-3645 (import inside the method to avoid import cycles)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    async def _build_database_bot(self, bot_model: Any, app: web.Application) -> AbstractBot:  # :434
        # class_name = self._resolve_database_bot_class(bot_model)  (:460)
        # bot_instance = class_name(chatbot_id=..., ..., tools_enabled=bot_model.tools_enabled,
        #     auto_tool_detection=..., tool_threshold=..., available_tools=bot_model.tools,   ← :515 anchor
        #     operation_mode=bot_model.operation_mode, ...)
        # await bot_instance.configure(app)  # :540
```

### Does NOT Exist
- ~~`available_tools` consumption anywhere in AbstractBot/ToolInterface~~ — the kwarg is dead; remove it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_build_database_bot_tools.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._build_database_bot"
  ]
}
```

---

## Implementation Notes

Keep every other constructor kwarg untouched.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Compute `tooling` right before `bot_instance = class_name(` — *why*: one normalization per build.
2. Swap the kwarg — *why*: AC13 / S1.
3. Test.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            available_tools=bot_model.tools,' manager.py)
# REPLACE `            available_tools=bot_model.tools,` (verified: manager.py:515) with:
            tools=tooling.tools + tooling.toolkits,
            agent_mcp_servers=tooling.mcp_servers,

# occurrences: 1 (verified: grep -c '        bot_instance = class_name(' manager.py)
# BEFORE `        bot_instance = class_name(` insert:
        # FEAT-593: DB agents get their tools (+ toolkit specs, agent-level MCP) through the
        # same normalization boundary as YAML agents. `available_tools=` was never consumed.
        from ..tools.spec import normalize_tooling  # pylint: disable=import-outside-toplevel

        tooling = normalize_tooling(
            bot_model.tools,
            mcp_servers=getattr(bot_model, "mcp_servers", None) or [],
            toolkit_config=getattr(bot_model, "toolkit_config", None) or {},
        )
```
**Why**: `..tools.spec` resolves to `parrot.tools.spec` from `parrot.manager` (the file already
imports `from ..handlers.models import BotModel` at :68). FILL IN: if the relative import fails
because `parrot.manager` lives in the server distribution, use the absolute `from parrot.tools.spec import normalize_tooling`.

### FILL IN checklist
- [ ] Import form (relative vs absolute); bounded by ruff clean + test passing

---

## Acceptance Criteria

- [ ] The constructed bot receives `tools=[...plain..., ToolkitSpec...]` and `agent_mcp_servers=[...]`.
- [ ] `available_tools` no longer appears in manager.py.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/manager/test_build_database_bot_tools.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/manager/test_build_database_bot_tools.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.manager.manager import BotManager
from parrot.tools.spec import ToolkitSpec


class _Captured:
    kwargs = None

    def __init__(self, **kwargs):
        _Captured.kwargs = kwargs
        self.configure = AsyncMock()


@pytest.mark.asyncio
async def test_tools_passed(monkeypatch):
    mgr = BotManager.__new__(BotManager)
    mgr.logger = MagicMock()
    mgr._resolve_database_bot_class = MagicMock(return_value=_Captured)
    mgr._normalize_database_bot_permissions = MagicMock(return_value={})
    mgr._apply_prompt_config = MagicMock()
    # FILL IN: stub create_reranker / post-configure steps that _build_database_bot calls
    #   (read manager.py:434-560) so the call reaches class_name(...)
    bot_model = SimpleNamespace(tools=["jira", "weather"], toolkit_config={"jira": {"params": {}}}, mcp_servers=[])
    # FILL IN: fill the remaining attributes _build_database_bot reads from bot_model
    await mgr._build_database_bot(bot_model, app=MagicMock())
    assert "available_tools" not in _Captured.kwargs
    assert "weather" in _Captured.kwargs["tools"]
    assert any(isinstance(t, ToolkitSpec) for t in _Captured.kwargs["tools"])
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
