# TASK-2761: Tool & client legibility — no blank errors on the REPL path

**Feature**: FEAT-500 — REPL Worker Readiness Handshake & Non-Lethal Namespace Timeouts
**Spec**: `sdd/specs/bug-workerpool-repl.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2759
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / G3. The incident surfaced as
`Error executing Python code: ` and `ValueError('')` because
`PythonREPLTool._execute()` copies `str(e)` verbatim into the error dict
(`pythonrepl.py:959-962`) and `AbstractClient` does
`raise ValueError(result.error)` (`clients/base.py:1500`). TASK-2759 makes
the worker layer raise messaged exceptions, but the tool/client layers must
also stop *propagating* blanks, and `PythonPandasTool` must stop hiding the
namespace failures it swallows around each execution
(`pythonpandas.py:939-942, 981-995`).

---

## Scope

- `PythonREPLTool._execute()` exception branch: compute
  `detail = str(e) or type(e).__name__`; return
  `{"status": "error", "result": f"ToolError: {type(e).__name__}: {detail}", "error": detail}`;
  log the same `detail`.
- `PythonPandasTool._get_worker_handle()` seeding loop: wrap each
  `inject_dataframe`/`set_var` call so `NamespaceTimeoutError` and
  `WorkerBootstrapError` are re-raised as the same type with the message
  prefixed `f"seeding {name!r} into the REPL worker failed: "` (use
  `raise type(exc)(msg) from exc`). Keep the identity-based reseed logic
  and the DataFrame/scalar split unchanged.
- `PythonPandasTool._execute()`: the two `except Exception` blocks around
  `list_vars()` (`:939-942`, `:981-984`) and the one around `get_var()`
  (`:992-994`) log at `debug` with the exception text
  (`self.logger.debug("python_repl_pandas: namespace probe failed: %s", exc)`).
- `AbstractClient` (`clients/base.py:1500`):
  `raise ValueError(result.error or f"Tool {tool_name} returned status=error without a message")`.
- Grep for callers that special-case `asyncio.TimeoutError` by identity on
  the namespace API (`bots/data.py` `get_var`/`snapshot` at 1724, 2210,
  2501, 2613, 2677; `bots/agent.py:251`; `tools/agent.py:424-430`) —
  `NamespaceTimeoutError` subclasses `TimeoutError`, so `except TimeoutError`
  still matches; only adjust a caller if it compares types with `is`/`==`.
  Record what you found in the completion note.
- Unit tests for the two non-blank guarantees.

**NOT in scope**: handle/pool behaviour (TASK-2759/2760), the cold-start
integration test (TASK-2762).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/pythonrepl.py` | MODIFY | non-blank `error` in `_execute` |
| `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | MODIFY | messaged seeding errors; debug-log swallowed probes |
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | fallback text for `ValueError` |
| `packages/ai-parrot/tests/repl_worker/test_integration.py` | MODIFY | `test_execute_error_dict_never_blank` |
| `packages/ai-parrot/tests/unit/clients/test_tool_error_message.py` (or nearest existing client test module) | CREATE/MODIFY | `test_client_value_error_never_blank` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.repl_worker import NamespaceTimeoutError, WorkerBootstrapError   # exported by TASK-2759 (repl_worker/__init__.py __all__)
from parrot.tools.pythonrepl import PythonREPLTool          # pythonrepl.py; also imported by pythonpandas.py:7
from parrot.tools.pythonpandas import PythonPandasTool      # pythonpandas.py:25
from parrot.tools.abstract import ToolResult                # ToolResult is what abstract.py:1014-1028 builds from the dict (verify the import path with grep "class ToolResult" before use)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):
    async def _execute(self, code: str, debug: bool = False, **kwargs) -> Any    # :920-977
        # :944 try: ... :945 self.logger.info(f"Executing Python code: {code[:100]}...")
        # :957-958 async with self._worker_session() as handle: output = await handle.execute(query, debug=debug)
        # :959-962 except Exception as e: self.logger.error(f"Error executing Python code: {e}"); msg = f"ToolError: {type(e).__name__}: {str(e)}"; return {"status": "error", "result": msg, "error": str(e)}
    _worker_session (asynccontextmanager) → _get_worker_handle()        # :894-918, :871-892

# packages/ai-parrot/src/parrot/tools/pythonpandas.py
class PythonPandasTool(PythonREPLTool):                                # :25 ; name = "python_repl_pandas" :40
    async def _get_worker_handle(self)                                 # :137-181
        # :169 handle = await super()._get_worker_handle(); :170-172 identity-based reseed reset
        # :173 new_names = set(self.df_locals) - self._seeded_df_names
        # :175-180 for name in new_names: value = self.df_locals[name]; if isinstance(value, pd.DataFrame): await handle.inject_dataframe(name, value) else: await handle.set_var(name, value)
        # :181 self._seeded_df_names |= new_names
    async def _execute(self, code, debug=False, **kwargs) -> Any       # :910-1010
        # :939-942 try: pre_keys = set(await self.list_vars()) except Exception: pre_keys = set()
        # :944 result = await super()._execute(code, debug=debug, **kwargs)
        # :981-984 try: current_keys = set(await self.list_vars()) except Exception: current_keys = set()
        # :992-994 try: val = await self.get_var(key) except Exception: continue

# packages/ai-parrot/src/parrot/clients/base.py
#   :1495-1502  result = await self.tool_manager.execute_tool(...); if isinstance(result, ToolResult): if result.status == "error": raise ValueError(result.error)  (:1499-1500); return result.result
#   :1503-1506  except Exception as e: self.logger.error(f"Error executing tool {tool_name}: {e}"); raise

# packages/ai-parrot/src/parrot/tools/abstract.py
#   :1014-1028  dict with "status"+"result" → ToolResult(**raw_result)

# packages/ai-parrot/tests/repl_worker/test_integration.py
async def _shutdown(tool: PythonREPLTool) -> None                      # :26 ; fixture `tool` :32 ; class TestExecuteContract :38
```

