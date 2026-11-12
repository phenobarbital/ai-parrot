# TASK-5550: AgentsFlow FLOW defaults (`FLOW_LLM`, `FLOW_<PROVIDER>_API_KEY`) + `component="FLOW"` usage tag

**Feature**: FEAT-882 — Per-Agent Env LLM Credentials + AgentsFlow Default Key
**Spec**: `sdd/specs/per-agent-env-llm-credentials.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5548
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (rev 0.2), decision D3. `AgentCrew` injects `CREW_GOOGLE_API_KEY` into Google agents
without their own credential (`crew.py:859`); `AgentsFlow` has no equivalent. Unlike the crew,
`AgentsFlow` does not build its agents: `from_definition` takes cached instances from an
`AgentRegistry` (`flow.py:635`, `:661`), which normally configured them already (`registry.py:217`).
D3 (resolved with the author): FLOW defaults apply only to agents that are NOT yet configured — in
practice programmatic flows — and a configured agent is left alone with one INFO log per agent name.

---

## Scope

- Add module-level `_FLOW_BUILTIN_LLM`, `_flow_skip_logged`, `_flow_usage_scope` and `_apply_flow_defaults` to `flow.py`.
- Call `_apply_flow_defaults` for every agent resolved in `from_definition` (single `agent` nodes and decision-group members) and for the agent of every `AgentNode` passed to `add_node`.
- Decorate `run_flow` with `_flow_usage_scope` so its LLM calls carry `UsageRecord.component == "FLOW"`.
- Create `packages/ai-parrot/tests/bots/flows/test_flow_default_key.py`.

**NOT in scope**: the resolver/injector (TASK-5548), per-agent env in `configure()` (TASK-5549), docs
(TASK-5552), a `component=` hint on `AgentRegistry.get_instance` (rejected in D3), any change to `AgentCrew`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | FLOW defaults + usage scope |
| `packages/ai-parrot/tests/bots/flows/test_flow_default_key.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# flow.py already has:
import asyncio                                                     # verified: flow.py:20  (add `import functools` below it)
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple, Type, Union   # verified: flow.py:26
from navconfig.logging import logging                              # verified: flow.py:30
from ..core.node import AgentNode, EndNode, Node, StartNode        # verified: flow.py:34
logger = logging.getLogger(__name__)                               # verified: flow.py:81 (module logger)
# NEW in flow.py (same relative depth as crew.py:63):
from ....observability.context import usage_component              # verified: parrot/observability/context.py:171; crew.py:63 uses this exact form
from ....llm_defaults import apply_component_api_key, resolve_component_llm   # resolve_component_llm verified: llm_defaults.py:47; apply_component_api_key created by TASK-5548
# tests:
from parrot.bots.flows.flow import AgentsFlow                      # verified: tests/bots/flows/test_from_definition.py:13
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition  # verified: test_from_definition.py:15-19
from parrot.bots.flows.core.node import AgentNode                  # verified: bots/flows/core/node.py:193
from parrot.observability.context import current_component, usage_component  # verified: observability/context.py:167,171
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
class AgentsFlow(PersistenceMixin):                                 # :212
    def add_node(self, node: Node) -> None:                         # :407
        ...
        self._nodes[node.node_id] = node                            # :419
    def from_definition(cls, definition, *, agent_registry=None, ...) -> "AgentsFlow"   # :550 (classmethod)
            agent = agent_registry.get_bot_instance(agent_ref)      # :635
            ...
            resolved_agents[node_def.id] = agent                    # :639
                agent = agent_registry.get_bot_instance(ref)        # :661  (decision-group members)
                ...
                group[ref] = agent                                  # :664
    async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult   # :1226

# packages/ai-parrot/src/parrot/bots/flows/core/node.py
class AgentNode(Node):                                              # :193
    agent: AgentLike                                                # :228 (attribute)

# packages/ai-parrot/src/parrot/bots/flows/crew/crew.py — pattern to mirror
def _crew_usage_scope(func):                                        # :150
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        with usage_component("CREW"):
            return await func(*args, **kwargs)
    return wrapper
_CREW_BUILTIN_LLM = "google:gemini-4-argon"                         # :121

# packages/ai-parrot/src/parrot/llm_defaults.py
def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM   # :47  source in {"component","global","builtin"}
def apply_component_api_key(agent: Any, component: str) -> bool               # TASK-5548: no-op for configured agents / explicit creds

