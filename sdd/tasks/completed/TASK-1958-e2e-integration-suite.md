# TASK-1958: End-to-end integration suite

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1953, TASK-1954, TASK-1956
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests". The unit tests in TASK-1947…1957 each verify one
module in isolation. This task verifies the five behaviors that only exist
when the whole pipeline runs together — and that are exactly the ones the
acceptance criteria are written against.

The most important of the five is `test_e2e_kill_switch_restores_behavior`:
it is the executable form of the promise that an unconfigured deployment
behaves exactly as it does today (G2).

---

## Scope

Implement the five integration tests from spec §4, against a real
`ToolManager` with real tools (no mocked stage):

1. `test_e2e_database_query_columnar` — `execute_tool` on a
   `DatabaseQueryToolkit`-shaped result (500 rows × 12 cols) → columnar
   output, metrics in metadata, `AfterToolCallEvent` emitted, measurable size
   reduction.
2. `test_e2e_lossy_roundtrip_via_wm` — `NORMAL` compression → `_tee` pointer
   → `wm_get_result(include_raw=True)` recovers the full original payload
   without re-running the tool.
3. `test_e2e_kill_switch_restores_behavior` — `PARROT_COMPRESSION_DISABLED=1`
   → byte-identical behavior to the pre-feature baseline.
4. `test_e2e_compressed_persists_compressed` — the compressed result is what
   persists to conversational memory; history replay does not recompress.
5. `test_e2e_both_tool_routes` — the pipeline applies identically to a plain
   `AbstractTool` and to a `ToolkitTool` (G1).

Plus the shared fixtures from spec §4 "Test Data / Fixtures":
`row_oriented_payload`, `heterogeneous_payload`, `tool_manager_with_wm`,
`tool_manager_without_wm`, `compressors_toml`.

Also assert the cross-cutting acceptance criteria that only an e2e test can
prove:
- `grep` finds compression logic in exactly ONE place (G1) — a test that
  greps the source tree for a second compression site.
- `_result_hooks` signature and contract unchanged.
- No breaking change to the existing public API of `ToolManager`.

**NOT in scope**:
- Latency/p99 benchmarks → TASK-1959.
- Rust parity → TASK-1955 owns that suite.
- Documentation → TASK-1962.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/compression/test_e2e.py` | CREATE | The five integration tests |
| `packages/ai-parrot/tests/tools/compression/conftest.py` | MODIFY | Add `tool_manager_with_wm`, `tool_manager_without_wm`, `compressors_toml` fixtures (extends the file created by TASK-1954) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.
> A stale build copy exists at
> `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/parrot/` — exclude it
> from any grep-based assertion or the G1 test will produce false positives.

### Verified Imports

```python
from parrot.tools import AbstractTool, ToolResult, AbstractToolkit, ToolkitTool
    # re-export tools/__init__.py:142-143; __all__ entries 216-219
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.decorators import tool_schema            # decorators.py:37
from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.memory import AnswerMemory                     # memory/__init__.py:5
from parrot.core.events.lifecycle.events import AfterToolCallEvent
```

### Existing Signatures to Use

```python
# parrot/tools/manager.py:1379
async def execute_tool(
    self, tool_name: str, parameters: Dict[str, Any],
    permission_context: Optional["PermissionContext"] = None,
) -> Any: ...
def add_result_hook(self, fn: Callable[[str, Any, Dict[str, Any]], None]) -> None: ...  # line 1777
def clone(self, *, include_search_tool: bool = False) -> "ToolManager": ...             # line 1697

# parrot/tools/working_memory/tool.py:44
class WorkingMemoryToolkit(AbstractToolkit):
    tool_prefix: str = "wm"                                       # line 78
    async def store_result(self, key, data, data_type="auto",     # def at line 205
                           description="", metadata=None, turn_id=None) -> dict: ...
    async def get_result(self, key, max_length=500,               # def at line 256
                         include_raw=False) -> dict: ...

# parrot/tools/databasequery/base.py:148
class QueryResult(BaseModel):
    driver: str; rows: list[dict[str, Any]]; row_count: int
    columns: list[str]; execution_time_ms: float

