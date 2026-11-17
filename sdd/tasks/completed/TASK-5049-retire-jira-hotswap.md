# TASK-5049: Retire the FEAT-083 Jira hot-swap placeholder (`JiraConnectTool`, `_bootstrap_jira_oauth_session`)

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §1 problem 6, §3 Module 6, G6, AC-10. `JiraConnectTool` / `setup_jira_oauth_session` /
`hotswap_to_full_toolkit` (`parrot/tools/jira_connect_tool.py`) are reachable only through
`agent.jira_credential_resolver`, which nothing sets. Since S-1, `JiraToolkit` declares
`credential_provider = "jira"` (`parrot_tools/jiratoolkit.py:838`) and is gated by the broker seam, so the
placeholder and its AgentTalk bootstrap are dead code. This task deletes them with every reference.

---

## Scope

- Delete `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` and `packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py`.
- In `handlers/agent.py`: delete the bootstrap call + its comment block in `_setup_agent_tools`, delete
  `_bootstrap_jira_oauth_session`, and reword the comment at the `user_id` extraction that cites it.
- Drop the stale `handler._bootstrap_jira_oauth_session = AsyncMock()` stub in `test_tooling_identity.py`.
- Reword the two example prose references to `JiraConnectTool` (README + docstring) to point at the Connections flow.
- Add `test_jira_connect_tool_removed`.

