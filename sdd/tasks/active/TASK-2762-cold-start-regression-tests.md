# TASK-2762: Cold-start death-spiral regression & behaviour tests

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2760, TASK-2761
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / G6 / AC7. The proposal reproduced the incident
deterministically (`sdd/state/FEAT-518/findings/F016-probe-death-spiral-under-load.md`,
"Probe B"): a `PythonPandasTool` with one scalar in `df_locals` and a
worker whose bootstrap exceeds the old 5 s budget produced the exact log
signature (`worker is dead, restarting` → 5 s → blank error → repeat).
This task turns that probe into the permanent regression test, plus the
integration-level behaviour tests the unit tasks did not cover. It uses
`setup_code` to delay the worker's bootstrap — no production test hook.

---

## Scope

- `tests/repl_worker/test_integration.py` (or a new
  `test_cold_start.py` in the same directory) with:
  1. `test_cold_worker_seeding_survives_slow_bootstrap` — **the Probe B
     regression**: `PythonPandasTool(dataframes=None, generate_guide=False, report_dir=tmp_path, setup_code="import time\ntime.sleep(8)")`,
     `tool.df_locals["n_rows"] = 3`; three consecutive `await tool._execute("print(n_rows)")`
     all return a `str` containing `3`; caplog (logger
     `parrot.tools.repl_worker.pool`) contains **zero**
     `worker is dead, restarting` lines and exactly **one** `spawned worker pid=`
     line for the session worker (prewarm spares excluded — set
     `worker_config=WorkerConfig(prewarm_pool_size=0, ...)` to make the count exact).
  2. `test_pandas_seeding_order_independent` — same tool with a real
     `pd.DataFrame` registered via the constructor `dataframes={"sales": df}`
     (produces DataFrame + 8 scalar entries, `pythonpandas.py:505-522`) and
     the slow bootstrap: `_execute("print(sales.shape)")` succeeds; run the
     seeding twice with different `df_locals` insertion orders (rebuild the
     tool with the dict reversed) to show order does not matter.
  3. `test_namespace_api_after_soft_timeout_keeps_state` — set `x=1` via
     `_execute`, force one non-lethal `list_vars` timeout (monkeypatch the
     handle's `_roundtrip` as in TASK-2759's test, `namespace_timeout_ms=200`),
     restore, then `await tool.get_var("x") == 1`.
  4. Update the docstring of `TestE2E.test_e2e_runaway_loop_recovery`
     (`test_integration.py:137-147`): `deadline_ms` no longer has to cover
     bootstrap; keep its assertions.
- Mark the ≥8 s tests with `@pytest.mark.slow` **only if** a `slow` marker
  is already registered in `pyproject.toml` / `pytest.ini` (grep first);
  otherwise leave unmarked.
- Run the full `tests/repl_worker/` directory and
  `tests/test_pythonrepl_executor.py`; fix nothing outside tests — if a
  product bug surfaces, stop and report it in the completion note.

**NOT in scope**: product code changes (report instead), docs (TASK-2763).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/repl_worker/test_cold_start.py` | CREATE | Probe B regression + order-independence + soft-timeout state test |
| `packages/ai-parrot/tests/repl_worker/test_integration.py` | MODIFY | docstring of `test_e2e_runaway_loop_recovery` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd
from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools.pythonpandas import PythonPandasTool          # pythonpandas.py:25
from parrot.tools.repl_worker import WorkerConfig, NamespaceTimeoutError   # __init__ exports (TASK-2757/2759)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):
    def __init__(..., report_dir=None, setup_code: Optional[str] = None, ..., worker_config=None, **kwargs)   # :180-193
        self.setup_code = setup_code or self._get_default_setup_code()   # :236
        self._worker_repl_kwargs = {"setup_code": self.setup_code}       # :266-268  ← mirrored into the worker; runs in the worker's __init__ → _bootstrap() (:433-446, enforce_security=False)
        self._worker_pool = None                                         # :264 (WorkerPool created lazily at :853-868)
    async def _execute(self, code, debug=False, **kwargs) -> Any       # :920-977
    async def get_var(self, name) -> Any                               # :979-989
    async def list_vars(self) -> List[str]                             # :1001-1004

# packages/ai-parrot/src/parrot/tools/pythonpandas.py
class PythonPandasTool(PythonREPLTool):                                # :25 ; name "python_repl_pandas" :40
    def __init__(self, dataframes=None, generate_guide=..., ..., **kwargs)   # :~100-135 (kwargs go to PythonREPLTool.__init__ at :132) — verify exact signature
    self.df_locals: dict[str, Any]                                     # populated by _process_dataframes :505-522 (df, alias, *_row_count/_col_count/_shape/_columns)
    async def _get_worker_handle(self)                                 # :137-181 seeding
    async def _execute(self, code, debug=False, **kwargs) -> Any       # :910-1010 (list_vars before/after)

# packages/ai-parrot/src/parrot/tools/repl_worker/pool.py log lines (grep targets)
#   "WorkerPool: session %r worker is dead, restarting"                 # :241
#   "WorkerHandle: spawned worker pid=%s"                               # handle.py:187
# packages/ai-parrot/tests/repl_worker/test_integration.py
async def _shutdown(tool: PythonREPLTool) -> None                      # :26  (await tool._worker_pool.shutdown() if created — reuse)
class TestE2E: test_e2e_runaway_loop_recovery                         # :137-165 (docstring :139-147)
```

