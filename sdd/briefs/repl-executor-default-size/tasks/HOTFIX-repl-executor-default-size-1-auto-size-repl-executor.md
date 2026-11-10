# TASK HOTFIX-repl-executor-default-size-1: Auto-size PythonREPLTool executor to WorkerPool capacity

**Feature**: repl-executor-default-size (brief)
**Spec**: `sdd/briefs/repl-executor-default-size.brief.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

## Context
Default `executor_max_workers=4` is smaller than the WorkerPool's live-worker capacity
(auto ceiling + prewarm), so every default PandasAgent warns and queues requests. See the brief.

## Scope
- `PythonREPLTool.__init__`: change `executor_max_workers: int = 4` to `Optional[int] = None`. When `None`,
  compute `cfg = worker_config or WorkerConfig()` and use
  `WorkerPool._effective_ceiling(cfg) + cfg.prewarm_pool_size`. Explicit ints unchanged. Update the docstring.
- `PandasAgent.__init__`: add `python_repl_executor_max_workers: Optional[int] = None`, store it, forward it as
  `executor_max_workers=` to `PythonPandasTool` at `data.py:621`. Document in the docstring.
- Tests.

**NOT in scope**: changing `WorkerPool` / `_warn_if_executor_undersized`; per-clone executors in
`PythonPandasTool._clone`; changing `WorkerConfig` defaults.

## Files to Modify
- `packages/ai-parrot/src/parrot/tools/pythonrepl.py`
- `packages/ai-parrot/src/parrot/bots/data.py`
- `packages/ai-parrot/tests/test_pythonrepl_executor.py`

## Codebase Contract
### Verified Imports
- `from parrot.tools.repl_worker import WorkerPool` (used at `pythonrepl.py:900`)
- `from parrot.tools.repl_worker.protocol import WorkerConfig` (used at `pythonrepl.py:959`)
### Existing Signatures
- `pythonrepl.py:222` — `executor_max_workers: int = 4,`
- `pythonrepl.py:286` — `self._repl_executor = ThreadPoolExecutor(max_workers=executor_max_workers, ...)`
- `pool.py:207-212` — `@staticmethod def _effective_ceiling(config: WorkerConfig) -> int`
- `pool.py:190` — `needed = self._ceiling + self._config.prewarm_pool_size`
- `data.py:459` — `python_repl_execution_mode: Optional[str] = None,` ; `data.py:621` — `PythonPandasTool(...)`
### Does NOT Exist
- No public accessor for `ThreadPoolExecutor` size (tests read `_max_workers`).
- No `executor_max_workers` parameter on `PandasAgent` today.

## Implementation Notes
Lint with `ruff check` on the two source files before committing. Import `WorkerPool`/`WorkerConfig` lazily inside `__init__` (the module already imports repl_worker lazily) to
avoid import cycles. Log the resolved size in the existing debug line.

## Acceptance Criteria
- [ ] `PythonREPLTool()` executor `_max_workers == WorkerPool._effective_ceiling(WorkerConfig()) + WorkerConfig().prewarm_pool_size`.
- [ ] `PythonREPLTool(worker_config=WorkerConfig(max_workers=2, prewarm_pool_size=1))` → executor size 3.
- [ ] `PythonREPLTool(executor_max_workers=2)` → size 2 (unchanged behaviour).
- [ ] Default-constructed tool's `_get_worker_pool()` emits no "shared executor has" warning (caplog).
- [ ] `PandasAgent(python_repl_executor_max_workers=N)` forwards N to its `PythonPandasTool` executor.
- [ ] Validation commands pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_pythonrepl_executor.py -q`

## Test Specification
Replace `test_pool_is_bounded` (asserts 4) with an auto-size assertion; add the worker_config, no-warning and
PandasAgent-forwarding cases (PandasAgent case may monkeypatch `PythonPandasTool` to capture kwargs).

## Agent Instructions
Implement exactly the scope above; run validation with `PYTHONPATH=packages/ai-parrot/src`.

## Completion Note
Implemented as specified: `executor_max_workers: Optional[int] = None` auto-sizes to `WorkerPool._effective_ceiling(cfg) + cfg.prewarm_pool_size`; `PandasAgent(python_repl_executor_max_workers=)` forwards it. Tests: 5 new/updated pass (auto-size, worker_config size 3, no 'shared executor has' warning, PandasAgent forwarding). Pre-existing env failures remain in tests using `tmp_path` as report_dir (`output_dir escapes allowed directories`: /tmp is outside STATIC_DIR here) — unrelated to this change. Pre-existing ruff findings (F541/F841/E721) in pythonrepl.py untouched. Implemented sequentially by the worker (task too small for chunk dispatch).
