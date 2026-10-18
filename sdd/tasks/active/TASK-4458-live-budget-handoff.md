# TASK-4458: Hand the E2E plan's live budget to the fixture agent through one forwarded env var

**Feature**: FEAT-701 — Propagate the E2E plan's live budget to the fixture agent
**Spec**: `sdd/specs/fixgroup-27d350c92624.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: issue:5076d67c9758

---

## Context

Ledger fix lane (`/sdd-fix`, fixgroup:27d350c92624). `run_plan` discards
`E2EPlan.budget` (`runner.py:183`), and the fixture agent builds its
`GenerationBudget` from `LiveBudget()` defaults (`live.py:451-452`), so
`live.md`'s `timeout_s: 90` runs as 60 and plan ceilings are no-ops.
Implements spec §3 M1 end to end.

---

## Scope

- `live.py`: `LIVE_BUDGET_ENV`, append to `FORWARDED_ENV_VARS`,
  `resolve_plan_budget()`, wire `budget=` in `_ensure_agent`, export both
  names in `__all__`.
- `runner.py`: `_LiveBudgetContext.child_env()`; merge it into the pytest
  child env; drop the `_ = live_budget` placeholder.
- Tests in `test_live_gate.py` and `test_runner.py` per spec §4.

**NOT in scope**: `targets/mcp.py` (forwards the var already), `targets/base.py`,
`tests/e2e/plans/live.md`, `GenerationBudget`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/live.py` | MODIFY | env var, resolver, `_ensure_agent` wiring |
| `packages/ai-parrot-server/src/parrot/e2e/runner.py` | MODIFY | producer side |
| `packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py` | MODIFY | `TestResolvePlanBudget` + forwarding/plan-driven tests |
| `packages/ai-parrot-server/tests/unit/e2e/test_runner.py` | MODIFY | `child_env` test; env captured in the `run_plan` test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.e2e.models import LiveBudget  # verified: live.py:58
from parrot.e2e.errors import E2EBudgetError, E2EConfigError, E2EPrerequisiteError  # verified: live.py:57
from parrot.e2e import live as e2e_live  # verified: test_live_gate.py:15
from parrot.e2e import runner  # verified: test_runner.py:10
from parrot.e2e.models import E2EPlan, ProcessIdentity, RunState, ScenarioSpec, SourceIdentity, TargetConfig  # verified: test_runner.py:9
```

### Existing Signatures to Use
```python
# live.py
FORWARDED_ENV_VARS: tuple[str, ...] = (PARROT_TEST_E2E_ENV, PARROT_TEST_REAL_LLM_ENV, GOOGLE_API_KEY_ENV, E2E_MODEL_ENV, E2E_MAX_LLM_CALLS_ENV)  # :106-112
def require_live_opt_in(*, budget: Optional[LiveBudget] = None, env: Optional[Mapping[str, str]] = None) -> LiveOptIn  # :161
def build_live_generation_budget(opt_in: LiveOptIn, *, budget: Optional[LiveBudget] = None) -> "GenerationBudget"  # :242
# _ensure_agent, live.py:449-452:
#     if self._agent is None:
#         opt_in = require_live_opt_in()
#         budget = build_live_generation_budget(opt_in)
# runner.py
@dataclass class _LiveBudgetContext: plan: E2EPlan  # :49-60
# runner.py:192-200 pytest child env: {**os.environ, ENV_RUN_ID: ..., ENV_OWNER_ID: owner_id, ENV_CONTROL_SOCKET: "", ENV_RESULTS_PATH: str(bridge_path), "PARROT_TEST_E2E": "1"}
# models.py
class LiveBudget(_E2EBaseModel): model: str; max_calls: int(gt=0); max_output_tokens: int(gt=0); max_request_bytes: int(gt=0); timeout_s: float(gt=0)  # :120-135
# test_live_gate.py: _FULL_OPT_IN_ENV (:31), _skip_no_google_budget (:26), class TestBuildLiveGenerationBudget (:137)
# test_runner.py: _plan(), _scenario(), test_run_plan_executes_declared_nodes_and_cleans_targets (monkeypatches runner.asyncio.create_subprocess_exec with a lambda *_args, **_kwargs)
```

### Does NOT Exist
- ~~`TargetAdapter.set_budget` / any adapter budget hook~~.
- ~~`ScenarioSpec.budget`~~ — plan-level only.
- ~~`pydantic.ValidationError` import in live.py~~ — catch `ValueError`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/e2e/live.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/e2e/runner.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/unit/e2e/test_runner.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/e2e/live.py#require_live_opt_in",
    "sym:packages/ai-parrot-server/src/parrot/e2e/live.py#build_live_generation_budget",
    "sym:packages/ai-parrot-server/src/parrot/e2e/runner.py#_LiveBudgetContext"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `live.py` keeps provider imports lazy; the new code uses only already
  imported names.
- The runner imports `LIVE_BUDGET_ENV` from `parrot.e2e.live` at module
  scope (light module — spec §7).
- Empty string counts as unset (defaults), malformed JSON or an invalid
  field value is `E2EConfigError(reason_code="invalid_budget")`.

---

## Implementation Blueprint

### Steps (in order)
1. `live.py`: constant + `FORWARDED_ENV_VARS` entry + `resolve_plan_budget` + `_ensure_agent` wiring + `__all__`.
2. `runner.py`: import, `child_env()`, env merge, remove placeholder line.
3. Tests (spec §4), then validation + `ruff check --fix`.

### `packages/ai-parrot-server/src/parrot/e2e/live.py` (MODIFY)
```python
# AFTER `E2E_MAX_LLM_CALLS_ENV = "E2E_MAX_LLM_CALLS"` (verified: live.py:99):
#: JSON-serialized :class:`~parrot.e2e.models.LiveBudget` the runner hands to
#: every live child (pytest → ``mcp-agent`` adapter → this module's fixture
#: agent) so the plan's ceilings, not ``LiveBudget()`` defaults, bound the run.
LIVE_BUDGET_ENV = "PARROT_E2E_LIVE_BUDGET"

