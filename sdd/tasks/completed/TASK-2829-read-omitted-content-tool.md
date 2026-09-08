# TASK-2829: `read_omitted_content` recovery tool + `search_tools` exclusion

**Feature**: FEAT-525 — Per-Turn Conversation Compaction
**Spec**: `sdd/specs/per-turn-conversation-compaction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2822, TASK-2825, TASK-2826
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11, goals G6/G12 and the resolved decision "Does
`read_omitted_content` need an `AbstractToolkit`? — No." The LLM recovers
omitted bytes through one plain async function bound to a
`ConversationMemory`, registered on the bot's `ToolManager` exactly like the
`search_tools` meta-tool (TASK-2830 does the bot-side registration). The
function resolves its session key from three ContextVars and **fails closed**
on any `None`. This task also hides the tool from `search_tools` results.

---

## Scope

- Create `parrot/memory/compaction/recover.py` with:
  - `READ_OMITTED_CONTENT_NAME = "read_omitted_content"`.
  - `READ_OMITTED_CONTENT_DESCRIPTION: str` — tells the model when to call it (a `<tool-output-omitted …/>`
    notice in history) and that it takes a `content_id` (`om_…`) **or** a `turn_id`.
  - `READ_OMITTED_CONTENT_SCHEMA = {"type": "object", "properties": {"content_id": {"type": "string", "description": …},
    "turn_id": {"type": "string", "description": …}}, "required": []}`.
  - `UNAVAILABLE_MESSAGE = "read_omitted_content is unavailable in this context (no active conversation scope)."`
  - `NO_ARGS_MESSAGE = "Provide content_id (om_…) or turn_id."`
  - `bind_read_omitted_content(memory: ConversationMemory) -> Callable[..., Awaitable[str]]` returning
    `async def read_omitted_content(content_id: Optional[str] = None, turn_id: Optional[str] = None) -> str`:
    1. `key_id, user_id, session_id = current_memory_key_id.get(), current_user_id.get(), current_session_id.get()`;
       any `None` ⇒ return `UNAVAILABLE_MESSAGE` **without** touching the store.
    2. `session_key = memory.omission_key(user_id, session_id, key_id)`.
    3. `content_id` given ⇒ `await memory.omission_store.get(session_key, content_id)`; `None` ⇒
       `EXPIRED_MESSAGE.format(content_id=content_id)`; else the exact bytes.
    4. else `turn_id` given ⇒ `ids = await memory.omission_store.list_by_turn(session_key, turn_id)`; for each id
       `get` → `f'<omitted id="{cid}">\n{content}\n</omitted>'` (skip ids that expired), joined by `"\n"`;
       nothing found ⇒ `f"No omitted content is known for turn {turn_id} — it may have expired; re-run the tool."`.
    5. neither ⇒ `NO_ARGS_MESSAGE`. Never raise to the caller; log at debug.
    The returned function has `__name__ == "read_omitted_content"` and a docstring (ToolManager may read it).
- `tools/manager.py`: add module-level `_INTERNAL_TOOL_NAMES: frozenset[str] = frozenset({"search_tools", "read_omitted_content"})`
  and change `rank_tools`' loop guard (`if name == "search_tools": continue`, dev `:608`) to
  `if name in _INTERNAL_TOOL_NAMES: continue`; update the docstring sentence at `:602`. **Do not** touch `clone()` (`:2109`).
- Tests: `tests/unit/memory/compaction/test_recover.py` (fail-closed, by id, by turn, expired) and
  `tests/unit/tools/test_internal_tool_exclusion.py` (registered via `register_tool(function=…)` ⇒ present in
  `get_tool_schemas()` and `list_tools()`, absent from `rank_tools()`/`search_tools()`, present after `clone()`).

**NOT in scope**: calling `_register_recovery_tool()` from the bot (TASK-2830); any `AbstractTool`/`AbstractToolkit` subclass (rejected); any client change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/compaction/recover.py` | CREATE | schema, messages, `bind_read_omitted_content` |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | `_INTERNAL_TOOL_NAMES` frozenset; one-line guard change in `rank_tools` |
| `packages/ai-parrot/tests/unit/memory/compaction/test_recover.py` | CREATE | fail-closed / by id / by turn / expired |
| `packages/ai-parrot/tests/unit/tools/test_internal_tool_exclusion.py` | CREATE | ToolManager registration, hidden from search, survives clone |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use only what is listed here. Verify anything else before using it.

