# TASK-1957: Savings report (per-tool / per-session, `rtk gain` equivalent)

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1952
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8. "Measure, don't assume" is a stated constraint of this
feature (§7): `MINIMAL` looks like a 40% byte win but BPE tokenizers merge
whitespace runs, so the real token saving is more like 5–15%. Without a
report, nobody will ever find that out.

The report aggregates from `AfterToolCallEvent` — **tokens saved AND
milliseconds spent**. A saving that cannot be checked against its cost is not
evaluable, which is why both travel together.

Below-`min_rows` passthroughs are recorded as "no gain" on purpose: knowing
which tools never benefit is how the default manifest gets tuned.

---

## Scope

- Implement `report.py`:
  - A listener that subscribes to `AfterToolCallEvent` and accumulates
    per-tool and per-session counters: calls, compressed calls, skipped calls
    (by reason), `bytes_before`, `bytes_after`, `est_tokens_saved`, total and
    p50/p99 `compression_duration_ms`.
  - `CompressionReport.summary()` → a structured (Pydantic) report with a
    per-tool breakdown and a session total.
  - `CompressionReport.render()` → a compact human-readable text table for
    logs/CLI.
- Track "no gain" explicitly: a compressed call whose `bytes_after >=
  bytes_before`, and every `compression_skipped` reason, appear in the
  breakdown rather than being dropped.
- Document the token-estimate caveat directly in the report output:
  percentages are reliable, absolute token values are approximate
  (`bytes/4`, no tokenizer).
- Per-session isolation: the report holds per-session state, so it must be one
  of the things `ToolManager.clone()` does NOT share (already handled by
  TASK-1952 — verify, do not re-implement).

**NOT in scope**:
- Emitting the events → TASK-1952 already extends `AfterToolCallEvent` and
  populates the fields.
- Persisting reports to disk or a database.
- A CLI command or HTTP endpoint. `render()` returns a string; wiring it to a
  surface is future work.
- Benchmarking / calibration → TASK-1959.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/compression/report.py` | CREATE | `CompressionReport` + event listener |
| `packages/ai-parrot/src/parrot/tools/compression/__init__.py` | MODIFY | Export `CompressionReport` |
| `packages/ai-parrot/tests/tools/compression/test_report.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Verified Imports

```python
from pydantic import BaseModel, Field
from parrot.core.events.lifecycle.events import AfterToolCallEvent
    # `events` is a PACKAGE (core/events/lifecycle/events/), not events.py.
    # Symbols live in events/tool.py, re-exported by events/__init__.py.
    # parrot/tools/abstract.py:22 already uses this exact import.
```

### Existing Signatures to Use

```python
# parrot/core/events/lifecycle/events/tool.py — AFTER TASK-1952's extension
class AfterToolCallEvent(LifecycleEvent):        # line 30, @dataclass(frozen=True)
    tool_name: str = ""                          # line 42
    duration_ms: float = 0.0                     # line 43
    result_status: str = ""                      # line 44 — "success" | "partial"
    result_size_bytes: int = 0                   # line 45 ← POST-compression size
    # Added by TASK-1952 (all with defaults — frozen dataclass):
    compression_codec: str = ""
    compression_level: str = ""
    result_size_bytes_original: int = 0
    compression_duration_ms: float = 0.0
    compression_teed: bool = False
```

### Does NOT Exist

- ~~A new compression-specific lifecycle event~~ — resolved in the brainstorm:
  **extend `AfterToolCallEvent`, no new event**. Do not add one.
- ~~A tokenizer~~ — `est_tokens_saved` is `bytes/4`. The report must state
  this caveat in its own output; do not present absolute token counts as
  exact.
- ~~A metrics backend (Prometheus, StatsD) wired into `parrot.tools`~~ —
  verify before assuming; this task adds in-process aggregation only.
- ~~`rtk gain`~~ — RTK is an external binary and is NOT a dependency. This is
  a functional equivalent, not a wrapper.

---

## Implementation Notes

### Pattern to Follow

```python
class ToolSavings(BaseModel):
    tool_name: str
    calls: int = 0
    compressed_calls: int = 0
    skipped: dict[str, int] = Field(default_factory=dict)   # reason -> count
    bytes_before: int = 0
    bytes_after: int = 0
    est_tokens_saved: int = 0
    compression_ms_total: float = 0.0

    @property
    def pct_saved(self) -> float:
        return 0.0 if not self.bytes_before else \
            100.0 * (self.bytes_before - self.bytes_after) / self.bytes_before
```