# occurrences: 1 (verified: grep -c '^FORWARDED_ENV_VARS' live.py) — append LIVE_BUDGET_ENV as the last tuple entry.

# AFTER build_live_generation_budget (before build_live_client, verified: live.py:280):
def resolve_plan_budget(env: Optional[Mapping[str, str]] = None) -> LiveBudget:
    """Resolve the plan budget the runner forwarded through :data:`LIVE_BUDGET_ENV`.

    Args:
        env: Environment mapping to read; ``os.environ`` when omitted.

    Returns:
        The forwarded :class:`LiveBudget`, or a default instance when the variable is unset/empty.

    Raises:
        E2EConfigError: If the payload is not a valid ``LiveBudget`` JSON document.
    """
    environ = env if env is not None else os.environ
    raw = environ.get(LIVE_BUDGET_ENV)
    if not raw:
        return LiveBudget()
    try:
        return LiveBudget.model_validate_json(raw)
    except ValueError as exc:
        raise E2EConfigError(
            f"{LIVE_BUDGET_ENV} is not a valid LiveBudget payload: {exc}",
            reason_code="invalid_budget",
        ) from exc

# occurrences: 1 (verified: grep -c 'opt_in = require_live_opt_in()' live.py) — REPLACE lines 451-452 with:
                plan_budget = resolve_plan_budget()
                opt_in = require_live_opt_in(budget=plan_budget)
                budget = build_live_generation_budget(opt_in, budget=plan_budget)

# __all__: add "LIVE_BUDGET_ENV" after "LIVE_API_KEY_ENV" and "resolve_plan_budget" after "build_live_generation_budget".
```

### `packages/ai-parrot-server/src/parrot/e2e/runner.py` (MODIFY)
```python
# imports: add `from parrot.e2e.live import LIVE_BUDGET_ENV` next to the other parrot.e2e imports (verified: runner.py:35-40)

# occurrences: 1 (verified: grep -c '^class _LiveBudgetContext' runner.py) — REPLACE the dataclass body/docstring:
@dataclass
class _LiveBudgetContext:
    """One shared live budget identity for a single runner invocation.

    The runner never calls a provider; it hands the validated plan budget to
    every live child through :data:`LIVE_BUDGET_ENV` so sequential live
    scenarios share ONE run-scoped allowance (spec §2 "Live Provider Budget").
    """

    plan: E2EPlan

    def child_env(self) -> dict[str, str]:
        """The one env entry carrying the plan budget into the pytest child (and, forwarded, the fixture agent)."""
        return {LIVE_BUDGET_ENV: self.plan.budget.model_dump_json()}