### Verified Imports
```python
from parrot.observability.context import current_user_id, current_session_id                 # dev: context.py:58, :60
from parrot.observability.context import current_memory_key_id                              # TASK-2825
from parrot.memory.abstract import ConversationMemory                                       # dev: memory/abstract.py:135
from parrot.memory.compaction.omission import EXPIRED_MESSAGE, InMemoryOmissionStore        # TASK-2822 (EXPIRED_MESSAGE has a {content_id} placeholder)
from parrot.memory import InMemoryConversation                                              # dev: memory/__init__.py:11 (tests; gains omission_store/omission_key in TASK-2826)
from parrot.tools.manager import ToolManager                                                # dev: tools/manager.py
import logging
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/manager.py  (dev @ f3a5fe7ea, verified 2026-09-04)
def __init__(..., include_search_tool: bool = False, ...)                     # :254 ; self._tools: Dict[str, Union[ToolDefinition, AbstractTool]] = {}  :280
        if include_search_tool:
            self.register_tool(name="search_tools", description="Search for available tools ...",
                               input_schema={"type": "object", "properties": {...}, "required": ["query"]},
                               function=self.search_tools)                    # :351-370  ← registration shape to copy
def rank_tools(self, query: str, limit: int = 15) -> list[tuple[float, Any]]  # ~:590 ; docstring "...named `search_tools` is always excluded." :602
        for name, tool in self._tools.items():
            if name == "search_tools":                                       # :608  ← change to `in _INTERNAL_TOOL_NAMES`
                continue
def search_tools(self, query: str, limit: int = 15) -> str                    # :620  JSON wrapper over rank_tools
def register_tool(self, tool=None, name: str = None, description: str = None,
                  input_schema: Dict[str, Any] = None, function: Callable = None) -> None   # :714-720
def get_tool_schemas(self, provider_format: ToolFormat = ToolFormat.GENERIC) -> List[Dict[str, Any]]   # :1152
def get_tool(self, tool_name) :1231 ; def list_tools(self) -> List[str] :1251 ; def remove_tool(self, tool_name) :1286
def clone(self, *, include_search_tool: bool = False) -> "ToolManager"       # :2057 ; loop :2108-2111 skips ONLY "search_tools" — leave as is

# TASK-2826: ConversationMemory.omission_store -> OmissionStore ; omission_key(user_id, session_id, chatbot_id) -> "{chatbot_id or '_default'}:{user}:{session}"
# TASK-2822: OmissionStore.get(session_key, content_id) -> Optional[str] ; list_by_turn(session_key, turn_id) -> List[str]
# TASK-2825: current_memory_key_id: ContextVar[Optional[str]] (default None); tests bind via invocation_context(..., memory_key_id=)
```

### Does NOT Exist
- ~~`parrot.memory.compaction.recover`~~ — this task creates it.
- ~~`ReadOmittedContentToolkit` / any `AbstractTool` subclass for recovery~~ — never; plain function + `register_tool(function=…)`.
- ~~`ToolManager._INTERNAL_TOOL_NAMES`~~ — does not exist; add it as a **module-level** frozenset in `tools/manager.py`.
- ~~A `turn_id` concept inside `ToolManager`~~ — absent (`tools/compression/tee.py:29-37`); the turn scope comes from ContextVars only.
- ~~`wm_get_result` as the recovery path~~ — that is FEAT-380's process-local working memory (`tools/working_memory/tool.py:259`); different tool, do not import.
- ~~Raising exceptions from the tool~~ — the function always returns a string (the LLM reads it).
- ~~Reading `current_agent_name` to build the key~~ — the key uses `current_memory_key_id` (explicit chatbot_id or bot name, set by the bot), never the agent-name ContextVar directly.

---

## Implementation Notes

