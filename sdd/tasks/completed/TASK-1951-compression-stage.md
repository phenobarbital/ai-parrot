# TASK-1951: `CompressionStage` — gates, level resolution, codec dispatch, metrics

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1948, TASK-1949, TASK-1950
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (the stage itself). `CompressionStage` is the pure,
independently testable core of the pipeline: given a tool name, a payload, a
status and metadata, it decides whether to compress, with which codec, at
which level, on which route — and returns the (possibly compressed) payload
plus metrics.

It is deliberately decoupled from `ToolManager`: this task must not touch
`manager.py`. Wiring the stage into `execute_tool()` is TASK-1952. That split
keeps the hot-path edit small and reviewable.

---

## Scope

- Implement `stage.py` with `CompressionStage`:
  - Constructor takes the `CompressorRegistry`, a `BudgetRouter`, and an
    optional tee callback (`None` until TASK-1953 supplies one).
  - `async def run(tool_name, payload, *, status, metadata, return_direct,
    level_override=None) -> tuple[Any, dict]` — returns
    `(payload, compression_metadata)`.
- **Entry gates** (any one → full passthrough, tee included, zero metrics
  beyond a `skipped` reason):
  1. `PARROT_COMPRESSION_DISABLED=1` env kill switch
  2. `return_direct is True`
  3. `metadata` already carries the `_compressed` marker (idempotency /
     fresh-execution-only)
- **Effective-level precedence** (highest wins), exactly per spec §2:
  1. per-call override (`level_override`)
  2. `status != "success"` → forces `FilterLevel.NONE` (G5)
  3. `tool_name` entry in the registry
  4. global configured default
  5. `FilterLevel.MINIMAL` when nothing configured (G2)
- **Codec dispatch**: resolve the entry via `registry.resolve(tool_name)`, get
  the codec class via `get_codec(entry.codec)`, ask `BudgetRouter.route(...)`,
  then run inline, via `loop.run_in_executor(...)`, or passthrough.
- **Safety**: the whole codec invocation is wrapped in `try/except Exception`
  → return the ORIGINAL payload + `logger.warning`. A broken codec can never
  break a tool call, and the exception never propagates.
- **Metrics**: write into the returned compression metadata dict:
  `_compressed` (marker), `compression_codec`, `compression_level`,
  `result_size_bytes_original`, `result_size_bytes`,
  `compression_duration_ms`, `compression_teed`, plus a `compression_skipped`
  reason when a gate fired.
- Record every call into the `BudgetRouter` (`record(...)`) so the circuit
  breaker sees real durations.
- Call the tee callback when `outcome.lossy` is `True` (callback is `None` in
  this task; TASK-1953 provides the real one).

**NOT in scope**:
- Any edit to `parrot/tools/manager.py` → TASK-1952.
- Any edit to `parrot/core/events/lifecycle/events/tool.py` → TASK-1952.
- The tee implementation itself → TASK-1953. Here it is an injected callback
  with signature `Callable[[str, Any, str], str | None]` returning the tee key.
- The `columnar` codec → TASK-1954.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/stage.py` | CREATE | `CompressionStage` |
| `packages/ai-parrot/src/parrot/tools/compression/__init__.py` | MODIFY | Export `CompressionStage` |
| `packages/ai-parrot/tests/tools/compression/test_stage.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
import os
import asyncio
import logging
import time

# Created by TASK-1947 / 1948 / 1950:
from parrot.tools.compression import (
    FilterLevel, CompressionOutcome, CompressorRegistry, get_codec,
)
from parrot.tools.compression.levels import cap
from parrot.tools.compression.budget import Route, BudgetRouter
```

### Existing Signatures to Use

```python
# parrot/tools/manager.py:1490-1506 — VERBATIM, the context this stage will be
# wired into by TASK-1952. Read it; do NOT edit it in this task.
result = await tool.execute(**exec_kwargs)
if isinstance(result, ToolResult):
    if result.status == 'forbidden':
        return result
    if result.status == "error":
        raise ValueError(result.error)         # ← TASK-1953 reorders this
    out = result.result
    meta = getattr(result, "metadata", {}) or {}
else:
    out = result
    meta = {}
self._postprocess_result(tool_name, out, meta)     # def at manager.py:1663
self._run_result_hooks(tool_name, out, meta)       # def at manager.py:1781
return out                                          # ← UNWRAPPED payload

