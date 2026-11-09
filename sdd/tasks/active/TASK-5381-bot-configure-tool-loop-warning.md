# TASK-5381: AbstractBot warns once at configure() when its client has no tool loop

**Feature**: FEAT-848 — Client tool-loop capability flag
**Spec**: `sdd/specs/client-tool-loop-capability.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G6, AC-8). A bot hands its tools to the client through `tool_manager` and
`use_tools=True`, never as inline `tools=`. `TransformersClient` only warns on inline `tools=`, so an hf
`Agent` drops its tools with no log at all; every `Agent` registers `ToJsonTool` by default, so this hits
every hf/jev `Agent`. This task adds a private helper `AbstractBot._warn_if_client_lacks_tool_loop()` and
calls it in `configure()` right after the default client is created and synced. It logs one warning and
never raises: refusing would break every existing hf/jev `Agent`.

The helper reads the flag with `getattr(..., True)`, so it does not need TASK-5379 to land first: its tests
use plain stub client classes that declare the flag themselves.

---

## Scope

- Add `_warn_if_client_lacks_tool_loop(self) -> None` to `AbstractBot`, before `is_agent_mode`.
- Call it in `configure()` after the `sync_tools` if-block (same indentation as that `if`).
- Create `packages/ai-parrot/tests/bots/test_tool_loop_warning.py` with five tests.

**NOT in scope**:
- Refusing a client, changing how the bot calls it, or any per-call warning.
- Checking per-call client overrides or the `ModelSwitchingMixin` secondary client (spec Non-Goals).
- Any change to `test_double_configure.py` or `test_configure_override_guards.py` — both must pass unchanged.
- Declaring the flag on clients (TASK-5379); documentation (TASK-5383).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | new helper before `is_agent_mode`; one call in `configure()` |
| `packages/ai-parrot/tests/bots/test_tool_loop_warning.py` | CREATE | helper and configure-level tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev @ d8832d3fc8` (2026-11-09).

### Verified Imports
```python
# test file only (abstract.py needs no new import):
from types import SimpleNamespace                     # verified: packages/ai-parrot/tests/bots/test_double_configure.py:3
from unittest.mock import AsyncMock, MagicMock        # verified: test_double_configure.py:4
import pytest                                         # verified: test_double_configure.py:6
from aiohttp import web                               # verified: test_double_configure.py:7
from parrot.bots.abstract import AbstractBot          # verified: test_double_configure.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # :216
    # __init__: self.name: str = name                                                       # :375
    # __init__: self.enable_tools: bool = kwargs.get("enable_tools", kwargs.get("use_tools", True))   # :416
    # __init__: self.operation_mode: str = kwargs.get("operation_mode", "adaptive")         # :568
    async def configure(self, app=None) -> None:                                            # :1604
        # self._configured = False on every non-no-op run                                   # :1649
        # if not self._configured:   (LLM block)                                            # :1678
        #     try:
        #         self._llm = self._create_llm_client(config)                               # :1692
        #         if self.tool_manager and hasattr(self._llm, "tool_manager"):              # :1693  (20 spaces)
        #             self.sync_tools(self._llm)                                            # :1694  (24 spaces, 1 occurrence)
        #     except Exception as e:                                                        # :1695
        #         self.logger.error(f"Error configuring LLM: {e}"); raise
    def is_agent_mode(self) -> bool:                                                        # :3704 (4 spaces, 1 occurrence)
        # return self.enable_tools and self.has_tools() and self.operation_mode in ["agentic", "adaptive"]
    def get_tools_count(self) -> int:                                                       # :4746 — return self.tool_manager.tool_count()
    def has_tools(self) -> bool:                                                            # :4751 — self.get_tools_count() > 0

# packages/ai-parrot/src/parrot/interfaces/tools.py
class ToolInterface:                                                                        # :24
    def sync_tools(self, llm: AbstractClient = None) -> None:                               # :387 — llm.tool_manager = self.tool_manager; llm.enable_tools = True

# packages/ai-parrot/src/parrot/bots/agent.py
    def _get_default_tools(self, tools, *, use_tools: bool = True) -> List[AbstractTool]:   # :451 — appends ToJsonTool() :466 (why every Agent has tools)

# packages/ai-parrot/tests/bots/test_double_configure.py (192 lines)
class _ConfigureTestBot(AbstractBot)                                                       # :12-29
def _stub_bot() -> AbstractBot                                                             # :32-72 — object.__new__ bot; logger MagicMock; tool_manager MagicMock(_server_param_source=None);
                                                                                           #   _create_llm_client -> MagicMock() (:46); sync_tools MagicMock; name "test-bot" (:71); NO enable_tools / operation_mode
def _app() -> SimpleNamespace                                                              # :75-79
async def test_second_configure_is_noop()                                                  # :82 — same app twice: second call is a no-op
# packages/ai-parrot/tests/bots/test_configure_override_guards.py:70 — _create_llm_client -> MagicMock() as well
```

