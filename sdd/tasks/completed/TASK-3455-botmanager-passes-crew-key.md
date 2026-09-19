# TASK-3455: `BotManager._create_crew_from_definition` passes `CREW_AI_KEY`

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3454
**Assigned-to**: unassigned

---

## Context

Spec §2 step 5 + §3 Module 3 (first call site). `BotManager._create_crew_from_definition`
is the **execution** build path: it is what `get_crew(identifier, as_new=True)`,
the Redis reload and `load_crews()` all funnel through, so every crew run through
`/api/v1/crew` execution is built here.

It already delegates to `AgentCrew.from_definition`. This task adds the one kwarg
that turns the whole chain on. It is goal G3 / AC5, execution half.

---

## Scope

- Import `get_crew_google_api_key` in `manager.py`.
- Pass `google_api_key=get_crew_google_api_key()` to the existing
  `AgentCrew.from_definition(...)` call.
- Write a unit test asserting the key reaches `from_definition`.

**NOT in scope**:
- `CrewHandler._create_crew_from_definition` — TASK-3456 (different file, runs in parallel).
- The method's signature, its docstring contract about `tool_resolver=None`, or any
  other `BotManager` method.
- The integration test — TASK-3457.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Import + one kwarg |
| `packages/ai-parrot-server/tests/manager/test_crew_google_key.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already in manager.py:
from ..bots.flows.crew import AgentCrew                 # verified: manager.py:82
from ..models.crew_definition import CrewDefinition     # verified: manager.py:83

# NEW — same relative depth as the AgentCrew import above (manager.py is at
# packages/ai-parrot-server/src/parrot/manager/manager.py, so `..` is `parrot`):
from ..bots.flows.crew.credentials import get_crew_google_api_key
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/manager/manager.py — VERBATIM, lines 3081-3099
    async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:
        """Create an AgentCrew from a CrewDefinition.

        Delegates to ``AgentCrew.from_definition()``, passing
        ``self.get_bot_class`` as ``class_resolver``. Shared tool
        resolution is not available in this context (no tool registry on
        BotManager); ``from_definition`` handles the ``tool_resolver=None``
        default by skipping shared tool resolution.

        Args:
            crew_def: Crew definition.

        Returns:
            AgentCrew instance.
        """
        return AgentCrew.from_definition(
            crew_def,
            class_resolver=self.get_bot_class,      # line 3098 — UNIQUE anchor
        )

# callers of this method (context only — do NOT modify):
    async def get_crew(self, identifier, as_new=False, tenant=None)   # line 2818
    async def load_crews(self) -> None                                # line 2981

# packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py  (TASK-3451)
def get_crew_google_api_key() -> Optional[str]: ...

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py  (TASK-3454)
@classmethod
def from_definition(cls, crew_def, *, class_resolver, tool_resolver=None,
                    google_api_key: Optional[str] = None, **kwargs) -> "AgentCrew": ...
```

### Does NOT Exist

- ~~`packages/ai-parrot-server/src/parrot/conf.py`~~ — the server has NO own `conf.py`.
  `manager.py:93`'s `from ..conf import ...` resolves to **core** `parrot/conf.py`.
  Do NOT read `CREW_AI_KEY` from `..conf` directly here — always go through
  `get_crew_google_api_key()`, which owns the warn-once behaviour (AC6).
- ~~`BotManager.crew_google_api_key`~~ / any BotManager attribute holding the key —
  does not exist and must not be added; the key is resolved per call.
- ~~`_create_crew_from_definition` takes a `tenant` argument~~ — it does not; its only
  parameter is `crew_def` and its signature is UNCHANGED by this task.
- ~~`AgentCrew.from_definition` is awaited~~ — it is a sync `@classmethod`; the
  existing `return AgentCrew.from_definition(...)` has no `await` and must keep none.

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
      "path": "packages/ai-parrot-server/tests/manager/test_crew_google_key.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._create_crew_from_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#get_crew_google_api_key",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.from_definition"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Resolve per call, not at import.** `get_crew_google_api_key()` must be called
  inside the method so a monkeypatched `parrot.conf.CREW_AI_KEY` is honoured and the
  warn-once latch fires at first use rather than at import.
- **Do not change the method signature or its docstring contract.** Only add the kwarg
  (and optionally one sentence to the docstring about the credential).
- `manager.py` lives in `ai-parrot-server` but imports core through `..` — the
  `parrot.*` namespace is merged via PEP 420, so `..bots.flows.crew.credentials`
  resolves to the core module created by TASK-3451.

### Test setup note

