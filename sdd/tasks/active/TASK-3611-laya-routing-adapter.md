# TASK-3611: Request-local routing — `choose_route` and `LayaEvaluationAgent`

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3605
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 3**. Laya answers a fixed choice question (`primary` / `cheap` /
`abstain`); `choose_route()` maps a *validated* result through the run's explicit model
allowlist (`primary_api_model`, `cheap_api_model`) and falls back to primary — with a distinct
reason — on abstention, invalid/missing output, error, or confidence below `routing_threshold`.
It never invents a model name (spec §2).

`LayaEvaluationAgent` is an evaluation-only `Agent` subclass: `ask_routed()` binds a
`RouteDecision` in a `ContextVar`, calls the inherited `ask`, and resets the var in `finally`;
`execute_llm_call()` copies the kwargs, injects `model=<selected>` and delegates to
`super().execute_llm_call` so budget propagation (FEAT-550) and client defaults are untouched.
An unbound decision leaves parent behaviour unchanged (spec §3 M3).

The isolation test builds the agent with `LayaEvaluationAgent.__new__` (no `__init__`) because
`BasicAgent.__init__` unconditionally instantiates a Google client (`agent.py:114-116`).

---

## Scope

- Create `artifacts/laya/routing.py`: `_DECISION: ContextVar[RouteDecision | None]`,
  `choose_route`, `LayaEvaluationAgent`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_routing.py` (spec §4 rows "Routing fallback", "Model isolation").

**NOT in scope**: the live pair runner and call cap (TASK-3613/3615); constructing a real
`AnthropicClient` (TASK-3616); any change under `packages/ai-parrot/src/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/routing.py` | CREATE | `choose_route` + `LayaEvaluationAgent` with ContextVar-scoped model injection |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_routing.py` | CREATE | Fallback reasons; ContextVar reset; copied kwargs; super reached; defaults unchanged |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
from parrot.bots.agent import Agent                 # verified: packages/ai-parrot/src/parrot/bots/agent.py:1325  (class Agent(BasicAgent))
from parrot.clients.base import AbstractClient      # verified: packages/ai-parrot/src/parrot/bots/abstract.py:35 (existing import)
from parrot.models.responses import AIMessage       # verified: packages/ai-parrot/src/parrot/models/responses.py:75
from parrot.models.basic import CompletionUsage     # verified: packages/ai-parrot/src/parrot/models/basic.py:48 (tests only)
from artifacts.laya.models import ROUTING_QUESTION_ID, EvaluationConfig, PredictionResult, RouteDecision  # TASK-3605
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py:1215
async def execute_llm_call(self, client: AbstractClient, method: str = "ask", **llm_kwargs: Any) -> Any:
    # designates the root budget owner and forwards budget_scope when the client's method accepts it,
    # then: return await getattr(client, method)(**llm_kwargs)          # line 1248
# packages/ai-parrot/src/parrot/bots/abstract.py:1202
def get_client(self) -> AbstractClient:        # returns self._llm
# packages/ai-parrot/src/parrot/bots/base.py:984  (Agent.ask is inherited from here; agent.py defines no ask)
async def ask(self, question: str, session_id=None, user_id=None, ..., use_vector_context: bool = True,
              use_conversation_history: bool = True, ..., use_tools: bool = True, **kwargs) -> AIMessage