### Does NOT Exist
- ~~`AbstractBot.supports_tool_loop`~~ — the bot has no flag; it reads `self._llm.supports_tool_loop`.
- ~~`AbstractBot._warn_if_client_lacks_tool_loop`~~ before this task — you create it.
- ~~an importable `_stub_bot` fixture~~ — it is a private helper of `test_double_configure.py`; copy it, do not import across test modules.
- ~~`self.client`~~ / ~~`self.llm`~~ as the configured client inside `configure()` — the attribute is `self._llm`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/test_tool_loop_warning.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.is_agent_mode",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_tools_count",
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface.sync_tools",
    "sym:packages/ai-parrot/tests/bots/test_double_configure.py#_stub_bot"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Order is part of the contract**: check `getattr(self._llm, "supports_tool_loop", True) is False` first. The stubs in `test_double_configure.py` and `test_configure_override_guards.py` use a `MagicMock` client on an `object.__new__` bot with no `enable_tools`; a `MagicMock` attribute is never `False`, so the helper returns before touching bot state. Calling `is_agent_mode()` first would raise `AttributeError` in those tests.
- `self.logger.warning` with `%`-style arguments (no f-string); never raise.
- The call sits inside the LLM `try:` block, so an exception would be re-raised as "Error configuring LLM" — the helper must not raise.
- One warning per real `configure()` run: a no-op second call (same app) adds none; `reconfigure()` / a new app reruns it, which is intended.
- In a worktree, run tests with `PYTHONPATH=packages/ai-parrot/src`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper before `is_agent_mode` — *why*: it reuses `is_agent_mode()`; keeping them adjacent documents the condition.
2. Add the call after the `sync_tools` if-block in `configure()` — *why*: the client exists and holds the bot's tool manager at that point (spec §2).
3. Create the test file, copying the stub helpers from `test_double_configure.py` — *why*: AC-8 needs helper-level and configure-level coverage without importing private helpers across test modules.
4. Run all three Validation Commands — *why*: AC-8 requires the two existing configure test files to pass unchanged.

### `packages/ai-parrot/src/parrot/bots/abstract.py` (MODIFY — 2 edits)
```python
# Edit 1 — occurrences: 1 (verified: grep -cF 'def is_agent_mode(self) -> bool:' packages/ai-parrot/src/parrot/bots/abstract.py)
# BEFORE — insert above `    def is_agent_mode(self) -> bool:` (verified: abstract.py:3704), followed by one blank line
    def _warn_if_client_lacks_tool_loop(self) -> None:
        """Log one warning when an agent-mode bot's client declares ``supports_tool_loop = False``.

        FEAT-848: such a client ignores the bot's tools (``TransformersClient`` does so without a log of
        its own), so the operator gets one signal per real ``configure()`` run. Never raises and never
        changes behaviour. The flag is checked first, by identity: ``configure()`` test stubs use a
        ``MagicMock`` client on a bot that has no ``enable_tools``.
        """
        if getattr(self._llm, "supports_tool_loop", True) is not False:
            return
        if not self.is_agent_mode():
            return
        self.logger.warning(
            "%s: LLM client %s (%s) declares supports_tool_loop=False; "
            "its %d registered tools will not be executed",
            self.name,
            type(self._llm).__name__,
            getattr(self._llm, "client_type", "?"),
            self.tool_manager.tool_count(),
        )

# Edit 2 — occurrences: 1 (verified: grep -cF 'self.sync_tools(self._llm)' packages/ai-parrot/src/parrot/bots/abstract.py)
# AFTER — insert below the if-block (verified: abstract.py:1693-1694), at the indentation of the `if` (20 spaces):
#                     if self.tool_manager and hasattr(self._llm, "tool_manager"):
#                         self.sync_tools(self._llm)
                    # FEAT-848: one warning when an agent-mode bot's client runs no tool loop.
                    self._warn_if_client_lacks_tool_loop()
```
**Why this shape**: the message format and the check order are fixed by spec §3 M5 — copy both verbatim. The call
goes after the if-block, not inside it, so a client without a `tool_manager` attribute is still checked.

