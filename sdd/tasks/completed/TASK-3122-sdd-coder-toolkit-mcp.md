# TASK-3122: `SddCoderToolkit` MCP surface, `_pre_execute` validation, example yaml, `.gitignore`

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3121
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The toolkit is the thin `AbstractToolkit` served by
`parrot mcp-local sdd-coder` (`create_toolkit_mcp_server`, FEAT-485). It exposes exactly
seven tools, wraps every result in `CoderResult`, maps `CoderFailure` to
`status="error"`, and validates arguments in `_pre_execute` because the generic MCP
adapter calls `tool._execute(**arguments)` with no validation (design research S6,
AC-23). The probe runs on the first tool call via `auto_open` (S12). The tracked
artefact operators copy is `examples/sdd-coder-mcp.yaml`; `.parrot/` and `.mcp.json`
are git-ignored.

---

## Scope

- Implement `SddCoderToolkit` in `sdd_coder/toolkit.py` (seven tools, `arg_models`, `_pre_execute`, `_open`, `_close`).
- Add `examples/sdd-coder-mcp.yaml`; add `.sdd-coder/` to `.gitignore`.
- Export from the package; tests incl. `create_toolkit_mcp_server("sdd-coder", config_path=examples/...)` listing the seven tools.

**NOT in scope**: `.mcp.json` / `.parrot/mcp-toolkits.yaml` (operator-local, documented in TASK-3126), prompt changes (TASK-3123/3124).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | CREATE | `SddCoderToolkit` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/__init__.py` | MODIFY | export `SddCoderToolkit` |
| `examples/sdd-coder-mcp.yaml` | CREATE | roster example (tracked) |
| `.gitignore` | MODIFY | `.sdd-coder/` job journal |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | CREATE | tool exposure / validation / error mapping / wait cap / mcp-local build |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ValidationError
from parrot.tools.toolkit import AbstractToolkit                        # verified: parrot/tools/toolkit.py:206
from parrot.mcp.toolkit_server import create_toolkit_mcp_server         # verified: parrot/mcp/toolkit_server.py:29 (tests only)
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import (CoderError, CoderResult, RosterConfig, CoderPlanArgs, CoderRunChunkArgs,
                                                    CoderPrepareNativeArgs, CoderMergeArgs, CoderWaitArgs, CoderStatusArgs, CoderCleanupArgs)
from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe
```

### Existing Signatures to Use
```python
# parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                   # :206 — public `async def` methods become tools (docstring :12-25)
    llm_dependent_tools: frozenset = frozenset()              # :294
    auto_open: bool = False                                   # :319 — when True, the first tool call runs _ensure_open() → _open() (ToolkitTool._execute, :169-172)
    def __init__(self, **kwargs)                              # :321
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None    # :455 — hook invoked by ToolkitTool._execute BEFORE the method
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any   # :470
    def get_tools(self)                                       # :486
# parrot/mcp/toolkit_server.py:29-130
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides) -> StdioMCPServer
    #  cfg = load_toolkits_config(root, config_path=overrides.get("config_path"))  (:69)
    #  toolkit = toolkit_cls(**dict(section.kwargs))  (+ llm_client only when section.llm)  (:113-117)
    #  all_tools = toolkit.get_tools(); include/exclude filters  (:121-130)
# parrot/mcp/adapter.py:79   result = await self.tool._execute(**arguments)   — NO argument validation in the adapter (S6)
# parrot/mcp/toolkit_config.py:19  ToolkitSection(class_path alias "class", enabled, kwargs, include, exclude, llm, llm_kwargs, env)
# parrot/mcp/local_server.py:63   response = await self._handle_request(request)  — requests handled sequentially (S4)
# PATTERN — packages/ai-parrot-tools/src/parrot_tools/tool_optimizations/base.py:33-110
class OptimizationToolkitBase(AbstractToolkit):
    arg_models: dict[str, type[BaseModel]] = {}               # :45
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None   # :83 — model = self.arg_models.get(tool_name); model(**kwargs) → ValidationError → structured error
# .gitignore anchors (verified): line 389 `.mcp.json`, line 407 `.parrot/`, line 346 `*.log`
# examples/tool-optimizations-mcp.yaml — section shape (class / kwargs / optional llm)
```

