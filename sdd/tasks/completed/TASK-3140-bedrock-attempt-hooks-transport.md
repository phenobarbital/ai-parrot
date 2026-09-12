# TASK-3140: Bedrock Per-Attempt Reservation Hooks, No-Retry Transport and Suspension Envelope

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3136, TASK-3139
**Assigned-to**: unassigned

---

## Context

Module 4, client-integration half 1. `BedrockConverseBase` opts in
(`budget_supported_methods`), and **every physical attempt** through `_sdk_create`,
`_sdk_stream` and `_invoke_native` is admitted by the ledger before dispatch and
reconciled exactly once after (spec §2.2, §2.4). Budgeted requests use a **separate**
no-retry Runtime client (`BotoConfig(retries={"total_max_attempts": 1, "mode": "standard"})`)
kept alongside the existing per-loop cache, never mutating the shared client's adaptive
retry config (spec §2.4). Interrupt handlers merge the `token_budget` envelope into
`HumanInteractionInterrupt.state` (spec §2.6).

`NovaClient` inherits everything (spec §3 M4 "Nova text receives behavior through
existing inheritance"). Finalization/draining inside the loops is TASK-3141.

---

## Scope

- `bedrock.py` class `BedrockConverseBase`:
  - `budget_supported_methods = frozenset({"ask", "ask_stream", "resume", "invoke"})`;
  - `_budget_adapter: BedrockBudgetAdapter` created lazily (`_get_budget_adapter()`);
  - `_get_budgeted_client()` → per-loop no-retry client built by a new
    `_build_client(*, no_retry: bool)` that factors the body of `get_client()` and swaps
    the `BotoConfig`; cache in `self._budgeted_clients_by_loop: dict[int, Any]`; close
    them in `close()` via `super().close()` chaining (add an override that also
    `__aexit__`s the budgeted clients);
  - `_budgeted_attempt(payload, *, route, stream: bool, call_id, round_number, attempt_number, phase="work")`
    async context manager: if `current_budget_scope()` is `None` → yields
    `(self.client, None)` (pass-through); else counts via adapter, computes
    `max_output_tokens` from `payload["inferenceConfig"]["maxTokens"]` (Converse) or
    `body["max_tokens"]` (native), `min_output_tokens` = 1 or the model's thinking minimum
    when `additionalModelRequestFields.thinking` is set, calls `ledger.reserve(...)`,
    **lowers the payload's output cap to `reservation.output_cap`** (spec §2.2 "Always
    forward an explicit bounded output parameter"), yields `(budgeted_client, reservation)`;
    on exit: caller reports outcome via `reservation`-bound helpers `settle(raw_usage)`,
    `uncertain(reason)`, `release()` exposed on a small `_AttemptHandle`;
  - `_sdk_create(payload)` / `_sdk_stream(payload)` gain an optional `handle` argument
    (default `None`); when a handle is present they dispatch on `handle.client` instead of
    `self.client`;
  - `_invoke_native` wraps `invoke_model` in the same attempt protocol with `route="invoke_model"`;
  - in `ask`/`resume` loops: wrap `result = await self._sdk_create(payload)` calls with
    `_budgeted_attempt`; settle with `result.get("usage")`; on exception after dispatch
    → `uncertain("dispatch_failed")`; a fallback-model retry is a **new** attempt
    (`attempt_number += 1`, recount for the new `modelId`);
  - in `ask_stream`: reserve before `_sdk_stream`; settle at the `metadata` usage event
    (snapshot, not delta); missing terminal usage → `uncertain("missing_terminal_usage")`
    in the generator's `finally`;
  - the three `HumanInteractionInterrupt` sites (`e.agent_name = resolved_model`, 3
    occurrences) additionally set `e.state = {**(e.state or {}), TOKEN_BUDGET_STATE_KEY: await registry.suspend(scope)}`
    when a scope is live; `resume()` deep-copies `state["messages"]` before mutating.
- Tests (append to `test_token_budget_bedrock.py`): every physical attempt admitted
  (mock `_sdk_create`, assert reservations == SDK calls, including fallback retry),
  output cap lowered in the forwarded payload, uncertain on post-dispatch failure,
  streaming settle-at-metadata / uncertain-when-missing, no-retry config used for
  budgeted calls while an unbudgeted concurrent call still sees `"adaptive"`, Nova
  inherits, interrupt carries the envelope, no-budget path performs zero adapter calls.

**NOT in scope**: draining → finalization → report attachment → `stop_reason` (TASK-3141);
Mantle (TASK-3142/3143).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` | MODIFY | Opt-in, budgeted client, attempt hooks, envelope |
| `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py` | MODIFY | Append attempt/transport/stream/envelope tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11.

### Verified Imports
```python
from parrot.clients.budget_scope import current_budget_scope, get_default_registry, TOKEN_BUDGET_STATE_KEY   # TASK-3134
from parrot.core.exceptions import BudgetExhausted, BudgetAccountingError                                   # TASK-3132
from .budget import BedrockBudgetAdapter, fingerprint                                                       # TASK-3139
# bedrock.py already imports: json, time, uuid (:35-37), Any/AsyncIterator/Dict/List/Optional (:40), AbstractClient (:44),
#   CompletionUsage, ToolCall (:52), current_session_id/current_user_id (:43)
# botocore.config.Config is imported lazily as BotoConfig inside get_client (bedrock.py:302)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py
class BedrockConverseBase(AbstractClient):                                   # line 141
    _default_max_tokens: int = 4096                                          # line 161 ← anchor (1 occurrence) for the opt-in attribute
    def __init__(..., max_retries: int = 4, read_timeout: int = 120, ...)    # line 163
        self._max_retries = max_retries; self._read_timeout = read_timeout   # lines ~270-271
    async def get_client(self) -> Any                                        # line 289 — builds aioboto3 Session + client_kwargs with
        "config": BotoConfig(retries={"max_attempts": self._max_retries, "mode": "adaptive"}, read_timeout=self._read_timeout)   # line 308-309 ← anchor (1 occurrence)
        client_ctx = session.client("bedrock-runtime", **client_kwargs); return await client_ctx.__aenter__()   # lines 353-354
    async def _sdk_create(self, payload: dict) -> Dict[str, Any]:            # line 393 ← anchor (1 occurrence); body: return await self.client.converse(**payload)
    async def _sdk_stream(self, payload: dict) -> AsyncIterator[Dict[str, Any]]:   # line 397; body: response = await self.client.converse_stream(**payload); return response["stream"]
    async def _invoke_native(self, messages, model=None, max_tokens=None, temperature=0.0, system_prompt=None) -> Dict[str, Any]:   # line 661
        response = await self.client.invoke_model(modelId=..., body=json.dumps(body), ...)   # line 708 ← anchor (1 occurrence)
    async def ask(...)                                                        # line 723; loop `while True:` at 897; `result = await self._sdk_create(payload)` (4 occurrences in file: ask 901, ask fallback 912, resume 1454, invoke 1668)
    async def ask_stream(...)                                                 # line 1101; `stream = await self._sdk_stream(payload)` line 1231 (1 occurrence); usage at `if "metadata" in event: usage_dict = event["metadata"].get("usage", {})` line ~1265
    async def resume(self, session_id, user_input, state)                    # line 1374; messages from state (mutated in place today)
    async def invoke(...)                                                     # line 1607
    # HumanInteractionInterrupt sites: `e.agent_name = resolved_model` at lines 998, 1325, 1540 (3 occurrences) — each preceded by e.session_id / e.messages / e.tool_call_id assignments

# packages/ai-parrot/src/parrot/clients/base.py
    self._clients_by_loop: dict[int, _LoopClientEntry]; self._locks_by_loop: dict[int, asyncio.Lock]   # lines 372-375
    async def _ensure_client(self, **hints) -> Any                            # line 903
    async def close(self) -> None                                              # line 1213
    def _should_use_fallback(self, model, error) -> bool                       # line 1075
```

### Does NOT Exist
- ~~`BotoConfig(retries={"max_attempts": 1})` as "no retry"~~ — `max_attempts` counts *retries*; the spec mandates `retries={"total_max_attempts": 1, "mode": "standard"}` (accepted by botocore 1.35.36).
- ~~mutating `self.client.meta.config` or `self._max_retries` per call~~ — forbidden (spec §2.4 "do not mutate a shared SDK's retry settings while concurrent calls are running").
- ~~`self.client` swapped to the no-retry client~~ — budgeted attempts use the handle's client; `self.client` stays the shared one.
- ~~`event["metadata"]["usage"]` deltas~~ — Converse sends ONE metadata event with the round's usage; treat it as a snapshot (spec §2.4).
- ~~`state["messages"]` mutated in place in resume~~ — today it is (line ~1390); this task must `copy.deepcopy` first (spec §2.6).

---

## Implementation Notes

### Pattern to Follow
```python
# Every physical attempt: reserve → dispatch on the budgeted client → settle/uncertain/release exactly once
async with self._budgeted_attempt(payload, route="converse", stream=False, call_id=call_id, round_number=n, attempt_number=k) as handle:
    try:
        result = await self._sdk_create(payload, handle=handle)
    except Exception:
        await handle.uncertain("dispatch_failed")   # spec §2.4: an HTTP error is not proof of zero charge
        raise
    await handle.settle(result.get("usage"))
```

### Key Constraints
- `_AttemptHandle` (dataclass): `client`, `reservation | None`, `ledger | None`, `adapter`, `route`,
  `_done: bool`. `settle(raw)`: if no reservation → no-op; `usage = adapter.normalize_usage(raw, route=route)`
  → `ledger.settle(id, usage)`; on `BudgetAccountingError` from a missing usage → fall back to
  `ledger.mark_uncertain(id, "missing_usage")`. `uncertain(reason)`, `release()` guard `_done`.
  If the context exits without any resolution and no exception → `mark_uncertain("unresolved")`
  (never leave a reservation in flight).
- `call_id` per public-method invocation (`str(uuid.uuid4())` at method start), `round_number`
  from the existing `_lc_round_number`, `attempt_number` starts at 1 and increments for the
  fallback retry.
- Cap lowering: Converse `payload["inferenceConfig"]["maxTokens"] = reservation.output_cap`;
  native `body["max_tokens"] = reservation.output_cap`. Keep the original in the `min` (the
  ledger already does `min(M, A-I)`). If `output_cap < min_output_tokens`, the ledger raised
  `BudgetExhausted` — let it propagate (TASK-3141 handles draining).
- Thinking minimum: when `payload.get("additionalModelRequestFields", {}).get("thinking")`
  is present with `budget_tokens`, `min_output_tokens = budget_tokens + 1` — never send a
  reduced cap below the configured thinking budget (spec §2.2).
- Budgeted client lifecycle: `_budgeted_clients_by_loop[id(loop)]`; build under the same
  per-loop lock as `_ensure_client`; on `close()` call `await client.__aexit__(None, None, None)`
  for each, then clear (spec §2.4 "Its dedicated transport participates in ordinary client cleanup").
- Envelope: only when `current_budget_scope()` is not `None`; `registry = scope.registry`;
  `envelope = await registry.suspend(scope)`; `e.state = {**(getattr(e, "state", None) or {}), TOKEN_BUDGET_STATE_KEY: envelope}`.
- No budget: `_budgeted_attempt` must not touch the adapter, the registry or build the
  no-retry client (AC "No … ledger allocation … added to the no-budget path").

### References in Codebase
- `bedrock.py:897-935` — ask loop with fallback; the fallback branch's second `_sdk_create` is the second attempt.
- `bedrock.py:1231-1270` — stream loop; metadata event site.
- `packages/ai-parrot-client-amazon/tests/unit/test_bedrock_multiround_usage.py` — how `_sdk_create` is patched (`patch.object(client, "_sdk_create", side_effect=[...])`).

---

## Implementation Blueprint

### Steps (in order)
1. Opt-in attribute + adapter accessor + budgeted client factory/cache/cleanup — *why*: transport isolation must exist before any hook uses it.
2. `_AttemptHandle` + `_budgeted_attempt` — *why*: one protocol shared by all three dispatch seams.
3. Thread `handle` through `_sdk_create`/`_sdk_stream`; wrap `_invoke_native` — *why*: spec §3 M4 "Count/admit at `_sdk_create`, `_sdk_stream`, and native `_invoke_native`".
4. Wrap the four loop call sites (ask ×2, resume, invoke) and the stream site; add `finally` uncertain for streams.
5. Envelope at the three interrupt sites; deepcopy in `resume`.
6. Tests.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` (MODIFY — opt-in + imports)
```python
# occurrences: 1 (verified: grep -c 'from ...models.outputs import StructuredOutputConfig' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# AFTER — insert below `from ...models.outputs import StructuredOutputConfig` (verified: bedrock.py:55)
import copy
from contextlib import asynccontextmanager
from dataclasses import dataclass
from ...clients.budget_scope import TOKEN_BUDGET_STATE_KEY, current_budget_scope
from ...core.exceptions import BudgetAccountingError
from .budget import BedrockBudgetAdapter
```
```python
# occurrences: 1 (verified: grep -c '    _default_max_tokens: int = 4096' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# AFTER — insert below `    _default_max_tokens: int = 4096` (verified: bedrock.py:161)
    # FEAT-550: Bedrock Converse (and Nova text by inheritance) honours cumulative
    # question budgets on all four public text methods (spec §2.1 capability gate).
    budget_supported_methods = frozenset({"ask", "ask_stream", "resume", "invoke"})
```
**Why**: the gate in `AbstractClient._budget_gate` (TASK-3136) reads this attribute; `NovaClient(BedrockConverseBase, …)` inherits it.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` (MODIFY — budgeted transport)
```python
# occurrences: 1 (verified: grep -c 'retries={"max_attempts": self._max_retries, "mode": "adaptive"},' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# FILL IN: refactor get_client() (bedrock.py:289-354) into `async def _build_client(self, *, no_retry: bool = False) -> Any` whose only
#          difference is the retries dict: no_retry -> {"total_max_attempts": 1, "mode": "standard"}, else the existing adaptive dict.
#          get_client() becomes `return await self._build_client(no_retry=False)`. Bounded by spec §2.4 (no shared-config mutation).
```
```python
# occurrences: 1 (verified: grep -c '    async def _sdk_create(self, payload: dict) -> Dict\[str, Any\]:' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# BEFORE — insert above `    async def _sdk_create(self, payload: dict) -> Dict[str, Any]:` (verified: bedrock.py:393)
    def _get_budget_adapter(self) -> BedrockBudgetAdapter:
        """Lazily build the counting/normalization adapter (never on the no-budget path)."""
        adapter = getattr(self, "_budget_adapter", None)
        if adapter is None:
            adapter = self._budget_adapter = BedrockBudgetAdapter()
        return adapter

    async def _get_budgeted_client(self) -> Any:
        """Per-loop no-retry Runtime client for budgeted attempts (spec §2.4); cached alongside the shared client."""
        loop_id = id(asyncio.get_running_loop())
        cache = self.__dict__.setdefault("_budgeted_clients_by_loop", {})
        async with self._get_or_create_lock():
            client = cache.get(loop_id)
            if client is None:
                client = cache[loop_id] = await self._build_client(no_retry=True)
                self.logger.info("Bedrock: built no-retry budgeted client for loop %s", loop_id)
            return client

    @asynccontextmanager
    async def _budgeted_attempt(
        self, payload: Dict[str, Any], *, route: str, stream: bool, call_id: str, round_number: int, attempt_number: int, phase: str = "work",
    ):
        """Reserve → yield (client, handle) → guarantee exactly-once resolution (spec §2.2/§2.4)."""
        scope = current_budget_scope()
        if scope is None:
            yield _AttemptHandle(client=self.client)
            return
        adapter = self._get_budget_adapter()
        estimate = await adapter.count_input(payload, route=route, mode=scope.policy.budget_mode, endpoint=self._region)
        # FILL IN: max_output_tokens from payload["inferenceConfig"]["maxTokens"] (converse) or payload["max_tokens"] (invoke_model);
        #          min_output_tokens = thinking budget_tokens + 1 if configured else 1. Bounded by spec §2.2 "Model-specific reasoning minimums".
        reservation = await scope.ledger.reserve(
            estimate, max_output_tokens=max_output_tokens, min_output_tokens=min_output_tokens,
            call_id=call_id, round_number=round_number, attempt_number=attempt_number, phase=phase,
        )
        # FILL IN: lower the forwarded cap to reservation.output_cap in the right payload slot. Bounded by spec §2.2 "Always forward an explicit bounded output parameter".
        handle = _AttemptHandle(client=await self._get_budgeted_client(), reservation=reservation, ledger=scope.ledger, adapter=adapter, route=route)
        try:
            yield handle
        finally:
            if not handle.done:
                await handle.uncertain("unresolved")
```
```python
# module level, above `class _StaticBedrockTokenProvider:` (bedrock.py:113) — CREATE block
@dataclass
class _AttemptHandle:
    """Per-attempt resolution helper returned by BedrockConverseBase._budgeted_attempt."""

    client: Any
    reservation: Any = None
    ledger: Any = None
    adapter: Any = None
    route: str = "converse"
    done: bool = False

    async def settle(self, raw_usage: Any) -> None:
        if self.reservation is None or self.done:
            return
        self.done = True
        try:
            await self.ledger.settle(self.reservation.reservation_id, self.adapter.normalize_usage(raw_usage, route=self.route))
        except BudgetAccountingError:
            await self.ledger.mark_uncertain(self.reservation.reservation_id, "missing_or_malformed_usage")

    async def uncertain(self, reason: str) -> None:
        if self.reservation is None or self.done:
            return
        self.done = True
        await self.ledger.mark_uncertain(self.reservation.reservation_id, reason)

    async def release(self) -> None:
        if self.reservation is None or self.done:
            return
        self.done = True
        await self.ledger.release_unspent(self.reservation.reservation_id)
```
**Why**: the handle makes "resolve its state once" (spec §2.2) a local invariant; `finally → uncertain("unresolved")` covers generator close / cancellation (spec §2.4 "retain uncertain reservations on disconnect").

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py` (MODIFY — dispatch seams + loops)
```python
# REPLACE the two seam signatures/bodies (verified bedrock.py:393-395 and 397-405):
    async def _sdk_create(self, payload: dict, handle: Optional[_AttemptHandle] = None) -> Dict[str, Any]:
        """Dispatch a non-streaming ``converse()`` call (on the budgeted client when a handle is given)."""
        client = handle.client if handle is not None else self.client
        return await client.converse(**payload)

    async def _sdk_stream(self, payload: dict, handle: Optional[_AttemptHandle] = None) -> AsyncIterator[Dict[str, Any]]:
        client = handle.client if handle is not None else self.client
        response = await client.converse_stream(**payload)
        return response["stream"]
```
```python
# occurrences: 4 for `            result = await self._sdk_create(payload)` (ask:901, ask-fallback:912, resume:1454, invoke:1668)
# FILL IN: disambiguate each by its enclosing method; wrap each in the _budgeted_attempt pattern from "Pattern to Follow" above.
#          ask: call_id = str(uuid.uuid4()) before the while loop; attempt_number=1 for the first call, 2 for the fallback retry (recount happens
#          automatically because _budgeted_attempt counts the mutated payload with the new modelId). resume: same with its own call_id.
#          invoke: single attempt. Bounded by spec §2.4 "each physical attempt must reserve again".
```
```python
# occurrences: 1 (verified: grep -c '                stream = await self._sdk_stream(payload)' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# FILL IN: wrap the stream round (bedrock.py:1229-1268) — `async with self._budgeted_attempt(payload, route="converse", stream=True, ...) as _h:`
#          around `stream = await self._sdk_stream(payload, handle=_h)` and the `async for event in stream:` loop; at the `"metadata" in event`
#          branch call `await _h.settle(event["metadata"].get("usage"))`; the context's finally marks uncertain if no metadata arrived.
#          Bounded by spec §2.4 streaming paragraph.
```
```python
# occurrences: 1 (verified: grep -c '        response = await self.client.invoke_model(' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# FILL IN: in _invoke_native (bedrock.py:661-720) wrap the invoke_model call: route="invoke_model", payload=body (so count_input sees
#          "system"/"messages" and the cap slot is body["max_tokens"]); `response = await _h.client.invoke_model(...)`; after decoding
#          `await _h.settle(decoded.get("usage"))`. Bounded by spec §3 M4 "Guard the existing native text invoke_model fallback as well".
```
```python
# occurrences: 3 (verified: grep -c '                            e.agent_name = resolved_model' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py)
# FILL IN: disambiguate — apply to ALL THREE sites (ask ~998, ask_stream ~1325, resume ~1540); insert directly below each:
                            _scope = current_budget_scope()
                            if _scope is not None:
                                e.state = {**(getattr(e, "state", None) or {}), TOKEN_BUDGET_STATE_KEY: await _scope.registry.suspend(_scope)}
# Bounded by spec §2.6 "merge the new namespaced envelope" (never overwrite integration-owned state).
```
```python
# FILL IN: resume() (bedrock.py:1374-1400): replace the in-place use of state["messages"] with `bedrock_messages = copy.deepcopy(state["messages"])`.
#          Bounded by spec §2.6 "Resume deep-copies request state instead of mutating the stored message list".
```
**Why**: hooks sit exactly at the physical dispatch seams so tests that patch `_sdk_create` (existing suite) keep working — they now receive an extra `handle=` kwarg, so update `test_bedrock_multiround_usage.py` mocks to accept `**kwargs` if they fail.

### `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3139: grep -c 'class TestFinalizationPayload' packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py)
# AFTER — append at end of file
from unittest.mock import AsyncMock, patch  # noqa: E402
from parrot.clients.amazon.bedrock import BedrockConverseClient  # noqa: E402
from parrot.clients.amazon.nova import NovaClient  # noqa: E402
from parrot.clients.budget_scope import BudgetRegistry, current_budget_scope  # noqa: E402
from parrot.models.token_budget import TokenBudgetPolicy  # noqa: E402


def _final(usage, text="done"):
    return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "usage": usage}