# parrot/tools/toolkit.py
class ToolkitTool(AbstractTool): ...        # line 32
class AbstractToolkit(ABC): ...             # line 207
async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any: ...  # line 390
```

### Does NOT Exist

- ~~A pre-existing e2e compression test~~ — you are writing the first.
- ~~`MAX_TOOL_RESULT_CHARS` outside `parrot/clients/google/client.py`~~ —
  `claude.py` / `groq.py` / `grok.py` have NO equivalent truncation (only
  unrelated `[:100]` log slices and a max-tokens warning string). The G1 grep
  assertion must account for the Google client's client-side truncation being
  a legitimate *last* line of defense, not a second compression site.
- ~~`parrot/` at the repo root~~ — the package lives at
  `packages/ai-parrot/src/parrot/`; scope all greps there.
- ~~A tokenizer~~ — size assertions must be in **bytes**, not tokens.

---

## Implementation Notes

### Key Constraints

- Use real objects: a real `ToolManager`, a real `WorkingMemoryToolkit`, real
  codecs. Mocking the stage defeats the purpose of this task.
- The kill-switch test needs a genuine baseline. Capture the expected output
  by running the same tool with `PARROT_COMPRESSION_DISABLED=1` and asserting
  it equals the raw tool output — do not hardcode a fixture that could drift.
- `test_e2e_compressed_persists_compressed`: verify both directions — what
  lands in memory is compressed, AND replaying it does not compress again
  (the `_compressed` marker gate).
- `test_e2e_both_tool_routes` must construct one plain `AbstractTool` and one
  real `AbstractToolkit` (whose tools are `ToolkitTool`), and assert identical
  compression metadata for identical payloads.
- The G1 grep test should exclude `build/`, `.claude/worktrees/`, and test
  files themselves.
- Mark slow tests appropriately; a 500 × 12 payload is fine, do not scale it
  to 500k rows here (that belongs in TASK-1959).

### References in Codebase

- `packages/ai-parrot/tests/tools/` — existing tool test conventions
  (e.g. `test_grants.py`, `databasequery/`).
- `parrot/tools/working_memory/tests/test_working_memory.py` — in-package WM
  test patterns.

---

## Acceptance Criteria

- [ ] All five spec §4 integration tests implemented and passing.
- [ ] Fixtures match the names and docstrings in spec §4 "Test Data /
      Fixtures".
- [ ] `test_e2e_kill_switch_restores_behavior` compares against a
      dynamically-captured baseline, not a hardcoded literal.
- [ ] G1 assertion: no second compression site in
      `packages/ai-parrot/src/parrot/` (build dir and worktrees excluded).
- [ ] `_result_hooks` contract assertion passes.
- [ ] Suite passes with the Rust extension ABSENT.
- [ ] Suite passes on both tool routes.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_e2e.py
import os
import pytest


class TestEndToEnd:
    async def test_e2e_database_query_columnar(self, tool_manager_with_wm,
                                               row_oriented_payload, captured_events):
        out = await tool_manager_with_wm.execute_tool("execute_database_query", {})
        assert "columns" in out["rows"]
        evt = captured_events.of_type("AfterToolCallEvent")[-1]
        assert evt.compression_codec == "columnar"
        assert evt.result_size_bytes < evt.result_size_bytes_original

    async def test_e2e_lossy_roundtrip_via_wm(self, tool_manager_with_wm,
                                              row_oriented_payload):
        out = await tool_manager_with_wm.execute_tool("execute_database_query", {})
        key = out["_tee"]["key"]
        wm = tool_manager_with_wm.get_toolkit("working_memory")
        recovered = await wm.get_result(key=key, include_raw=True)
        assert recovered["raw"] == row_oriented_payload      # no tool re-run

    async def test_e2e_kill_switch_restores_behavior(self, tool_manager_with_wm,
                                                     monkeypatch):
        monkeypatch.setenv("PARROT_COMPRESSION_DISABLED", "1")
        disabled = await tool_manager_with_wm.execute_tool("execute_database_query", {})
        monkeypatch.delenv("PARROT_COMPRESSION_DISABLED")
        enabled = await tool_manager_with_wm.execute_tool("execute_database_query", {})
        assert disabled != enabled
        assert disabled == RAW_TOOL_OUTPUT                  # captured, not hardcoded

    async def test_e2e_compressed_persists_compressed(self, tool_manager_with_wm):
        out = await tool_manager_with_wm.execute_tool("execute_database_query", {})
        # replay: feeding the already-compressed payload back does nothing
        again, meta = await tool_manager_with_wm._compression_stage.run(
            "execute_database_query", out, status="success",
            metadata={"_compressed": True}, return_direct=False,
        )
        assert again is out

    async def test_e2e_both_tool_routes(self, tool_manager_with_wm):
        a = await tool_manager_with_wm.execute_tool("plain_bulky_tool", {})
        b = await tool_manager_with_wm.execute_tool("toolkit_bulky_tool", {})
        assert _shape(a) == _shape(b)


def test_compression_logic_exists_in_exactly_one_place():
    """G1: no per-client compression anywhere."""
    import subprocess
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", "-l", "CompressionStage",
         "packages/ai-parrot/src/parrot/"],
        capture_output=True, text=True,
    ).stdout.split()
    assert all("/compression/" in h or h.endswith("manager.py") for h in hits)


def test_result_hooks_contract_untouched():
    import inspect
    from parrot.tools.manager import ToolManager
    assert list(inspect.signature(ToolManager.add_result_hook).parameters) == ["self", "fn"]
```

---

## Agent Instructions

1. **Read the spec** (§4 Integration Tests + Fixtures, §5 acceptance criteria).
2. **Check dependencies** — TASK-1953, TASK-1954, TASK-1956 must all be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — confirm the fixtures' target APIs.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope. Prefer real objects over mocks throughout.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — list any acceptance criterion you could
   NOT prove with a test and why.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous, Sonnet) + adversarial code-review fix pass
**Date**: 2026-07-28
**Notes**: Implemented per spec in the FEAT-380 worktree
(`feat-FEAT-380-tool-result-compression`); acceptance criteria verified via
`pytest packages/ai-parrot/tests/tools/compression/` (144 passed, 6 skipped)
and, where applicable, `cargo test` in `codec-rs/` (12 passed). An
adversarial code review (Claude subagent + Codex, independently verified)
found 3 BLOCKING and 4 SHOULD-FIX cross-cutting issues after all 15 tasks
landed; all were fixed in a follow-up commit
(`fix(tool-result-compression): resolve adversarial code-review findings`)
with 9 additional regression tests, re-verified green.

**Deviations from spec**: none beyond what each task's own file documents
(e.g. TASK-1959's latency recalibration, TASK-1961's truncation
demotion) — see the code-review fix commit for the post-hoc corrections
above.
