# TASK-3457: End-to-end test — a handler-built Google agent's client uses `CREW_AI_KEY`

**Feature**: FEAT-575 — AgentCrew Handler Default Google Key (`CREW_AI_KEY`)
**Spec**: `sdd/specs/agentcrew-handler-default-key.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3456
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests. Every unit test in this feature stops at
`agent._llm_kwargs["api_key"]`. None of them proves the claim that actually matters:
that the injected kwarg survives `AbstractBot.configure()`'s LLM resolution chain and
lands on the constructed Google client as `api_key`.

That chain is three hops in code this feature deliberately does NOT modify:
`configure()` → `_resolve_llm_config(**self._llm_kwargs)` → `_apply_llm_params`
(`config.extra.update(kwargs)`) → `_create_llm_client` (`**config.extra`) →
`GoogleGenAIClient.__init__` (`kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))`).

This task is the single test that closes that gap. It is the only direct proof of AC1
end-to-end, and the regression guard if `abstract.py`'s kwargs plumbing ever changes.

---

## Scope

- Write `test_handler_built_google_agent_client_uses_crew_key`: build a crew through
  `CrewHandler._create_crew_from_definition` with a Google agent, `configure()` that
  agent with the Google SDK's network client mocked, and assert the constructed
  client's `api_key` equals `CREW_AI_KEY` — not `GOOGLE_API_KEY`.
- Write the negative counterpart: with `CREW_AI_KEY` unset, the client falls back to
  `GOOGLE_API_KEY`.

**NOT in scope**:
- Any production-code change. This task is tests only. If the test fails, the bug is
  in TASK-3451..3456 — report it, do not patch around it here.
- Real network calls or a real Gemini key.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_crew_google_key_integration.py` | CREATE | End-to-end credential-plumbing test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.handlers.crew.handler import CrewHandler            # verified: handler.py:26
from parrot.models.crew_definition import AgentDefinition, CrewDefinition
#   verified: crew_definition.py:31, :178
from parrot.bots.agent import BasicAgent   # VERIFY the exact path before use:
#   crew.py:56 imports it as `from ...agent import BasicAgent` relative to
#   parrot/bots/flows/crew/, i.e. parrot.bots.agent
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/abstract.py — the chain under test, UNMODIFIED
class AbstractBot:
    _default_llm: str = "google"                                # line 220
    self._llm_raw = llm                                         # line 452
    self._llm_kwargs = kwargs.get("llm_kwargs", {})             # line 516
    # configure():
    config = self._resolve_llm_config(
        llm=self._llm_raw, model=model_arg, preset=self._llm_preset, **self._llm_kwargs
    )                                                            # lines 1537-1539
    def _apply_llm_params(self, config, preset=None, **kwargs) -> LLMConfig:
        config.extra.update(kwargs)                              # line 998
    def _create_llm_client(self, config: LLMConfig) -> AbstractClient:   # line 1002
        client = config.client_class(
            model=config.model, temperature=config.temperature,
            top_k=config.top_k, top_p=config.top_p,
            max_tokens=config.max_tokens, tool_manager=self.tool_manager,
            **config.extra,                                      # line 1032
        )

# packages/ai-parrot-client-google/src/parrot/clients/google/client.py
class GoogleGenAIClient(AbstractClient):                         # line 101
    client_name: str = "google"                                  # line 117
    self.api_key = kwargs.pop("api_key", config.get("GOOGLE_API_KEY"))  # line 189

# packages/ai-parrot/src/parrot/clients/factory.py
SUPPORTED_CLIENTS: Dict[str, Any] = _LazyClientRegistry()        # line 100

# packages/ai-parrot-server/src/parrot/handlers/crew/handler.py  (TASK-3456)
    async def _create_crew_from_definition(self, crew_def: CrewDefinition) -> AgentCrew:  # line 90
```

### Does NOT Exist

- ~~`packages/ai-parrot/src/parrot/clients/google/`~~ as source — the Google clients
  ship from the `ai-parrot-client-google` satellite. `pytest.importorskip` the module
  rather than assuming it is installed.
- ~~`GoogleGenAIClient.get_api_key()`~~ — the credential is the plain instance
  attribute `self.api_key` (client.py:189).
- ~~`AbstractBot.configure()` is synchronous~~ — it is `async`; the test must `await` it.
- ~~`config.extra` is a dict of only unknown kwargs~~ — `_apply_llm_params` pops the
  known ones (`temperature`, `max_tokens`, `top_k`, `top_p`) FIRST and merges the rest,
  so `api_key` is what reaches `**config.extra`. Do not assert on `extra`'s full shape.
- ~~a shared `packages/ai-parrot-server/tests/integration/conftest.py` fixture for
  crews~~ — unverified. Read the directory before assuming one exists.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/integration/test_crew_google_key_integration.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._create_llm_client",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot._apply_llm_params",
    "sym:packages/ai-parrot-server/src/parrot/handlers/crew/handler.py#CrewHandler._create_crew_from_definition"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Mock at the SDK boundary, not at `_create_llm_client`.** The point of this test is
  that the real `_resolve_llm_config` / `_apply_llm_params` / `_create_llm_client` chain
  runs. Patch whatever `GoogleGenAIClient.__init__` uses to reach the network (its
  `genai` client factory / `get_client()`), or patch only the
  `SUPPORTED_CLIENTS["google"]` entry with a subclass that records `api_key` and skips
  the network — never patch `_create_llm_client` itself, or the test proves nothing.
- **Assert on the client's `api_key`**, and additionally assert it is NOT the
  `GOOGLE_API_KEY` value (set both to distinct sentinels via monkeypatch) — the whole
  business case is that the two are separable.
- **No real key, no network.** Set both `parrot.conf.CREW_AI_KEY` and
  `parrot.conf.GOOGLE_API_KEY` to obvious test sentinels.
- If the satellite is not installed, `pytest.importorskip` — a missing optional backend
  must skip, never fail.

---

## Implementation Blueprint

### Steps (in order)
1. Read `packages/ai-parrot-server/tests/integration/` for existing conftest/fixtures — *why*: reuse beats hand-rolling, and this directory's conventions are unverified.
2. Build the crew through the real handler method — *why*: the unit tests already cover the injection; this test exists for the plumbing *after* it.
3. `await agent.configure()` with the SDK boundary mocked — *why*: that is the code path under test.
4. Assert `client.api_key == CREW_AI_KEY` and `!= GOOGLE_API_KEY` — *why*: AC1 plus the separability claim.
5. Add the unset-key counterpart — *why*: AC6 end-to-end.

### `packages/ai-parrot-server/tests/integration/test_crew_google_key_integration.py` (CREATE)
```python
"""End-to-end: a handler-built Google agent's client uses CREW_AI_KEY (FEAT-575, TASK-3457).

Unit tests stop at ``agent._llm_kwargs["api_key"]``. This module proves the kwarg
survives AbstractBot.configure()'s resolution chain and lands on the constructed
Google client — the three hops FEAT-575 deliberately does not modify.
"""
import pytest

