# TASK-3454: `AgentCrew.from_definition(google_api_key=)` — per-agent injection + forwarding

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3452, TASK-3453
**Assigned-to**: unassigned

---

## Context

Spec §2 step 4 (second half) + §3 Module 2. `AgentCrew.from_definition` is the crew
build path used by every server **execution** (`BotManager.get_crew(as_new=True)`,
Redis reload, `load_crews`). It constructs one agent per `AgentDefinition` and then
builds the crew.

This task gives it a keyword-only `google_api_key`, applies `apply_google_api_key`
to every constructed agent, and forwards the key to `AgentCrew.__init__` (added by
TASK-3453). It is goals G1 + G3 for the execution path.

---

## Scope

- Add `google_api_key: Optional[str] = None` as a keyword-only parameter to
  `AgentCrew.from_definition`, and document it.
- Call `apply_google_api_key(agent, google_api_key)` for each constructed agent,
  immediately after `cls._apply_definition_prompt(...)`.
- Forward `google_api_key=google_api_key` into the `cls(...)` call.
- Write unit tests in a NEW test module.

**NOT in scope**:
- `AgentCrew.__init__` — TASK-3453 (same file, which is why this task depends on it).
- `manager.py` / `handler.py` call sites — TASK-3455 / TASK-3456.
- Refactoring `CrewHandler._create_crew_from_definition` to delegate here — spec §1
  Non-Goals explicitly excludes it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | `from_definition` parameter + per-agent call + forward |
