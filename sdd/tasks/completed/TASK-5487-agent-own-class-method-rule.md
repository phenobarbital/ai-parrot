# TASK-5487: Own-class method rule (agent_toolkit, part 1)

**Feature**: FEAT-877 — Agent as a local stdio MCP server
**Spec**: `sdd/specs/agent-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5485
**Assigned-to**: unassigned

---

## Context

Every agent inherits ~55 public coroutine methods from the framework (`shutdown`,
`reconfigure`, `delete_conversation_history`, `ask`, …). FEAT-877 exposes ONLY the
methods the author wrote on the agent's own class (spec G1, G2, decision
`own-class-methods-only`). This task creates `parrot/mcp/agent_toolkit.py` with the pure,
class-level part of spec §3 **Module 3**: the own-class rule (§2 Overview steps 1-5) and
the `allow` narrowing. No registry lookup, no toolkit — those are TASK-5488 and
TASK-5489, which append to this same file.

---

## Scope

- Create `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` with: `NEVER_EXPOSED`,
  `AgentExposureError`, `framework_agent_bases()`, `own_coroutine_methods()`,
  `exposed_methods()`.
- Create `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` with the rule tests.

**NOT in scope**: `ResolvedAgent`, `ExposableAgent`, `discover_agents`,
`resolve_exposable_agent`, `list_exposable_agents` (TASK-5488); `AgentToolkit` (TASK-5489);
`@mcp_tool` tool naming (TASK-5488).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` | CREATE | Own-class rule + allow narrowing |
| `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` | CREATE | Rule unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `origin/dev` at `41df674d50` (2026-11-11).

### Verified Imports
```python
from parrot.registry.registry import MCPLocalExposure   # created by TASK-5485 (registry.py, above BotConfig)
from parrot.bots.abstract import AbstractBot             # verified: bots/abstract.py:216
from parrot.bots.base import BaseBot                     # verified: bots/base.py:94
from parrot.bots.basic import BasicBot                   # verified: bots/basic.py:3
from parrot.bots.chatbot import Chatbot                  # verified: bots/chatbot.py:33
from parrot.bots.agent import BasicAgent, Agent          # verified: bots/agent.py:40,1576
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(MCPEnabledMixin, DBInterface, LocalKBMixin, EventEmitterMixin, ToolInterface, VectorInterface, ABC):  # line 216
    async def configure(self, app=None) -> None      # line 1604
    async def shutdown(self, **kwargs) -> None       # line 4691
    async def cleanup(self) -> None                  # line 5450
# bots/base.py:94      class BaseBot(AbstractBot)
# bots/basic.py:3      class BasicBot(BaseBot)
# bots/chatbot.py:33   class Chatbot(BaseBot)
# bots/agent.py:40     class BasicAgent(Chatbot, NotificationMixin)
# bots/agent.py:1576   class Agent(BasicAgent)

# MCPLocalExposure (TASK-5485): enabled: bool = True; allow: Optional[List[str]] = None; extra="forbid"
```

### Does NOT Exist
- ~~`AbstractBot.exposed_methods`~~ / ~~`BotConfig.exposed_methods`~~ — `exposed_methods` exists only in agentd's daemon YAML (unrelated).
- ~~`AbstractToolkit.exclude_tools` as the mechanism here~~ — the rule is computed from the MRO, never a hand-kept exclude list (decision rejected alternative).
- ~~`parrot.mcp.agent_toolkit`~~ — created by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/agent_toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/mcp/test_agent_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot",
    "sym:packages/ai-parrot/src/parrot/bots/base.py#BaseBot",
    "sym:packages/ai-parrot/src/parrot/bots/basic.py#BasicBot",
    "sym:packages/ai-parrot/src/parrot/bots/chatbot.py#Chatbot",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent"
  ]
}
```

---

## Implementation Notes

### The rule (spec §2 Overview — do not reinterpret)
1. *Framework classes* = every class in the MRO of the six generic bases, plus every class
   in `agent_cls.__mro__` that is NOT an `AbstractBot` subclass (all mixins and `object`).
2. *Own classes* = the remaining classes of `agent_cls.__mro__`.
3. *Reserved names* = every public name in any framework class's `__dict__`, plus
   `ask`/`ask_stream` always.
4. *Candidates* = walking own classes most-derived first, the first definition of a public
   name decides: it is a candidate only if it is a plain `async def` function
   (`isinstance(v, types.FunctionType) and inspect.iscoroutinefunction(v)`) and the name
   is not reserved. A more-derived sync redefinition hides an inherited async one.
5. `allow`: exactly its entries (allow order, duplicates dropped); any entry that is not a
   candidate fails; an empty result fails.

### Key Constraints
- Import the six bases lazily inside `framework_agent_bases()` — `parrot.bots` is heavy and
  the module is imported by `toolkit_server` only for agent sections.
- The error message format is part of the contract (spec §3 M3); tests assert the phrases.
- `exposed_methods` keeps the spec's positional signature and adds the keyword-only
  `agent_name: str | None = None` so its messages can say `Agent '<name>'` (the spec's
  messages need the registry name, which the class does not carry). TASK-5488 passes it.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with the block below — *why*: TASK-5488/5489 append to it.
2. Fill the candidate loop and the allow narrowing — *why*: AC-1, AC-2, AC-4.
3. Write the tests, run the Validation Commands.

### `packages/ai-parrot/src/parrot/mcp/agent_toolkit.py` (CREATE)
```python
"""Serve a registered agent's own async methods as a local stdio MCP toolkit (FEAT-877).

Only the methods the author wrote on the agent's own class are exposed; every name a
framework class or mixin defines — and ``ask``/``ask_stream`` always — is reserved.
"""
from __future__ import annotations