### `packages/ai-parrot/tests/bots/test_tool_loop_warning.py` (CREATE)
```python
"""FEAT-848 — AbstractBot warns once at configure() when its client declares no tool loop."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.bots.abstract import AbstractBot

# FILL IN: copy `_ConfigureTestBot`, `_stub_bot` and `_app` VERBATIM from
#   packages/ai-parrot/tests/bots/test_double_configure.py:12-79 — do not import them (private test helpers).


class _NoLoopClient:
    """Client double declaring no text ask() tool loop."""

    supports_tool_loop = False
    client_type = "noloop"


class _LoopClient:
    """Client double declaring a tool loop."""

    supports_tool_loop = True
    client_type = "loop"


def _agent_bot(client: object, *, enable_tools: bool = True, tools: int = 1, mode: str = "adaptive") -> AbstractBot:
    """A bare bot with just the state the helper reads."""
    bot = object.__new__(_ConfigureTestBot)
    bot.logger = MagicMock()
    bot.name = "test-bot"
    bot._llm = client
    bot.enable_tools = enable_tools
    bot.operation_mode = mode
    bot.tool_manager = MagicMock()
    bot.tool_manager.tool_count.return_value = tools
    return bot


def _tool_loop_warnings(bot: AbstractBot) -> list:
    """The warning calls this feature emits (other code may warn too)."""
    return [c for c in bot.logger.warning.call_args_list if "supports_tool_loop=False" in str(c.args[0])]


def test_warns_once_for_agent_mode_no_loop_client() -> None:
    """One warning naming bot, client class, client_type and tool count."""
    # FILL IN: bot = _agent_bot(_NoLoopClient()); bot._warn_if_client_lacks_tool_loop();
    #   assert len(_tool_loop_warnings(bot)) == 1 and its args[1:] == ("test-bot", "_NoLoopClient", "noloop", 1) — bounded by AC-8


def test_silent_for_loop_client() -> None:
    """A True client logs nothing."""
    # FILL IN: _agent_bot(_LoopClient()) -> helper -> _tool_loop_warnings(bot) == [] — bounded by AC-8


@pytest.mark.parametrize("kwargs", [{"enable_tools": False}, {"tools": 0}, {"mode": "conversational"}])
def test_silent_when_not_agent_mode(kwargs: dict) -> None:
    """Tools disabled, no tools, or conversational mode log nothing."""
    # FILL IN: _agent_bot(_NoLoopClient(), **kwargs) -> helper -> _tool_loop_warnings(bot) == [] — bounded by AC-8


def test_silent_for_mock_client_without_bot_state() -> None:
    """A MagicMock client on a bot with no enable_tools: no warning, no AttributeError."""
    # FILL IN: bot = object.__new__(_ConfigureTestBot); bot.logger = MagicMock(); bot._llm = MagicMock();
    #   helper must return; assert bot.logger.warning.call_count == 0 — bounded by AC-8 (identity check first)


@pytest.mark.asyncio
async def test_configure_calls_warning_after_client_creation() -> None:
    """configure() warns once; a no-op second configure() with the same app adds none."""
    bot, app = _stub_bot(), _app()
    bot._create_llm_client = MagicMock(return_value=_NoLoopClient())
    bot.enable_tools = True
    bot.operation_mode = "adaptive"
    bot.tool_manager.tool_count.return_value = 1
    # FILL IN: await bot.configure(app) twice; assert len(_tool_loop_warnings(bot)) == 1 — bounded by AC-8
```
**Why**: `_agent_bot` sets only what `is_agent_mode()` → `has_tools()` → `get_tools_count()` → `tool_manager.tool_count()`
read. `_tool_loop_warnings` filters by message so unrelated warnings in `configure()` cannot break the count.

### FILL IN checklist
- [ ] copy `_ConfigureTestBot`, `_stub_bot`, `_app` verbatim — bounded by test_double_configure.py:12-79
- [ ] `test_warns_once_for_agent_mode_no_loop_client` — count + args; bounded by AC-8
- [ ] `test_silent_for_loop_client` / `test_silent_when_not_agent_mode` / `test_silent_for_mock_client_without_bot_state` — bounded by AC-8
- [ ] `test_configure_calls_warning_after_client_creation` — two configure calls, one warning; bounded by AC-8

---

## Acceptance Criteria

- [ ] `AbstractBot.configure()` logs exactly one warning, and never raises, when the bot is in agent mode and its client declares `supports_tool_loop = False` (spec AC-8).
- [ ] A `True` client, a non-agent-mode bot and a `MagicMock` client log nothing (spec AC-8).
- [ ] `test_double_configure.py` and `test_configure_override_guards.py` pass unchanged (spec AC-8).
- [ ] `ruff check` passes on every file this task touches.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/bots/test_tool_loop_warning.py -q`
- `pytest packages/ai-parrot/tests/bots/test_double_configure.py -q`
- `pytest packages/ai-parrot/tests/bots/test_configure_override_guards.py -q`

---

## Test Specification

See the CREATE block above: four helper-level tests on a bare bot (`_agent_bot`) and one configure-level test on
the copied `_stub_bot`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug client-tool-loop-capability --feature-id FEAT-848`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/client-tool-loop-capability.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/client-tool-loop-capability.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5381 client-tool-loop-capability verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