| `packages/ai-parrot/tests/bots/flows/crew/test_crew_from_definition_google_key.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# NEW in crew.py (TASK-3453 already added GOOGLE_PROVIDER_KEYS from the same module):
from .credentials import apply_google_api_key            # created by TASK-3452

# in the test module:
from parrot.bots.flows.crew import AgentCrew             # verified: handlers/crew/handler.py:20
from parrot.models.crew_definition import AgentDefinition, CrewDefinition
#   verified: crew_definition.py:31 and :178; re-exported by
#   packages/ai-parrot-server/src/parrot/handlers/crew/models.py:18-24
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — from_definition, VERBATIM
    @classmethod
    def from_definition(
        cls,
        crew_def: "CrewDefinition",                                             # line 769
        *,
        class_resolver: Callable[[str], Optional[type]],                        # line 771
        tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None,  # line 772 — UNIQUE anchor
        **kwargs,                                                                # line 773
    ) -> "AgentCrew":
        agents = []
        for agent_def in crew_def.agents:
            agent_class = class_resolver(agent_def.agent_class)
            if agent_class is None:
                agent_class = BasicAgent
            agent = agent_class(
                name=agent_def.name or agent_def.agent_id,
                tools=list(agent_def.tools),
                **agent_def.config,
            )
            cls._apply_definition_prompt(agent, agent_def.system_prompt)   # line 801 — UNIQUE anchor
            agents.append(agent)                                           # line 802

        max_parallel_tasks = kwargs.pop("max_parallel_tasks", crew_def.max_parallel_tasks)
        tenant = kwargs.pop("tenant", crew_def.tenant)
        generate_infographic = kwargs.pop("generate_infographic", getattr(crew_def, "generate_infographic", False))
        result_agent_name = kwargs.pop("result_agent_name", getattr(crew_def, "result_agent_name", "result-agent"))
        infographic_theme = kwargs.pop("infographic_theme", getattr(crew_def, "infographic_theme", None))
        enable_execution_wiki = kwargs.pop("enable_execution_wiki", getattr(crew_def, "enable_execution_wiki", True))
        execution_wiki_path = kwargs.pop("execution_wiki_path", getattr(crew_def, "execution_wiki_path", None))
        crew = cls(                                                        # UNIQUE anchor `        crew = cls(`
            name=crew_def.name,
            agents=agents,
            max_parallel_tasks=max_parallel_tasks,
            tenant=tenant,
            generate_infographic=generate_infographic,
            result_agent_name=result_agent_name,
            infographic_theme=infographic_theme,
            enable_execution_wiki=enable_execution_wiki,
            execution_wiki_path=execution_wiki_path,
            **kwargs,
        )

    @classmethod
    def _apply_definition_prompt(cls, agent: Any, system_prompt: Optional[str]) -> None:  # line 657

# packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py  (TASK-3452)
def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool: ...

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py  (TASK-3453)
def __init__(self, ..., infographic_theme=None, google_api_key: Optional[str] = None, **kwargs): ...
```

### Does NOT Exist

- ~~`from_definition` currently accepts `google_api_key`~~ — it does not; today the
  signature ends at `tool_resolver` + `**kwargs` (crew.py:767-773).
- ~~`CrewDefinition.google_api_key`~~ / ~~`CrewDefinition.api_key`~~ — not fields, and
  spec §2 Data Models states `CrewDefinition` / `AgentDefinition` are UNCHANGED. The
  key must never be read from or written to the definition (AC7).
- ~~`kwargs.pop("google_api_key", None)`~~ — do NOT implement it that way. It must be
  an explicit keyword-only parameter so `**kwargs` stays clean.
- ~~`AgentCrew.from_definition` is async~~ — it is a sync `@classmethod`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/flows/crew/crew.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/bots/flows/crew/test_crew_from_definition_google_key.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew.from_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#AgentCrew._apply_definition_prompt",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#apply_google_api_key",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#CrewDefinition",
    "sym:packages/ai-parrot/src/parrot/models/crew_definition.py#AgentDefinition"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Keyword-only, explicit, defaulting to `None`.** With the default, `from_definition`
  must behave exactly as today (AC8) — `apply_google_api_key(agent, None)` is already
  a no-op returning `False`, so the call can be unconditional.
- **Call site order matters**: after `cls._apply_definition_prompt(agent, ...)` and
  before `agents.append(agent)`. The agent is constructed but not configured there,
  which is exactly the window `apply_google_api_key` requires.
- **Forward explicitly**, not through `**kwargs`: add `google_api_key=google_api_key`
  to the `cls(...)` call alongside the other named arguments.
- **Never write the key into `crew_def`.** The test asserts `crew_def.model_dump()`
  does not contain the key value (AC7).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `.credentials` import in `crew.py` with `apply_google_api_key` — *why*: TASK-3453 already created that import line; extend it rather than adding a second one.
2. Add the keyword-only parameter + its docstring Args entry — *why*: `BotManager` (TASK-3455) calls it by name.
3. Insert the per-agent call after `_apply_definition_prompt` — *why*: that is the constructed-but-unconfigured window.
4. Forward the key into `cls(...)` — *why*: AC4, so the crew's own orchestration client is covered on the execution path too.
5. Write the tests — *why*: `test_from_definition_default_none_unchanged` is the AC8 regression guard.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from \.credentials import ' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — the line TASK-3453 added)
# REPLACE that line with:
from .credentials import GOOGLE_PROVIDER_KEYS, apply_google_api_key
```
**Why**: one import line from the sibling module keeps the dependency surface obvious.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — signature)
```python
# occurrences: 1 (verified: grep -c '^        tool_resolver: Optional\[Callable\[\[str\], Optional\[AbstractTool\]\]\] = None,$' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# AFTER — insert below `        tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None,`
# (verified: crew.py:772), i.e. immediately before `        **kwargs,` (crew.py:773).
        google_api_key: Optional[str] = None,
```
**Why**: keyword-only (it is after the bare `*`), so no positional call site can break.
Add to the docstring Args block: `google_api_key: When set, every Google agent without
its own credential receives it, and it is forwarded to AgentCrew.__init__. None ->
today's behaviour (GOOGLE_API_KEY).`

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — per-agent call)
```python
# occurrences: 1 (verified: grep -c '^            cls._apply_definition_prompt(agent, agent_def.system_prompt)$' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# AFTER — insert below `            cls._apply_definition_prompt(agent, agent_def.system_prompt)`
# (verified: crew.py:801), above `            agents.append(agent)` (crew.py:802).
            apply_google_api_key(agent, google_api_key)
```
**Why**: unconditional is correct and simplest — the helper already no-ops on a falsy
key, on a non-Google agent, and on an agent that brought its own credential. Its
return value is intentionally discarded; nothing here branches on it.