import inspect
import logging
import types
from collections.abc import Awaitable, Callable
from typing import Any

from parrot.registry.registry import MCPLocalExposure

logger = logging.getLogger(__name__)

NEVER_EXPOSED: frozenset[str] = frozenset({"ask", "ask_stream"})


class AgentExposureError(ValueError):
    """An agent cannot be exposed as a local MCP toolkit; the message names the fix."""


def framework_agent_bases() -> tuple[type, ...]:
    """Return the generic agent bases, imported lazily.

    Returns:
        ``(AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent)``.
    """
    from parrot.bots.abstract import AbstractBot  # noqa: PLC0415
    from parrot.bots.agent import Agent, BasicAgent  # noqa: PLC0415
    from parrot.bots.base import BaseBot  # noqa: PLC0415
    from parrot.bots.basic import BasicBot  # noqa: PLC0415
    from parrot.bots.chatbot import Chatbot  # noqa: PLC0415

    return (AbstractBot, BaseBot, BasicBot, Chatbot, BasicAgent, Agent)


def _framework_classes(agent_cls: type) -> set[type]:
    """Classes whose public names are reserved for ``agent_cls`` (spec §2 step 1)."""
    bases = framework_agent_bases()
    abstract_bot = bases[0]
    framework: set[type] = set()
    for base in bases:
        framework.update(base.__mro__)
    framework.update(klass for klass in agent_cls.__mro__ if not issubclass(klass, abstract_bot))
    return framework


def own_coroutine_methods(agent_cls: type) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Return the exposable candidates of ``agent_cls`` (spec §2 steps 1-4), ordered by name.

    Args:
        agent_cls: An ``AbstractBot`` subclass (never instantiated).

    Returns:
        Method name → the class function (unbound).
    """
    framework = _framework_classes(agent_cls)
    reserved: set[str] = set(NEVER_EXPOSED)
    for klass in framework:
        reserved.update(name for name in vars(klass) if not name.startswith("_"))
    candidates: dict[str, Callable[..., Awaitable[Any]]] = {}
    seen: set[str] = set()
    for klass in agent_cls.__mro__:
        if klass in framework:
            continue
        for name, value in vars(klass).items():
            # FILL IN: skip names already in `seen` (a more-derived own class decided them),
            #   then add `name` to `seen`; keep it only when public, not in `reserved`, and
            #   `isinstance(value, types.FunctionType) and inspect.iscoroutinefunction(value)`
            #   — bounded by spec §2 step 4 and AC-1
            ...
    return dict(sorted(candidates.items()))


def exposed_methods(
    agent_cls: type, exposure: MCPLocalExposure, *, agent_name: str | None = None
) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Apply ``exposure.allow`` to the candidates (spec §2 step 5).

    Args:
        agent_cls: The agent class.
        exposure: The agent's ``mcp_local`` declaration.
        agent_name: Registry name used in error messages (defaults to the class name).

    Returns:
        Exposed method name → class function; allow order when ``allow`` is set, else by name.

    Raises:
        AgentExposureError: an allow entry is not a candidate, or the result is empty.
    """
    label = agent_name or agent_cls.__name__
    candidates = own_coroutine_methods(agent_cls)
    # FILL IN: allow is None → every candidate; else collect `bad` entries (not candidates) and raise
    #   AgentExposureError(f"Agent '{label}': allow entries are not own-class public async methods: {', '.join(bad)}")
    #   appending " (ask/ask_stream are never exposed)" when any bad entry is in NEVER_EXPOSED;
    #   keep allow order, drop duplicates; empty result →
    #   AgentExposureError(f"Agent '{label}' ({agent_cls.__name__}) defines no exposable methods")
    #   — bounded by spec §3 M3 messages, AC-2, AC-4, AC-5
    ...
