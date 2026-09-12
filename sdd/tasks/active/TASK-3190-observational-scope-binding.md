# TASK-3190: Bind one observational budget scope around the turn loop

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3185, TASK-3189
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. With the ledger able to observe (TASK-3186) and the funnel
keeping the ordinary client view (TASK-3187), this task opens ONE root scope
around the whole turn loop so that all 40-60 turns of a coding attempt land in a
single ledger — one attempt is one budgeted "question".

`OpenAIBaseClient._chat_completion` consults `current_budget_scope()` on every
wire call (`openai_base.py:262-264`), so binding the scope is the only wiring
needed: nothing in the loop changes. The ledger's report is then attached to the
telemetry TASK-3189 emits.

---

## Scope

- Add three settings to `parrot/conf.py`: `DEV_LOOP_CODER_TELEMETRY`,
  `DEV_LOOP_CODER_LEDGER`, `SDD_CODER_TELEMETRY_DIR`.
- Add `_observational_policy(profile)` to `LLMCodeDispatcher`.
- Wrap the turn loop in the root scope when enabled, and pass
  `(await scope.ledger.report()).model_dump()` into the terminal telemetry.
- Write tests for both switches and for scope identity across turns.

**NOT in scope**: the sink that consumes `SDD_CODER_TELEMETRY_DIR`
(TASK-3191/3193 — this task only declares the setting), the ledger semantics
(TASK-3186), the funnel branch (TASK-3187), and any ceiling validation — there
is deliberately no ceiling knob.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | Three settings |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `_observational_policy` + scope binding + report on telemetry |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | Switch + scope-identity tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.budget_scope import get_default_registry, current_budget_scope  # verified: parrot/clients/budget_scope.py:297,33
from parrot.models.token_budget import TokenBudgetPolicy                            # verified: parrot/models/token_budget.py:25
from parrot import conf                                                             # verified: parrot/flows/dev_loop/sdd_coder/roster.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/budget_scope.py
class BudgetRegistry:
    async def create(self, policy: TokenBudgetPolicy) -> BudgetScope: ...  # line 131
    #   raises BudgetRegistryFull when retained capacity is exhausted       # line 136
class BudgetScope:
    async def __aenter__(self) -> "BudgetScope": ...   # line 80 — binds the ContextVar
    async def __aexit__(self, exc_type, exc, tb) -> None: ...  # line 89 — closes the ledger on a root
    ledger: QuestionBudget                             # attribute set in __init__ (line 49)
def get_default_registry() -> BudgetRegistry: ...      # line 297

# packages/ai-parrot/src/parrot/clients/budget.py
async def report(self) -> BudgetReport: ...            # line 280

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py
client = self._create_client(profile, run_id=run_id)   # line 272
model = self._resolve_model(profile, client)           # line 274
try:                                                   # line 306  <-- the loop's try
    for turn_index in range(profile.max_turns):        # line 307

# packages/ai-parrot/src/parrot/flows/dev_loop/models/llm.py
class LLMCodeDispatchProfile(BaseModel):
    max_turns: int = Field(default=24, ge=1, le=100)   # line 23
    max_tokens: int = Field(default=8192, ge=256, le=32768)  # line 24

# packages/ai-parrot/src/parrot/conf.py
from navconfig import BASE_DIR, config                 # line 6
_wt: str = config.get("WORKTREE_BASE_PATH", fallback=str(BASE_DIR / ".claude/worktrees"))  # line 828
WORKTREE_BASE_PATH: str = os.path.normpath(_wt) if os.path.isabs(_wt) else os.path.normpath(str(BASE_DIR / _wt))  # line 829

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
ENV_LLM_MAX_TURNS: str = "DEV_LOOP_LLM_MAX_TURNS"      # line 133
DEFAULT_LLM_MAX_TURNS: int = 60                        # line 134 — the roster path's REAL turn budget
```

### Does NOT Exist
- ~~`DEV_LOOP_CODER_SHADOW_BUDGET`~~ — deliberately NOT added. Observational mode admits
  everything, so a ceiling knob would be decoration (spec §10 R1).
- ~~`LLMCodeDispatcher._min_safe_ceiling`~~ — removed from the design; no function of
  `max_turns`/`max_tokens` can bound input, salvage, retries or uncertain debits. Do not
  reintroduce it.
- ~~`conf.SDD_CODER_TELEMETRY_DIR` defaulting through `BASE_DIR`~~ — `BASE_DIR` comes from
  navconfig, which resolves a virtualenv's parent or an arbitrary override
  (`navconfig/project.py:129-161`), NOT the git main checkout. The default is the empty
  string; TASK-3191 resolves a durable root (spec §10 R7).
- ~~`BudgetScope.enforcement`~~ — read it from `scope.policy.enforcement`.

---

## Implementation Notes

### Key Constraints
- `final_answer_reserve=0` for the observational policy: an unenforced ledger
  never finalizes, so a protected partition would only distort the report's
  `remaining_*` fields. (The `2 × max_tokens` absolute reserve is the
  recommendation for the *enforcing* configuration the campaign later produces —
  see spec §7. Do not put it here.)
- `token_budget` is still required by `TokenBudgetPolicy` and must be a positive
  reference value so the report's `remaining_*` fields stay meaningful. It can
  never deny in this mode.
- `BudgetRegistryFull` must degrade, not fail: log once, run the attempt with no
  scope, and let the telemetry carry `budget_report=None`.
- The scope wraps the loop **including** the salvage call, so `async with` must
  enclose the existing `try:` at line 306, not sit inside it.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/base.py:1352-1357` — how `AbstractBot`
  binds a question scope around an LLM call; same shape, one level up.