### Pattern to Follow
```python
def bind_read_omitted_content(memory: "ConversationMemory") -> Callable[..., Awaitable[str]]:
    async def read_omitted_content(content_id: Optional[str] = None, turn_id: Optional[str] = None) -> str:
        """Return the exact bytes of an omitted tool output (by content_id) or every omitted block of a turn."""
        key_id, user_id, session_id = current_memory_key_id.get(), current_user_id.get(), current_session_id.get()
        if key_id is None or user_id is None or session_id is None:
            return UNAVAILABLE_MESSAGE
        session_key = memory.omission_key(user_id, session_id, key_id)
        store = memory.omission_store
        if content_id:
            found = await store.get(session_key, content_id)
            return found if found is not None else EXPIRED_MESSAGE.format(content_id=content_id)
        if turn_id:
            ...
        return NO_ARGS_MESSAGE
    return read_omitted_content
```

### Key Constraints
- Fail closed **before** any store access (assert with a store spy that `get`/`list_by_turn` were not called).
- Cross-session isolation comes from the key: a foreign `content_id` simply yields `EXPIRED_MESSAGE`.
- Leaf-module rule: `recover.py` imports `parrot.observability.context` and `parrot.memory.*` only — never `parrot.tools` (the registration happens in the bot, TASK-2830).
- Keep the `manager.py` change to the frozenset + one guard + one docstring line; nothing else in that 2 000-line file.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/manager.py:351-370` — meta-tool registration shape.
- `packages/ai-parrot/tests/test_dynamic_tool_search.py`, `tests/test_toolmanager_ranker.py` — existing `search_tools`/`rank_tools` tests (keep them green).

---

## Acceptance Criteria

- [ ] With any of the three ContextVars unset, the tool returns `UNAVAILABLE_MESSAGE` and the store spy records no call.
- [ ] Inside `invocation_context("bot", user_id="u", session_id="s", memory_key_id="bot")`: a known id returns the exact bytes; an unknown id returns `EXPIRED_MESSAGE.format(content_id=…)`; a `turn_id` with two omissions returns two `<omitted id="…">` blocks in insertion order; a `turn_id` with none returns the fixed "may have expired" message; no args returns `NO_ARGS_MESSAGE`.
- [ ] A second session (`session_id="other"`) cannot read the first session's id (gets `EXPIRED_MESSAGE`).
- [ ] `ToolManager()` + `register_tool(name="read_omitted_content", description=…, input_schema=READ_OMITTED_CONTENT_SCHEMA, function=fn)`: name in `list_tools()` and in `get_tool_schemas()`; absent from `rank_tools("omitted content")` and from `search_tools("omitted")` JSON; present in `clone().list_tools()`.
- [ ] `tests/test_dynamic_tool_search.py` and `tests/test_toolmanager_ranker.py` still pass.
- [ ] All tests pass: `timeout -s KILL 300 pytest packages/ai-parrot/tests/unit/memory/compaction/test_recover.py packages/ai-parrot/tests/unit/tools/test_internal_tool_exclusion.py packages/ai-parrot/tests/test_dynamic_tool_search.py packages/ai-parrot/tests/test_toolmanager_ranker.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/memory/compaction/recover.py packages/ai-parrot/src/parrot/tools/manager.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/memory/compaction/test_recover.py
import pytest
from parrot.memory import InMemoryConversation
from parrot.memory.compaction.omission import EXPIRED_MESSAGE, content_id
from parrot.memory.compaction.recover import (NO_ARGS_MESSAGE, UNAVAILABLE_MESSAGE, bind_read_omitted_content)
from parrot.observability.context import invocation_context


@pytest.fixture
def memory():
    return InMemoryConversation()


async def test_read_omitted_content_fail_closed(memory, monkeypatch):
    calls = []
    monkeypatch.setattr(memory.omission_store, "get", lambda *a, **k: calls.append(a))
    fn = bind_read_omitted_content(memory)
    assert await fn(content_id="om_x") == UNAVAILABLE_MESSAGE and calls == []
    with invocation_context("bot", user_id="u", session_id=None, memory_key_id="bot"):
        assert await fn(content_id="om_x") == UNAVAILABLE_MESSAGE and calls == []