```
**Why this shape**: the rule is computed from the MRO at call time, so a framework method
added later is reserved automatically. `_framework_classes` stays private — only the three
spec functions are public.

### `packages/ai-parrot/tests/mcp/test_agent_toolkit.py` (CREATE)
```python
"""FEAT-877 Module 3 — own-class rule, resolution and AgentToolkit."""
from __future__ import annotations

import pytest

from parrot.bots.agent import Agent, BasicAgent
from parrot.mcp.agent_toolkit import AgentExposureError, exposed_methods, own_coroutine_methods
from parrot.registry.registry import MCPLocalExposure


class AuditMixin:
    """A user mixin: not an AbstractBot subclass → its names are reserved."""

    async def audit(self) -> str:
        return "audit"


class FinanceBase(Agent):
    """An author's intermediate base: an own class."""

    async def reconcile(self, account: str) -> dict:
        """Reconcile one account."""
        return {"account": account}


class FinanceAgent(AuditMixin, FinanceBase):
    async def forecast(self, months: int) -> dict:
        """Forecast cash for the next `months` months."""
        return {"months": months}

    async def configure(self, app=None) -> None:  # own override of a framework name → excluded
        return None

    async def ask(self, question: str, **kwargs):  # own override of ask → excluded
        return None

    def sync_helper(self) -> int:  # sync → excluded
        return 1

    async def _private(self) -> None:  # private → excluded
        return None


def test_own_methods_exclude_framework() -> None:
    assert list(own_coroutine_methods(FinanceAgent)) == ["forecast", "reconcile"]


def test_own_override_of_framework_name_excluded() -> None:
    # FILL IN: "configure" and "ask" not in own_coroutine_methods(FinanceAgent) — AC-1/AC-2
    ...


def test_mixin_methods_excluded() -> None:
    # FILL IN: "audit" not a candidate — AC-1
    ...


def test_intermediate_user_base_included() -> None:
    # FILL IN: "reconcile" (defined on FinanceBase) is a candidate and maps to FinanceBase.reconcile
    ...


def test_sync_and_private_excluded() -> None:
    # FILL IN: "sync_helper" and "_private" absent; also a subclass redefining `forecast` as sync drops it
    ...


def test_allow_narrows() -> None:
    # FILL IN: MCPLocalExposure(allow=["reconcile"]) → exactly ["reconcile"] — AC-4
    ...


def test_allow_unknown_entry_fails() -> None:
    # FILL IN: allow=["forecast", "shutdown", "nope"] → AgentExposureError whose message contains
    #   "allow entries are not own-class public async methods" and both "shutdown" and "nope" — AC-4
    ...


def test_ask_never_allowlistable() -> None:
    # FILL IN: allow=["ask"] → message contains "(ask/ask_stream are never exposed)" — AC-2
    ...


def test_generic_class_has_no_candidates() -> None:
    # FILL IN: exposed_methods(BasicAgent, MCPLocalExposure(), agent_name="x") raises with
    #   "defines no exposable methods" — AC-5 (class level; the YAML path is tested in TASK-5488)
    ...
```

### FILL IN checklist
- [ ] `own_coroutine_methods` loop body — spec §2 step 4, AC-1.
- [ ] `exposed_methods` body — spec §3 M3 messages, AC-2/AC-4/AC-5.
- [ ] every `...` test body.

---

## Acceptance Criteria

- [ ] Only own-class public `async` methods are candidates; framework names, own overrides of them, mixin methods, sync and private methods never are (AC-1).
- [ ] `ask`/`ask_stream` are never candidates and an allow entry naming either fails with the note (AC-2).
- [ ] `allow` narrows exactly; a non-candidate entry fails naming it (AC-4).
- [ ] A generic class (`BasicAgent`) yields "defines no exposable methods" (AC-5).
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/agent_toolkit.py packages/ai-parrot/tests/mcp/test_agent_toolkit.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_agent_toolkit.py -q`

---

## Test Specification

See the CREATE block above: spec §4 Module 3 rows `test_own_methods_exclude_framework`,
`test_own_override_of_framework_name_excluded`, `test_mixin_methods_excluded`,
`test_intermediate_user_base_included`, `test_sync_and_private_excluded`,
`test_allow_narrows`, `test_allow_unknown_entry_fails`, `test_ask_never_allowlistable`,
plus `test_generic_class_has_no_candidates`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug agent-local-mcp --feature-id FEAT-877`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/agent-local-mcp.json`
4. **Verify the Codebase Contract** before writing code; if anything changed, update the contract first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5487 agent-local-mcp verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note


- Task: TASK-5487
- Feature: agent-local-mcp
- Implementation SHA: 6be06f17097bdd4d54da566b87995e438c6a7ca2
- Closed at (UTC): 2026-11-11T00:21:00+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 203s · Tokens: n/a |
