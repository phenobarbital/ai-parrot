# TASK-4755: Round-trip integration test — execute slug → materialize → pinned refreshable widget

**Feature**: FEAT-757 — Materialize a chat turn as a linked widget
**Spec**: `sdd/specs/materialize-turn-linked-widget.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4754
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, `test_materialize_then_refresh_roundtrip`. The unit tests in TASK-4754 use fake sibling
tools. This test proves that the real chain works end to end inside one process: a real `QuerysourceToolkit`
(with QuerySource faked at its seam), registered on a real `ToolManager`, plus a real `PublishSurfaceTool`
(standalone lane, fake store). Specifically, it checks that the tool's calls line up with the real toolkit's
signatures and that the pinned envelope is linked.

---

## Scope

- Create `packages/ai-parrot-tools/tests/querysource/test_materialize_widget_roundtrip.py`. It lives in
  `querysource/` so it can use that directory's `patched_qs` conftest fixture.
- Copy the `fake_core_qs` fixture pattern from `test_build_linked_surface_tool.py` into the new file. Do not import
  it from there, and do not move it into `conftest.py`.

**NOT in scope**: any source change; editing `querysource/conftest.py` (that would make this task exclusive);
real Postgres or a real HTTP server.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/querysource/test_materialize_widget_roundtrip.py` | CREATE | Integration round-trip test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from parrot.memory import ConversationHistory, ConversationTurn                 # verified: memory/__init__.py:3
from parrot.memory.compaction.models import ToolInvocation                      # verified: compaction/models.py:46
from parrot.outputs.a2ui.linked import has_data_sources                          # verified: linked/__init__.py:63
from parrot.tools.manager import ToolManager                                    # verified: tools/manager.py:289
from parrot_tools.querysource.toolkit import QuerysourceToolkit                 # verified: test_build_linked_surface_tool.py:13
from parrot_tools.ui_surfaces import PublishSurfaceTool                         # verified: parrot_tools/ui_surfaces.py:65
from parrot_tools.materialize_widget import MaterializeWidgetTool               # created by TASK-4754
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/tests/querysource/conftest.py — fixtures `fake_rows` (line 16), `patched_qs` (line 71)
# packages/ai-parrot-tools/tests/querysource/test_build_linked_surface_tool.py:16-48 — `fake_core_qs(patched_qs, monkeypatch)`
#   monkeypatches "parrot.tools.dataset_manager.sources.query_slug._get_qs" / "_get_multiqs" with Fake(Multi)QS
#   returning a 12-row frame with columns day / visits / program; QuerysourceToolkit(dsn="postgres://fake");
#   the slug used there is "epson_field_activity", component {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]}.

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def __init__(self, logger=None, debug=False, include_search_tool=False, resolver=None, execution_policy=None)  # line 299
    def register_toolkit(self, toolkit, **kwargs) -> List[AbstractTool]     # line 1190 — registers qs_* tools
    def register_tool(self, tool=None, ...) -> None                         # line 853
    def get_tool(self, tool_name: str) -> Optional[Any]                     # line 1392

# packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py
class PublishSurfaceTool(AbstractTool):                                     # line 65
    def __init__(self, bot=None, surface_store=None, agent_id=None, user_id=None, session_id=None,
                 linked_service=None, guard=None, **kwargs)                 # line 86
    # standalone lane (bot=None): linked envelope -> linked_service.validate_for_persistence + ensure_snapshot,
    # then store.save(record) (lines 190-266). Fake service/store pattern: test_publish_surface_tool_linked.py:55-65.
```

### Does NOT Exist
- ~~a shared `fake_core_qs` fixture in `conftest.py`~~ — it is module-local in `test_build_linked_surface_tool.py`; copy it.
- ~~an in-memory `UISurfaceStore` class~~ — use the `MagicMock` store pattern (`store.save = AsyncMock(...)`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/tests/querysource/test_materialize_widget_roundtrip.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/ui_surfaces.py#PublishSurfaceTool",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_toolkit"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create the test file from the block below — *why*: it fixes the fixture wiring and the assertions the spec requires.
2. Complete the `FILL IN` markers — *why*: the exact turn fixture and the service double are the only open choices.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`.