async def test_read_omitted_content_by_id_and_turn(memory):
    key = memory.omission_key("u", "s", "bot")
    a = await memory.omission_store.put(key, "AAA", turn_id="t1"); b = await memory.omission_store.put(key, "BBB", turn_id="t1")
    fn = bind_read_omitted_content(memory)
    with invocation_context("bot", user_id="u", session_id="s", memory_key_id="bot"):
        assert await fn(content_id=a) == "AAA"
        assert await fn(content_id="om_ffffffffffffffff") == EXPIRED_MESSAGE.format(content_id="om_ffffffffffffffff")
        assert await fn(turn_id="t1") == f'<omitted id="{a}">\nAAA\n</omitted>\n<omitted id="{b}">\nBBB\n</omitted>'
        assert "may have expired" in await fn(turn_id="nope") and await fn() == NO_ARGS_MESSAGE
    with invocation_context("bot", user_id="u", session_id="other", memory_key_id="bot"):
        assert await fn(content_id=a) == EXPIRED_MESSAGE.format(content_id=a)


# packages/ai-parrot/tests/unit/tools/test_internal_tool_exclusion.py
import json
from parrot.tools.manager import ToolManager
from parrot.memory import InMemoryConversation
from parrot.memory.compaction.recover import READ_OMITTED_CONTENT_SCHEMA, bind_read_omitted_content


def test_recovery_tool_registered_and_hidden():
    tm = ToolManager(include_search_tool=True)
    tm.register_tool(name="read_omitted_content", description="recover omitted tool output",
                     input_schema=READ_OMITTED_CONTENT_SCHEMA, function=bind_read_omitted_content(InMemoryConversation()))
    assert "read_omitted_content" in tm.list_tools()
    assert any(s.get("name") == "read_omitted_content" for s in tm.get_tool_schemas())
    assert all(getattr(t, "name", None) != "read_omitted_content" for _, t in tm.rank_tools("recover omitted content"))
    assert "read_omitted_content" not in json.dumps(json.loads(tm.search_tools("omitted")))
    assert "read_omitted_content" in tm.clone().list_tools()
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2822, 2825, 2826 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code; update it first if anything changed
4. **Update status** in `sdd/tasks/index/per-turn-conversation-compaction.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2829-read-omitted-content-tool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-04
**Notes**: Implemented `parrot/memory/compaction/recover.py`:
schema/messages constants, `bind_read_omitted_content` (fail-closed
before any store access, `by content_id` / `by turn_id` / no-args
paths, never raises). `tools/manager.py`: added module-level
`_INTERNAL_TOOL_NAMES` frozenset and changed `rank_tools`'s guard to
`if name in _INTERNAL_TOOL_NAMES`; `clone()` untouched (still gates
only `"search_tools"`, per spec). All 3 task-specified tests pass;
`tests/test_toolmanager_ranker.py` (15 tests) still green; `ruff check`
clean on both new/modified files.

**Deviations from spec**: (1) `test_internal_tool_exclusion.py`'s given
assertion `json.loads(tm.search_tools("omitted"))` fails on the
no-match branch — `search_tools()` returns a plain "No tools found
matching '...'" string, not JSON, when nothing matches
(`tools/manager.py:659`), which is exactly what correct exclusion
produces here. Replaced with a substring check (`"read_omitted_content"
not in tm.search_tools("omitted")`) that covers both the JSON and
plain-text return shapes. (2) `tests/test_dynamic_tool_search.py`
(`test_ask_lazy_flow`, `test_prepare_lazy_tools`) were in this task's
own acceptance-criteria test list but fail identically with and without
this task's `manager.py` change (confirmed via `git stash` bisection) —
pre-existing, unrelated (an `AbstractClient.client` deprecated-setter
issue and a `_prepare_lazy_tools` lookup issue in `clients/base.py`,
neither touched here); not fixed, out of scope. (3) A set of 7 failures
in `tests/unit/infographic_*`/`test_adhoc_dataset_adapter.py` appear
only when the full `tests/unit/tools/` directory runs together —
confirmed via bisection (stashing this task's `manager.py` change
reproduces the identical 7 failures), so this is pre-existing
test-order-dependent flakiness, not caused by this task.