class TestAttemptHooks:
    async def test_every_physical_attempt_reserved_including_fallback(self):
        # FILL IN: client = BedrockConverseClient(aws_access_key="k", aws_secret_key="s"); patch _get_budgeted_client -> AsyncMock client whose
        #          converse side_effect = [capacity error, _final({...})]; patch _should_use_fallback -> True; ask(..., token_budget=10_000);
        #          assert ledger report shows 2 attempts (1 uncertain, 1 settled) and the forwarded payload's maxTokens <= reservation cap.
        raise NotImplementedError

    async def test_no_budget_path_touches_nothing(self):
        # FILL IN: no token_budget -> _get_budget_adapter never called (patch it to raise), _sdk_create called with handle whose reservation is None.
        raise NotImplementedError

    async def test_stream_settles_at_metadata_and_uncertain_when_missing(self):
        # FILL IN: two fake streams — one with a metadata event (settled), one without (uncertain in report).
        raise NotImplementedError

    async def test_budgeted_client_is_no_retry_and_shared_stays_adaptive(self):
        # FILL IN: patch aioboto3.Session.client to capture config; build both clients; assert config.retries == {"total_max_attempts":1,"mode":"standard"}
        #          for the budgeted one and "adaptive" for the shared one. Bounded by spec §2.4.
        raise NotImplementedError

    async def test_nova_inherits_opt_in(self):
        assert NovaClient.budget_supported_methods == BedrockConverseClient.budget_supported_methods

    async def test_interrupt_carries_envelope_and_resume_deepcopies(self):
        # FILL IN: tool raises HumanInteractionInterrupt under a budget -> e.state["token_budget"]["operation_id"] == scope id;
        #          resume(state) leaves state["messages"] length unchanged. Bounded by spec §2.6.
        raise NotImplementedError