**NOT in scope**: `JiraToolkit` itself, `JiraOAuthManager`, Slack Jira commands (TASK-5044), the AgentTalk
`auth_required` work (TASK-5051 — it edits the same `agent.py` after this task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/jira_connect_tool.py` | DELETE | dead placeholder |
| `packages/ai-parrot/tests/unit/test_agentalk_jira_connect.py` | DELETE | its test |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | remove bootstrap call + method |
| `packages/ai-parrot-server/tests/studio/test_tooling_identity.py` | MODIFY | drop stale stub |
| `examples/orchestrator/README.md` | MODIFY | prose |
| `examples/orchestrator/escalation.py` | MODIFY | docstring prose |
| `packages/ai-parrot-server/tests/unit/test_jira_connect_tool_removed.py` | CREATE | removal test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import importlib                                                  # stdlib
from parrot.handlers.agent import AgentTalk                       # verified: test_tooling_identity.py uses agent_module.AgentTalk
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
#   inside _setup_agent_tools: comment block :1031-1035, call `        await self._bootstrap_jira_oauth_session(` :1036-1040,
#   followed by `        return tool_manager` :1042
async def _bootstrap_jira_oauth_session(self, agent, tool_manager, request_session) -> None   # :1044-1090
#   (lazy `from ..tools.jira_connect_tool import setup_jira_oauth_session` :1073)
#   :1180  "# Extract user_id from session (same pattern as _bootstrap_jira_oauth_session)"

# packages/ai-parrot-server/tests/studio/test_tooling_identity.py:35
    handler._bootstrap_jira_oauth_session = AsyncMock()
```

### Does NOT Exist
- ~~Any other reference~~ — `grep -rn "jira_connect_tool\|JiraConnectTool\|hotswap_to_full_toolkit\|_bootstrap_jira_oauth_session\|setup_jira_oauth_session\|jira_credential_resolver" packages/*/src packages/*/tests tests`
  (verified 2026-10-31) hits only: the two files deleted here, `handlers/agent.py` (:1032, :1035, :1036, :1044, :1053, :1058, :1073, :1076, :1180),
  `test_tooling_identity.py:35`, and the untracked build artifact `packages/ai-parrot/src/ai_parrot.egg-info/SOURCES.txt` (NOT in git — do not edit).
  Outside `packages/`: `examples/orchestrator/README.md:112`, `examples/orchestrator/escalation.py:115` (tracked) and
  `docs/superpowers/plans/2026-04-17-feat107-review-fixes.md` (historical plan — leave it).
- ~~A lazy-import map entry for `jira_connect_tool`~~ — `parrot/tools/__init__.py` has none.

---

## Complexity Contract

> DELETE rows are not complexity targets (the evaluator accepts only CREATE/MODIFY and its table parser
> skips DELETE rows), so the two deleted files are intentionally absent below.

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/agent.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/studio/test_tooling_identity.py", "action": "MODIFY"},
    {"path": "examples/orchestrator/README.md", "action": "MODIFY"},
    {"path": "examples/orchestrator/escalation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/test_jira_connect_tool_removed.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/agent.py#AgentTalk._bootstrap_jira_oauth_session"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `git rm` the two files — *why*: AC-10.
2. Edit `agent.py` — *why*: the call is the only reachable entry into the deleted module.
3. Drop the test stub and reword the examples — *why*: AC-10 "no remaining reference in `packages/`"; the examples would otherwise point readers at a removed class.
4. Add the removal test; run the Validation Commands.

### `packages/ai-parrot-server/src/parrot/handlers/agent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        await self._bootstrap_jira_oauth_session(' packages/ai-parrot-server/src/parrot/handlers/agent.py)
# DELETE the comment block "# Optional Jira OAuth 2.0 (3LO) session bootstrap. …" (:1031-1035) and the call (:1036-1040);
# keep `        return tool_manager` (:1042).

# occurrences: 1 (verified: grep -c '    async def _bootstrap_jira_oauth_session(' …agent.py)
# DELETE the method `_bootstrap_jira_oauth_session` entirely (:1044 through the end of its `except` block, :1090).

# :1180 — REPLACE the comment with:
        # Extract user_id from the request session
```

### `packages/ai-parrot-server/tests/studio/test_tooling_identity.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    handler._bootstrap_jira_oauth_session = AsyncMock()' …test_tooling_identity.py)
# DELETE line :35.
```

### Examples (MODIFY — prose only)
```text
examples/orchestrator/README.md:111-113  → "...for a call to your full Jira toolkit (`JiraToolkit` with
  `credential_provider="jira"`; users connect Jira once through the Connections flow)."
examples/orchestrator/escalation.py:114-116 (docstring) → "(JiraToolkit, gated by the credential broker, is the OAuth bridge)."
```

### `packages/ai-parrot-server/tests/unit/test_jira_connect_tool_removed.py` (CREATE)
```python
"""FEAT-777 M6: the FEAT-083 hot-swap placeholder is gone."""
import importlib

import pytest

from parrot.handlers.agent import AgentTalk


def test_jira_connect_tool_removed() -> None:
    """The module is not importable and AgentTalk no longer bootstraps it."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("parrot.tools.jira_connect_tool")
    assert not hasattr(AgentTalk, "_bootstrap_jira_oauth_session")
```
**Why**: `parrot.tools.<x>` falls back through a `sys.meta_path` finder to `parrot_tools.<x>` / `plugins.tools.<x>`
(CLAUDE.md); confirm it still raises `ModuleNotFoundError` for an unknown name — if the finder raises `ImportError`
instead, widen the `pytest.raises` to `ImportError` (its parent class).

### FILL IN checklist
- [ ] confirm the meta_path finder's exception type for a missing name — bounded by the test above
- [ ] example wording — bounded by "prose only, no code change"

---

## Acceptance Criteria

- [ ] The grep in "Does NOT Exist" returns nothing under `packages/*/src`, `packages/*/tests`, `tests/` (AC-10).
- [ ] `test_jira_connect_tool_removed` and `test_tooling_identity.py` pass.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_jira_connect_tool_removed.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_identity.py -q`

---

## Test Specification

See `test_jira_connect_tool_removed.py` above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** (re-run the grep) before deleting anything
5. **Update status** in the per-spec index → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`
8. **Commit the code** — stage only the files listed above (`git rm` for the deletions)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5049 connections-web-slack verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seats codex terra/sol/luna + native sonnet
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated (only red: 3 failures that also fail on origin/dev: test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: spec M6 lists three files; the stale test stub and example prose are included so AC-10 holds.
