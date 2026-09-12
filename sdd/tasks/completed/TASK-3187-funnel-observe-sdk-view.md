# TASK-3187: Keep the ordinary SDK client view in the budgeted funnel under observe mode

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3185, TASK-3186
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (third file) and the resolution of §10 R2. The budgeted funnel
swaps in a no-retry SDK view — `self.client.with_options(max_retries=0)`
(`openai_base.py:349`) — so that each *physical* request gets its own
reservation. The ordinary funnel keeps the SDK default of 2 retries
(`openai/_constants.py:8`; `get_client` does not override it,
`openai_base.py:152`) under three tenacity attempts (`openai_base.py:273`).

Worst case the ordinary path makes nine physical requests and the budgeted path
three. A provider recovering on the fourth would succeed uninstrumented and fail
instrumented — instrumentation changing the outcome it measures.

Per-physical-attempt exactness only exists so enforcement can deny the right
request. Nothing can be denied in observe mode, so this task drops the swap
there and keeps it for enforcement.

---

## Scope

- In `_chat_completion_budgeted`, select the SDK view by mode: keep
  `with_options(max_retries=0)` when `scope.policy.enforcement == "enforce"`,
  use `self.client` unchanged when it is `"observe"`.
- Document the reasoning at the call site — this is a two-line change whose
  justification is the whole point.
- Write tests proving both regimes.

**NOT in scope**: the settle/uncertain logic (lines 396-406, unchanged and
already correct for both modes), `_budgeted_stream`, `_finalize_budgeted_chat`,
the tenacity policy (`stop_after_attempt(3)` stays in both modes), and the
ordinary non-budgeted funnel.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/openai_base.py` | MODIFY | Mode-selected SDK view |
| `packages/ai-parrot/tests/unit/clients/test_token_budget.py` | MODIFY | Retry-regime tests for both modes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .budget_scope import current_budget_scope, TOKEN_BUDGET_STATE_KEY  # verified: parrot/clients/openai_base.py:58
```
Already imported in the module — add nothing.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/openai_base.py
budget_adapter_factory: Callable[[], Any] | None = None               # line 99 (class attribute, base default)
async def _chat_completion(self, model, messages, use_tools=False,
                           stream=False, **kwargs) -> Any:            # line 228
    _scope = current_budget_scope()                                   # line 262
    if _scope is not None and self.budget_adapter_factory is not None:  # line 263
        return await self._chat_completion_budgeted(...)              # line 264
    #   ordinary funnel below: AsyncRetrying(stop=stop_after_attempt(3))  # line 273
async def _chat_completion_budgeted(self, scope, *, model, messages,
                                    use_tools, stream, **kwargs) -> Any:  # line 334
    adapter = self.budget_adapter_factory()                           # line 340
    cap_key = "max_completion_tokens" if "max_completion_tokens" in kwargs else "max_tokens"  # line 346
    max_out = kwargs.get(cap_key) or self._resolve_max_tokens(None)   # line 347
    view = self.client.with_options(max_retries=0)                    # line 349
    stop_strategy = stop_after_attempt(1) if ctx.get("single_attempt") else stop_after_attempt(3)  # line 364
    #   estimate = await adapter.count_input(body, route=..., mode=scope.policy.budget_mode, ...)  # line 376
    #   reservation = await scope.ledger.reserve(estimate, max_output_tokens=max_out, ...)  # line 380
    kwargs[cap_key] = reservation.output_cap                          # line 388
    #   except Exception: await scope.ledger.mark_uncertain(..., "dispatch_failed"); raise  # lines 390-393
    #   settle-from-usage block, unchanged by this task                # lines 396-406

def get_client(self):
    return AsyncOpenAI(api_key=..., base_url=..., timeout=self._timeout)  # line 152 — no max_retries

# packages/ai-parrot/src/parrot/clients/budget_scope.py
class BudgetScope:
    @property
    def policy(self) -> TokenBudgetPolicy: ...                        # line 59
```

### Does NOT Exist
- ~~`self.client.with_options(max_retries=2)`~~ — do NOT re-assert the default by hand;
  use `self.client` unchanged so whatever the SDK/user configured stays in force.
- ~~`scope.enforcement`~~ — the flag lives on `scope.policy.enforcement`.
- ~~`AbstractClient.max_retries`~~ — not an attribute of the parrot client.
- ~~A per-request retry count on `BudgetReservation`~~ — reservations do not track
  physical HTTP attempts; `attempt_number` counts *tenacity* attempts only.

---

## Implementation Notes

### Key Constraints
- The tenacity policy stays `stop_after_attempt(3)` in both modes. Only the SDK
  view changes.
- In observe mode one reservation may now cover several physical HTTP requests
  (the SDK's internal retries). That is correct and intended: failed requests
  are not billed and report no usage, and nothing is being denied. Say so in the
  docstring so a future reader does not "fix" it.
- `view` is used further down the method; keep the variable name so the rest of
  the body is untouched.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/openai_base.py:268-280` — the ordinary
  funnel, i.e. exactly the regime observe mode must match.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the unconditional `view = ...` assignment with a mode-selected one — *why*: the no-retry view is an enforcement requirement, not a budgeting requirement, and applying it to observation is what changes run outcomes.