```
**Why**: spec §4 rows "Bedrock accounting … every physical attempt admitted", "Streaming", "Unknown outcomes" (provider part), plus AC on hidden SDK retries.

### FILL IN checklist
- [ ] `bedrock.py::_build_client` refactor; bounded by spec §2.4 BotoConfig literal
- [ ] `bedrock.py::_budgeted_attempt` — cap slots / thinking minimum; bounded by spec §2.2
- [ ] four `_sdk_create` sites + stream site + `_invoke_native`; bounded by spec §2.4
- [ ] three interrupt envelope sites + resume deepcopy; bounded by spec §2.6
- [ ] `close()` override closing `_budgeted_clients_by_loop`
- [ ] tests

---

## Acceptance Criteria

- [ ] `BedrockConverseBase.budget_supported_methods` covers all four methods; `NovaClient` inherits it
- [ ] Under a budget, reservations == physical SDK calls (fallback retry included); forwarded `maxTokens`/`max_tokens` never exceeds the reservation cap
- [ ] Post-dispatch exception → attempt marked uncertain; pre-dispatch (count/reserve) failure → no SDK call
- [ ] Stream: settled once at the metadata event; uncertain when it never arrives or the iterator is closed early
- [ ] Budgeted attempts use a client built with `retries={"total_max_attempts": 1, "mode": "standard"}`; the shared client's config is untouched; budgeted clients are closed by `close()`
- [ ] `HumanInteractionInterrupt.state["token_budget"]` carries the envelope under a budget; `resume()` no longer mutates `state["messages"]`
- [ ] No budget → adapter/registry/no-retry client never constructed
- [ ] `pytest packages/ai-parrot-client-amazon/tests/unit -q` passes (existing multiround/format-history tests included)

---

## Test Specification

Scaffold above. Add `test_native_invoke_model_guarded` (patch `invoke_model` on the budgeted client; assert one reservation with `route="invoke_model"` and body `max_tokens` lowered).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.2, §2.4, §2.6, §3 Module 4
2. **Check dependencies** — TASK-3136 and TASK-3139 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-run every `grep -c`; the 4× and 3× anchors MUST be handled site by site
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3140-bedrock-attempt-hooks-transport.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker orchestrator (parrot-sdd-coder pool: codex-spark CLI arg error on
attempt 1, qwen timed out on attempt 2 — no code produced by either; orchestrator implemented
directly as attempt 3, following the blueprint's disambiguated anchors precisely)
**Date**: 2026-09-11
**Notes**: Added `budget_supported_methods` opt-in, `_AttemptHandle` dataclass (settle/
uncertain/release, exactly-once via `done`), `_build_client(no_retry=...)` (refactored from
`get_client()`, swapping only the `BotoConfig.retries` dict — never mutating the shared
client's config), `_get_budget_adapter()`/`_get_budgeted_client()` (per-loop cache alongside
the shared client, same lock idiom as `_ensure_client`), `_budgeted_attempt` (pass-through
when no scope is live; counts, reserves, lowers the payload's output cap to
`reservation.output_cap`, computes the thinking-budget minimum when
`additionalModelRequestFields.thinking.budget_tokens` is set), and a `close()` override that
tears down every budgeted client alongside the shared one. Threaded `handle=` through
`_sdk_create`/`_sdk_stream`/`_invoke_native`, wrapped all four dispatch seams (`ask`'s primary
+ fallback attempts, `ask_stream`'s per-round stream, `resume`, `invoke`) in
`_budgeted_attempt`, merged the namespaced envelope at all three `HumanInteractionInterrupt`
sites, and replaced `resume()`'s shallow `list(state["messages"])` with `copy.deepcopy`.
Verification surfaced two things needing fixes of my own: (1) the signature change adds a
`handle=` kwarg to `_sdk_create`/`_sdk_stream`, which broke 8 EXISTING tests across
`test_bedrock_converse.py`, `test_bedrock_errors.py`, `test_bedrock_integration.py`,
`test_bedrock_thinking.py` and `test_nova.py` whose `side_effect` callables took a bare
`payload` argument — the task's own blueprint anticipated and authorized this ("update … mocks
to accept **kwargs if they fail"); added `handle=None` to each affected mock signature.
(2) A test-environment hazard: the shared venv's editable install for `ai-parrot-client-amazon`
currently resolves to THIS worktree even from the main repo checkout, making a naive
"run on dev to check pre-existing" comparison unreliable for this package — worked around by
git-showing the pre-TASK-3140 HEAD version of `bedrock.py` into place, confirming only 3
pre-existing unrelated failures remained, then restoring my changes and confirming the same 8
failures disappeared once the mock signatures were fixed.
Wrote the full `TestAttemptHooks` group (7 tests, including the required
`test_native_invoke_model_guarded` addition): fallback retry is two reservations (first
uncertain from the dispatch failure, second settled — a generous budget confirms the ledger's
"an HTTP error is not proof of zero charge" rule keeps the failed attempt's full reservation
debited); no-budget path never touches the adapter; stream settles once at the metadata event
and marks uncertain when it never arrives; the budgeted client's `BotoConfig.retries` differs
from the shared client's; `NovaClient` inherits the opt-in; a tool-raised
`HumanInteractionInterrupt` under a budget carries `state["token_budget"]["operation_id"]` and
`resume()` never mutates the caller's stored message list; and `_invoke_native` reserves once
with `route="invoke_model"` and lowers `body["max_tokens"]`.
Verified: `pytest packages/ai-parrot-client-amazon/tests/unit/test_token_budget_bedrock.py -v`
→ 16 passed; `pytest packages/ai-parrot-client-amazon/tests/unit -q` → 48 passed; broader sweep
across all Bedrock/Nova/Mantle client test files plus `packages/ai-parrot/tests/unit/clients`
→ 554 passed / 4 pre-existing unrelated failures (2 in `test_bedrock_inference_config.py`, 1 in
`test_factory_bedrock.py`, 1 in `test_folder_convention.py[google]` — all confirmed identical to
`dev`/pre-TASK-3140 HEAD); `ruff check` clean on `bedrock.py` and every touched test file.

**Deviations from spec**: none — fixed 8 pre-existing test mocks whose breakage the task's own
blueprint explicitly anticipated as a consequence of the mandated `handle=` signature change.

Seat: codex-spark (attempt 1, CLI `--ask-for-approval` arg incompatibility, 1.0s) → qwen
(attempt 2, timed out after 552.3s, no code produced) → sdd-worker orchestrator (attempt 3,
implemented directly) · Backend: codex → nova → orchestrator (Claude Sonnet 5) · Attempts: 2
(pool, both non-productive) + 1 (orchestrator) · Duration: 1.0s + 552.3s (pool) + orchestrator
implementation/test-authoring time · Tokens: pool attempts produced no billable output
(dispatch-level failures).