### Does NOT Exist
- ~~`from parrot_tools.tool_optimizations.base import OptimizationToolkitBase`~~ in core — dependency direction forbids it; replicate `arg_models` + `_pre_execute` (spec §7).
- ~~a startup hook in `create_toolkit_mcp_server` / `StdioMCPServer`~~ — `stop()` only flips `_running` (local_server.py:80-82); `_open()` runs on the first tool call via `auto_open` (S12); `_close()` is best-effort (spec §8 Q4).
- ~~automatic Pydantic → JSON conversion guarantee in the adapter~~ — check `adapter.py:79-95`: if it does not serialise `BaseModel` results, return `result.model_dump()` from `_post_execute` (FILL IN).
- ~~`parrot mcp-local sdd-coder` without a yaml section~~ — `BUILTIN_TOOLKITS` (toolkit_config.py:89) has only scraping/browsing/memory; the section must come from `--config` or `.parrot/mcp-toolkits.yaml`.

---

## Implementation Notes

### Key Constraints
- Seven public `async def` tools named exactly `coder_plan`, `coder_run_chunk`, `coder_prepare_native`, `coder_merge`, `coder_wait`, `coder_status`, `coder_cleanup`; everything else underscore-prefixed.
- `_pre_execute`: `self.arg_models[tool_name](**kwargs)`; `ValidationError` ⇒ raise a `CoderFailure("invalid_arguments", ...)` that `_run` turns into `CoderResult(status="error")` — never let a raw exception escape as MCP `isError` for domain problems.
- `_run(operation, coro)` helper: times the call, wraps `CoderFailure` → `CoderResult(error=CoderError(code, message, details))`, unexpected exceptions → `internal_error` (logged with `self.logger.exception`).
- `auto_open = True`; `_open()` → `await self._engine.open()` (roster_empty is NOT fatal for `_open`: log + let `coder_plan` report it).
- yaml `kwargs.roster` is a list of dicts ⇒ `RosterConfig(seats=roster)` in `__init__` (accept an already-built `RosterConfig` too).

### References in Codebase
- `examples/tool-optimizations-mcp.yaml` — file header comments explaining `repo_root` and credentials; mirror the tone.
- `docs/mcp-local-toolkits.md:20-40` — `.mcp.json` wiring commands.

---

## Implementation Blueprint