- `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py:84` —
  `conf.config.get(key, fallback=...)`; use an injectable getter for tests.

---

## Implementation Blueprint

### Steps (in order)
1. Add the three settings to `conf.py` — *why*: every other dev-loop knob lives there and the dispatcher reads `conf.*`, so tests can monkeypatch one place.
2. Add `_observational_policy` as a static method — *why*: it encodes three decisions (observe, estimated, reserve=0) that must not be re-derived at the call site.
3. Wrap the loop — *why*: one scope per attempt is the semantic this whole feature rests on; a scope per turn would reset the ledger 60 times.
4. Thread the report into the telemetry call TASK-3189 added — *why*: the report is the calibration half of the dataset.
5. Add the tests — *why*: AC-1 (no scope when disabled) and AC-2 (one operation_id across turns) are the two things a reader cannot check.

### `packages/ai-parrot/src/parrot/conf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'WORKTREE_BASE_PATH: str = os.path.normpath(_wt)' packages/ai-parrot/src/parrot/conf.py)
# AFTER — insert below `WORKTREE_BASE_PATH: str = os.path.normpath(_wt) if os.path.isabs(_wt) else os.path.normpath(str(BASE_DIR / _wt))` (verified: packages/ai-parrot/src/parrot/conf.py:829)
# FEAT-554: sdd-coder token telemetry. Master switch: False means no budget
# scope is bound, no rows are written and no new payload is produced.
DEV_LOOP_CODER_TELEMETRY: bool = config.getboolean("DEV_LOOP_CODER_TELEMETRY", fallback=False)
# With telemetry on: bind the OBSERVATIONAL ledger (True) or record provider
# totals only (False). There is no ceiling setting — an observational ledger
# admits everything, so a number would be decoration. When sizing a REAL
# ceiling later, note that a coding attempt's cumulative question total is
# measured in MILLIONS (~4.7M for 60 turns; see
# artifacts/logs/sdd-coder-count-input-overhead-20260912.md), NOT in
# context-window units.
DEV_LOOP_CODER_LEDGER: bool = config.getboolean("DEV_LOOP_CODER_LEDGER", fallback=True)
# Absolute durable directory for the telemetry dataset, or empty to derive the
# git main checkout at startup. Deliberately NOT defaulted through BASE_DIR:
# navconfig resolves a virtualenv's parent or an arbitrary SITE_ROOT/BASE_DIR
# override (navconfig/project.py:129-161), so a feature checkout with its own
# virtualenv would put the dataset inside the worktree /sdd-done deletes.
SDD_CODER_TELEMETRY_DIR: str = config.get("SDD_CODER_TELEMETRY_DIR", fallback="")
```
**Why**: Placed next to `WORKTREE_BASE_PATH` because `resolve_durable_root` (TASK-3191) validates one against the other. The comments carry the two facts a future operator will otherwise get wrong: the millions-not-thousands scale, and why `BASE_DIR` is not the default.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY — policy helper)
```python
# occurrences: 1 (verified: grep -c '    def _completion_usage_payload(' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# BEFORE — insert above `    def _completion_usage_payload(` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:585)
    @staticmethod
    def _observational_policy(profile: LLMCodeDispatchProfile) -> Optional[TokenBudgetPolicy]:
        """Build the non-enforcing policy for one coding attempt, or None when disabled.

        Three decisions, none of them re-derivable at the call site:

        * ``enforcement="observe"`` — account without ever denying or resizing an
          output cap. Non-interference is a property of this mode, not of a
          large ceiling: no function of ``max_turns``/``max_tokens`` can bound
          input, the post-loop salvage call, per-call retries or uncertain
          debits (spec §10 R1).
        * ``budget_mode="estimated"`` — Mantle has no strict qualification, so
          strict would raise ``BudgetUnsupported``
          (verified: packages/ai-parrot-client-amazon/.../budget.py:326-330).
        * ``final_answer_reserve=0`` — an observational ledger never finalizes,
          so a protected partition would only distort the report's
          ``remaining_*`` fields. The absolute ``2 x max_tokens`` reserve is the
          recommendation for the ENFORCING configuration a campaign produces
          (spec §7), not for this one.
        """
        if not (conf.DEV_LOOP_CODER_TELEMETRY and conf.DEV_LOOP_CODER_LEDGER):
            return None
        # FILL IN: choose the reference `token_budget` — a positive value large
        # enough that the report's remaining_* fields read sensibly for a
        # multi-million-token attempt. Bounded by: it can never deny in observe
        # mode, so this is a display reference only; document the choice.
        raise NotImplementedError