#   max_tokens = kwargs.get("max_tokens", self._llm_kwargs.get("max_tokens"))                  # base.py:1137-1138
#   llm_kwargs = {"prompt", "system_prompt", "temperature", "history", "use_tools"} (+max_tokens) # base.py:1359-1365
#   response = await self.execute_llm_call(client, "ask", **llm_kwargs)                        # base.py:1395
#   -> the dispatch kwargs NEVER contain "model": injecting it here is the only per-call route.
# packages/ai-parrot/src/parrot/bots/agent.py:69-131  BasicAgent.__init__ imports and instantiates GoogleGenAIClient
#   unconditionally (lines 114-116) -> unit tests must NOT call __init__; use __new__ and set attributes.
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:470
async def ask(self, prompt: str, model: Union[Enum, str] = None, max_tokens: Optional[int] = None, ...) -> AIMessage
```

### Does NOT Exist
- ~~`Agent.ask(model=...)` as a per-call override~~ — `ask()` does not forward a caller `model` into the dispatch kwargs (spec §6).
- ~~`ClaudeModel.OPUS_5` / an `opus-5` alias~~ — `models.py:4-32` has OPUS_4_8 … OPUS_4_1 only; never map `anthropic:opus-5` to another family.
- ~~mutating `client.model` / `client.default_model`~~ — forbidden (spec §2 "never mutate client defaults").
- ~~`ModelSwitchingMixin` reuse~~ — different purpose (availability fallback); this adapter is a plain `Agent` subclass.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/routing.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_routing.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/agent.py#Agent",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.execute_llm_call",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.get_client",
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Fallback reasons are distinct literal prefixes so tests and reports can group them:
  `"error:<code>"`, `"invalid_answer"`, `"abstain"`, `"low_confidence:<conf>"`, `"cheap"`, `"primary"`.
- A bound decision whose `selected_model is None` in `execute_llm_call` raises `ValueError`
  ("invalid live configuration", spec §3 M3) — the CLI preflight (TASK-3613) prevents reaching this.
- Only `method == "ask"` gets the injection; other methods pass through unchanged.
- `ask_routed` forces `use_tools=False, use_vector_context=False, use_conversation_history=False`
  (spec §2 restriction) unless the caller passed them explicitly.

---

## Implementation Blueprint

### Steps (in order)
1. Write `choose_route` — *why*: pure function; every fallback branch is a spec §2 sentence.
2. Write the ContextVar + `LayaEvaluationAgent` — *why*: the hook must copy, inject, delegate; nothing else.
3. Write tests using `__new__`-built instances and a `FakeClient` — *why*: `BasicAgent.__init__` needs a Google client.
4. `git add -f` both files.

### `artifacts/laya/routing.py` (CREATE)
```python
"""Request-local model routing for the Laya evaluation (spec §3 Module 3)."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from parrot.bots.agent import Agent  # verified: packages/ai-parrot/src/parrot/bots/agent.py:1325
from parrot.clients.base import AbstractClient  # verified: packages/ai-parrot/src/parrot/bots/abstract.py:35
from parrot.models.responses import AIMessage  # verified: packages/ai-parrot/src/parrot/models/responses.py:75

from artifacts.laya.models import ROUTING_QUESTION_ID, EvaluationConfig, PredictionResult, RouteDecision

_DECISION: ContextVar[RouteDecision | None] = ContextVar("laya_route_decision", default=None)


def choose_route(result: PredictionResult, config: EvaluationConfig) -> RouteDecision:
    """Choose only a configured model; abstention/error/low confidence retains primary.

    ``selected_model`` is ``config.primary_api_model`` / ``config.cheap_api_model`` and stays
    ``None`` when the corresponding CLI input is absent — a model name is never invented.
    """
    primary = config.primary_api_model
    if result.status == "error":
        return RouteDecision(choice="primary", selected_model=primary, confidence=None, reason=f"error:{result.error_code}")
    answer = result.answers.get(ROUTING_QUESTION_ID)
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return RouteDecision(choice="primary", selected_model=primary, confidence=None, reason="invalid_answer")
    choice, confidence = answer.get("choice"), answer.get("confidence")
    # FILL IN: choice == "abstain" -> primary/"abstain"; confidence < config.routing_threshold -> primary/f"low_confidence:{confidence:.3f}";
    #          choice == "cheap" -> RouteDecision(choice="cheap", selected_model=config.cheap_api_model, confidence, reason="cheap");
    #          choice == "primary" -> primary/"primary"; anything else -> primary/"invalid_answer"
    #          — bounded by spec §2 "Abstention, missing/invalid output, timeout and confidence below the recorded routing threshold select primary"
    raise NotImplementedError


class LayaEvaluationAgent(Agent):
    """Evaluation-only Agent with a request-scoped downstream model decision."""

    async def ask_routed(self, question: str, decision: RouteDecision, **kwargs: Any) -> AIMessage:
        """Bind decision, call inherited ask, and reset its ContextVar even on cancellation."""
        kwargs.setdefault("use_tools", False)
        kwargs.setdefault("use_vector_context", False)
        kwargs.setdefault("use_conversation_history", False)
        token = _DECISION.set(decision)
        try:
            return await self.ask(question, **kwargs)
        finally:
            _DECISION.reset(token)

    async def execute_llm_call(self, client: AbstractClient, method: str = "ask", **llm_kwargs: Any) -> Any:
        """Inject the scoped model into copied ask kwargs and delegate through super."""
        decision = _DECISION.get()
        if decision is None or method != "ask":
            return await super().execute_llm_call(client, method, **llm_kwargs)
        if decision.selected_model is None:
            raise ValueError("bound RouteDecision has no selected_model: invalid live configuration (spec §3 M3)")
        scoped = dict(llm_kwargs)  # copy — never mutate the caller's dict or client defaults
        scoped["model"] = decision.selected_model
        self.logger.debug("routed call: choice=%s model=%s reason=%s", decision.choice, decision.selected_model, decision.reason)
        return await super().execute_llm_call(client, method, **scoped)
```
**Why this shape**: spec §2 — "copies kwargs, injects the selected model, and delegates to
`super().execute_llm_call`. Reset the ContextVar in `finally`; never mutate client defaults."
`super()` keeps `AbstractBot.execute_llm_call`'s budget-owner designation (abstract.py:1239-1247).

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_routing.py` (CREATE)
```python
"""FEAT-589 M3 — choose_route fallbacks and request-local model isolation at the dispatch hook."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

