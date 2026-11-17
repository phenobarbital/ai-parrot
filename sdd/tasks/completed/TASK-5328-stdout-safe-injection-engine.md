# TASK-5328: Stdout-safe injection-engine resolution + bound stdio output stream

**Feature**: FEAT-844 — PageIndex Toolkit Fixes
**Spec**: `sdd/specs/pageindex-toolkit-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:70f18da2a8d5`

---

## Context

Implements spec §3 **Module 1**. Over `parrot mcp-local pageindex`, the first ingest runs
`PageIndexToolkit._scan`, which resolves the ML prompt-injection scorer through
`get_injection_scoring_engine` in a worker thread. pytector's fallback engine `print()`s
`Loading Hugging Face model from: …` to **stdout** at that moment — at tool-call time, outside the
factory's `redirect_stdout(sys.stderr)` block — so a non-JSON line lands on the JSON-RPC channel
(ledger `issue:70f18da2a8d5`, found by FEAT-842 TASK-5318). `StdioMCPServer._send` also reads the
*name* `sys.stdout` on every write, so any process-wide redirect would misroute protocol frames.

Ledger context (`wikitoolkit ledger context` over the group's files): every other open issue on
these files is handled by TASK-5329..5331; no other claim touches `security/prompt_injection.py`
or `mcp/local_server.py`.

---

## Scope

- In `get_injection_scoring_engine`, run the lazy import **and** `_resolve_injection_engine(...)`
  inside `contextlib.redirect_stdout(sys.stderr)`; document why in the docstring.
- In `StdioMCPServer`: add `self._stdout: Optional[TextIO] = None` in `__init__`, bind
  `self._stdout = sys.stdout` at the top of `start()` (next to `self._running = True`), and make
  `_send` write to `self._stdout if self._stdout is not None else sys.stdout`.
- Tests: new `tests/security/test_prompt_injection_stdout.py` (resolver banner → stderr, for the
  plain call and for the `PageIndexToolkit._scan` path); two new tests in
  `tests/mcp/test_local_server.py` (bound stream survives a redirect; fallback before `start()`).

**NOT in scope**: `_scan` itself (unchanged); eager engine resolution in the toolkit constructor;
the pageindex MCP template; the model download on first ingest (spec Non-Goals); any xfail removal
(the merged `test_pageindex_serves_over_stdio` carries none).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/prompt_injection.py` | MODIFY | redirect around resolution; add `contextlib`, `sys` imports |
| `packages/ai-parrot/src/parrot/mcp/local_server.py` | MODIFY | `_stdout` bound in `start()`, used by `_send` |
| `packages/ai-parrot/tests/security/test_prompt_injection_stdout.py` | CREATE | AC-1 tests |
| `packages/ai-parrot/tests/mcp/test_local_server.py` | MODIFY | AC-2 tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `origin/dev` @ `a3dec1c902` (2026-11-08). Re-locate anchors with `grep -nF`; a count
> of `0` means drift — stop and report.

### Verified Imports
```python
from parrot.security.prompt_injection import get_injection_scoring_engine          # prompt_injection.py:313
from parrot.bots.guardrails.builtin.prompt_injection import _resolve_injection_engine  # guardrails/builtin/prompt_injection.py:503 (lazy, inside the function)
from parrot.mcp.local_server import StdioMCPServer                                 # local_server.py:54
from parrot.mcp.server_base import LocalServerConfig                               # local_server.py:28
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                    # toolkit.py:89
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/prompt_injection.py
# imports at :4-8 — typing, enum, re, datetime, navconfig.logging. NO `contextlib`, NO `sys` yet.
def get_injection_scoring_engine(force_reresolve: bool = False) -> Optional[InjectionScoringEngine]:  # :313
    try:                                                                                              # :320
        from parrot.bots.guardrails.builtin.prompt_injection import _resolve_injection_engine         # :321
        return _resolve_injection_engine(force_reresolve)                                             # :322
    except Exception as exc:  # noqa: BLE001                                                          # :323
        logger.warning("ML injection scoring engine unavailable: %s", exc)
        return None

# packages/ai-parrot/src/parrot/mcp/local_server.py
import asyncio, json, logging, sys ; from typing import Any                                            # :22-26
class StdioMCPServer(LocalMCPServerBase):                                                              # :54
    def __init__(self, config: LocalServerConfig):                                                     # :63
        self._by_request_id: dict[Any, "asyncio.Task[None]"] = {}                                      # :68 (last line of __init__)
    async def start(self):                                                                             # :70
        self._running = True                                                                           # :80
    def _send(self, response: dict[str, Any]) -> None:                                                 # :197
        sys.stdout.write(json.dumps(response) + "\n")                                                  # :203
        sys.stdout.flush()                                                                             # :204

# packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py
from parrot.security.prompt_injection import PromptInjectionDetector, get_injection_scoring_engine     # :68
class PageIndexToolkit(AbstractToolkit):
    def __init__(..., storage_dir=None, ..., scan_injection: bool = True, ...)                          # :213 keyword
    async def _scan(self, segments: list) -> Optional[ScanReport]:                                     # :1617
        engine = await asyncio.to_thread(get_injection_scoring_engine)                                  # :1622
        return await scan_segments(segments, detector=self._detector, engine=engine, threshold=...)    # :1623

# packages/ai-parrot/tests/mcp/test_local_server.py
class TestStdioMCPServer:                                                                              # :36
    # tests build `StdioMCPServer(LocalServerConfig(name="test"))` (:39) and use `capsys`/`monkeypatch`
    async def test_slow_tool_does_not_block_later_requests(self, monkeypatch, capsys):                 # :113
```

### Does NOT Exist
- ~~`StdioMCPServer._stdout`~~ — created by this task.
- ~~`parrot.security.prompt_injection.contextlib` / `sys`~~ — not imported yet; add both.
- ~~`pytest.mark.xfail` on `tests/mcp/test_pageindex_template.py::test_pageindex_serves_over_stdio`~~ — none; do not touch that file.
- ~~`PageIndexToolkit._injection_engine`~~ — no cached engine attribute; `_scan` resolves per call (memoized inside the guardrail module).
- ~~`StdioMCPServer.start(stdout=...)`~~ — `start()` takes no arguments; the stream is read from `sys.stdout` when it runs.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/security/prompt_injection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/mcp/local_server.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/security/test_prompt_injection_stdout.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/mcp/test_local_server.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/prompt_injection.py#get_injection_scoring_engine",
    "sym:packages/ai-parrot/src/parrot/bots/guardrails/builtin/prompt_injection.py#_resolve_injection_engine",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer",
    "sym:packages/ai-parrot/src/parrot/mcp/local_server.py#StdioMCPServer._send",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py#PageIndexToolkit._scan"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `contextlib.redirect_stdout` rebinds the process-global `sys.stdout`; that is exactly why the
  transport must capture its stream once (spec §7 Risks). Capture in `start()`, **not** in
  `__init__`: `create_toolkit_mcp_server` constructs the server inside its own
  `redirect_stdout(sys.stderr)` block (`toolkit_server.py:310`), so an `__init__`-time capture
  would bind stderr. `start()` runs from `asyncio.run(...)` in `local_cli.py:291`, outside any redirect.
- Never use `sys.__stdout__`: pytest's `capsys` replaces `sys.stdout` before `start()` runs and the
  existing `test_slow_tool_does_not_block_later_requests` reads frames through `capsys`.
- The redirect in `get_injection_scoring_engine` wraps the *whole* try body (import + resolve): the
  import itself can trigger pytector/transformers banners.
- Logging stays on `logger` (module logger in `security/prompt_injection.py`, `self.logger` in the server).

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/toolkit_server.py:131,310` and `local_cli.py:258` — the existing redirect pattern.
- `packages/ai-parrot/tests/knowledge/pageindex/test_read_tools.py:38-41` — tests monkeypatch
  `parrot.knowledge.pageindex.toolkit.get_injection_scoring_engine`; unaffected by this change.

---

## Implementation Blueprint

### Steps (in order)
1. Add `import contextlib` and `import sys` to `security/prompt_injection.py` — *why*: both are needed by the redirect and are not imported today.
2. Wrap the resolver call — *why*: the banner is printed during resolution (first call), so the redirect must enclose the import and the call.
3. Add `_stdout` to `StdioMCPServer.__init__`, bind it in `start()`, use it in `_send` — *why*: AC-2, frames must survive a process-wide redirect.
4. Write the four tests — *why*: AC-1/AC-2 must be deterministic (no real model load).

### `packages/ai-parrot/src/parrot/security/prompt_injection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from typing import Optional, Dict, Any, List, Protocol, Tuple, runtime_checkable' packages/ai-parrot/src/parrot/security/prompt_injection.py)
# BEFORE — insert above `from typing import Optional, Dict, Any, List, Protocol, Tuple, runtime_checkable` (verified: prompt_injection.py:4)
import contextlib
import sys

# occurrences: 1 (verified: grep -cF 'def get_injection_scoring_engine(force_reresolve: bool = False) -> Optional[InjectionScoringEngine]:' packages/ai-parrot/src/parrot/security/prompt_injection.py)
# REPLACE the whole function body (verified: prompt_injection.py:313-325) with:
def get_injection_scoring_engine(force_reresolve: bool = False) -> Optional[InjectionScoringEngine]:
    """Return the process-wide ML engine the PromptInjectionGuardrail uses, or ``None`` (regex only).

    The resolution chain lives in ``parrot.bots.guardrails.builtin.prompt_injection``, which owns the
    pytector/onnxruntime import boundary; it is imported lazily here so ``parrot.security`` never
    imports ``parrot.bots`` at module import time. Import and resolution run with stdout redirected
    to stderr: pytector prints a "Loading Hugging Face model …" banner on first use, and a caller
    serving a stdio JSON-RPC channel (``parrot mcp-local``) must never see it on stdout. Never raises.
    """
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.bots.guardrails.builtin.prompt_injection import _resolve_injection_engine

            return _resolve_injection_engine(force_reresolve)
    except Exception as exc:  # noqa: BLE001 - callers fall back to the regex detector
        logger.warning("ML injection scoring engine unavailable: %s", exc)
        return None
```
**Why this shape**: the redirect encloses both the lazy import and the memoized resolver call, so
the first (and only printing) resolution can never reach stdout; the memoized path costs one stream
swap. The signature and the never-raises contract are fixed by the spec.

### `packages/ai-parrot/src/parrot/mcp/local_server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from typing import Any' packages/ai-parrot/src/parrot/mcp/local_server.py)
# REPLACE `from typing import Any` (verified: local_server.py:26) with:
from typing import Any, Optional, TextIO

# occurrences: 1 (verified: grep -cF '        self._by_request_id: dict[Any, "asyncio.Task[None]"] = {}' packages/ai-parrot/src/parrot/mcp/local_server.py)
# AFTER — insert below `        self._by_request_id: dict[Any, "asyncio.Task[None]"] = {}` (verified: local_server.py:68)
        # The JSON-RPC output stream, bound once in start(). Reading `sys.stdout` per write would
        # follow any later process-wide redirect (a library banner guard, for example) and misroute frames.
        self._stdout: Optional[TextIO] = None

# occurrences: 1 (verified: grep -cF '        self._running = True' packages/ai-parrot/src/parrot/mcp/local_server.py)
# AFTER — insert below `        self._running = True` (verified: local_server.py:80)
        self._stdout = sys.stdout

# occurrences: 1 (verified: grep -cF '        sys.stdout.write(json.dumps(response) + "\n")' packages/ai-parrot/src/parrot/mcp/local_server.py)
# REPLACE the two lines `sys.stdout.write(json.dumps(response) + "\n")` / `sys.stdout.flush()` (verified: local_server.py:203-204) with:
        out = self._stdout if self._stdout is not None else sys.stdout
        out.write(json.dumps(response) + "\n")
        out.flush()
```
**Why**: binding at `start()` (not `__init__`) is deliberate — see Key Constraints. The
`None` fallback keeps every existing unit test that calls `_handle_request`/`_send` without
`start()` writing to `sys.stdout` (and so to `capsys`). Also extend the `_send` docstring with one
sentence: "Writes to the stream bound in :meth:`start` (``sys.stdout`` before ``start()`` runs)."

### `packages/ai-parrot/tests/security/test_prompt_injection_stdout.py` (CREATE)
```python
"""The injection-scorer resolver must never write to stdout (FEAT-844 / issue:70f18da2a8d5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.security.prompt_injection import get_injection_scoring_engine

BANNER = "Loading Hugging Face model from: protectai/deberta-v3-base-prompt-injection"


def _printing_resolver(force_reresolve: bool = False):
    print(BANNER)  # noqa: T201 - simulates pytector's banner
    return None


def test_get_injection_scoring_engine_keeps_stdout_clean(monkeypatch, capsys) -> None:
    """AC-1: the banner lands on stderr, stdout stays empty, the result is passed through."""
    monkeypatch.setattr(
        "parrot.bots.guardrails.builtin.prompt_injection._resolve_injection_engine", _printing_resolver
    )
    assert get_injection_scoring_engine() is None
    captured = capsys.readouterr()
    assert captured.out == ""
    assert BANNER in captured.err


async def test_scan_resolution_keeps_stdout_clean(monkeypatch, capsys, tmp_path: Path) -> None:
    """AC-1 via the toolkit path that the stdio server hits on first ingest."""
    monkeypatch.setattr(
        "parrot.bots.guardrails.builtin.prompt_injection._resolve_injection_engine", _printing_resolver
    )

    async def _no_scan(segments, *, detector, engine, threshold):
        return None

    monkeypatch.setattr("parrot.knowledge.pageindex.toolkit.scan_segments", _no_scan)
    toolkit = PageIndexToolkit(storage_dir=tmp_path)
    # FILL IN: await toolkit._scan([object()]) ; assert capsys.readouterr().out == "" and BANNER in .err
    #   — bounded by AC-1 (no real model load; scan_segments is stubbed)
```
**Why**: both tests stub the resolver, so they are deterministic and never touch a model; the
second test proves the exact call path (`asyncio.to_thread(get_injection_scoring_engine)`).

### `packages/ai-parrot/tests/mcp/test_local_server.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    async def test_slow_tool_does_not_block_later_requests(self, monkeypatch, capsys):' packages/ai-parrot/tests/mcp/test_local_server.py)
# BEFORE — insert above `    async def test_slow_tool_does_not_block_later_requests(self, monkeypatch, capsys):` (verified: test_local_server.py:113), inside class TestStdioMCPServer
    def test_send_uses_stream_bound_at_start(self):
        """AC-2: a redirect active during _send does not capture the frame."""
        import io
        server = StdioMCPServer(LocalServerConfig(name="test"))
        bound, other = io.StringIO(), io.StringIO()
        server._stdout = bound  # what start() binds from sys.stdout
        with contextlib.redirect_stdout(other):
            server._send({"jsonrpc": "2.0", "id": 1, "result": {}})
        # FILL IN: assert json.loads(bound.getvalue()) == {...} and other.getvalue() == "" — bounded by AC-2

    def test_send_before_start_writes_sys_stdout(self, capsys):
        """AC-2 fallback: without start(), _send still writes to sys.stdout."""
        server = StdioMCPServer(LocalServerConfig(name="test"))
        server._send({"jsonrpc": "2.0", "id": 2, "result": {}})
        # FILL IN: assert json.loads(capsys.readouterr().out.strip())["id"] == 2 — bounded by AC-2
```
**Why**: `contextlib` and `json` are already imported at the top of this test module (:2-3).
Binding `_stdout` directly stands in for `start()`, which needs a stdin loop.

### FILL IN checklist
- [ ] `test_scan_resolution_keeps_stdout_clean` body — bounded by AC-1
- [ ] `test_send_uses_stream_bound_at_start` / `test_send_before_start_writes_sys_stdout` assertions — bounded by AC-2
- [ ] `_send` docstring sentence

---

## Acceptance Criteria

- [ ] AC-1 `get_injection_scoring_engine()` with a resolver that prints leaves `capsys.readouterr().out == ""`; banner on stderr.
- [ ] AC-2 `_send` writes to the stream bound in `start()` even under `redirect_stdout`; before `start()` it writes to `sys.stdout`.
- [ ] Existing `tests/mcp/test_local_server.py` and `tests/mcp/test_pageindex_template.py::test_pageindex_serves_over_stdio` still pass.
- [ ] AC-13 `ruff check` clean on the four files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/security/test_prompt_injection_stdout.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_local_server.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_pageindex_template.py::test_pageindex_serves_over_stdio -q`
- `pytest packages/ai-parrot/tests/knowledge/pageindex/test_injection_scan.py -q`

---

## Test Specification

See the CREATE block for `test_prompt_injection_stdout.py` and the MODIFY block for
`test_local_server.py` above.

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug pageindex-toolkit-fixes --feature-id FEAT-844`); never on `dev`.
2. Re-locate every anchor with `grep -nF`; mark `in-progress` in `sdd/tasks/index/pageindex-toolkit-fixes.json`, commit only the index.
3. Implement from the blueprint; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Commit the four files; `parrot sdd task close TASK-5328 pageindex-toolkit-fixes verified`; fill the Completion Note; commit the SDD state.

---

## Completion Note

**Completed by**: Claude Opus 5.5 (/sdd-fix session agent:sdd-fix:507d6e6a)
**Date**: 2026-11-08
**Notes**: `get_injection_scoring_engine` now runs the lazy import and `_resolve_injection_engine` inside `contextlib.redirect_stdout(sys.stderr)` (imports added). `StdioMCPServer` gained `_stdout` (None until `start()` binds `sys.stdout`); `_send` writes to it with a `sys.stdout` fallback. Tests: 3 in the new `tests/security/test_prompt_injection_stdout.py` (plain call, engine pass-through, `_scan` path) and 2 in `tests/mcp/test_local_server.py` (bound stream under redirect; fallback). Validation: 20 passed incl. `test_pageindex_serves_over_stdio`; ruff clean. Black was not applied: all three modified files were already non-conformant at base, and reformatting them is outside scope. Code commit: b797bdcc71.

**Deviations from spec**: none