# occurrences: 1 (verified: grep -c '_ = live_budget' runner.py) — DELETE lines 181-183 (the two comment lines + `_ = live_budget`).
# occurrences: 1 (verified: grep -c '"PARROT_TEST_E2E": "1",' runner.py) — INSERT after that line:
                **live_budget.child_env(),
```

### `packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py` (MODIFY)
```python
# AFTER class TestBuildLiveGenerationBudget (verified: :137-153) — add:
class TestResolvePlanBudget:
    def test_unset_returns_defaults(self) -> None: ...  # resolve_plan_budget(env={}) == LiveBudget(); also env={LIVE_BUDGET_ENV: ""}
    def test_payload_round_trips(self) -> None: ...     # LiveBudget(timeout_s=90, max_calls=2).model_dump_json() → equal model
    @pytest.mark.parametrize("raw", ["{not json", '{"max_calls": 0}'])
    def test_malformed_is_config_error(self, raw: str) -> None: ...  # E2EConfigError, reason_code == "invalid_budget"
    def test_live_budget_env_is_forwarded(self) -> None: ...  # e2e_live.LIVE_BUDGET_ENV in e2e_live.FORWARDED_ENV_VARS

@_skip_no_google_budget
class TestPlanBudgetDrivesFixtureBudget:
    def test_plan_budget_drives_opt_in_and_generation_budget(self) -> None:
        env = {**_FULL_OPT_IN_ENV, e2e_live.LIVE_BUDGET_ENV: LiveBudget(timeout_s=90, max_calls=2, max_output_tokens=512, max_request_bytes=16384).model_dump_json()}
        plan_budget = e2e_live.resolve_plan_budget(env)
        opt_in = e2e_live.require_live_opt_in(budget=plan_budget, env=env)
        budget = e2e_live.build_live_generation_budget(opt_in, budget=plan_budget)
        assert (opt_in.max_calls, budget.max_calls, budget.timeout_s, budget.max_output_tokens, budget.max_request_bytes) == (2, 2, 90, 512, 16384)
```

### `packages/ai-parrot-server/tests/unit/e2e/test_runner.py` (MODIFY)
```python
# AFTER test_live_lane_requires_opt_in_and_provider_key (verified: :53-64) — add:
def test_live_budget_context_child_env_carries_plan_budget() -> None:
    plan = _plan(_scenario()).model_copy(update={"budget": LiveBudget(timeout_s=90)})  # or build E2EPlan(..., budget=LiveBudget(timeout_s=90))
    env = runner._LiveBudgetContext(plan=plan).child_env()
    assert LiveBudget.model_validate_json(env[LIVE_BUDGET_ENV]) == plan.budget

# In test_run_plan_executes_declared_nodes_and_cleans_targets: replace the create_subprocess_exec lambda with a fake that
# records kwargs["env"] into a list, then assert recorded_env[0][LIVE_BUDGET_ENV] == plan.budget.model_dump_json().
# Imports: `from parrot.e2e.live import LIVE_BUDGET_ENV` and add `LiveBudget` to the models import.
```

---

## Acceptance Criteria

- [ ] AC1–AC5 of the spec.
- [ ] `test_mcp_targets.py` still green (no exact forwarded-env pin found at f3d22f21f; re-check).
- [ ] No linting errors on the four files.

---

## Validation Commands

- `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/unit/e2e/test_live_gate.py packages/ai-parrot-server/tests/unit/e2e/test_runner.py -q -p no:cacheprovider -o addopts=""`
- `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src pytest packages/ai-parrot-server/tests/unit/e2e/test_mcp_targets.py -q -p no:cacheprovider -o addopts=""`

---

## Test Specification

See blueprint and spec §4.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug fixgroup-27d350c92624 --feature-id FEAT-701`)
2. **Read the spec** for full context
3. **Check dependencies** — none
4. **Verify the Codebase Contract** before writing any code
5. **Update status** in `sdd/tasks/index/fixgroup-27d350c92624.json` → `"in-progress"` and commit only that index file
6. **Implement** from the Implementation Blueprint
7. **Verify** acceptance criteria — run the Validation Commands
8. **Commit the code** — stage only the four listed files
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4458 fixgroup-27d350c92624 verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*