from artifacts.laya.models import ROUTING_QUESTION_ID, EvaluationConfig, PredictionResult, RouteDecision
from artifacts.laya.routing import _DECISION, LayaEvaluationAgent, choose_route


def _cfg(**kw) -> EvaluationConfig:
    base = dict(worker_python=Path("/bin/python3"), checkpoint_path=Path("/tmp/c"), checkpoint_revision="r",
                output_dir=Path("/tmp/o"), primary_api_model="claude-primary-id", cheap_api_model="claude-cheap-id")
    base.update(kw)
    return EvaluationConfig(**base)


def _res(choice: str, conf: float) -> PredictionResult:
    probs = {c: (1.0 if c == choice else 0.0) for c in ("primary", "cheap", "abstain")}
    return PredictionResult(request_id="r", status="ok",
                            answers={ROUTING_QUESTION_ID: {"type": "choice", "choice": choice, "probabilities": probs, "confidence": conf}})


@pytest.mark.parametrize("result, expected_choice, expected_model, reason_prefix", [
    (_res("cheap", 0.95), "cheap", "claude-cheap-id", "cheap"),
    (_res("primary", 0.95), "primary", "claude-primary-id", "primary"),
    (_res("abstain", 0.95), "primary", "claude-primary-id", "abstain"),
    (_res("cheap", 0.5), "primary", "claude-primary-id", "low_confidence"),
    (PredictionResult(request_id="r", status="error", error_code="inference_timeout", error_message="t"), "primary", "claude-primary-id", "error:inference_timeout"),
    (PredictionResult(request_id="r", status="ok", answers={}), "primary", "claude-primary-id", "invalid_answer"),
])
def test_choose_route_fallbacks_have_distinct_reasons(result, expected_choice, expected_model, reason_prefix):
    d = choose_route(result, _cfg())
    assert (d.choice, d.selected_model) == (expected_choice, expected_model) and d.reason.startswith(reason_prefix)


def test_choose_route_never_invents_a_model_without_cli_inputs():
    d = choose_route(_res("cheap", 0.99), _cfg(primary_api_model=None, cheap_api_model=None))
    assert d.choice == "cheap" and d.selected_model is None