### Steps (in order)
1. `toolkit.py` — *why*: the tool names are the contract `sdd-worker.md` (TASK-3124) hardcodes in `tools:`.
2. yaml example + `.gitignore` — *why*: operators install from the tracked example; the journal dir must never be committed.
3. Export + tests (`create_toolkit_mcp_server` with a monkeypatched `RosterProbe.probe`).

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (CREATE)
```python
"""`parrot mcp-local sdd-coder` — MCP surface of the sdd_coder kernel (FEAT-549, spec §3 M5)."""
from __future__ import annotations

import logging, time
from typing import Any, Awaitable, Dict, List, Optional, Union

from pydantic import BaseModel, ValidationError

from parrot.tools.toolkit import AbstractToolkit                          # verified: parrot/tools/toolkit.py:206
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import (CoderCleanupArgs, CoderError, CoderMergeArgs, CoderPlanArgs, CoderPrepareNativeArgs,
                                                    CoderResult, CoderRunChunkArgs, CoderStatusArgs, CoderWaitArgs, RosterConfig)


class SddCoderToolkit(AbstractToolkit):
    """Orchestration kernel for the interactive sdd-worker. Seven tools; every result is a CoderResult."""

    llm_dependent_tools: frozenset = frozenset()
    auto_open: bool = True                                    # probe on FIRST tool call (toolkit.py:169-172); no server startup hook exists (S12)
    arg_models: Dict[str, type[BaseModel]] = {
        "coder_plan": CoderPlanArgs, "coder_run_chunk": CoderRunChunkArgs, "coder_prepare_native": CoderPrepareNativeArgs,
        "coder_merge": CoderMergeArgs, "coder_wait": CoderWaitArgs, "coder_status": CoderStatusArgs, "coder_cleanup": CoderCleanupArgs,
    }

    def __init__(self, *, roster: Union[List[Dict[str, Any]], RosterConfig], redis_url: Optional[str] = None,
                 worktree_base_path: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        cfg = roster if isinstance(roster, RosterConfig) else RosterConfig(seats=roster)   # yaml kwargs arrive as list[dict]
        self._engine = SddCoderEngine(roster=cfg, redis_url=redis_url, worktree_base_path=worktree_base_path)

    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Validate against arg_models (extra='forbid'); adapter.py:79 does not validate (S6)."""
        model = self.arg_models.get(tool_name)
        if model is None:
            return
        try:
            model(**kwargs)
        except ValidationError as exc:
            raise CoderFailure("invalid_arguments", "invalid tool arguments", errors=exc.errors()) from exc

    async def _open(self) -> None:
        try:
            await self._engine.open()
        except CoderFailure as exc:                            # roster_empty: let coder_plan report it, do not break the server
            self.logger.warning("sdd-coder probe: %s", exc.message)

    async def _close(self) -> None:
        # FILL IN: cancel running JobTable tasks + journal final snapshots — bounded by spec §8 Q4 (best-effort; host may never call it)
        return None

    async def _run(self, operation: str, coro: Awaitable[BaseModel]) -> CoderResult:
        t0 = time.monotonic()
        try:
            data = await coro
            return CoderResult(status="ok", operation=operation, data=data.model_dump(), elapsed_ms=int((time.monotonic() - t0) * 1000))
        except CoderFailure as exc:
            return CoderResult(status="error", operation=operation, error=CoderError(code=exc.code, message=exc.message, details=exc.details),
                               elapsed_ms=int((time.monotonic() - t0) * 1000))
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("sdd-coder %s crashed", operation)
            return CoderResult(status="error", operation=operation, error=CoderError(code="internal_error", message=str(exc)),
                               elapsed_ms=int((time.monotonic() - t0) * 1000))

    async def coder_plan(self, feature: str, worktree: str) -> CoderResult:
        """Next wave of `feature` sliced into distinct-seat chunks; roster availability; orphan branches."""
        return await self._run("coder_plan", self._engine.plan(feature, worktree))

    async def coder_run_chunk(self, feature: str, worktree: str, task_ids: List[str]) -> CoderResult:
        """Dispatch the MCP-seat tasks of the current chunk in parallel; returns a job id immediately."""
        return await self._run("coder_run_chunk", self._engine.run_chunk(feature, worktree, task_ids))

    async def coder_prepare_native(self, feature: str, worktree: str, task_id: str) -> CoderResult:
        """Create the sub-worktree for a native (haiku) task; the orchestrator launches the agent itself."""
        return await self._run("coder_prepare_native", self._engine.prepare_native(feature, worktree, task_id))

    async def coder_merge(self, feature: str, worktree: str, task_id: str) -> CoderResult:
        """Clean-status check, fidelity check and merge of the task's latest attempt branch."""
        return await self._run("coder_merge", self._engine.merge(feature, worktree, task_id))

    async def coder_wait(self, job_id: str, timeout_seconds: int = 120) -> CoderResult:
        """Block up to timeout_seconds (≤ 300) and return the job snapshot."""
        return await self._run("coder_wait", self._engine.wait(job_id, timeout_seconds))

    async def coder_status(self, job_id: str) -> CoderResult:
        """Non-blocking job snapshot."""
        async def _s() -> BaseModel: return self._engine.status(job_id)
        return await self._run("coder_status", _s())

    async def coder_cleanup(self, feature: str, worktree: str, keep_conflicted: bool = True) -> CoderResult:
        """Remove merged sub-worktrees; keep conflicted ones unless told otherwise."""
        return await self._run("coder_cleanup", self._engine.cleanup(feature, worktree, keep_conflicted))
```
**Why this shape**: mirrors `OptimizationToolkitBase` (arg models + `_pre_execute`) without importing it; `_run` centralises the envelope so every tool behaves identically (AC-23, spec §2 error codes). If `adapter.py:79-95` does not serialise `BaseModel`, add `_post_execute` returning `result.model_dump()` (FILL IN).

