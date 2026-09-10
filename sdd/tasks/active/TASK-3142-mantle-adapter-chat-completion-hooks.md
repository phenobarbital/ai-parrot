# TASK-3142: `MantleBudgetAdapter`, Mantle Opt-In and Per-Attempt Hooks in `OpenAIBaseClient._chat_completion`

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3136, TASK-3139
**Assigned-to**: unassigned

---

## Context

Module 5 (spec §3 "Module 5: Mantle Adapter and Shared OpenAI-Compatible Loops"), half 1.
`BedrockMantleClient` is a thin `OpenAIBaseClient` subclass that overrides none of the
four text methods (verified `nova/mantle.py:35-142`). All wire calls funnel through
`OpenAIBaseClient._chat_completion` (`openai_base.py:216`), whose tenacity loop retries
physical SDK calls (`:252-266`). This task:

- appends `MantleBudgetAdapter` to the Amazon `budget.py` module (TASK-3139 owns the file
  first — spec §7 "M4 establishes Amazon adapter common code before M5");
- sets `budget_supported_methods` **only** on `BedrockMantleClient` (spec §1 non-goal:
  "OpenAI-compatible siblings do not become covered merely because they inherit the
  modified shared base");
- adds **guarded, inert-when-unbudgeted** per-attempt hooks inside `_chat_completion`:
  count the prepared wire body, reserve, dispatch on `self.client.with_options(max_retries=0)`,
  settle from the SDK response `.usage` (aggregate `prompt_tokens`/`completion_tokens`),
  each tenacity attempt reserving again; streams settle at the terminal usage chunk.

Finalization inside `_run_tool_call_loop` / the streaming loop / `resume` is TASK-3143.

---

## Scope

- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` — append
  `MantleBudgetAdapter` with the same three signatures as `BedrockBudgetAdapter`
  (`count_input(payload, *, route="chat_completions", mode)`, `normalize_usage(raw, *, route)`,
  `prepare_finalization(frame)`), `provider="bedrock-mantle"`:
  - counting fields: `messages`, `tools`, `response_format` (the **prepared wire body**,
    not a Python type — spec §3 M5), plus `model` in the fingerprint;
  - `normalize_usage` accepts an SDK object or dict: input = `prompt_tokens`, output =
    `completion_tokens` (both required, else `BudgetAccountingError`); `prompt_tokens_details.cached_tokens`
    and `completion_tokens_details.reasoning_tokens` go to `details` only — never re-added
    (spec §2.2 bullet 3; fixture 950/50 with cached 800 + reasoning 20 → 1000, not 1820);
  - `prepare_finalization`: drop `tools`/`tool_choice`; rewrite assistant `tool_calls` and
    `role: "tool"` messages into deterministic text (`[tool call <id>] name(args) -> result|UNEXECUTED`);
    keep `response_format`; append the `FINALIZATION_INSTRUCTION` user message;
  - strict mode: always `BudgetUnsupported` unless an injected registry matches
    (`route="chat_completions"`, `sdk_versions=installed_sdk_versions("openai")`).
- `packages/ai-parrot/src/parrot/clients/openai_base.py`:
  - class attribute `budget_adapter_factory: Optional[Callable[[], Any]] = None` (None →
    hooks inert even under a scope; the gate in `AbstractClient` already rejected
    unbudgeted providers, so this is defence in depth);
  - `_chat_completion(...)`: build the wire body `body = {"model": model, "messages": messages, **kwargs}`;
    if `current_budget_scope()` is `None` or `self.budget_adapter_factory is None` → existing
    behaviour byte-for-byte; else per tenacity attempt: `estimate = await adapter.count_input(body, route="chat_completions", mode=...)`,
    `reservation = await ledger.reserve(...)` with `max_output_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens") or self._resolve_max_tokens(None)`
    and `min_output_tokens=1`, forward `max_tokens=reservation.output_cap` (or `max_completion_tokens`
    if the caller used that key), dispatch on `self.client.with_options(max_retries=0).chat.completions.<create|parse>`,
    settle from `response.usage`; for `stream=True` return a wrapper async iterator that
    settles when a chunk carries `.usage` (snapshot) and marks uncertain in `finally` if none did;
  - a `_budget_call_context` ContextVar/attribute pair carrying `call_id` / `round_number` /
    `attempt_number` set by the public methods (TASK-3143 sets round numbers; this task sets
    `call_id` per `_chat_completion` invocation and increments `attempt_number` per tenacity attempt).
- `nova/mantle.py`: `budget_supported_methods = frozenset({"ask","ask_stream","resume","invoke"})`
  and `budget_adapter_factory = staticmethod(lambda: MantleBudgetAdapter())` (lazy import inside
  a small function to avoid a satellite import at core import time).
- Tests `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py`: "Mantle
  accounting" (dict + SDK-shaped usage; cache/reasoning subsets not re-added), "no sibling
  opt-in" (`OpenAIBaseClient.budget_supported_methods == frozenset()`, a sibling subclass under a
  budget → `BudgetUnsupported`), per-attempt reservation across tenacity retries, `with_options(max_retries=0)`
  used for budgeted attempts only, stream settle-at-usage / uncertain-when-missing.

