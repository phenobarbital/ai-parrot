# TASK-4601: Integration tests — double configure end to end, parallel agents

**Feature**: FEAT-721 — Double-`configure()` Is Not a Crash
**Spec**: `sdd/specs/double-configure-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4596, TASK-4597
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. The unit tests pin each layer; these two prove the goal
*"never raise, for ANY agent — including third-party subclasses nobody edits"*: an agent
whose `post_configure()` still builds and registers a fresh `WorkingMemoryToolkit` every
time (the OLD fireflies shape, deliberately left unfixed in the test) must survive
`configure()` → `reconfigure()`, and two agents configured concurrently must each keep
their own toolkits (keep-first is per `ToolManager`, not global).

---

## Scope

- Append `test_configure_twice_end_to_end` and `test_two_agents_parallel_configure` to
  `packages/ai-parrot/tests/bots/test_double_configure.py`, reusing its `_stub_bot()` and `_app()`.

**NOT in scope**: any production code; the M2 unit tests already in the file (TASK-4597).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/test_double_configure.py` | MODIFY | append two integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.manager import ToolManager                # verified: tools/manager.py:289
from parrot.tools.working_memory import WorkingMemoryToolkit # verified: tools/working_memory/__init__.py:3
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/bots/test_double_configure.py — created by TASK-4597
def _stub_bot() -> AbstractBot          # every configure() collaborator stubbed; tool_manager is a MagicMock — REPLACE it
def _app() -> SimpleNamespace           # truthy app wrapper, get_app() returns a fresh object()

# packages/ai-parrot/src/parrot/bots/abstract.py — created by TASK-4597
async def reconfigure(self, app=None) -> None
@property configure_count -> int

# packages/ai-parrot/src/parrot/tools/manager.py
ToolManager(include_search_tool=False)                                  # ctor arg verified: manager.py:303
def find_registered_toolkit(self, toolkit_cls, *, tool_prefix=None)     # created by TASK-4596
def list_tools(self) -> List[str]: ...                                  # line 1393
```

### Does NOT Exist
- ~~A shared/global ToolManager across bots~~ — each bot owns its own; the parallel test relies on that.
- ~~`_stub_bot()` with a real ToolManager~~ — it sets a MagicMock; the tests must assign a real one, AND set `bot.tool_manager._server_param_source` is not needed then (real attr exists).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/bots/test_double_configure.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/tool.py#WorkingMemoryToolkit"
  ]
}
```

---

## Implementation Notes

- The stub's `post_configure` must be a **real coroutine** bound to the bot that builds
  `WorkingMemoryToolkit(session_id=...)` and calls `self.tool_manager.register_toolkit(...)`
  unconditionally — that is the unfixed third-party shape under test. Do NOT adopt.
- A real `ToolManager` makes `configure()`'s `set_server_param_source` path real too; that is fine.

---

## Implementation Blueprint

### Steps (in order)
1. Append the two tests — *why*: they prove the cross-layer goal no unit test covers.
2. Run the file.

### `packages/ai-parrot/tests/bots/test_double_configure.py` (MODIFY — append at end of file)
```python
def _wm_registering_bot() -> AbstractBot:
    """A stub bot whose post_configure() re-registers a FRESH WorkingMemoryToolkit every call (unfixed shape)."""
    from parrot.tools.manager import ToolManager
    from parrot.tools.working_memory import WorkingMemoryToolkit

    bot = _stub_bot()
    bot.tool_manager = ToolManager(include_search_tool=False)

    async def post_configure() -> None:
        bot.tool_manager.register_toolkit(WorkingMemoryToolkit(session_id=f"{bot.name}-wm"))

    bot.post_configure = post_configure
    return bot


@pytest.mark.asyncio
async def test_configure_twice_end_to_end() -> None:
    bot, app = _wm_registering_bot(), _app()
    await bot.configure(app)
    await bot.configure(app)
    await bot.reconfigure()
    # FILL IN: no exception reached here; wm_* names appear exactly once in bot.tool_manager.list_tools();
    #          find_registered_toolkit(WorkingMemoryToolkit) is the FIRST instance (capture it after the first configure)


@pytest.mark.asyncio
async def test_two_agents_parallel_configure() -> None:
    import asyncio

    first, second = _wm_registering_bot(), _wm_registering_bot()
    second.name = "test-bot-2"
    await asyncio.gather(first.configure(_app()), second.configure(_app()))
    # FILL IN: each manager has its own WorkingMemoryToolkit; the two instances are distinct objects
```

### FILL IN checklist
- [ ] assertions in both tests

---

## Acceptance Criteria

- [ ] An agent with the unfixed register-every-time `post_configure()` survives `configure` → `configure` → `reconfigure` without raising.
- [ ] Two concurrently configured agents each keep their own working memory.
- [ ] `ruff check packages/ai-parrot/tests/bots/test_double_configure.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`

---

## Test Specification

Two appended tests (above).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug double-configure-agents --feature-id FEAT-721`).
2. **Read the spec** (§2, §4, §5).
3. **Check dependencies** — TASK-4596 and TASK-4597 must be `"done"` in `sdd/tasks/index/double-configure-agents.json`.
4. **Verify the Codebase Contract** — confirm the symbols the dependencies created exist before writing.
5. **Update status** → `"in-progress"`; commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. **Commit** — only the files this task lists.
9. **Close** with `scripts/sdd/close_task.sh TASK-4601 double-configure-agents verified`.
10. **Fill in the Completion Note**, commit the SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
