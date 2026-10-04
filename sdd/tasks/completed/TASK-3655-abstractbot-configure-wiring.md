# TASK-3655: AbstractBot: pop agent_mcp_servers, call apply_tooling_specs() in configure()

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3654
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (2), §3 Module 5. `configure()` is the universal async hook for both the DB
(manager.py:540) and YAML paths. `agent_mcp_servers` is the kwarg TASK-3653 and TASK-3656 pass.

---

## Scope

- In `AbstractBot.__init__`, next to `self._credentials = ...` (:402): store
  `self._pending_mcp_specs = list(kwargs.pop("agent_mcp_servers", []) or [])` — before
  `_initialize_tools(tools)` runs.
- In `configure()`, immediately after `self.configure_conversation_memory()` (:1518), add
  `await self.apply_tooling_specs()` wrapped in try/except → `self.logger.error` (must not
  abort configure; the method itself never raises but be defensive).
- Test with a minimal concrete bot subclass if one is cheap, else unit-test via
  `AbstractBot.__new__` + patched collaborators.

**NOT in scope**: the apply logic (TASK-3654).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Pop agent_mcp_servers kwarg; await apply_tooling_specs() in configure() |
| `packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
# no new imports
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    def __init__(self, name="Nav", system_prompt=None, llm=None, instructions=None, tools=None, ..., **kwargs):  # :274
        self._credentials: list = list(kwargs.pop("credentials", []) or [])  # :402 ← anchor
        if tools:                                                             # :404
            self._initialize_tools(tools)                                     # :405
    async def configure(self, app=None) -> None:  # :1500 — try/finally sets self._configured
            self.configure_conversation_memory()  # :1518 ← anchor (inside the try)
```

### Does NOT Exist
- ~~`AbstractBot.agent_mcp_servers` public attribute~~ — stored privately as `_pending_mcp_specs`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.__init__",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure"
  ]
}
```

---

## Implementation Notes

Placement after conversation memory keeps KB/store configuration unchanged and before tools sync with the LLM client.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Pop the kwarg next to `_credentials` — *why*: must be off kwargs before they reach parents that reject unknown keys.
2. Await apply in configure — *why*: first async point for every build path.
3. Test.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — __init__)
```python
# occurrences: 1 (verified: grep -c 'self._credentials: list = list(kwargs.pop("credentials", \[\]) or \[\])' abstract.py)
# AFTER that line (verified: abstract.py:402) insert:
        # FEAT-593: agent-level MCP servers (AgentMCPServerSpec) — applied in configure().
        self._pending_mcp_specs: list = list(kwargs.pop("agent_mcp_servers", []) or [])
```

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — configure)
```python
# occurrences: 1 (verified: grep -c '            self.configure_conversation_memory()' abstract.py)
# AFTER `            self.configure_conversation_memory()` (verified: abstract.py:1518) insert:

            # FEAT-593: configured toolkits + agent-level MCP (async: vault, datasource replay)
            try:
                await self.apply_tooling_specs()
            except Exception as e:  # noqa: BLE001
                self.logger.error("Error applying tooling specs: %s", type(e).__name__)
```

### FILL IN checklist
- [ ] Confirm `_pending_mcp_specs` is set before any code path reads it; bounded by TASK-3654 getattr defaults

---

## Acceptance Criteria

- [ ] `agent_mcp_servers` kwarg never reaches parents (no TypeError on construction).
- [ ] `configure()` awaits `apply_tooling_specs()` exactly once per configure call.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.bots.abstract import AbstractBot


@pytest.mark.asyncio
async def test_configure_calls_apply(monkeypatch):
    bot = AbstractBot.__new__(AbstractBot)
    bot.logger = MagicMock()
    bot.apply_tooling_specs = AsyncMock(return_value=[])
    bot.configure_conversation_memory = MagicMock(side_effect=RuntimeError("stop-after"))
    # FILL IN: either stub every configure() step after memory, or assert ordering by making
    #   configure_conversation_memory a no-op and patching configure_kb etc. — read abstract.py:1500-1600
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

**Completed by**: sdd-worker orchestrator (execution `a3f5c9e2-7b41-4d8a-9c3e-591fd0d7a5b2`), coder seat `gpt-5.6-terra` (MCP backend `codex`), delivered via `coder_run_chunk` job `job-7cd277f8753b`, attempt `0538347634b64732847a45af08b0e78c`.
**Date**: 2026-09-23
**Feature branch**: `feat-FEAT-593-tool-configuration-agentstudio`
**Implementation SHA**: `bd32389e9e8223afac20aa4eb8e53a9c8032c4c3` (`feat(tool-configuration-agentstudio): TASK-3655 — engine-committed coder deliverable`)
**Merge commit**: `30906b0fa`
**Review**: `coder_record_review` recorded — `feedback_id: coder-review:64c032363a3d8b604aca423a`, `fix_commits: []`.

**Notes**: `coder_wait`/`coder_merge` returned `outcome: "merged"`, attempt `terminal: "completed"`, 1 attempt,
0 retries, 0 failures (171s). Diff verified against the task's file table: `parrot/bots/abstract.py` (MODIFY,
8 insertions — pops `agent_mcp_servers` kwarg, awaits `apply_tooling_specs()` in `configure()`) and
`tests/interfaces/test_configure_applies_tooling.py` (CREATE, 57 insertions) — exactly the 2 declared files,
no unlisted files, nothing under `sdd/` touched. Merge-time lint residual count was 14 for this file; spot-checked
that `abstract.py` is a large pre-existing file and this task's own diff is only 8 lines — pre-existing/unrelated
style debt per project policy, deferred to `/sdd-done`, not fixed here.

**Deviations from spec**: none.