**NOT in scope**: finalization / `_run_tool_call_loop` / `ask_stream` loop / `resume` (TASK-3143).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` | MODIFY | Append `MantleBudgetAdapter` |
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Guarded per-attempt hooks in `_chat_completion` |
| `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py` | MODIFY | Opt-in + adapter factory |
| `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py` | CREATE | Mantle accounting / hooks / no-sibling tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11.

### Verified Imports
```python
from parrot.clients.budget_scope import current_budget_scope                       # TASK-3134
from parrot.core.exceptions import BudgetAccountingError, BudgetUnsupported          # TASK-3132
from parrot.models.token_budget import BudgetUsage, TokenEstimate                    # TASK-3132
from .budget_qualifications import installed_sdk_versions, match_qualification, QualificationKey, STRICT_QUALIFICATIONS   # TASK-3139 (same package)
# openai_base.py already imports: json, time, uuid (:22-25), AsyncIterator/Callable (:26), Any/Sequence (:28),
#   tenacity AsyncRetrying/retry_if_exception_type/stop_after_attempt/wait_exponential (:30-36), CompletionUsage (:38-44), AbstractClient (:53)
# mantle.py imports: `from ...openai_base import OpenAIBaseClient` (:31), `from ..models import AmazonModel` (:32)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
class OpenAIBaseClient(AbstractClient):                                              # line 65
    _default_timeout: float = 60.0                                                   # line 87
    async def get_client(self) -> Any:  return AsyncOpenAI(api_key=..., base_url=..., timeout=self._timeout)   # line 120-144
    async def _chat_completion(self, model: str, messages: Any, use_tools: bool = False, stream: bool = False, **kwargs) -> Any:   # line 216
        from openai import APIConnectionError, APIError, RateLimitError               # line 250
        retry_policy = AsyncRetrying(retry=retry_if_exception_type((...)), wait=..., stop=stop_after_attempt(3), reraise=True)   # line 252-257 ← anchor (1 occurrence)
        if use_tools: method = self.client.chat.completions.create
        else: method = getattr(self.client.chat.completions, "parse", self.client.chat.completions.create)
        if stream: kwargs["stream"] = True
        async for attempt in retry_policy:                                            # line 264 ← anchor (1 occurrence)
            with attempt:
                return await method(model=model, messages=messages, **kwargs)
    @staticmethod def _extract_completion_usage(response_obj) -> tuple[CompletionUsage|None, dict|None]   # line 269 — uses CompletionUsage.from_openai(usage_obj) + usage_obj.model_dump()

# packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py
class BedrockMantleClient(OpenAIBaseClient):                                         # line 35
    client_type: str = "bedrock-mantle"; client_name: str = "bedrock-mantle"          # lines 87-88 ← anchor `    client_name: str = "bedrock-mantle"` (1 occurrence)
    _fallback_model: str | None = None                                               # line 101