### Key Constraints

- Aggregation must be O(1) per event — no storing every event.
- p99 over a bounded rolling window (reuse the window shape from
  `budget.py`'s `CircuitBreaker` rather than inventing a second one; if the
  implementation there is not reusable, say so in the Completion Note instead
  of duplicating logic silently).
- The listener must never raise into the event bus: wrap the handler body and
  log warnings.
- A call with `result_size_bytes_original == 0` (uncompressed / skipped) is
  counted as a call but contributes zero saving — do not divide by zero.
- `render()` output must include the caveat line, e.g.
  `token figures are bytes/4 estimates — percentages reliable, absolutes approximate`.
- Google-style docstrings, strict type hints, `self.logger`.

### References in Codebase

- `parrot/core/events/lifecycle/events/tool.py:30` — the event shape.
- `parrot/tools/compression/budget.py` (TASK-1950) — rolling-window helper to
  reuse for p99.

---

## Acceptance Criteria

- [ ] Feeding a sequence of `AfterToolCallEvent`s yields correct per-tool and
      session totals for bytes, tokens and milliseconds.
- [ ] "No gain" cases (below `min_rows` passthrough, `bytes_after >=
      bytes_before`, every `compression_skipped` reason) appear in the
      breakdown with their reason.
- [ ] `render()` includes the token-estimate caveat.
- [ ] Milliseconds spent are reported alongside tokens saved — never one
      without the other.
- [ ] A listener exception is logged and swallowed, never propagated to the
      event bus.
- [ ] Per-session isolation verified against `ToolManager.clone()`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/tools/compression/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/tools/compression/`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/compression/test_report.py
import pytest
from parrot.core.events.lifecycle.events import AfterToolCallEvent
from parrot.tools.compression.report import CompressionReport


def _evt(tool, before, after, ms=0.5, codec="columnar", skipped=None):
    return AfterToolCallEvent(
        tool_name=tool, duration_ms=10.0, result_status="success",
        result_size_bytes=after, result_size_bytes_original=before,
        compression_codec=codec, compression_level="normal",
        compression_duration_ms=ms, compression_teed=False,
    )


class TestCompressionReport:
    def test_aggregates_bytes_tokens_and_ms(self):
        r = CompressionReport()
        r.handle(_evt("db", 1000, 400))
        r.handle(_evt("db", 2000, 800))
        s = r.summary().tools["db"]
        assert s.calls == 2
        assert s.bytes_before == 3000 and s.bytes_after == 1200
        assert s.est_tokens_saved == (600 + 1200) // 4
        assert s.compression_ms_total == pytest.approx(1.0)
        assert s.pct_saved == pytest.approx(60.0)

    def test_no_gain_is_recorded(self):
        r = CompressionReport()
        r.handle(_evt("small", 500, 500))
        s = r.summary().tools["small"]
        assert s.pct_saved == 0.0
        assert s.calls == 1

    def test_skipped_reasons_tracked(self):
        r = CompressionReport()
        evt = _evt("t", 0, 0, codec="")
        r.handle(evt, skipped_reason="min_rows")
        assert r.summary().tools["t"].skipped["min_rows"] == 1

    def test_render_includes_caveat(self):
        r = CompressionReport()
        r.handle(_evt("db", 1000, 400))
        out = r.render()
        assert "bytes/4" in out or "approximate" in out
        assert "ms" in out              # cost shown next to saving

    def test_listener_never_raises(self, caplog):
        r = CompressionReport()
        r.handle(None)                  # malformed
        assert r.summary() is not None

    def test_no_division_by_zero(self):
        r = CompressionReport()
        r.handle(_evt("t", 0, 0, codec=""))
        assert r.summary().tools["t"].pct_saved == 0.0
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 8, §7 "Measure, don't assume").
2. **Check dependencies** — TASK-1952 must be in `sdd/tasks/completed/` (the
   event fields must exist before you can aggregate them).
3. **Verify the Codebase Contract** — confirm the new `AfterToolCallEvent`
   fields landed with the names listed above.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

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
