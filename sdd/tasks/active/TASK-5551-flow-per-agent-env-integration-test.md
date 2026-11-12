# TASK-5551: End-to-end test — per-agent env key vs FLOW default inside an AgentsFlow

**Feature**: FEAT-882 — Per-Agent Env LLM Credentials + AgentsFlow Default Key
**Spec**: `sdd/specs/per-agent-env-llm-credentials.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5549, TASK-5550
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests (`test_flow_agent_uses_per_agent_env_key_end_to_end`) and the precedence
table (#3 per-agent env beats #5 component default). The unit tests of TASK-5549 and TASK-5550 each
cover one half; this test proves the halves compose: a real `BasicAgent` resolved by
`AgentsFlow.from_definition` gets `FLOW_GOOGLE_API_KEY` injected pre-configure (TASK-5550), and at
`configure()` the per-agent `<AGENT>_GOOGLE_API_KEY` replaces it because the FLOW key is a component
default (TASK-5549 + TASK-5548 `is_component_default_key`).

---

## Scope

- Create `packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py` with three tests:
  1. only `FLOW_GOOGLE_API_KEY` set -> the client is built with the FLOW key;
  2. `FLOW_GOOGLE_API_KEY` and `FEAT882_FLOW_AGENT_GOOGLE_API_KEY` set -> the client gets the per-agent key;
  3. an already-configured registry agent + `FEAT882_FLOW_AGENT_GOOGLE_API_KEY` set before its configure -> per-agent key, FLOW key never applied.

**NOT in scope**: production code changes. If a test exposes a bug in TASK-5548/5549/5550 code, stop and
record it in the Completion Note (`done-with-issues`) rather than patching another task's files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py` | CREATE | end-to-end precedence test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot import llm_defaults as ld                           # verified: tests/unit/test_llm_defaults.py:5
from parrot.bots.agent import BasicAgent                        # verified: bots/agent.py:40
from parrot.bots.flows.flow import AgentsFlow                   # verified: tests/bots/flows/test_from_definition.py:13
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition  # verified: test_from_definition.py:15-19
from parrot.clients import factory                              # verified: tests/unit/test_llm_defaults.py:6
```

### Existing Signatures to Use
```python
# AgentsFlow.from_definition(definition, *, agent_registry=...)   flow.py:550 — registry needs only get_bot_instance(name)
# stub registry pattern: tests/bots/flows/test_from_definition.py (class StubRegistry)
# offline BasicAgent + configure(): tests/docs/test_getting_started_claims.py:370-397
agent = BasicAgent(name="...", llm="google", from_database=False); await agent.configure()
# client construction: abstract.py:1066-1074 — config.client_class(model=..., ..., **config.extra); api_key arrives in kwargs
# TASK-5550: flow_module._flow_skip_logged (module-level set) — reset it per test
```

### Does NOT Exist
- ~~a real provider call~~ — never; the google entry is a recording fake client.
- ~~`AgentRegistry` in this test~~ — use a stub with `get_bot_instance`, exactly like `test_from_definition.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.from_definition",
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#BasicAgent"
  ]
}
```

---

## Implementation Notes

- Agent name `feat882-flow-agent` -> token `FEAT882_FLOW_AGENT`; unique so a developer's `.env` cannot leak in.
- Layer the test variables over the real config (pass-through wrapper, see TASK-5549's `env` fixture) so
  `configure()` still reads every unrelated setting normally.
- Configure the agent AFTER `from_definition` for tests 1–2 (unconfigured -> FLOW injection happens),
  BEFORE it for test 3 (configured -> skipped).

---

## Implementation Blueprint

### Steps (in order)
1. Write the fixture and the stubs below — *why*: hermetic env + offline client.
2. Write the three tests — *why*: one per precedence outcome.
3. Run the file (the feature-tier Validation Contract also runs the upstream unit files) — *why*: a failure here usually points at TASK-5549/5550.

### `packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py` (CREATE)
```python
"""FEAT-882 — per-agent env key vs FLOW default, end to end through AgentsFlow + configure()."""

import pytest

from parrot import llm_defaults as ld
from parrot.bots.agent import BasicAgent
from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flows.flow import flow as flow_module
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.clients import factory

AGENT_NAME = "feat882-flow-agent"


class _FakeClient:
    """Records constructor kwargs instead of reaching a provider."""

    last_kwargs: dict = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = dict(kwargs)


class _Registry:
    def __init__(self, agents):
        self._agents = agents

    def get_bot_instance(self, name):
        return self._agents.get(name)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values: dict[str, str] = {}
    real_get = ld.config.get
    monkeypatch.setattr(
        ld.config, "get", lambda key, *args, **kwargs: values[key] if key in values else real_get(key, *args, **kwargs)
    )
    monkeypatch.setitem(factory.SUPPORTED_CLIENTS, "google", _FakeClient)
    monkeypatch.setattr(flow_module, "_flow_skip_logged", set())
    _FakeClient.last_kwargs = {}
    return values


def _definition() -> FlowDefinition:
    # FILL IN: start -> agent node (agent_ref=AGENT_NAME); mirror test_from_definition.py:_make_linear_def
    ...


async def test_flow_default_key_reaches_client(env): ...
async def test_per_agent_key_beats_flow_default(env): ...
async def test_configured_registry_agent_uses_per_agent_key(env): ...
# FILL IN: bodies — bounded by the three Scope outcomes; assert _FakeClient.last_kwargs["api_key"].
#   If parrot.clients.factory's lazy discovery overwrites the setitem'd entry, switch to the EntryPoint
#   pattern of tests/docs/test_getting_started_claims.py:378-389. If configure() needs an unavailable
#   service, monkeypatch that bot method to a no-op — never drop the api_key assertion.
```

### FILL IN checklist
- [ ] `_definition()` — mirror `_make_linear_def`.
- [ ] Three test bodies — Scope outcomes 1–3.

---

## Acceptance Criteria

- [ ] Test 1: client receives the FLOW key.
- [ ] Test 2: client receives `FEAT882_FLOW_AGENT_GOOGLE_API_KEY`, not the FLOW key.
- [ ] Test 3: configured agent keeps its per-agent key; one INFO "already configured" record.
- [ ] No real network call; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/test_flow_per_agent_env_integration.py -q`

---

## Test Specification

See the CREATE block above (three async tests; `pytest-asyncio` is the repo's test runner for async tests).

---

## Agent Instructions

1. Work in the feature worktree; TASK-5549 and TASK-5550 must be `done`.
2. Set the task `in-progress`; implement; run the Validation Commands.
3. Commit only the listed file; `parrot sdd task close TASK-5551 per-agent-env-llm-credentials verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