# openai SDK 3.3.1 (installed): AsyncOpenAI.with_options(max_retries=0) returns a request-local client view sharing the parent's transport (spec §2.4) —
#   verify with `python -c "import inspect, openai; print(inspect.signature(openai.AsyncOpenAI.with_options))"`.
# Chat Completions usage shape: .prompt_tokens, .completion_tokens, .total_tokens, .prompt_tokens_details.cached_tokens, .completion_tokens_details.reasoning_tokens
```

### Does NOT Exist
- ~~`MantleBudgetAdapter`~~ — appended by this task to the TASK-3139 module.
- ~~`OpenAIBaseClient.budget_supported_methods` non-empty~~ — MUST stay `frozenset()`; only `BedrockMantleClient` opts in.
- ~~`self.client.max_retries = 0`~~ or ~~`AsyncOpenAI(max_retries=0)` for the shared client~~ — forbidden; use the request-local `with_options` view (spec §2.4).
- ~~closing the `with_options` view~~ — it shares the parent transport; never `await view.close()` (spec §2.4).
- ~~`response_format` as a Python class in the count~~ — count what `_build_response_format_from` produced (the wire dict).
- ~~`usage` present on every stream chunk~~ — only the terminal chunk (when `stream_options.include_usage` is set) carries it; treat as a snapshot; if absent → uncertain.

---

## Implementation Notes

### Pattern to Follow
```python
# _chat_completion, budgeted branch — each tenacity attempt is a new reservation (spec §2.4)
attempt_no = 0
async for attempt in retry_policy:
    with attempt:
        attempt_no += 1
        estimate = await adapter.count_input(body, route="chat_completions", mode=scope.policy.budget_mode)
        reservation = await scope.ledger.reserve(estimate, max_output_tokens=max_out, min_output_tokens=1,
                                                 call_id=call_id, round_number=round_no, attempt_number=attempt_no, phase=phase)
        kwargs[cap_key] = reservation.output_cap
        try:
            response = await budgeted_method(model=model, messages=messages, **kwargs)
        except Exception:
            await scope.ledger.mark_uncertain(reservation.reservation_id, "dispatch_failed")
            raise
        ...settle...
