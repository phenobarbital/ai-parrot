# TASK-1953: Compression tee — working-memory escape hatch + error-branch reorder

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1952
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. G3 says **no unrecoverable loss**: anything lossy-compressed
must be recoverable by the agent without re-running the tool. The tee is that
guarantee — it writes the full payload into the session's
`WorkingMemoryToolkit` and appends a `_tee` pointer to the compressed result so
the LLM can call `wm_get_result` to get the original back.

It also fixes a pre-existing information sink: `execute_tool()` currently does
`raise ValueError(result.error)` and **discards `result.result`** entirely. The
error branch is reordered so the payload is captured for the tee *before* the
raise. The exception still raises identically — no observable change for
callers.

If no `WorkingMemoryToolkit` is registered, the tee is disabled AND the
effective level is capped to `MINIMAL`: never lossy without recovery.

---

## Scope

- Implement `tee.py`:
  - `CompressionTee` with an async `store(tool_name, payload, reason) -> str |
    None` that calls `WorkingMemoryToolkit.store_result()` and returns the key.
  - Key format `__tee__:<tool_name>:<turn_id>:<counter>` — the counter defends
    against `WorkingMemoryCatalog.put_generic()` silently overwriting a
    same-turn tee.
  - `attach_pointer(payload, key, reason) -> Any` — appends the `_tee` block
    described in spec §2.
  - Turn-based retention: keep the last N turns (default configurable), call
    `drop_stored()` for evicted keys and on session cleanup.
  - `available` property — `False` when no `WorkingMemoryToolkit` is
    registered on the manager.
- Wire the tee into `CompressionStage` (the callback left `None` by
  TASK-1951): invoke it when `outcome.lossy` is `True`, set
  `compression_teed=True` in the metrics.
- Cap the effective level to `MINIMAL` when `tee.available` is `False` (use
  `levels.cap`).
- Reorder the `status == "error"` branch in `execute_tool()` so the payload is
  teed before `raise ValueError(result.error)`. **The raise stays** and the
  exception type/message are unchanged.
- Locate the session's `WorkingMemoryToolkit` from the `ToolManager`'s
  registered tools (do not construct one).

**NOT in scope**:
- Disk persistence of tee entries — v1 is in-memory working memory only
  (spec Non-Goals).
- Any change to `WorkingMemoryToolkit`'s public API — it is a consumer
  relationship only.
- The columnar codec (the first real producer of `lossy=True`) → TASK-1954.
  Test with a stub lossy codec.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/tee.py` | CREATE | `CompressionTee` |
| `packages/ai-parrot/src/parrot/tools/compression/stage.py` | MODIFY | Invoke the tee on `lossy`; cap level when tee unavailable |
| `packages/ai-parrot/src/parrot/tools/manager.py` | MODIFY | Error-branch reorder (tee before raise); locate the `WorkingMemoryToolkit` |
| `packages/ai-parrot/tests/tools/compression/test_tee.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
from parrot.tools.working_memory import (
    WorkingMemoryToolkit, EntryType, GenericEntry,   # all present in __all__
)
from parrot.tools.working_memory.internals import (
    WorkingMemoryCatalog, CatalogEntry, _detect_entry_type,  # no __all__, direct import OK
)
from parrot.tools.compression import FilterLevel
from parrot.tools.compression.levels import cap
```

### Existing Signatures to Use

```python
# parrot/tools/working_memory/tool.py:44
class WorkingMemoryToolkit(AbstractToolkit):
    name: str = "working_memory"          # line 77
    tool_prefix: str = "wm"               # line 78 → tool names are wm_store_result, wm_get_result
    exclude_tools: tuple[str, ...] = ("store",)   # line 86

    @tool_schema(StoreResultInput)        # decorator at line 204
    async def store_result(               # def at line 205
        self, key: str, data: Any, data_type: str = "auto",
        description: str = "", metadata: Optional[dict] = None,
        turn_id: Optional[str] = None,
    ) -> dict: ...   # → {"status": "stored", "summary": entry.compact_summary()}

    @tool_schema(DropStoredInput)         # decorator at line 238
    async def drop_stored(self, key: str) -> dict: ...        # def at line 239

    @tool_schema(GetResultInput)          # decorator at line 255
    async def get_result(                 # def at line 256
        self, key: str, max_length: int = 500, include_raw: bool = False,
    ) -> dict: ...