class FakeClient:
    """AbstractClient-shaped stub recording every ask() kwargs dict (pattern: tests/bots/test_model_switching_mixin.py)."""

    def __init__(self):
        self.model = "client-default-model"
        self.calls: list[dict] = []

    async def ask(self, **kwargs):
        self.calls.append(kwargs)
        await asyncio.sleep(0)
        return AIMessage(input=kwargs.get("prompt", ""), output="ok", model=kwargs.get("model") or self.model, provider="fake",
                         usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


def _agent(client: FakeClient) -> LayaEvaluationAgent:
    agent = LayaEvaluationAgent.__new__(LayaEvaluationAgent)  # BasicAgent.__init__ instantiates a Google client — bypass it
    agent.logger = logging.getLogger("test")
    agent._llm = client
    agent.name = "laya-eval"
    return agent


async def test_unbound_decision_leaves_parent_behaviour_unchanged():
    client = FakeClient()
    await _agent(client).execute_llm_call(client, "ask", prompt="p", use_tools=False)
    assert "model" not in client.calls[0] and _DECISION.get() is None


async def test_bound_decision_injects_copy_and_reaches_super():
    client = FakeClient()
    original = {"prompt": "p", "use_tools": False}
    token = _DECISION.set(RouteDecision(choice="cheap", selected_model="claude-cheap-id", confidence=0.9, reason="cheap"))
    try:
        msg = await _agent(client).execute_llm_call(client, "ask", **original)
    finally:
        _DECISION.reset(token)
    assert client.calls[0]["model"] == "claude-cheap-id" and "model" not in original and msg.model == "claude-cheap-id"
    assert client.model == "client-default-model"


async def test_bound_decision_without_model_is_invalid_live_configuration():
    client = FakeClient()
    token = _DECISION.set(RouteDecision(choice="cheap", selected_model=None, confidence=0.9, reason="cheap"))
    try:
        with pytest.raises(ValueError):
            await _agent(client).execute_llm_call(client, "ask", prompt="p")
    finally:
        _DECISION.reset(token)


async def test_ask_routed_resets_contextvar_on_success_error_and_cancel():
    # FILL IN: monkeypatch agent.ask with (a) returning, (b) raising RuntimeError, (c) awaiting a cancelled sleep;
    #          after each, _DECISION.get() is None; (c) asserts CancelledError propagates — bounded by spec §4 "Model isolation"
    raise NotImplementedError


async def test_interleaved_scoped_calls_do_not_leak_models():
    # FILL IN: two tasks each set a different decision via ask_routed(agent.ask patched to call execute_llm_call with client);
    #          gather; assert each client call carries its own model — bounded by spec §3 M3 "request isolation at the hook"
    raise NotImplementedError
```
**Why**: spec §4 "Routing fallback" (distinct reasons) and "Model isolation" (reset on
success/error/cancel, copied kwargs, super reached, defaults unchanged).

### FILL IN checklist
- [ ] `routing.py::choose_route` branch ladder — abstain / low confidence / cheap / primary / invalid
- [ ] `test_laya_routing.py` — ContextVar reset triple; interleaved isolation

---

## Acceptance Criteria

- [ ] AC-1 — Six fallback shapes produce the six distinct reason prefixes and primary stays selected for all non-`cheap` outcomes.
- [ ] AC-2 — No CLI model inputs ⇒ `selected_model is None`, never a guessed identifier (spec §2).
- [ ] AC-3 — Unbound: dispatch kwargs unchanged. Bound: caller dict untouched, `model` injected on a copy, `client.model` unchanged, `AbstractBot.execute_llm_call` reached.
- [ ] AC-4 — ContextVar is `None` after success, error and cancellation of `ask_routed`.
- [ ] `ruff check artifacts/laya/routing.py` clean; no edits under `packages/ai-parrot/src/`.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_routing.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 routing paragraphs, §3 Module 3, §6 "Ask dispatch kwargs".
2. Confirm TASK-3605 is completed; re-verify `abstract.py:1215`, `base.py:1395` and `agent.py:114-116` with `grep -n`.
3. Implement from the Blueprint; run the Validation Command.
4. `git add -f` both files, commit, move this file, update the index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