from parrot.handlers.crew.handler import CrewHandler
from parrot.models.crew_definition import AgentDefinition, CrewDefinition

CREW_SENTINEL = "crew-key-sentinel"
GLOBAL_SENTINEL = "global-google-key-sentinel"


@pytest.fixture
def both_keys(monkeypatch):
    """Distinct sentinels for CREW_AI_KEY and GOOGLE_API_KEY, so they are separable."""
    monkeypatch.setattr("parrot.conf.CREW_AI_KEY", CREW_SENTINEL, raising=False)
    monkeypatch.setattr("parrot.conf.GOOGLE_API_KEY", GLOBAL_SENTINEL, raising=False)
    monkeypatch.setattr("parrot.bots.flows.crew.credentials._warned_unset", False, raising=False)


@pytest.mark.asyncio
async def test_handler_built_google_agent_client_uses_crew_key(both_keys, monkeypatch):
    # FILL IN (a): register a recording Google client in SUPPORTED_CLIENTS["google"] —
    # a subclass of the real GoogleGenAIClient (pytest.importorskip the satellite)
    # that records kwargs and does NOT open a network client. Do NOT patch
    # AbstractBot._create_llm_client — that is the code under test.
    # FILL IN (b): build a CrewDefinition with one Google agent declaring
    # llm="google:gemini-3.5-flash" and NO credential (read crew_definition.py:31-178
    # for the real required fields; extra="forbid").
    # FILL IN (c): drive CrewHandler._create_crew_from_definition with a stub self
    # (bot_manager.get_bot_class -> a real BasicAgent subclass, get_tool -> None).
    # FILL IN (d): await the Google agent's configure(), then assert the recorded
    # client api_key == CREW_SENTINEL and != GLOBAL_SENTINEL.
    # Bounded by AC1 and the spec §4 Integration Tests row.
    raise NotImplementedError


@pytest.mark.asyncio
async def test_handler_built_google_agent_falls_back_when_unset(monkeypatch):
    # FILL IN: same setup but with parrot.conf.CREW_AI_KEY unset — assert the
    # constructed client's api_key is the GOOGLE_API_KEY value, i.e. exactly
    # today's behaviour — bounded by AC6.
    raise NotImplementedError
```
**Why this shape**: two sentinels rather than one is what makes the assertion
meaningful — with a single value you cannot tell a working injection from an accidental
`GOOGLE_API_KEY` fallback. The agent must be a real `AbstractBot` subclass here (not the
stub used in the unit tests), because `configure()`'s chain is the thing under test.

### FILL IN checklist
- [ ] (a) recording Google client registered in `SUPPORTED_CLIENTS["google"]`, no network, `_create_llm_client` NOT patched; bounded by "mock at the SDK boundary"
- [ ] (b) `CrewDefinition` with real `AgentDefinition` fields; bounded by `extra="forbid"`
- [ ] (c) handler driven with a stub `self`; bounded by AC5
- [ ] (d) `api_key == CREW_SENTINEL` and `!= GLOBAL_SENTINEL`; bounded by AC1
- [ ] `test_handler_built_google_agent_falls_back_when_unset`; bounded by AC6

---

## Acceptance Criteria

- [ ] With `CREW_AI_KEY` set, the client constructed by a handler-built Google agent's `configure()` has `api_key == CREW_AI_KEY` and not `GOOGLE_API_KEY` (AC1).
- [ ] With `CREW_AI_KEY` unset, the same client falls back to `GOOGLE_API_KEY` (AC6).
- [ ] The test skips cleanly when `ai-parrot-client-google` is not installed.
- [ ] No real network call and no real credential is used.
- [ ] `AbstractBot._create_llm_client` is NOT patched by these tests.
- [ ] No linting errors: `ruff check packages/ai-parrot-server/tests/integration/test_crew_google_key_integration.py`

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/integration/test_crew_google_key_integration.py -q`

---

## Test Specification

The blueprint block IS the scaffold. This task adds no production code — if an
assertion fails, the defect is in TASK-3451..3456 and must be reported, not worked
around here.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3456 must be done (and transitively 3451..3453)
3. **Verify the Codebase Contract** — re-read `abstract.py:1537-1539`, `:998`, `:1025-1033` and `client.py:189`; these are the hops under test
4. **Update status** in `sdd/tasks/index/agentcrew-handler-default-key.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint block, complete every `# FILL IN:` marker
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-3457-crew-key-integration-test.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