### `examples/sdd-coder-mcp.yaml` (CREATE)
```yaml
# FEAT-549 — sdd-coder orchestration kernel as a local MCP toolkit.
# Serve with:  parrot mcp-local sdd-coder --config examples/sdd-coder-mcp.yaml
# Install:     copy this section into .parrot/mcp-toolkits.yaml (git-ignored) and add to .mcp.json (git-ignored):
#   "parrot-sdd-coder": {"command": "<venv>/bin/parrot", "args": ["mcp-local", "sdd-coder", "--config", ".parrot/mcp-toolkits.yaml"]}
# NOTE ON CREDENTIALS: none here. nova uses BEDROCK_MANTLE_API_KEY/AWS_NOVA_API_KEY, google-compat GEMINI_API_KEY/GOOGLE_API_KEY
# (both via navconfig env/.env), codex its own login. Unavailable seats are dropped by the probe and reported by coder_plan.
toolkits:
  sdd-coder:
    class: parrot.flows.dev_loop.sdd_coder.toolkit.SddCoderToolkit
    kwargs:
      roster:
        - {label: qwen,        kind: mcp,    backend: nova,          model: qwen.qwen3-coder-480b-a35b-instruct}
        - {label: gemini,      kind: mcp,    backend: google-compat, model: gemini-3.5-flash}
        - {label: codex-spark, kind: mcp,    backend: codex,         model: gpt-5.3-codex-spark, fallback_model: gpt-5.3-codex}
        - {label: haiku,       kind: native, model: haiku}
```

### `.gitignore` (MODIFY)
```gitignore
# occurrences: 1 (verified: grep -c '^\.mcp\.json$' .gitignore)
# AFTER — insert below `.mcp.json` (verified: .gitignore:389)
.sdd-coder/
```
**Why**: the job journal lives inside feature worktrees; it is runtime state, never source.

### `sdd_coder/__init__.py` (MODIFY)
```python
# AFTER the engine import line: from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit  # noqa: F401  ; __all__ += "SddCoderToolkit"
```

### FILL IN checklist
- [ ] `toolkit.py::_close` — cancel jobs + journal; bounded by §8 Q4
- [ ] `toolkit.py::_post_execute` (only if adapter needs JSON-safe results); bounded by `adapter.py:79-95`
- [ ] tests bodies

---

## Acceptance Criteria