```

### Key Constraints
- **Inert when unbudgeted**: the first statement of the budgeted branch is the guard; the
  legacy path must remain textually intact below it (spec §3 M5 "shared hooks inert for
  unbudgeted calls"; AC "existing … regression tests pass with no budget configured").
- `budgeted_method`: `view = self.client.with_options(max_retries=0)`; `view.chat.completions.create`
  or `.parse` chosen by the same `use_tools`/`getattr` rule as today.
- Cap key: if `"max_completion_tokens" in kwargs` use it, else `"max_tokens"`. Never leave the
  cap unspecified once budgeted (spec §2.2).
- Settle: `usage_obj = getattr(response, "usage", None)`; `adapter.normalize_usage(usage_obj, route="chat_completions")`;
  on `BudgetAccountingError` → `mark_uncertain("missing_usage")`. For `.parse()` failures that
  raise before usage is accessible → `mark_uncertain("parse_failed_no_usage")` (spec §3 M5
  transport restriction).
- Stream wrapper: an `async def _budgeted_stream(inner, reservation, ledger, adapter)` generator
  that yields chunks, settles at the first chunk with `getattr(chunk, "usage", None)`, and in
  `finally` marks uncertain if never settled. Add `stream_options={"include_usage": True}` to
  `kwargs` when `stream=True` under a budget (harmless on Mantle; verify the endpoint accepts it —
  if a live smoke shows a 400, gate on a class attribute `_budget_stream_include_usage = True`
  that Mantle can flip).
- Attempt context: module-level `_BUDGET_CALL_CTX: ContextVar[dict]` in `openai_base.py` holding
  `{"call_id", "round_number", "phase"}`; `_chat_completion` reads it (defaults: fresh uuid, 1,
  "work"). TASK-3143 sets it from the loops. Keep it in `openai_base.py`, not `budget_scope.py`
  (provider-local concern).
- `BedrockMantleClient.budget_adapter_factory` must import `MantleBudgetAdapter` lazily:
  ```python
  @staticmethod
  def budget_adapter_factory():
      from ..budget import MantleBudgetAdapter
      return MantleBudgetAdapter()
  ```

### References in Codebase
- `openai_base.py:216-267` — the funnel to modify.
- `packages/ai-parrot/tests/clients/test_bedrock_mantle.py` — existing Mantle tests (must keep passing).

---

## Implementation Blueprint

### Steps (in order)
1. Append `MantleBudgetAdapter` to `amazon/budget.py` — *why*: adapter records first, then hooks.
2. Add `_BUDGET_CALL_CTX`, `budget_adapter_factory`, and the guarded branch in `_chat_completion` — *why*: single funnel = single hook site.
3. Opt in `BedrockMantleClient` — *why*: only Mantle is covered (spec §1 non-goals).
4. Tests with a fake `AsyncOpenAI`-shaped client (`with_options` returning a sibling fake, `chat.completions.create/parse` AsyncMocks).

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3139: grep -c '^__all__ = \["BedrockBudgetAdapter"' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py)
# BEFORE — insert above `__all__ = ["BedrockBudgetAdapter", ...]`; then add "MantleBudgetAdapter" to __all__
_CHAT_TOKEN_FIELDS = ("messages", "tools", "response_format")


class MantleBudgetAdapter:
    """Chat Completions (Bedrock Mantle) counting and usage normalization; estimated mode only until qualified (spec §3 M5)."""

    provider = "bedrock-mantle"

    def __init__(self, *, counter: Optional[TokenCounter] = None, method: Optional[str] = None) -> None:
        self.logger = logging.getLogger(__name__)
        if counter is None:
            counter, method = local_counter()
        self._counter, self._method = counter, method or "heuristic"

    async def count_input(
        self, payload: dict[str, Any], *, route: str = "chat_completions", mode: str = "estimated",
        registry: tuple[QualificationRecord, ...] = STRICT_QUALIFICATIONS, endpoint: str = "",
    ) -> TokenEstimate:
        """Count the prepared wire body (messages, tools, response_format) — never a Python type object."""
        body = {k: payload.get(k) for k in _CHAT_TOKEN_FIELDS if k in payload}
        fp = hashlib.sha256(f"{route}|{payload.get('model', '')}|{canonical_json(body)}".encode("utf-8")).hexdigest()
        if mode == "strict":
            key = QualificationKey(
                model=str(payload.get("model", "")), endpoint=endpoint, route=route, tools="tools" in payload,
                schema="response_format" in payload, cache=False, thinking=False, stream=bool(payload.get("stream")),
                sdk_versions=installed_sdk_versions("openai"), count_method="local_estimate", output_cap_semantics="max_tokens",
            )
            rec = match_qualification(key, registry=registry)
            if rec is None:
                raise BudgetUnsupported("Mantle Chat Completions has no strict qualification on the installed openai SDK")
            # FILL IN: exact path for injected registry (quality="exact", qualification_id=rec.qualification_id). Bounded by spec §2.5.
            raise NotImplementedError
        n = self._counter.count(canonical_json(body))
        return TokenEstimate(input_tokens=n, method=self._method, quality="estimated", request_fingerprint=fp)

    def normalize_usage(self, raw: Any, *, route: str = "chat_completions") -> BudgetUsage:
        """prompt_tokens/completion_tokens are complete aggregates; cached/reasoning details are retained, never re-added (spec §2.2)."""
        data = raw if isinstance(raw, dict) else (raw.model_dump() if hasattr(raw, "model_dump") else None)
        if not isinstance(data, dict) or data.get("prompt_tokens") is None or data.get("completion_tokens") is None:
            raise BudgetAccountingError("Chat Completions usage missing aggregate fields (unknown, never zero)")
        # FILL IN: negative/non-int guards; details = {"cached_tokens": (prompt_tokens_details or {}).get("cached_tokens"), "reasoning_tokens": ...}
        #          filtered to ints; return BudgetUsage(input_tokens=prompt, output_tokens=completion, details=..., provider=self.provider,
        #          model=str(data.get("model", "")), route=route). Bounded by spec §2.2 bullet 3.
        raise NotImplementedError

    def prepare_finalization(self, frame: dict[str, Any]) -> dict[str, Any]:
        """Drop tools/tool_choice, render tool protocol as text, keep response_format, append the finalization instruction."""
        payload = json.loads(canonical_json(frame["payload"]))
        payload.pop("tools", None)
        payload.pop("tool_choice", None)
        # FILL IN: rewrite messages — assistant with "tool_calls" -> content text listing each call; role "tool" -> user text
        #          "[tool result <tool_call_id>] <content>"; pending ids (frame["pending_tool_calls"]) -> UNEXECUTED; append
        #          {"role": "user", "content": FINALIZATION_INSTRUCTION}. Bounded by spec §2.3 finalization frame rules.
        raise NotImplementedError
```
**Why this shape**: same three signatures as `BedrockBudgetAdapter` (spec §3 M5); the Mantle key uses `installed_sdk_versions("openai")` so any SDK upgrade invalidates a qualification (spec §2.5 "SDK package versions").

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — imports/context)
```python
# occurrences: 1 (verified: grep -c '^from .base import AbstractClient' packages/ai-parrot/src/parrot/clients/openai_base.py)
# AFTER — insert below `from .base import AbstractClient` (verified: openai_base.py:53)
from contextvars import ContextVar
from .budget_scope import current_budget_scope
from ..core.exceptions import BudgetAccountingError

# FEAT-550: per-call attempt context set by the public loops (TASK-3143) and read by _chat_completion.
_BUDGET_CALL_CTX: ContextVar[dict[str, Any]] = ContextVar("parrot_openai_budget_call", default={})
```
```python
# occurrences: 1 (verified: grep -c '    _default_timeout: float = 60.0' packages/ai-parrot/src/parrot/clients/openai_base.py)
# AFTER — insert below `    _default_timeout: float = 60.0` (verified: openai_base.py:87)
    # FEAT-550: providers that honour question budgets supply an adapter factory; None keeps
    # the shared hooks inert (OpenAI-compatible siblings stay uncovered — spec §1 non-goals).
    budget_adapter_factory: Callable[[], Any] | None = None
```

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY — `_chat_completion` budgeted branch)
```python
# occurrences: 1 (verified: grep -c '        retry_policy = AsyncRetrying(' packages/ai-parrot/src/parrot/clients/openai_base.py)
# BEFORE — insert above `        retry_policy = AsyncRetrying(` (verified: openai_base.py:252)
        _scope = current_budget_scope()
        if _scope is not None and self.budget_adapter_factory is not None:
            return await self._chat_completion_budgeted(_scope, model=model, messages=messages, use_tools=use_tools, stream=stream, **kwargs)
```
```python
# occurrences: 1 (verified: grep -c '    def _extract_completion_usage(response_obj: Any) -> tuple:' packages/ai-parrot/src/parrot/clients/openai_base.py)
# BEFORE — insert above the `@staticmethod` decorating `_extract_completion_usage` (verified: openai_base.py:268-269)
    async def _chat_completion_budgeted(self, scope: Any, *, model: str, messages: Any, use_tools: bool, stream: bool, **kwargs) -> Any:
        """Budgeted funnel: reserve per physical attempt on a no-retry SDK view, settle from usage (FEAT-550 §2.2/§2.4)."""
        from openai import APIConnectionError, APIError, RateLimitError

        adapter = self.budget_adapter_factory()
        ctx = _BUDGET_CALL_CTX.get()
        call_id, round_no, phase = ctx.get("call_id") or str(uuid.uuid4()), ctx.get("round_number", 1), ctx.get("phase", "work")
        cap_key = "max_completion_tokens" if "max_completion_tokens" in kwargs else "max_tokens"
        max_out = kwargs.get(cap_key) or self._resolve_max_tokens(None)
        view = self.client.with_options(max_retries=0)  # request-local; shares transport, never closed here (spec §2.4)
        method = view.chat.completions.create if use_tools else getattr(view.chat.completions, "parse", view.chat.completions.create)
        if stream:
            kwargs["stream"] = True
            kwargs.setdefault("stream_options", {"include_usage": True})
        retry_policy = AsyncRetrying(
            retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIError)),
            wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3), reraise=True,
        )
        attempt_no = 0
        async for attempt in retry_policy:
            with attempt:
                attempt_no += 1
                body = {"model": model, "messages": messages, **kwargs}
                estimate = await adapter.count_input(body, route="chat_completions", mode=scope.policy.budget_mode, endpoint=str(self.base_url or ""))
                reservation = await scope.ledger.reserve(
                    estimate, max_output_tokens=max_out, min_output_tokens=1, call_id=call_id,
                    round_number=round_no, attempt_number=attempt_no, phase=phase,
                )
                kwargs[cap_key] = reservation.output_cap
                try:
                    response = await method(model=model, messages=messages, **kwargs)
                except Exception:
                    await scope.ledger.mark_uncertain(reservation.reservation_id, "dispatch_failed")
                    raise
                if stream:
                    return self._budgeted_stream(response, reservation, scope.ledger, adapter)
                # FILL IN: settle from getattr(response, "usage", None) via adapter.normalize_usage; BudgetAccountingError -> mark_uncertain("missing_usage").
                #          Bounded by spec §2.2 / §3 M5 "Reconcile raw usage before parsing where possible".
                return response

    async def _budgeted_stream(self, inner: Any, reservation: Any, ledger: Any, adapter: Any):
        """Yield chunks; settle once at the terminal usage snapshot; uncertain if it never arrives (spec §2.4)."""
        settled = False
        try:
            async for chunk in inner:
                usage = getattr(chunk, "usage", None)
                if usage is not None and not settled:
                    # FILL IN: settle via adapter.normalize_usage(usage); settled = True. Bounded by spec §2.4 "snapshots, not additive chunk deltas".
                    pass
                yield chunk
        finally:
            if not settled:
                await ledger.mark_uncertain(reservation.reservation_id, "missing_terminal_usage")
```
**Why this shape**: the guard is a two-condition `if` above the legacy code so unbudgeted behaviour is unchanged; the budgeted path reproduces the same retry predicates (spec §2.4 "Ordinary retries retain existing provider error predicates and attempt limits") but reserves per attempt.

### `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    client_name: str = "bedrock-mantle"' packages/ai-parrot-client-amazon/src/parrot/clients/amazon/nova/mantle.py)
# AFTER — insert below `    client_name: str = "bedrock-mantle"` (verified: mantle.py:88)
    # FEAT-550: Mantle opts in to cumulative question budgets (estimated mode; strict
    # refuses until a qualification exists — spec §2.5). Siblings stay uncovered.
    budget_supported_methods = frozenset({"ask", "ask_stream", "resume", "invoke"})

    @staticmethod
    def budget_adapter_factory():
        from ..budget import MantleBudgetAdapter  # lazy: keep import-time cost off the no-budget path
        return MantleBudgetAdapter()
```
**Why**: explicit opt-in on the concrete class only (spec §3 M5 "Enable capabilities only on Mantle").

### `packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py` (CREATE)
```python
"""FEAT-550 M5 — Mantle accounting, per-attempt hooks, no sibling opt-in (spec §4 rows)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.clients.amazon.budget import MantleBudgetAdapter
from parrot.clients.amazon.nova import BedrockMantleClient
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.core.exceptions import BudgetAccountingError, BudgetUnsupported

USAGE = {"prompt_tokens": 950, "completion_tokens": 50, "total_tokens": 1000,
         "prompt_tokens_details": {"cached_tokens": 800}, "completion_tokens_details": {"reasoning_tokens": 20}}


class TestMantleAccounting:
    def test_dict_and_sdk_shapes_not_readded(self):
        a = MantleBudgetAdapter()
        assert a.normalize_usage(USAGE).total_tokens == 1000
        sdk = SimpleNamespace(model_dump=lambda: USAGE)
        u = a.normalize_usage(sdk)
        assert u.total_tokens == 1000 and u.details.get("cached_tokens") == 800

    def test_missing_aggregate_unknown(self):
        with pytest.raises(BudgetAccountingError):
            MantleBudgetAdapter().normalize_usage({"completion_tokens": 1})

    async def test_strict_refused(self):
        with pytest.raises(BudgetUnsupported):
            await MantleBudgetAdapter().count_input({"model": "m", "messages": []}, mode="strict")


class TestNoSiblingOptIn:
    def test_base_and_siblings_uncovered(self):
        assert OpenAIBaseClient.budget_supported_methods == frozenset()
        assert OpenAIBaseClient.budget_adapter_factory is None
        assert BedrockMantleClient.budget_supported_methods == frozenset({"ask", "ask_stream", "resume", "invoke"})


def _fake_openai(create_side_effects):
    view = MagicMock()
    view.chat.completions.create = AsyncMock(side_effect=create_side_effects)
    view.chat.completions.parse = AsyncMock(side_effect=create_side_effects)
    root = MagicMock()
    root.with_options = MagicMock(return_value=view)
    root.chat.completions.create = AsyncMock(side_effect=AssertionError("shared client must not be used when budgeted"))
    return root, view


class TestChatCompletionHooks:
    async def test_each_tenacity_attempt_reserves_and_uses_no_retry_view(self):
        # FILL IN: BedrockMantleClient(api_key="k"); client.client = root; side effects [openai.APIConnectionError(...), response with .usage];
        #          under a root scope call client._chat_completion(model="m", messages=[...], max_tokens=100) ; assert root.with_options called
        #          with max_retries=0, view.create awaited twice, ledger report: 1 uncertain + 1 settled, forwarded max_tokens <= cap.
        raise NotImplementedError

    async def test_unbudgeted_path_untouched(self):
        # FILL IN: no scope -> root.chat.completions.create used (not with_options); with_options never called.
        raise NotImplementedError

    async def test_stream_settles_at_usage_or_uncertain(self):
        # FILL IN: two async-iterable fakes (with and without a usage-bearing terminal chunk). Bounded by spec §2.4.
        raise NotImplementedError
```
**Why**: spec §4 rows "Mantle accounting", "Unsupported providers … no sibling opt-in", "Streaming" (Mantle part), and the AC on hidden SDK retries.

### FILL IN checklist
- [ ] `budget.py::MantleBudgetAdapter.count_input` strict-exact / `normalize_usage` guards+details / `prepare_finalization` rewrite; bounded by spec §2.2-2.3
- [ ] `openai_base.py::_chat_completion_budgeted` settle branch; `_budgeted_stream` settle; bounded by spec §2.2/§2.4
- [ ] `test_token_budget_mantle.py` bodies

---

## Acceptance Criteria

- [ ] `from parrot.clients.amazon.budget import MantleBudgetAdapter` works; fixture 950/50 (+cached 800, reasoning 20) → total 1000, never 1820
- [ ] `OpenAIBaseClient.budget_supported_methods == frozenset()` and `budget_adapter_factory is None`; `BedrockMantleClient` opts in on all four
- [ ] Under a budget each tenacity attempt reserves anew; dispatch goes through `self.client.with_options(max_retries=0)`; the shared client's `create` is never called
- [ ] Forwarded `max_tokens`/`max_completion_tokens` equals the reservation cap
- [ ] Streams settle once at the usage-bearing chunk; missing usage → uncertain
- [ ] No scope → `_chat_completion` legacy path unchanged (`tests/clients/test_bedrock_mantle.py` and `tests/unit/clients` pass)
- [ ] `pytest packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py packages/ai-parrot/tests/clients/test_bedrock_mantle.py -q` passes

---

## Test Specification

Scaffold above. Add `test_response_format_counted_as_wire_dict` (payload with `response_format={"type":"json_schema",...}` changes the estimate vs. without) and `test_parse_failure_without_usage_marks_uncertain`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.2 bullet 3, §2.4, §2.5 Mantle row, §3 Module 5
2. **Check dependencies** — TASK-3136 and TASK-3139 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — `python -c "import inspect, openai; print(inspect.signature(openai.AsyncOpenAI.with_options))"` shows `max_retries`
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3142-mantle-adapter-chat-completion-hooks.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