# parrot/tools/toolkit.py:390 — the transformer-contract precedent
# (return value REPLACES the result; note the positional-only marker `/`)
async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any: ...

# parrot/tools/abstract.py:126
class AbstractTool(EventEmitterMixin, ABC):
    return_direct: bool = False                       # line 144
```

`ToolResult.status` verified literals in `parrot/tools/`: `"success"`,
`"error"`, `"forbidden"`, `"pending"`, `"authorization_required"`,
`"not_found"` (manager.py:1403), `"done_with_errors"`, plus `"cancelled"` /
`"timeout"` reachable via `status=confirm_decision.status` (manager.py:1460).
**The G5 gate treats everything `!= "success"` as non-compressible** — do not
enumerate the error literals, negate the success one.

### Does NOT Exist

- ~~`ToolManager.add_result_hook` with a transforming return~~ — hooks are
  `Callable[[str, Any, Dict[str, Any]], None]` **observers**
  (manager.py:1777/1781). This stage is a NEW, separate chain; the
  `_result_hooks` contract must stay untouched.
- ~~`AbstractToolkit._post_execute()` invoked for plain `AbstractTool`~~ —
  toolkit-only hook; non-toolkit tools never pass through it. You cannot use
  it as the compression insertion point.
- ~~`ToolResult.compressed` / `ToolResult.compress()`~~ — zero occurrences.
  The marker lives in `metadata`, keyed `_compressed`.
- ~~A tee implementation~~ — TASK-1953. Inject it; do not write it here.
- ~~`parrot_codec`~~ — the Rust extension does not exist yet; `rust_available`
  is `False` and all tests must pass in that state.

---

## Implementation Notes

### Pattern to Follow

```python
async def run(self, tool_name, payload, *, status, metadata,
              return_direct, level_override=None):
    if os.getenv("PARROT_COMPRESSION_DISABLED") == "1":
        return payload, {"compression_skipped": "kill_switch"}
    if return_direct:
        return payload, {"compression_skipped": "return_direct"}
    if metadata.get("_compressed"):
        return payload, {"compression_skipped": "already_compressed"}

    level = self._effective_level(tool_name, status, level_override)
    if level is FilterLevel.NONE:
        return payload, {"compression_skipped": "level_none"}
    ...
    started = time.perf_counter()
    try:
        route = self._router.route(payload, level=level, codec_name=entry.codec,
                                   rust_available=self._rust_available)
        if route is Route.PASSTHROUGH:
            return payload, {"compression_skipped": "budget_passthrough"}
        if route is Route.INLINE:
            outcome = codec.compress(payload, level=level, params=entry.params)
        else:
            loop = asyncio.get_running_loop()
            outcome = await loop.run_in_executor(
                None, partial(codec.compress, payload, level=level, params=entry.params)
            )
    except Exception as exc:                      # G: never break a tool call
        self.logger.warning("Compressor %s failed for %s: %s", entry.codec, tool_name, exc)
        return payload, {"compression_skipped": "codec_error"}
    finally:
        self._router.record(entry.codec, (time.perf_counter() - started) * 1000, route)