# parrot/tools/working_memory/internals.py
def _detect_entry_type(data: Any) -> EntryType: ...           # line 34
@dataclass
class GenericEntry:                                            # line 70
    key: str
    data: Any
    entry_type: EntryType
    created_at: float = field(default_factory=time.time)
    description: str = ""
    turn_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    def compact_summary(self, max_length: int = 500) -> dict: ...   # line 96

class CatalogEntry: ...                                        # line 175
    def compact_summary(self, max_rows: int = 5, max_cols: int = 20) -> dict: ...  # line 203
    # ⚠️ DIFFERENT signature from GenericEntry.compact_summary — do not confuse them.

class WorkingMemoryCatalog: ...                                # line 458
    def put_generic(...)                                       # line 499
    # ⚠️ SILENTLY OVERWRITES on key collision → the tee key needs the counter.

# parrot/tools/working_memory/models.py:15
class EntryType(str, Enum):
    DATAFRAME = "dataframe"; TEXT = "text"; JSON = "json"
    MESSAGE = "message"; BINARY = "binary"; OBJECT = "object"
```

**VERBATIM branch to reorder — `parrot/tools/manager.py` lines 1493-1500:**

```python
if isinstance(result, ToolResult):
    # Return forbidden results directly without post-processing
    if result.status == 'forbidden':
        return result
    if result.status == "error":
        raise ValueError(result.error)         # ← tee result.result BEFORE this line
    out = result.result
    meta = getattr(result, "metadata", {}) or {}
```

Tee pointer shape (spec §2):

```json
{"_tee": {"key": "__tee__:execute_database_query:t7",
          "reason": "lossy",
          "hint": "use wm_get_result for the full payload"}}
```

### Does NOT Exist

- ~~A tee/spill mechanism anywhere in `parrot/`~~ — zero occurrences; you are
  writing it.
- ~~Disk persistence for working memory entries~~ — in-memory only; do not
  add a file backend (explicit Non-Goal).
- ~~`WorkingMemoryToolkit.store()`~~ — it is in `exclude_tools`
  (tool.py:86). Use `store_result()`.
- ~~`put_generic()` raising on collision~~ — it silently overwrites. The
  counter in the key is the only defense.
- ~~A `turn_id` automatically available on `ToolManager`~~ — verify how the
  manager exposes turn/session context before assuming an attribute name. If
  none exists, derive a stable per-execution counter and document it.

---

## Implementation Notes

### Pattern to Follow

```python
class CompressionTee:
    async def store(self, tool_name: str, payload: Any, reason: str) -> str | None:
        if not self.available:
            return None
        key = f"__tee__:{tool_name}:{self._turn_id()}:{self._next_counter()}"
        try:
            await self._wm.store_result(
                key=key, data=payload, data_type="auto",
                description=f"Full pre-compression payload for {tool_name} ({reason})",
                metadata={"tee": True, "reason": reason, "tool": tool_name},
                turn_id=self._turn_id(),
            )
        except Exception as exc:
            self.logger.warning("Tee failed for %s: %s", tool_name, exc)
            return None
        return key