### Does NOT Exist
- ~~a bootstrap-delay env var / test hook in `worker.py`~~ — none and none should be added; use `setup_code`.
- ~~`tests/repl_worker/conftest.py`~~ — none; define fixtures in the new module.
- ~~a `slow` pytest marker~~ — unknown; grep `pyproject.toml` for `markers` before using one.
- ~~`PythonPandasTool.register_scalar()`~~ — none; write directly to `tool.df_locals[...]` as the probe did.
- ~~seeding order guarantees~~ — `new_names` is a `set` (`pythonpandas.py:173`); the test must not assume an order.

---

## Implementation Notes

### Pattern to Follow
```python
# Probe B, made deterministic (from sdd/state/FEAT-518 findings F016 + spec §4)
SLOW_BOOT = "import time\ntime.sleep(8)"

async def test_cold_worker_seeding_survives_slow_bootstrap(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="parrot.tools.repl_worker")
    cfg = WorkerConfig(deadline_ms=60_000, max_workers=2, idle_ttl_seconds=60, prewarm_pool_size=0)
    tool = PythonPandasTool(dataframes=None, generate_guide=False, report_dir=str(tmp_path),
                            setup_code=SLOW_BOOT, worker_config=cfg)
    tool.df_locals["n_rows"] = 3
    try:
        for _ in range(3):
            out = await tool._execute("print(n_rows)")
            assert isinstance(out, str) and "3" in out
        assert "worker is dead, restarting" not in caplog.text
        assert caplog.text.count("spawned worker pid=") == 1
    finally:
        await _shutdown(tool)
```

### Key Constraints
- The host-side `PythonPandasTool.__init__` also runs `setup_code` in its own `_bootstrap()` (`pythonrepl.py:433-446`, class-level `_bootstrapped` flag :97) — so the 8 s sleep happens **twice** (host + worker) per tool construction. Budget ≈20 s per test; construct the tool once per test.
- `caplog` must capture the `parrot.tools.repl_worker.*` loggers at DEBUG for the `spawned worker pid=` count.
- Tests spawn real workers (directory convention); always shut the pool down in `finally`.

### References in Codebase
- `sdd/state/FEAT-518/findings/F016-probe-death-spiral-under-load.md` — the original probe and expected log signature
- `test_integration.py:137-165` — existing e2e pattern

---

## Acceptance Criteria

- [ ] Probe B regression passes: three calls succeed, zero `worker is dead, restarting`, one `spawned worker pid=`
- [ ] Order-independence test passes with a DataFrame + scalars in both insertion orders
- [ ] Soft-timeout state test passes (`x` preserved after a non-lethal timeout)
- [ ] `test_e2e_runaway_loop_recovery` docstring updated; assertions untouched and green
- [ ] `pytest packages/ai-parrot/tests/repl_worker/ -v` and `pytest packages/ai-parrot/tests/test_pythonrepl_executor.py -v` pass; `ruff check` clean on the test files
- [ ] Spec AC7, AC9

---

## Test Specification

See "Pattern to Follow" for test 1; tests 2–3 follow the same fixture shape
(`PythonPandasTool(..., setup_code=SLOW_BOOT, worker_config=cfg)` /
monkeypatched `handle._roundtrip` obtained via `await tool._get_worker_handle()`).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§4 Test Specification)
2. **Check dependencies** — TASK-2760 and TASK-2761 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `PythonPandasTool.__init__`'s signature and the pool/handle log strings before writing assertions
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2762-cold-start-regression-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