- [ ] `SddCoderToolkit(roster=[...]).get_tools()` names == the seven `coder_*` tools; no private method exposed (AC-3).
- [ ] `_pre_execute("coder_run_chunk", feature="f", worktree="rel", task_ids=["TASK-1"])` ⇒ `CoderFailure("invalid_arguments")`; via `_execute` path ⇒ `CoderResult(status="error", error.code="invalid_arguments")` (AC-23).
- [ ] `CoderFailure("feature_not_found")` from the engine ⇒ `CoderResult(status="error", error.code="feature_not_found")`.
- [ ] `coder_wait(timeout_seconds=900)` is rejected by validation (le=300); `coder_wait(timeout_seconds=300)` reaches the engine clamp.
- [ ] `create_toolkit_mcp_server("sdd-coder", config_path=Path("examples/sdd-coder-mcp.yaml"))` builds and lists the seven tools (probe monkeypatched to no-op; `redis_url` bogus) — AC-3/AC-15.
- [ ] `git check-ignore .claude/worktrees/x/.sdd-coder/jobs/j.json` matches after the `.gitignore` change.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -v` passes; `ruff`/`mypy` clean.

---

## Test Specification

```python
# test_toolkit.py (sketch)
def test_toolkit_exposes_seven_tools(three_seat_roster): ...
async def test_toolkit_pre_execute_rejects_bad_args(three_seat_roster): ...
async def test_toolkit_maps_failure_to_error_result(three_seat_roster, monkeypatch): ...   # monkeypatch engine.plan to raise CoderFailure("feature_not_found", "x")
async def test_toolkit_wait_caps_timeout(three_seat_roster, monkeypatch): ...               # spy engine.wait receives min(…,300)
def test_mcp_local_serves_sdd_coder(monkeypatch): ...                                       # monkeypatch RosterProbe.probe → all available; create_toolkit_mcp_server(...); assert tool names
```

---

## Agent Instructions

1. **Read the spec** §3 Module 5, §2 "New Public Interfaces", §9 rows S4/S6/S12.
2. **Check dependencies** — TASK-3121 completed.
3. **Verify the Codebase Contract** — read `toolkit.py:150-180, 290-330, 450-480`, `adapter.py:59-95`, `toolkit_server.py:60-130`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** from the blueprint.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3122-sdd-coder-toolkit-mcp.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-10
**Notes**: Implemented `SddCoderToolkit` per the blueprint (seven tools,
`arg_models`, `_pre_execute`, `_open`, `_run` envelope), plus the two FILL
INs: `_close` (best-effort job cancel + final journal, reaching into
`JobTable`/engine internals since no public API exists, mirroring TASK-3120's
own `_created` precedent) and `_post_execute` (serialises `CoderResult` to a
JSON string, since `adapter.py`'s "direct result" branch does `str(result)` —
a Python repr, not JSON — for anything that isn't a `ToolResult`). Added
`examples/sdd-coder-mcp.yaml` and the `.sdd-coder/` `.gitignore` line. 9 new
tests pass; full `tests/flows/dev_loop` run: 1766 passed (up from 1757), same
11 pre-existing `test_pr_enrichment.py` failures, 6 skipped; `ruff`/`mypy`
clean.

**Deviations from spec**:
1. **`_pre_execute` must strip `_permission_context` before validating.**
   Verified `ToolkitTool._execute` (toolkit.py:176-182) *always* injects
   `_permission_context` into the kwargs passed to `_pre_execute`, even for
   toolkits (like this one) that never use permission contexts. The
   blueprint's `_pre_execute` body validates `**kwargs` verbatim against
   `arg_models[tool_name]`, whose models all set `extra="forbid"` — without
   popping `_permission_context` first, EVERY real tool call (even with
   perfectly valid arguments) would fail `_pre_execute` with
   `invalid_arguments` because of the extra key. Added
   `kwargs.pop("_permission_context", None)` before the `model(**kwargs)`
   call; covered by `test_toolkit_pre_execute_ignores_permission_context`.
2. **AC-23's "via `_execute` path ⇒ `CoderResult(status="error", ...)`" does
   not hold structurally as literally worded.** Verified
   `ToolkitTool._execute()` (toolkit.py:145-202) has NO try/except between
   `await toolkit._pre_execute(...)` and the bound method call — a
   `CoderFailure` raised by `_pre_execute` propagates straight out of
   `_execute()` as a Python exception, not as a returned value, so it cannot
   be a `CoderResult` object at that point. The actual observable behavior
   one layer up, at the real invocation surface
   (`MCPToolAdapter.execute(arguments)`, adapter.py:59-95, which is what
   `adapter.py:79` — the anchor this task's own contract cites for "no
   validation in the adapter" — wraps `tool._execute()` in), IS structured:
   its `except Exception` converts the propagated `CoderFailure` into
   `{"isError": True, "content": [...]}`, and — critically — the engine's
   `plan()` method is never invoked (verified via a monkeypatch that raises
   `AssertionError` if called). Implemented and tested this real path
   (`test_toolkit_pre_execute_via_full_execute_path_never_reaches_engine`)
   instead of asserting a literal `CoderResult` return value that the
   verified code cannot produce; the CoderFailure-raises-from-`_pre_execute`
   half of AC-23 is covered directly
   (`test_toolkit_pre_execute_rejects_bad_args`). Flagged for the spec
   author rather than silently reworded in the AC text itself.