```

### Key Constraints

- The stage NEVER raises. Every failure path returns the original payload.
- `_compressed` is written into the returned metadata dict so the marker
  persists with the result into conversational memory — that is what makes
  history replay a passthrough.
- Do not mutate the caller's `metadata` dict in place; return a new dict and
  let TASK-1952 merge it.
- `run()` is `async` only because of the executor branch; the inline branch
  must not `await` anything (sub-millisecond budget).
- Use `functools.partial` for the executor call — `run_in_executor` does not
  forward keyword arguments.
- `self.logger = logging.getLogger(__name__)`; never `print`.
- Google-style docstrings + strict type hints.

### References in Codebase

- `parrot/tools/toolkit.py:390` — transformer contract precedent.
- `parrot/tools/pythonrepl.py:969` — `run_in_executor` call shape.

---

## Acceptance Criteria

- [ ] `test_stage_gates`: kill switch, `return_direct=True`, `_compressed`
      marker → pipeline fully skipped (tee callback NOT invoked).
- [ ] `test_error_status_forces_none`: `status != "success"` → level `NONE`
      regardless of registry entry (G5).
- [ ] `test_compressor_exception_returns_original`: codec raises → original
      payload returned intact, `logger.warning` emitted, no exception escapes.
- [ ] `test_idempotency_marker`: re-running a `_compressed`-marked payload →
      passthrough.
- [ ] Effective-level precedence covers all 5 rules in order.
- [ ] Metrics dict carries all documented keys on the happy path.
- [ ] `BudgetRouter.record()` is called even when the codec raises.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_stage.py
import pytest
from parrot.tools.compression import FilterLevel, CompressorRegistry
from parrot.tools.compression.budget import BudgetRouter
from parrot.tools.compression.stage import CompressionStage


@pytest.fixture
def stage(tmp_path):
    return CompressionStage(
        registry=CompressorRegistry.load(project_root=tmp_path),
        router=BudgetRouter(),
    )


class TestGates:
    @pytest.mark.parametrize("kwargs,env", [
        ({}, {"PARROT_COMPRESSION_DISABLED": "1"}),
        ({"return_direct": True}, {}),
    ])
    async def test_stage_gates(self, stage, monkeypatch, kwargs, env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        data = {"a": None}
        out, meta = await stage.run(
            "t", data, status="success", metadata={},
            return_direct=kwargs.get("return_direct", False),
        )
        assert out is data
        assert "compression_skipped" in meta

    async def test_idempotency_marker(self, stage):
        data = {"a": None}
        out, meta = await stage.run(
            "t", data, status="success", metadata={"_compressed": True},
            return_direct=False,
        )
        assert out is data
        assert meta["compression_skipped"] == "already_compressed"


class TestLevelPrecedence:
    async def test_error_status_forces_none(self, stage):
        data = {"a": None}
        out, meta = await stage.run(
            "t", data, status="error", metadata={}, return_direct=False,
        )
        assert out is data

    async def test_per_call_override_wins(self, stage):
        data = {"a": None, "b": 1}
        out, _ = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
            level_override=FilterLevel.NONE,
        )
        assert out is data


class TestSafety:
    async def test_compressor_exception_returns_original(self, stage, monkeypatch, caplog):
        from parrot.tools.compression import get_codec
        codec_cls = get_codec("json_compact")
        monkeypatch.setattr(
            codec_cls, "compress",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        data = {"a": 1}
        out, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
        )
        assert out is data
        assert any("boom" in r.message or "json_compact" in r.message
                   for r in caplog.records)


class TestMetrics:
    async def test_happy_path_metadata_keys(self, stage):
        data = {"rows": [{"a": 1, "b": None} for _ in range(30)]}
        _, meta = await stage.run(
            "t", data, status="success", metadata={}, return_direct=False,
        )
        for key in ("_compressed", "compression_codec", "compression_level",
                    "result_size_bytes_original", "result_size_bytes",
                    "compression_duration_ms", "compression_teed"):
            assert key in meta
```

---

## Agent Instructions

1. **Read the spec** (§2 precedence tables, §3 Module 2, §7 risks).
2. **Check dependencies** — TASK-1948, TASK-1949, TASK-1950 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `manager.py:1490-1506` to
   confirm the fragment is unchanged before designing the stage signature.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope. Do NOT edit `manager.py`.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-07-27
**Notes**: Implemented `CompressionStage` (`stage.py`) exactly per the
given pattern: three entry gates (kill switch, `return_direct`,
`_compressed` marker) each short-circuit with a `compression_skipped`
reason before the tee callback could ever be invoked; 5-rule effective-level
precedence (`_effective_level`, with rules 3+4 delegated to
`CompressorRegistry.resolve()`'s exact>glob>wildcard match, rule 5 as a
defensive MINIMAL fallback for an entry-less registry); codec dispatch via
`BudgetRouter.route()` → inline / `run_in_executor` (via `functools.partial`)
/ passthrough; the whole dispatch wrapped in `try/except/finally` so a
broken codec always returns the original payload with a warning and
`BudgetRouter.record()` always fires. Metadata dict built fresh (never
mutates the caller's `metadata`) with all 7 documented keys plus
`compression_tee_key` when teed. Did NOT touch `manager.py` or the events
package (verified out of scope). Exported `CompressionStage` from
`compression/__init__.py`. 36 new tests pass (gates never invoking tee,
all 5 precedence rules incl. override-outranks-error-status, codec
exception safety, record-called-on-exception, unknown-codec passthrough via
a hand-built unvalidated registry, tee invocation on lossy outcomes with and
without a callback, budget passthrough/executor routes). Full compression
suite: 65/65 green. `ruff check` clean.

**Deviations from spec**: none