### `packages/ai-parrot-tools/tests/querysource/test_materialize_widget_roundtrip.py` (CREATE)
```python
"""FEAT-757 integration: execute a slug, materialize the turn, pin it as a refreshable linked widget."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from parrot.memory import ConversationHistory, ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.outputs.a2ui.linked import has_data_sources
from parrot.tools.manager import ToolManager
from parrot_tools.materialize_widget import MaterializeWidgetTool
from parrot_tools.querysource.toolkit import QuerysourceToolkit
from parrot_tools.ui_surfaces import PublishSurfaceTool

SLUG = "epson_field_activity"


@pytest.fixture
def fake_core_qs(patched_qs, monkeypatch):
    """Patch the executor's QuerySource seam with deterministic frames (copied from test_build_linked_surface_tool)."""
    # FILL IN: copy test_build_linked_surface_tool.py:16-48 verbatim (FakeQS / FakeMultiQS + the two monkeypatches).
    raise NotImplementedError


class _Memory:
    """ConversationMemory double: one history for ("u1", "s1")."""

    def __init__(self, history: ConversationHistory) -> None:
        self._history = history

    async def get_history(self, user_id, session_id, chatbot_id=None):
        if (user_id, session_id) == (self._history.user_id, self._history.session_id):
            return self._history
        return None


async def test_materialize_then_refresh_roundtrip(fake_core_qs):
    """A slug-backed turn materializes through the REAL toolkit and pins as a refreshable linked widget."""
    store = MagicMock()
    store.save = AsyncMock(return_value="surface-1")
    # FILL IN: linked service double — MagicMock with validate_for_persistence=AsyncMock() and
    # ensure_snapshot=AsyncMock(side_effect=lambda env, **kw: env) (pattern: test_publish_surface_tool_linked.py:55).
    service = MagicMock()

    tm = ToolManager()
    tm.register_toolkit(QuerysourceToolkit(dsn="postgres://fake"))
    tm.register_tool(PublishSurfaceTool(surface_store=store, linked_service=service, user_id="u1", agent_id="agent"))
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u1",
        user_message="visits by day",
        assistant_response="…",
        tool_invocations=[ToolInvocation(tool_name="qs_execute_slug", input={"slug": SLUG, "limit": 100})],
    )
    history = ConversationHistory(session_id="s1", user_id="u1", turns=[turn])
    bot = SimpleNamespace(conversation_memory=_Memory(history), memory_key_id="agent", tool_manager=tm)
    tool = MaterializeWidgetTool(bot=bot, user_id="u1")
    tm.register_tool(tool)

    on_screen = {"surfaceId": "structured_chart-1", "components": [
        {"id": "root", "component": "Chart", "type": "bar", "x": "day", "y": ["visits"], "data": {"path": "/rows"}}
    ], "dataModel": {"rows": [{"day": "2026-01-01", "visits": 1}]}}
    result = await tool.execute(turn_id="t1", session_id="s1", envelope=on_screen, pin=True)
    payload = result.result

    assert payload["status"] == "materialized"
    assert payload["pinned"] is True and payload["surface_id"] == "surface-1"
    assert payload["refreshable"] is True
    assert has_data_sources(payload["a2ui_envelope"])
    # FILL IN: assert service.validate_for_persistence was awaited once and store.save received a record whose
    # envelope carries parrot_data_sources[SLUG] with target "/<key>/rows" — bounded by spec AC1/AC2.
```
**Why this shape**: the real toolkit plus a real `ToolManager` is the only way to check that the tool calls
`qs_build_linked_surface` with arguments the real signature accepts. The fakes stop at the QuerySource seam and the
persistence store, so nothing touches a database. Unused imports (`pd`) are allowed only if the copied
`fake_core_qs` uses them; otherwise remove them so ruff passes.

### FILL IN checklist
- [ ] `fake_core_qs` copied verbatim from `test_build_linked_surface_tool.py:16-48`
- [ ] linked-service double returning the envelope unchanged
- [ ] persistence assertions (validate awaited, saved envelope linked)

---

## Acceptance Criteria

- [ ] The round-trip test passes against the real `QuerysourceToolkit` and `PublishSurfaceTool` (spec AC1, AC2)
- [ ] `ruff check packages/ai-parrot-tools/tests/querysource/test_materialize_widget_roundtrip.py` is clean
- [ ] No source file and no `conftest.py` modified

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/querysource/test_materialize_widget_roundtrip.py -q`

---

## Test Specification

The single test in the blueprint is the specification. Add a negative variant if cheap:
`test_roundtrip_pandas_turn_is_snapshot_only` (a turn whose invocations include a non-neutral tool →
`snapshot_only`, `store.save` never called).

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug materialize-turn-linked-widget --feature-id FEAT-757`)
2. **Read the spec** for full context.
3. **Check dependencies**: TASK-4754 must be `done`.
4. **Verify the Codebase Contract** before writing code.
5. **Update status** → `"in-progress"`, commit only the index file.
6. **Implement** from the blueprint, completing every `# FILL IN:`.
7. **Verify** with the Validation Commands.
8. **Commit the code**, staging only the file listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4755 materialize-turn-linked-widget verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