# agent attributes read (AbstractBot): _llm_raw (:483), _llm_model_explicit (:509), _model_config, is_configured (property, :1922)
```

### Does NOT Exist
- ~~`FLOW_LLM` / `FLOW_*_API_KEY` handling anywhere~~ — created by THIS task (plus TASK-5548's generic injector).
- ~~`AgentsFlow._flow_usage_scope`~~ — the scope helper is a MODULE-level function, like `_crew_usage_scope`.
- ~~`AgentRegistry.get_instance(..., component=...)`~~ — rejected in D3; do not add.
- ~~`import functools` in flow.py~~ — not imported today; add it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/flows/flow/flow.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/flows/test_flow_default_key.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.add_node",
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.from_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.run_flow",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py#_crew_usage_scope",
    "sym:packages/ai-parrot/src/parrot/llm_defaults.py#resolve_component_llm",
    "sym:packages/ai-parrot/src/parrot/observability/context.py#usage_component"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- G4 / AC1: with no `FLOW_*` variable set nothing changes. `FLOW_LLM` is applied only when
  `resolved.source == "component"` — a bare `DEFAULT_LLM` must NOT start re-pointing flow agents.
- `FLOW_LLM` is applied only when the agent declares no `llm` (`_llm_raw is None`), no explicit model
  (`_llm_model_explicit` falsy) and no `_model_config` — otherwise provider and model could disagree.
- A malformed `FLOW_LLM` raises `ValueError` from `resolve_component_llm`; let it propagate (fail fast, like `CREW_LLM`).
- `_apply_flow_defaults` must tolerate non-`AbstractBot` agents (the `FakeAgent` stubs in existing flow tests have no `_llm_raw`): `apply_component_api_key` already no-ops; guard the FLOW_LLM step with `hasattr`.
- One INFO log per agent name per process for configured agents (`_flow_skip_logged` set) — never a value.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import functools` and the two package imports — *why*: the helpers below need them.
2. Add the module-level helpers directly above `class AgentsFlow(PersistenceMixin):` — *why*: mirrors `_crew_usage_scope` placement and keeps them importable for tests.
3. Hook `add_node`, both `from_definition` resolution loops and `run_flow` — *why*: these are every path through which an agent enters a flow and the one entry point that runs it.
4. Write the tests; also run the existing `test_from_definition.py` — *why*: its `FakeAgent` stubs prove the no-op path.

### `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` (MODIFY — 1/5)
```python
# occurrences: 1 (verified: grep -c '^import asyncio$' flow.py)
# AFTER — insert below `import asyncio` (verified: flow.py:20)
import functools
```
```python
# occurrences: 1 (verified: grep -c 'from ..core.node import AgentNode, EndNode, Node, StartNode' flow.py)
# AFTER — insert below that line (verified: flow.py:34)
from ....llm_defaults import apply_component_api_key, resolve_component_llm
from ....observability.context import usage_component
```

### `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` (MODIFY — 2/5)
```python
# occurrences: 1 (verified: grep -c 'class AgentsFlow(PersistenceMixin):' flow.py)
# BEFORE — insert above `class AgentsFlow(PersistenceMixin):` (verified: flow.py:212)
_FLOW_BUILTIN_LLM = "google:gemini-4-argon"

#: Agent names already reported as "configured, FLOW defaults skipped" (one INFO per name per process).
_flow_skip_logged: set[str] = set()


def _flow_usage_scope(func):
    """Tag every client call made inside an AgentsFlow entry point as component ``FLOW`` (FEAT-882)."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        with usage_component("FLOW"):
            return await func(*args, **kwargs)

    return wrapper


def _apply_flow_defaults(agent: Any) -> None:
    """Apply ``FLOW_LLM`` / ``FLOW_<PROVIDER>_API_KEY`` to an agent that is not configured yet (FEAT-882 D3).

    Configured agents keep their client (one INFO log per name); their key comes from
    ``<AGENT>_<PROVIDER>_API_KEY`` instead. ``FLOW_LLM`` applies only when it is set and the agent
    declares no llm, model or model_config.

    Raises:
        ValueError: When ``FLOW_LLM`` is malformed.
    """
    if getattr(agent, "is_configured", False):
        name = str(getattr(agent, "name", None) or type(agent).__name__)
        if name not in _flow_skip_logged:
            _flow_skip_logged.add(name)
            logger.info(
                "AgentsFlow: agent %r is already configured; FLOW_* defaults not applied "
                "(set <AGENT>_<PROVIDER>_API_KEY / <AGENT>_MODEL instead)",
                name,
            )
        return
    # FILL IN: FLOW_LLM step — only if hasattr(agent, "_llm_raw") and agent._llm_raw is None and not
    #   getattr(agent, "_llm_model_explicit", False) and not getattr(agent, "_model_config", None):
    #   resolved = resolve_component_llm("FLOW", builtin=_FLOW_BUILTIN_LLM); if resolved.source == "component":
    #   agent._llm_raw = f"{resolved.provider}:{resolved.model}". Bounded by G4/AC1.
    apply_component_api_key(agent, "FLOW")

```
**Why this shape**: FLOW_LLM runs before the key so the injector derives the provider from the final
`_llm_raw`. Gating on `source == "component"` keeps G4: today `DEFAULT_LLM` does not touch flow agents.

### `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` (MODIFY — 3/5)
```python
# occurrences: 1 (verified: grep -c '        self._nodes\[node.node_id\] = node' flow.py)
# AFTER — insert below `        self._nodes[node.node_id] = node` (verified: flow.py:419)
        if isinstance(node, AgentNode):
            _apply_flow_defaults(node.agent)
```

