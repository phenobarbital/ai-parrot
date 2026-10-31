# TASK-5065: `MSTeamsCommandRouter` stores command arguments in `turn_state`

**Feature**: FEAT-775 — Connections on MS Teams
**Spec**: `sdd/specs/connections-msteams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Router arguments (M2)", §3 Module 2, AC-4. Handlers get only `turn_context`; agent commands re-read
`activity.text`, which is empty for a card `Action.Submit` routed at wrapper.py:601-605. `/connect jira` from a
card must behave exactly like the typed command. Keep the handler signature `handler(turn_context)` — agent,
auth and knowledge-upload handlers depend on it.

---

## Scope

- `COMMAND_ARGS_KEY = "msteams.command_args"` and `command_args(turn_context) -> str` in `commands/__init__.py`.
- `try_dispatch`: set `turn_state[COMMAND_ARGS_KEY] = parts[1].strip() if len(parts) > 1 else ""` right before
  calling the handler. `try_dispatch_plain`: set it to `""`.
- Tests: `test_router_stashes_args_text_and_card`.

**NOT in scope**: the connection handlers (TASK-5069/5070), wrapper changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` | MODIFY | args key, helper, two stash points |
| `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_command_args.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.msteams.commands import MSTeamsCommandRouter   # verified: commands/__init__.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py
from typing import Callable, Dict, TYPE_CHECKING                                 # :22
class MSTeamsCommandRouter:                                                      # :30
    def register(self, command: str, handler: Callable) -> None                  # :56 (lstrip("/"))
    async def try_dispatch(self, text: str, turn_context) -> bool                # :74
        parts = text.split(maxsplit=1)                                           # :90
        cmd = parts[0].lstrip("/")
        handler = self._handlers.get(cmd)
        ...
            await handler(turn_context)                                          # :97
    async def try_dispatch_plain(self, text: str, turn_context) -> bool          # :111
        handler = self._handlers.get(text)                                       # :133
            await handler(turn_context)                                          # :138
```
`TurnContext.turn_state` is a plain dict on botbuilder's `TurnContext`.

### Does NOT Exist
- ~~handler(turn_context, args)~~ — never change the signature.
- ~~`command_args`~~ / ~~`COMMAND_ARGS_KEY`~~ — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_command_args.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py#MSTeamsCommandRouter"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add key + helper below `logger = logging.getLogger(__name__)`.
2. Stash in `try_dispatch` after the `handler is None` check — *why*: unknown commands must not leave state behind.
3. Stash `""` in `try_dispatch_plain` likewise. 4. Tests.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/__init__.py` (MODIFY)
```python
# AFTER — insert below `logger = logging.getLogger(__name__)` (verify: grep -cxF 'logger = logging.getLogger(__name__)' commands/__init__.py → 1)
COMMAND_ARGS_KEY = "msteams.command_args"


def command_args(turn_context: "TurnContext") -> str:
    """Return the text after the dispatched command word ('' when none).

    Args:
        turn_context: The turn the router dispatched.

    Returns:
        The argument string stored by :class:`MSTeamsCommandRouter`.
    """
    state = getattr(turn_context, "turn_state", None)
    if not isinstance(state, dict):
        return ""
    value = state.get(COMMAND_ARGS_KEY, "")
    return value if isinstance(value, str) else ""


def _store_args(turn_context: "TurnContext", args: str) -> None:
    """Store ``args`` on the turn; tolerate test doubles without a turn_state dict."""
    # FILL IN: set turn_context.turn_state[COMMAND_ARGS_KEY] = args when turn_state is a dict — bounded by spec M2
```
In `try_dispatch`, directly before the first `            await handler(turn_context)` (occurrences of that line: 2,
:97 and :138 — disambiguate by the enclosing method; the :97 one follows `        try:` after `if handler is None: return False`
in `try_dispatch`):
```python
        _store_args(turn_context, parts[1].strip() if len(parts) > 1 else "")
```
In `try_dispatch_plain`, before the :138 call: `        _store_args(turn_context, "")`.
**Why**: card `Action.Submit {"command": "/connect jira"}` already reaches `try_dispatch` with the full text, so
the same parsing serves typed and card commands.

### `packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_command_args.py` (CREATE)
```python
"""FEAT-775 M2: router command arguments."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args


def _turn():
    tc = MagicMock()
    tc.turn_state = {}
    tc.send_activity = AsyncMock()
    return tc


@pytest.mark.asyncio
async def test_router_stashes_args_text_and_card():
    # FILL IN: register "connect" with a handler capturing command_args(tc); dispatch "/connect jira" and
    # "/connect   jira  " → "jira"; "/connect" → ""; assert handler signature still (turn_context) only
    ...


@pytest.mark.asyncio
async def test_plain_dispatch_clears_args():
    # FILL IN: a stale value in turn_state is replaced by "" on try_dispatch_plain("integrations", tc)
    ...


def test_command_args_without_turn_state():
    # FILL IN: object without turn_state → ""
    ...
```

### FILL IN checklist
- [ ] `_store_args` body
- [ ] three tests

---

## Acceptance Criteria

- [ ] Typed and card-submitted commands yield the same `command_args` (AC-4).
- [ ] Existing handlers unaffected (`test_agent_commands.py` still passes).
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_msteams_command_args.py -q`
- `pytest packages/ai-parrot-integrations/tests/integrations/msteams/test_agent_commands.py -q`

---

## Test Specification

Three tests listed in the test-file block.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-msteams --feature-id FEAT-775`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/connections-msteams.json`
4. **Verify the Codebase Contract** — before writing ANY code confirm every import and signature still exists;
   if anything changed, update the contract FIRST; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH` pointing at the changed packages
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-<NNN> connections-msteams verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