### `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` (MODIFY — forward to ctor)
```python
# occurrences: 1 (verified: grep -c '^        crew = cls($' packages/ai-parrot/src/parrot/bots/flows/crew/crew.py)
# AFTER — inside the `crew = cls(` call, insert below
# `            execution_wiki_path=execution_wiki_path,`, above `            **kwargs,`.
            google_api_key=google_api_key,
```
**Why**: AC4 on the execution path. Passing it explicitly (not via `**kwargs`) matches
how `tenant` / `generate_infographic` / `infographic_theme` are already threaded.

### `packages/ai-parrot/tests/bots/flows/crew/test_crew_from_definition_google_key.py` (CREATE)
```python
"""AgentCrew.from_definition credential injection (FEAT-575, TASK-3454)."""
import pytest

from parrot.bots.flows.crew import AgentCrew
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


def _crew_def():
    # FILL IN: build a CrewDefinition with TWO AgentDefinitions — one whose
    # config declares a Google llm and NO credential, one whose config declares
    # an OpenAI llm. Check the real required fields of AgentDefinition
    # (crew_definition.py:31, extra="forbid") before filling this in; do NOT
    # invent fields — bounded by AC1/AC3.
    raise NotImplementedError


def test_from_definition_injects_google_agents(monkeypatch):
    # FILL IN: from_definition(crew_def, class_resolver=lambda _: _StubAgent,
    # google_api_key="k") — assert ONLY the Google agent's _llm_kwargs gained
    # api_key == "k", and that "k" does not appear anywhere in
    # str(crew_def.model_dump()) — bounded by AC1, AC3 and AC7.
    # NOTE: AgentCrew.__init__ will try to build a default Google orchestration
    # client; patch the SUPPORTED_CLIENTS["google"] entry (as TASK-3453's tests do)
    # or pass an llm instance so the test never touches the network.
    raise NotImplementedError


def test_from_definition_default_none_unchanged(monkeypatch):
    # FILL IN: same build with NO google_api_key; assert no agent's _llm_kwargs
    # gained an "api_key" — bounded by AC8 (regression guard).
    raise NotImplementedError


def test_from_definition_forwards_key_to_crew(monkeypatch):
    # FILL IN: assert the constructed crew's _google_api_key == "k" — bounded by
    # AC4 (the crew's own orchestration client must be covered too).
    raise NotImplementedError


def test_from_definition_respects_agent_own_credential(monkeypatch):
    # FILL IN: a Google AgentDefinition whose config sets
    # llm_kwargs={"api_key": "own"} keeps "own" — bounded by AC2.
    raise NotImplementedError
```
**Why**: `class_resolver=lambda _: _StubAgent` avoids constructing a real agent (and
its DB/tool machinery) while still exercising the exact `_llm_raw`/`_llm_kwargs`
contract `apply_google_api_key` reads. The `model_dump()` assertion is the AC7 proof
on this path.

### FILL IN checklist
- [ ] `_crew_def()` — real `AgentDefinition` fields only; bounded by `extra="forbid"` (crew_definition.py:31)
- [ ] `test_from_definition_injects_google_agents` — bounded by AC1/AC3/AC7
- [ ] `test_from_definition_default_none_unchanged` — bounded by AC8
- [ ] `test_from_definition_forwards_key_to_crew` — bounded by AC4
- [ ] `test_from_definition_respects_agent_own_credential` — bounded by AC2

---

## Acceptance Criteria

- [ ] `from_definition(..., google_api_key="k")` injects `api_key="k"` into every Google agent that declared no credential (AC1).
- [ ] Non-Google agents and agents with their own credential are untouched (AC2, AC3).
- [ ] The key is forwarded to `AgentCrew.__init__` (AC4).
- [ ] `crew_def.model_dump()` never contains the key (AC7).
- [ ] `from_definition(...)` with no `google_api_key` behaves exactly as before (AC8).
- [ ] `google_api_key` is a keyword-only named parameter, never popped from `kwargs`.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_from_definition_google_key.py -q`

---

## Test Specification

See the blueprint's test block — it IS the scaffold. Before writing `_crew_def()`,
read `packages/ai-parrot/src/parrot/models/crew_definition.py:31-178` for the real
required fields; the model is `extra="forbid"` and will reject invented ones.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3452 (`apply_google_api_key`) and TASK-3453 (`AgentCrew.__init__(google_api_key=)`) must both be done
3. **Verify the Codebase Contract** — re-read `crew.py:767-773`, `:796-802` and the `crew = cls(` call; confirm TASK-3453's `google_api_key` parameter is present on `__init__`
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met, and ALSO re-run TASK-3453's suite
   (`pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_google_key.py -q`) —
   both tasks edit `crew.py`, so that file is this task's regression guard even
   though it is not one of this task's declared targets
7. **Move this file** to `sdd/tasks/completed/TASK-3454-from-definition-google-key.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