```

### Key Constraints

- **A failing tee must never break a tool call.** On failure: log a warning,
  return `None`, and the stage must then fall back to returning the ORIGINAL
  (uncompressed) payload — losing data because the escape hatch failed is
  exactly what G3 forbids.
- The error-branch reorder must keep `raise ValueError(result.error)` with the
  same type and message. Existing callers catch `ValueError`; that must not
  change. Add a test asserting the raise still happens.
- Level capping when the tee is unavailable applies to `NORMAL` and
  `AGGRESSIVE` only — `MINIMAL` is lossless and needs no tee.
- `store_result` is `async`; the tee call happens on the stage's async path,
  not inside the synchronous codec.
- Retention: evicting a turn calls `drop_stored(key)` for its tee keys. Do not
  let tee entries grow unboundedly across a long session.
- `_detect_entry_type` decision order is `str→TEXT, bytes→BINARY,
  dict|list→JSON, .content+.role→MESSAGE, DataFrame→DATAFRAME, else→OBJECT` —
  `data_type="auto"` is correct for tee payloads.

### References in Codebase

- `parrot/tools/working_memory/tool.py:205` — `store_result()`, the tee sink.
- `parrot/tools/working_memory/tool.py:256` — `get_result()`, the recovery
  path the LLM uses via `wm_get_result`.
- `parrot/tools/working_memory/internals.py:499` — `put_generic()`, the
  silent-overwrite hazard.

---

## Acceptance Criteria

- [ ] `test_tee_on_lossy`: `outcome.lossy=True` → full payload in working
      memory + `_tee` pointer appended to the compressed result.
- [ ] `test_tee_on_error_before_raise`: `status=="error"` → payload teed AND
      `ValueError(result.error)` still raised with the same message.
- [ ] `test_tee_key_collision_counter`: two tees for the same tool+turn
      produce distinct keys; neither entry is lost.
- [ ] `test_no_wm_caps_level_to_minimal`: no `WorkingMemoryToolkit` → tee off
      AND `NORMAL`/`AGGRESSIVE` capped to `MINIMAL` (G3).
- [ ] Tee failure → original uncompressed payload returned, warning logged,
      no exception escapes.
- [ ] Round trip: `wm_get_result(key, include_raw=True)` returns the full
      original payload.
- [ ] Existing manager tests still pass:
      `pytest packages/ai-parrot/tests/tools/ tests/manager/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/ packages/ai-parrot/src/parrot/tools/manager.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_tee.py
import pytest
from parrot.tools.compression import FilterLevel
from parrot.tools.compression.tee import CompressionTee


@pytest.fixture
def tool_manager_with_wm():
    """ToolManager with a WorkingMemoryToolkit registered (tee-capable)."""
    ...


@pytest.fixture
def tool_manager_without_wm():
    """ToolManager without working memory → tee degradation path."""
    ...


class TestTee:
    async def test_tee_on_lossy(self, tool_manager_with_wm):
        out = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        assert "_tee" in out
        assert out["_tee"]["reason"] == "lossy"
        assert out["_tee"]["key"].startswith("__tee__:lossy_tool:")

    async def test_tee_on_error_before_raise(self, tool_manager_with_wm):
        with pytest.raises(ValueError, match="boom"):
            await tool_manager_with_wm.execute_tool("erroring_tool", {})
        wm = tool_manager_with_wm.get_tool("wm_get_result")
        # the discarded result.result was captured despite the raise
        assert any(k.startswith("__tee__:erroring_tool:") for k in _keys(wm))

    async def test_tee_key_collision_counter(self, tool_manager_with_wm):
        a = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        b = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        assert a["_tee"]["key"] != b["_tee"]["key"]

    async def test_no_wm_caps_level_to_minimal(self, tool_manager_without_wm):
        out = await tool_manager_without_wm.execute_tool("lossy_tool", {})
        assert "_tee" not in out          # nothing lossy happened
        # level was capped: output is the lossless form, not the lossy one
        ...

    async def test_tee_failure_returns_original(self, tool_manager_with_wm,
                                                monkeypatch, caplog):
        wm = tool_manager_with_wm.get_toolkit("working_memory")
        async def boom(**kwargs): raise RuntimeError("wm down")
        monkeypatch.setattr(wm, "store_result", boom)
        out = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        assert "_tee" not in out
        assert any("wm down" in r.message or "Tee failed" in r.message
                   for r in caplog.records)

    async def test_roundtrip_recovers_full_payload(self, tool_manager_with_wm):
        out = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        wm = tool_manager_with_wm.get_toolkit("working_memory")
        recovered = await wm.get_result(key=out["_tee"]["key"], include_raw=True)
        assert recovered["raw"] == ORIGINAL_PAYLOAD
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 3, §5 G3/G5 criteria, §7 risks).
2. **Check dependencies** — TASK-1952 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read
   `working_memory/tool.py:205/239/256` and `manager.py:1493-1500` before
   editing. Confirm how `turn_id` is obtained; if the manager has no turn
   context, document the fallback you chose in the Completion Note.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria — especially that the `ValueError` still
   raises identically.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-07-28
**Notes**:

- Implemented `CompressionTee` (`tee.py`): `store()` (async,
  `__tee__:<tool>:<turn_id>:<counter>` keys, per-`tool_name` counter defends
  `put_generic`'s silent overwrite), `attach_tee_pointer()` (module-level
  function — the `_tee` block per spec §2), turn-based `_retain`/`cleanup`
  eviction via `drop_stored()`, and `bind_working_memory()` for lazy
  (re)binding. Never raises — a failing tee logs a warning and returns
  `None`.
- **`turn_id` deviation (flagged in advance by the task itself)**: verified
  `ToolManager` has no conversational-turn concept anywhere in `manager.py`.
  `CompressionTee` uses a stable per-instance UUID (generated once at
  construction — one `CompressionTee` per `ToolManager`, i.e. per user
  session after `clone()`) as the `turn_id` component, and retention tracks
  the last N tee *entries* rather than N conversational turns. Documented
  in the class docstring.
- Wired the tee into `CompressionStage` (`stage.py`): `_effective_level()`
  now caps a resolved `NORMAL`/`AGGRESSIVE` level to `MINIMAL` via
  `levels.cap()` whenever `tee.available` is falsy (G3), applied uniformly
  regardless of which precedence rule produced the level (including
  `level_override`, since a hard safety invariant must not be bypassable).
  `run()` now `await`s the tee (added `_invoke_tee`/`_tee_available` — the
  `tee` constructor param now accepts a real `CompressionTee` OR, for
  backward compatibility, a legacy bare callable duck-typed via
  `getattr(..., "store"/"available", ...)`) and, on a successful tee,
  attaches the `_tee` pointer to the RETURNED payload (not just metadata)
  via `attach_tee_pointer` — this is what makes `"_tee" in out` true for
  callers of `execute_tool()`.
- `manager.py`: reordered the `status == "error"` branch — `result.result`
  is now teed (`reason="error"`) BEFORE `raise ValueError(result.error)`;
  the raise itself, its type, and its message are byte-identical.
  `_find_working_memory_toolkit()` scans registered tools for one whose
  `bound_method.__self__` is a `WorkingMemoryToolkit` (never constructs
  one); `_bind_compression_tee()` calls it lazily on every
  `execute_tool()` invocation that reaches the tee, since a
  `WorkingMemoryToolkit` may be registered after the manager (and its
  `CompressionTee`) is constructed — verified with a dedicated test.
  `clone()` docstring extended; each clone gets its own fresh
  `CompressionTee` from its own `__init__` (never shared).
- **Necessary, documented deviation from the file scope**: fixing 3
  existing TASK-1951 tests in `test_stage.py` (not in this task's file
  list) was unavoidable — they encoded assumptions (NORMAL level stays
  NORMAL with no tee configured; a lossy `out` never carries a `_tee` key)
  that are directly superseded by this task's own G3 capping/pointer
  requirements. Left every other test in that file untouched; each fix is
  a single, minimally-scoped, clearly-commented change (two tests gained a
  dummy always-"available" tee stub so they keep probing what they
  originally probed — precedence and budget routing, not tee capping; one
  test's expected `out` was updated to include the now-attached `_tee`
  pointer).
- Verification: full compression suite 90/90 green; broader
  `tests/tools/` (excl. compression) unchanged at 51 pre-existing failures
  (same set as before this task, unrelated to compression);
  `test_toolmanager_load_tool.py` + `test_toolmanager_confirmation.py` +
  `test_tool_manager_mcp.py` + `tests/tools/test_grants.py` 62/62 (all
  green this run, incl. the two web_scraping tests that needed the
  worktree's missing compiled `.so` copied over per TASK-1952's note).
  `ruff check compression/ manager.py` — same single pre-existing `F821`
  finding on `manager.py` noted in TASK-1952, unrelated to this task;
  `tee.py`/`stage.py` lint clean.

**Deviations from spec**: `turn_id` is a stable per-`CompressionTee`
identifier, not a real conversational-turn counter (none exists — see
above); consequently retention is "last N tee entries" not "last N turns".
Additionally touched `tests/tools/compression/test_stage.py` (outside this
task's file list) to keep 3 TASK-1951 tests valid under the new G3
capping/pointer-attachment behavior — see notes above.
