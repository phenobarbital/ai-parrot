# TASK-3456: `CrewHandler._create_crew_from_definition` applies `CREW_AI_KEY`

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3452, TASK-3453
**Assigned-to**: unassigned

---

## Context

Spec §2 step 5 + §3 Module 3 (second call site). `CrewHandler._create_crew_from_definition`
is the **CRUD** build path — it runs on `PUT /api/v1/crew` (handler.py:265) and on
create/update (handler.py:388). Unlike `BotManager`, it does NOT delegate to
`AgentCrew.from_definition`: it constructs each agent itself and then calls
`AgentCrew(...)` directly.

Spec §1 Non-Goals explicitly rules out refactoring it to delegate. So it gets the same
wiring in place: the helper per agent, plus the crew kwarg. This is goal G3 / AC5,
CRUD half.

---

## Scope

- Import `apply_google_api_key` and `get_crew_google_api_key` in `handler.py`.
- Resolve the key ONCE per call, before the agent loop.
- Call `apply_google_api_key(agent, google_key)` after each `agent_class(...)` and
  after the system-prompt assignment, before `agents.append(agent)`.
- Pass `google_api_key=google_key` to the `AgentCrew(...)` construction.
- Write a unit test for the handler build path.

**NOT in scope**:
- `BotManager._create_crew_from_definition` — TASK-3455 (different file, runs in parallel).
- Refactoring this method to delegate to `from_definition` — spec §1 Non-Goals.
- The `CrewExecutionHandler` — execution loads crews via
  `bot_manager.get_crew(crew_id, as_new=True, tenant=tenant)` (execution_handler.py:683-687),
  which is covered by TASK-3455.
- The integration test — TASK-3457.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` | MODIFY | Imports + per-agent call + crew kwarg |
| `packages/ai-parrot-server/tests/handlers/test_crew_handler_google_key.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# already at the top of handler.py:
from .models import CrewDefinition, ExecutionMode        # verified: handler.py:18
from parrot.bots.flows.crew import AgentCrew             # verified: handler.py:20 — ABSOLUTE, not relative

# NEW — match the ABSOLUTE style of the AgentCrew import on handler.py:20:
from parrot.bots.flows.crew.credentials import apply_google_api_key, get_crew_google_api_key
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/crew/handler.py — VERBATIM, lines 90-147
    async def _create_crew_from_definition(
        self,
        crew_def: CrewDefinition
    ) -> AgentCrew:                                        # line 90
        # Create agents
        agents = []
        for agent_def in crew_def.agents:
            agent_class = self.bot_manager.get_bot_class(agent_def.agent_class)
            tools = []
            if agent_def.tools:
                tools.extend(iter(agent_def.tools))
            if agent_def.agent_class == "WebSearchAgent":
                self.logger.debug(...)
            agent = agent_class(
                name=agent_def.name or agent_def.agent_id,
                tools=tools,
                **agent_def.config
            )                                              # line 129 (closing paren)
            # Set system prompt if provided
            if agent_def.system_prompt:
                agent.system_prompt = agent_def.system_prompt
            agents.append(agent)                           # line 138 — UNIQUE anchor
        # Create crew
        crew = AgentCrew(
            name=crew_def.name,
            agents=agents,
            max_parallel_tasks=crew_def.max_parallel_tasks # line 145 — UNIQUE anchor, NO trailing comma
        )                                                  # line 146
        # Add shared tools
        for tool_name in crew_def.shared_tools:
            if tool := self.bot_manager.get_tool(tool_name):
                ...

# callers (context only — do NOT modify): PUT upload line 265, create/update line 388

# packages/ai-parrot-server/src/parrot/handlers/crew/models.py
# Re-exports ONLY — the canonical models live in parrot.models.crew_definition:
from parrot.models.crew_definition import (  # noqa: F401    # lines 18-24
    ExecutionMode, AgentDefinition, ToolNodeDefinition, FlowRelation, CrewDefinition,
)

# packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py  (TASK-3451/3452)
def get_crew_google_api_key() -> Optional[str]: ...
def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool: ...

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py  (TASK-3453)
def __init__(self, ..., infographic_theme=None, google_api_key: Optional[str] = None, **kwargs): ...
```

### Does NOT Exist

- ~~`CrewHandler._create_crew_from_definition` delegates to `AgentCrew.from_definition`~~
  — it does NOT. It builds agents itself. Do not "fix" that (spec §1 Non-Goals).
- ~~a separate `CrewDefinition` class in `handlers/crew/models.py`~~ — that module only
  re-exports `parrot.models.crew_definition`'s models (models.py:18-24). There is ONE
  `CrewDefinition`.
- ~~`handler.py` imports core with a relative `..`~~ — the AgentCrew import at
  handler.py:20 is ABSOLUTE (`from parrot.bots.flows.crew import AgentCrew`). Match it.
- ~~`max_parallel_tasks=crew_def.max_parallel_tasks,`~~ with a trailing comma — line 145
  has NO trailing comma. Adding the new kwarg means adding that comma.
- ~~`self.logger` is unavailable in `CrewHandler`~~ — it is a `BaseView`; `self.logger`
  works (used at handler.py:119).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/crew/handler.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/handlers/test_crew_handler_google_key.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler._create_crew_from_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#apply_google_api_key",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#get_crew_google_api_key",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.__init__"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Resolve the key ONCE per call**, above the `for agent_def in crew_def.agents:`
  loop — not once per agent. Calling it per agent would be correct but noisy; the spec
  fixes it as "once per call" (§3 M3).
- **Placement inside the loop**: after the `if agent_def.system_prompt:` assignment and
  before `agents.append(agent)`. The agent is constructed and unconfigured there, which
  is the window `apply_google_api_key` requires.
- **Never log the key** (AC7). If you add a log line, log only the *count* of agents
  that received it.
- **Signature unchanged** — only the body changes.
- With `CREW_AI_KEY` unset, `get_crew_google_api_key()` returns `None`,
  `apply_google_api_key(agent, None)` is a no-op, and `AgentCrew(google_api_key=None)`
  is today's behaviour (AC6, AC8).

---

## Implementation Blueprint

### Steps (in order)
1. Add the absolute import beside the existing `AgentCrew` import — *why*: handler.py imports core absolutely (handler.py:20), not relatively.
2. Resolve `google_key` once, above the agent loop — *why*: spec §3 M3 fixes it as once per call.
3. Insert the per-agent call before `agents.append(agent)` — *why*: constructed-but-unconfigured window.
4. Add the crew kwarg (and the missing trailing comma) — *why*: AC4, the crew's own orchestration client.
5. Write the test asserting Google injected / non-Google untouched / crew got the kwarg — *why*: that triple is exactly AC1+AC3+AC4 on this path.

### `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from parrot.bots.flows.crew import AgentCrew$' packages/ai-parrot-server/src/parrot/handlers/crew/handler.py)
# AFTER — insert below `from parrot.bots.flows.crew import AgentCrew` (verified: handler.py:20)
from parrot.bots.flows.crew.credentials import apply_google_api_key, get_crew_google_api_key
```
**Why**: absolute import, matching the line directly above it.

### `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (MODIFY — resolve once)
```python
# occurrences: 1 (verified: grep -c '^        # Create agents$' packages/ai-parrot-server/src/parrot/handlers/crew/handler.py)
# AFTER — insert below `        # Create agents` (the line above `        agents = []`,
# verified: handler.py:109-110), i.e. before the `for agent_def in ...` loop.
        # FEAT-575: default Google credential for handler-built crews. None when
        # CREW_AI_KEY is unset, which makes every use below a no-op.
        google_key = get_crew_google_api_key()
```
**Why**: one resolution per request means one warn-once check and one value shared by
the loop and the crew construction.

### `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (MODIFY — per agent)
```python
# occurrences: 1 (verified: grep -c '^            agents.append(agent)$' packages/ai-parrot-server/src/parrot/handlers/crew/handler.py)
# BEFORE — insert immediately above `            agents.append(agent)` (verified: handler.py:138),
# i.e. after the `if agent_def.system_prompt:` block.
            apply_google_api_key(agent, google_key)
```
**Why**: unconditional — the helper already no-ops on a falsy key, a non-Google agent,
or an agent that declared its own credential. Its return value is discarded.

### `packages/ai-parrot-server/src/parrot/handlers/crew/handler.py` (MODIFY — crew kwarg)
```python
# occurrences: 1 (verified: grep -c '^            max_parallel_tasks=crew_def.max_parallel_tasks$' packages/ai-parrot-server/src/parrot/handlers/crew/handler.py)
# REPLACE the line `            max_parallel_tasks=crew_def.max_parallel_tasks` (verified:
# handler.py:145 — it has NO trailing comma) with the two lines below.
            max_parallel_tasks=crew_def.max_parallel_tasks,
            google_api_key=google_key
```
**Why**: AC4 on the CRUD path. The trailing comma on the first line is required — the
original had none because it was the last argument.