```
**Why this shape**: A static method returning `Optional` keeps the call site a single `if policy is not None` and keeps every decision documented in one place. Returning `None` (rather than a disabled policy object) is what guarantees AC-1: with telemetry off, no scope object is ever constructed.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY — bind the loop)
```python
# occurrences: 1 (verified: grep -c '            model = self._resolve_model(profile, client)' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# AFTER — insert below `            model = self._resolve_model(profile, client)` (verified: packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:274)
            # ONE root scope per ATTEMPT, not per turn: every
            # `_chat_completion` in the loop below consults
            # `current_budget_scope()` (verified:
            # parrot/clients/openai_base.py:262-264), so a scope per turn would
            # reset the ledger ~60 times and measure nothing. Must enclose the
            # salvage call too (llm.py:552), i.e. the whole `try:` at line 306.
            # FILL IN: enter the scope around the existing loop `try:` —
            # `policy = self._observational_policy(profile)`; when it is None run
            # the loop unchanged, otherwise
            # `scope = await get_default_registry().create(policy)` and
            # `async with scope:` around it, capturing
            # `(await scope.ledger.report()).model_dump()` for the terminal
            # telemetry. Catch `BudgetRegistryFull` (budget_scope.py:136), log
            # once, and fall through to the unscoped path with
            # `budget_report=None`. Bounded by AC-1/AC-2/AC-11: no scope when
            # disabled, ONE operation_id across all turns, never fail a dispatch
            # for a measurement.
            raise NotImplementedError
```
**Why**: The binding is a `FILL IN` on purpose — it restructures an existing `try/finally` that spans 270 lines, and the executor must read that block rather than paste around it. What must NOT change: the loop body, the `finally`'s existing `_safe_emit_after_call`, and the fact that exactly one scope covers the whole attempt.

### FILL IN checklist
- [ ] `llm.py::_observational_policy` — the reference `token_budget` value; bounded by "display-only, can never deny; document the choice"
- [ ] `llm.py::dispatch` — enter/exit the scope around the loop `try:` and capture the report; bounded by AC-1, AC-2, AC-11
- [ ] `test_llm_code_dispatcher.py` — the four test bodies below

---

## Acceptance Criteria

- [ ] AC-1: with `DEV_LOOP_CODER_TELEMETRY=False`, `current_budget_scope()` is `None` inside the loop and no `BudgetScope` is constructed.
- [ ] `DEV_LOOP_CODER_TELEMETRY=True, DEV_LOOP_CODER_LEDGER=False` binds no scope but still emits telemetry (with `budget_report is None`).
- [ ] AC-2: with the ledger on, every budgeted request in one attempt reports the SAME ledger `operation_id`, including the salvage call.
- [ ] The emitted `AttemptTelemetry.budget_report` contains `settled_estimate_input_tokens` and `input_tokens`.
- [ ] `BudgetRegistryFull` is caught: the dispatch completes, `budget_report is None`, one WARNING logged.
- [ ] The observational policy has `enforcement="observe"`, `budget_mode="estimated"`, `final_answer_reserve == 0`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py packages/ai-parrot/src/parrot/conf.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py  (append)
import pytest

from parrot.clients.budget_scope import current_budget_scope


class TestObservationalScope:
    def test_policy_shape(self):
        # FILL IN: monkeypatch conf flags on, build a profile, assert the three
        # policy decisions — bounded by AC "enforcement/budget_mode/reserve"
        raise NotImplementedError

    async def test_disabled_binds_no_scope(self, monkeypatch):
        # FILL IN: conf.DEV_LOOP_CODER_TELEMETRY = False; a fake client whose
        # _chat_completion asserts current_budget_scope() is None
        raise NotImplementedError

    async def test_one_operation_id_across_turns(self, monkeypatch):
        # FILL IN: budget-capable fake client recording
        # current_budget_scope().operation_id per turn; assert the set has
        # exactly one element over a multi-turn run — bounded by AC-2
        raise NotImplementedError

    async def test_registry_full_degrades(self, monkeypatch):
        # FILL IN: monkeypatch BudgetRegistry.create to raise BudgetRegistryFull;
        # assert the dispatch still returns and budget_report is None
        # — bounded by AC-11
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 3, §7 Known Risks, §10 R1/R2.
2. **Check dependencies** — TASK-3185 and TASK-3189 must be in `sdd/tasks/completed/`; `TokenBudgetPolicy.enforcement` and `_emit_attempt_telemetry` must exist.
3. **Verify the Codebase Contract** — read `dispatch()` from line 270 to the `finally` at 574 in full before restructuring anything.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; do not add a ceiling knob or a `_min_safe_ceiling`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3190-observational-scope-binding.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