### `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` (MODIFY — 4/5)
```python
# occurrences: 1 (verified: grep -c '            resolved_agents\[node_def.id\] = agent' flow.py)
# BEFORE — insert above `            resolved_agents[node_def.id] = agent` (verified: flow.py:639)
            _apply_flow_defaults(agent)
```
```python
# occurrences: 1 (verified: grep -c '                group\[ref\] = agent' flow.py)
# BEFORE — insert above `                group[ref] = agent` (verified: flow.py:664)
                _apply_flow_defaults(agent)
```

### `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` (MODIFY — 5/5)
```python
# occurrences: 1 (verified: grep -c '    async def run_flow(' flow.py)
# BEFORE — insert directly above `    async def run_flow(` (verified: flow.py:1226)
    @_flow_usage_scope
```

### `packages/ai-parrot/tests/bots/flows/test_flow_default_key.py` (CREATE)
```python
"""FEAT-882 — AgentsFlow FLOW_* defaults for unconfigured agents and the FLOW usage tag."""

import pytest

from parrot import llm_defaults as ld
from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flows.flow import flow as flow_module
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.clients import factory


class _StubAgent:
    """Constructed-but-unconfigured AbstractBot stand-in (attributes the FLOW path reads)."""

    _default_llm = "google"

    def __init__(self, name: str, llm=None, llm_kwargs=None, configured: bool = False):
        self.name = name
        self._llm_raw = llm
        self._llm_model_explicit = False
        self._model_config = {}
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.is_configured = configured

    async def invoke(self, prompt, **kwargs):
        return "ok"

    async def ask(self, question="", **kwargs):
        return type("R", (), {"content": "ok"})()


class _Registry:
    def __init__(self, agents):
        self._agents = agents

    def get_bot_instance(self, name):
        return self._agents.get(name)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    values: dict[str, str] = {}
    monkeypatch.setattr(ld.config, "get", lambda key, fallback=None: values.get(key, fallback))
    monkeypatch.setattr(ld.conf, "DEFAULT_LLM", None, raising=False)
    monkeypatch.setattr(factory, "SUPPORTED_CLIENTS", {"google": object(), "openai": object()})
    monkeypatch.setattr(flow_module, "_flow_skip_logged", set())
    return values


# FILL IN: tests from the Test Specification — bounded by AC1-AC6 of this task; build definitions like
#   tests/bots/flows/test_from_definition.py:_make_linear_def (start -> agent nodes) and decision
#   groups via NodeDefinition(type="decision", config={"agent_refs": [...]}) only if that node type
#   validates offline; otherwise cover the group path with a direct _apply_flow_defaults call.
```

### FILL IN checklist
- [ ] `_apply_flow_defaults` FLOW_LLM step — G4/AC1, provider/model consistency.
- [ ] Test bodies — AC1–AC6.

---

## Acceptance Criteria

- [ ] AC1: no `FLOW_*` set (even with `DEFAULT_LLM` set) -> agents untouched by `from_definition` / `add_node`.
- [ ] AC2: unconfigured Google agent without credential receives `FLOW_GOOGLE_API_KEY` via `from_definition` (single node and decision-group member) and via `add_node(AgentNode(...))`; the original `llm_kwargs` dict object is not mutated.
- [ ] AC3: `FLOW_LLM=openai:gpt-x` sets `_llm_raw` only on agents with no llm/model/model_config; then `FLOW_OPENAI_API_KEY` is the injected key.
- [ ] AC4: configured agents are not touched; exactly one INFO record per agent name across repeated flows.
- [ ] AC5: inside `run_flow`, `parrot.observability.context.current_component.get() == "FLOW"` (assert from a stub agent's `ask`/`invoke`); outside it, the previous value is restored.
- [ ] AC6: existing `tests/bots/flows/test_from_definition.py` still passes (non-AbstractBot `FakeAgent` stubs).
- [ ] No key value in captured logs; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/flows/test_flow_default_key.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/test_from_definition.py -q`

---

## Test Specification

```python
def test_flow_from_definition_injects_flow_key(env): ...
def test_flow_from_definition_injects_decision_group_members(env): ...
def test_flow_add_node_injects_flow_key(env): ...
def test_flow_explicit_credential_not_overridden(env): ...
def test_flow_llm_applied_only_when_set_and_undeclared(env, monkeypatch): ...   # DEFAULT_LLM alone -> no change
def test_flow_configured_agent_not_injected_and_logged_once(env, caplog): ...
def test_flow_malformed_flow_llm_raises(env): ...
async def test_flow_run_tags_usage_component(env): ...
```

---

## Agent Instructions

1. Work in the feature worktree; TASK-5548 must be `done` in the per-spec index.
2. Re-run every anchor `grep -c` above; set the task `in-progress`.
3. Implement from the blueprint; complete every `# FILL IN:`; run the Validation Commands.
4. Commit only the listed files; `parrot sdd task close TASK-5550 per-agent-env-llm-credentials verified`; fill the Completion Note.

---

## Completion Note


- Task: TASK-5550
- Feature: per-agent-env-llm-credentials
- Implementation SHA: fda6a81904c982ca303ee41a7f21f40df97c8de8
- Closed at (UTC): 2026-11-12T19:31:33+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 288s · Tokens: n/a |