### `packages/ai-parrot-server/tests/handlers/test_crew_handler_google_key.py` (CREATE)
```python
"""CrewHandler applies CREW_AI_KEY to handler-built crews (FEAT-575, TASK-3456)."""
import pytest

from parrot.handlers.crew.handler import CrewHandler
from parrot.models.crew_definition import AgentDefinition, CrewDefinition


class _StubAgent:
    """Constructed-but-unconfigured agent stub, mirroring AbstractBot's contract."""

    _default_llm = "google"

    def __init__(self, name=None, tools=None, llm=None, llm_kwargs=None, **kwargs):
        self.name = name
        self._llm_raw = llm
        # abstract.py:516 assigns BY REFERENCE — reproduce that exactly.
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.system_prompt = None


@pytest.fixture
def crew_key(monkeypatch):
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", "crew-test-key", raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)
    return "crew-test-key"


@pytest.mark.asyncio
async def test_handler_create_crew_applies_crew_key(crew_key, monkeypatch):
    # FILL IN: build a CrewDefinition with one Google agent (no credential) and one
    # OpenAI agent — read crew_definition.py:31-178 for the REAL required fields
    # (extra="forbid"). Drive CrewHandler._create_crew_from_definition on a stub
    # self exposing .bot_manager (get_bot_class -> _StubAgent, get_tool -> None)
    # and .logger. Patch "parrot.handlers.crew.handler.AgentCrew" with a recorder.
    # Assert: the Google agent's _llm_kwargs["api_key"] == crew_key; the OpenAI
    # agent's has no api_key; the recorded AgentCrew kwargs carry
    # google_api_key == crew_key — bounded by AC1, AC3, AC4, AC5.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_handler_does_not_write_key_into_definition(crew_key, monkeypatch):
    # FILL IN: after the same build, assert crew_key does NOT appear anywhere in
    # str(crew_def.model_dump()) — bounded by AC7 (never persisted to Redis nor
    # returned by GET /api/v1/crew).
    raise NotImplementedError


@pytest.mark.asyncio
async def test_handler_without_key_is_unchanged(monkeypatch):
    # FILL IN: with parrot.conf.CREW_AI_KEY unset, assert no agent gained an
    # api_key and the recorded AgentCrew kwargs carry google_api_key is None —
    # bounded by AC6/AC8.
    raise NotImplementedError
```
**Why**: patching `parrot.handlers.crew.handler.AgentCrew` (the name bound *inside*
handler.py) is what makes the crew-kwarg assertion cover this call site. Driving the
method with a stub `self` avoids standing up aiohttp/navigator, which these assertions
do not need. Check `packages/ai-parrot-server/tests/handlers/conftest.py` first — if it
already provides a usable handler/bot_manager fixture, prefer it over a hand-rolled stub.

### FILL IN checklist
- [ ] `test_handler_create_crew_applies_crew_key` — real `AgentDefinition` fields; bounded by AC1/AC3/AC4/AC5
- [ ] `test_handler_does_not_write_key_into_definition` — bounded by AC7
- [ ] `test_handler_without_key_is_unchanged` — bounded by AC6/AC8

---

## Acceptance Criteria

- [ ] A Google agent with no credential, built through `CrewHandler._create_crew_from_definition`, gets `_llm_kwargs["api_key"] == CREW_AI_KEY` (AC1, AC5).
- [ ] Non-Google agents and agents with their own credential are untouched (AC2, AC3).
- [ ] The constructed `AgentCrew` receives `google_api_key` (AC4).
- [ ] `crew_def.model_dump()` never contains the key (AC7).
- [ ] With `CREW_AI_KEY` unset nothing changes (AC6, AC8).
- [ ] `_create_crew_from_definition`'s signature is unchanged.
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/crew/handler.py`

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/handlers/test_crew_handler_google_key.py -q`

---

## Test Specification

See the blueprint's test block — it IS the scaffold. Read
`packages/ai-parrot-server/tests/handlers/conftest.py` before hand-rolling fixtures.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3452 (`apply_google_api_key`) and TASK-3453 (`AgentCrew.__init__(google_api_key=)`) must both be done
3. **Verify the Codebase Contract** — re-read `handler.py:90-147`; confirm line 145 still has no trailing comma before applying the replace block
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3456-crewhandler-applies-crew-key.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