2. Keep the variable named `view` — *why*: lines below (the `method = ...` selection and the retry loop) already read it; renaming would widen the diff for nothing.
3. Add both retry-regime tests — *why*: AC-4 is the reason this task exists and cannot be verified by reading.

### `packages/ai-parrot/src/parrot/clients/openai_base.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        view = self.client.with_options(max_retries=0)' packages/ai-parrot/src/parrot/clients/openai_base.py)
# REPLACE the line `        view = self.client.with_options(max_retries=0)  # request-local; shares transport, never closed here (spec §2.4)` (verified: packages/ai-parrot/src/parrot/clients/openai_base.py:349)
        # Enforcement reserves per PHYSICAL request, so it must see every one:
        # `max_retries=0` hands the SDK's retries up to the tenacity loop above.
        # Observation cannot deny anything, so that exactness buys nothing and
        # would cost the run its retry budget — the ordinary funnel allows up to
        # 3 tenacity x 3 SDK attempts (openai_base.py:273, SDK
        # DEFAULT_MAX_RETRIES=2), the no-retry view only 3. A provider that
        # recovers on the 4th physical request would then succeed uninstrumented
        # and fail instrumented (spec §10 R2). In observe mode one reservation
        # may therefore cover several physical requests; that is intended —
        # failed requests are not billed and report no usage.
        view = (
            self.client
            if scope.policy.enforcement == "observe"
            else self.client.with_options(max_retries=0)  # request-local; shares transport, never closed here (spec §2.4)
        )
```
**Why this shape**: A conditional at the single point where the view is chosen, rather than a second code path through the method — everything downstream (cap assignment, reserve, settle, uncertain) is identical in both modes and must stay that way. `self.client` is used bare rather than `with_options(max_retries=2)` so an operator who configured a different retry count keeps it.

### FILL IN checklist
*(none — fully determined)*

---

## Acceptance Criteria

- [ ] With `enforcement="observe"`, `_chat_completion_budgeted` does not call `with_options` at all (assert with a fake client that records calls).
- [ ] With `enforcement="enforce"`, `with_options(max_retries=0)` is still called exactly once per budgeted call.
- [ ] A fake client that raises a retryable `APIError` on its first two physical calls and succeeds on the third returns the same result with `enforcement="observe"` as with no scope bound at all.
- [ ] The settle/uncertain behaviour is unchanged in both modes (existing tests untouched).
- [ ] AC-23 holds: `pytest packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py packages/ai-parrot/tests/integration/test_question_token_budget.py -q`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/openai_base.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_token_budget.py  (append)
import pytest


class _RecordingClient:
    """Minimal OpenAI-shaped double that records `with_options` calls."""

    def __init__(self) -> None:
        self.with_options_calls: list[dict] = []
        # FILL IN: expose `.chat.completions.create` / `.parse` returning an
        # object with `.usage.prompt_tokens/.completion_tokens` — bounded by what
        # `_chat_completion_budgeted` reads at openai_base.py:396-401

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        return self


class TestObserveRetryRegime:
    async def test_observe_does_not_swap_the_view(self):
        # FILL IN: bind an observe scope, call the funnel, assert
        # client.with_options_calls == [] — bounded by AC "does not call
        # with_options at all"
        raise NotImplementedError

    async def test_enforce_still_swaps_the_view(self):
        # FILL IN: same with enforcement="enforce"; assert
        # [{"max_retries": 0}] — bounded by AC "still called exactly once"
        raise NotImplementedError

    async def test_transient_failure_recovers_identically(self):
        # FILL IN: a client failing twice with a retryable APIError then
        # succeeding; assert the observed result equals the unscoped result
        # — bounded by AC-4 (spec §10 R2)
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 1 and §10 R2.
2. **Check dependencies** — TASK-3185 and TASK-3186 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm line 349 still reads as quoted before replacing it.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; touch nothing below line 349 in that method.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3187-funnel-observe-sdk-view.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (gemini seat) via parrot-sdd-coder orchestrator; 7 test-setup bugs in the coder's own new test class repaired by sdd-worker
**Date**: 2026-09-12
**Notes**: `_chat_completion_budgeted` now selects `self.client` (ordinary
SDK view, default retries) under `enforcement="observe"` and
`self.client.with_options(max_retries=0)` under `enforcement="enforce"`
(unchanged). Verification found the new `TestObserveRetryRegime` class
(3 tests) failed for 7 distinct test-authoring reasons — none in
`openai_base.py` itself: a nonexistent `BudgetScope(policy=...)`
constructor kwarg, a `BudgetReservation` built with fields from an
earlier draft (`input_estimate`/`total`/`state`) instead of the real
`operation_id`/`input_allowance`/`request_fingerprint`, a forbidden
direct `client_instance.client =` assignment (loop-local property),
an `APIError(response=...)` kwarg the SDK doesn't accept, a
`tenacity.nap_ops` monkeypatch target that never existed, only `.create`
overridden while the funnel prefers `.parse`, and `ledger.mark_uncertain`
never mocked as async. All fixed test-side only; the production diff is
untouched. All 37 tests in `test_token_budget.py` pass, plus both
FEAT-550 regression suites; `ruff check` clean.

**Deviations from spec**: none (test-only fixups, see note above)

Seat: gemini · Backend: google-compat · Model: gemini-3.5-flash · Attempts: 1 · Duration: 132.8s · Tokens: 1929674/5408