`packages/ai-parrot-server/tests/manager/` already exists and contains
`__init__.py`, `test_agent_mount_wiring.py`, `test_deeplink_routes_mounted.py`,
`test_reload_agent.py` — follow whichever construction/patching style those use for
`BotManager`. Do NOT instantiate a full `BotManager` if those tests avoid it; patching
`AgentCrew.from_definition` and calling the unbound method with a stub `self` is
sufficient and is the intent here.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import next to the existing crew imports — *why*: keeps the crew-related imports in one block (manager.py:82-83).
2. Add the kwarg to the `from_definition` call — *why*: this single line is AC5's execution half.
3. Write the test — *why*: the only thing worth asserting is that the resolved key actually reaches `from_definition`.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from \.\.models\.crew_definition import CrewDefinition$' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below `from ..models.crew_definition import CrewDefinition` (verified: manager.py:83)
from ..bots.flows.crew.credentials import get_crew_google_api_key
```
**Why**: sits in the existing `# Crew:` import block (manager.py:81-90) so the crew
wiring stays readable.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — call site)
```python
# occurrences: 1 (verified: grep -c '^            class_resolver=self.get_bot_class,$' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below `            class_resolver=self.get_bot_class,` (verified: manager.py:3098),
# inside the existing `return AgentCrew.from_definition(` call.
            google_api_key=get_crew_google_api_key(),
```
**Why**: one line, resolved per call. With `CREW_AI_KEY` unset this evaluates to
`None`, and `from_definition`'s `None` default means behaviour is identical to today
(AC6, AC8). Also append to the docstring's description: "Google agents without their
own credential receive ``CREW_AI_KEY`` when it is configured (FEAT-575)."

### `packages/ai-parrot-server/tests/manager/test_crew_google_key.py` (CREATE)
```python
"""BotManager passes CREW_AI_KEY to AgentCrew.from_definition (FEAT-575, TASK-3455)."""
import pytest

from parrot.manager.manager import BotManager


@pytest.fixture
def crew_key(monkeypatch):
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"


@pytest.mark.asyncio
async def test_manager_create_crew_passes_crew_key(crew_key, monkeypatch):
    # FILL IN: patch AgentCrew.from_definition (as imported INTO manager.py — patch
    # "parrot.manager.manager.AgentCrew.from_definition") with a recorder, invoke
    # BotManager._create_crew_from_definition on a minimal instance or via the
    # unbound function with a stub self exposing get_bot_class, and assert the
    # recorded kwargs contain google_api_key == crew_key — bounded by AC5.
    # Follow the BotManager construction style already used in
    # packages/ai-parrot-server/tests/manager/test_reload_agent.py.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_manager_create_crew_without_key_passes_none(monkeypatch):
    # FILL IN: with parrot.conf.CREW_AI_KEY unset, assert the recorded
    # google_api_key is None — bounded by AC6/AC8 (unset => today's behaviour).
    raise NotImplementedError
```
**Why**: patching `parrot.manager.manager.AgentCrew.from_definition` (the name bound
*inside* manager.py) rather than the class's home module is what makes the assertion
actually cover this call site.

### FILL IN checklist
- [ ] `test_manager_create_crew_passes_crew_key` — recorder patch + kwarg assertion; bounded by AC5
- [ ] `test_manager_create_crew_without_key_passes_none` — bounded by AC6/AC8

---

## Acceptance Criteria

- [ ] `BotManager._create_crew_from_definition` passes `google_api_key=get_crew_google_api_key()` to `AgentCrew.from_definition` (AC5).
- [ ] With `CREW_AI_KEY` unset the forwarded value is `None` and nothing else changes (AC6, AC8).
- [ ] The method signature is unchanged.
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/manager/manager.py`

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/manager/test_crew_google_key.py -q`

---

## Test Specification

See the blueprint's test block — it IS the scaffold. Mirror the `BotManager` setup
style of `packages/ai-parrot-server/tests/manager/test_reload_agent.py` rather than
inventing a new one.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3454 must be done; `AgentCrew.from_definition` must already accept `google_api_key`
3. **Verify the Codebase Contract** — re-read `manager.py:3081-3099`; if the `from_definition` call has changed shape, update the contract FIRST
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3455-botmanager-passes-crew-key.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (orchestrator) via native seat `sonnet`
**Date**: 2026-09-19
**Notes**: Added `from ..bots.flows.crew.credentials import get_crew_google_api_key`
to `manager.py`'s import block, and passed `google_api_key=get_crew_google_api_key()`
(resolved per-call) into the existing `AgentCrew.from_definition(...)` call
inside `BotManager._create_crew_from_definition`. Method signature unchanged.
Created `test_crew_google_key.py` (2 tests: CREW_AI_KEY set → forwarded;
unset → forwarded as None). Test run: 2 passed. `ruff check` flagged 1
pre-existing `B007` unused-loop-var finding at manager.py:3119, outside this
task's diff hunks — pre-existing, deferred to feature-completion ledger.

**Deviations from spec**: none