### Does NOT Exist
- ~~`PythonREPLTool.on_worker_error()` / an error-formatting hook~~ — none; the dict is built inline at `:959-962`.
- ~~`ToolResult.error` validation forbidding empty strings~~ — none; that is why the fallback lives in the client.
- ~~a `PythonPandasTool._seed_worker()` helper~~ — seeding is inline in `_get_worker_handle` (`:173-181`); you may extract one if it stays private and keeps the identity logic.
- ~~`asyncio.TimeoutError` distinct from `TimeoutError`~~ — same class on Python ≥3.11; `NamespaceTimeoutError(TimeoutError)` is caught by both spellings.

---

## Implementation Notes

### Pattern to Follow
```python
# pythonrepl.py:959-962 (target shape)
except Exception as e:
    detail = str(e) or type(e).__name__
    self.logger.error("Error executing Python code: %s", detail)
    return {"status": "error", "result": f"ToolError: {type(e).__name__}: {detail}", "error": detail}
```

### Key Constraints
- Keep the `{status, result, error}` contract (spec AC11); only the *content* of `error` changes (never empty).
- `PythonPandasTool` probes around execution must stay non-fatal (they are diagnostics); only their silence changes.
- The client change is one line; do not restructure the wrapper.
- Use `%s`-style logging, not f-strings, in new log calls (project logging pattern).

### References in Codebase
- `pythonrepl.py:920-977`, `pythonpandas.py:137-181, 910-1010`, `clients/base.py:1483-1506`

---

## Acceptance Criteria

- [ ] Forcing `_worker_session` to raise `TimeoutError()` makes `_execute` return `error == "TimeoutError"` and `result` starting with `ToolError: TimeoutError: TimeoutError`
- [ ] `ToolResult(status="error", error="")` through the client wrapper raises `ValueError` whose message is the fallback text
- [ ] A seeding failure message contains the variable name
- [ ] `pytest packages/ai-parrot/tests/repl_worker/ -v` and the client test pass; `ruff check` clean
- [ ] Completion note lists the namespace-API callers checked for type-identity comparisons
- [ ] Spec AC5, AC11

---

## Test Specification

```python
# packages/ai-parrot/tests/repl_worker/test_integration.py (addition)
async def test_execute_error_dict_never_blank(tmp_path, monkeypatch):
    tool = PythonREPLTool(report_dir=str(tmp_path))
    try:
        import contextlib
        @contextlib.asynccontextmanager
        async def boom():
            raise TimeoutError()
            yield  # pragma: no cover
        monkeypatch.setattr(tool, "_worker_session", boom)
        out = await tool._execute("x = 1")
        assert out["status"] == "error" and out["error"] == "TimeoutError"
        assert out["result"].startswith("ToolError: TimeoutError: TimeoutError")
    finally:
        await _shutdown(tool)

# client test — build the smallest AbstractClient subclass / mock tool_manager whose execute_tool returns
# ToolResult(status="error", result=None, error="") and assert:
#   with pytest.raises(ValueError, match="without a message"): await client.<tool wrapper>("t", {})
# (locate the wrapper's method name at clients/base.py:1483-1506 before writing the test)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2759 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm line numbers; find the client wrapper method name and the `ToolResult` import path with grep
4. **Update status** in `sdd/tasks/index/bug-workerpool-repl.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2761-tool-client-error-legibility.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
