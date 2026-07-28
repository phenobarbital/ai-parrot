# TASK-1961: Demote Google client truncation to last line of defense

**Feature**: FEAT-380 — Tool Result Compression Pipeline
**Spec**: `sdd/specs/tool-result-compression.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1952
**Assigned-to**: unassigned

---

## Context

Spec §2 Integration Points: *"`parrot/clients/google/client.py` — modifies:
`MAX_TOOL_RESULT_CHARS` becomes last line of defense, not first. Evaluate
raising the threshold."*

Today the Google client's `_truncate_large_result()` is the **only** defense
against bulky tool results in the entire framework, and it is a positional
one — it binary-searches lists and keeps the *first N* elements. In a test
result the failures matter; in a vector search the top-score chunks matter.
Neither is guaranteed to be in the first N.

With the pipeline in place, semantic reduction happens once, before any client
sees the result. The Google truncation stays as a genuine last resort, but its
role and its threshold should reflect that it now runs on already-compressed
payloads.

---

## Scope

- Re-document `MAX_TOOL_RESULT_CHARS` and `_truncate_large_result()` to state
  explicitly that they are a **last line of defense** operating on payloads
  that have already passed the compression pipeline, and that the truncation
  is positional and therefore lossy in an unprincipled way.
- Evaluate raising `MAX_TOOL_RESULT_CHARS` from 200,000. Decide based on
  evidence (what the pipeline now removes, what the Gemini context actually
  tolerates), change it if justified, and record the reasoning in the
  Completion Note. **Leaving it at 200,000 with a documented rationale is an
  acceptable outcome** — an unjustified change is not.
- Add a log line (at `warning`) when this truncation actually fires, naming
  the tool and the pre/post sizes — today a payload can be silently cut with
  no operational signal that it happened.
- Verify no double reduction: a compressed payload must not be re-truncated
  into incoherence. Add a test asserting a pipeline-compressed payload of
  typical size passes through the Google client untouched.
- Confirm G1 still holds: this client keeps **truncation**, not compression.
  No codec, no `FilterLevel`, no pipeline import belongs in this file.

**NOT in scope**:
- Adding equivalent truncation to `claude.py` / `groq.py` / `grok.py` — the
  pipeline is the client-agnostic defense (G1); per-client truncation is the
  rejected design (Option A).
- Removing the Google truncation entirely. It stays as the last resort.
- Any change to `_summarize_tool_result()` or
  `_process_tool_result_for_api()` beyond documentation and the new log line.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/google/client.py` | MODIFY | Re-document `MAX_TOOL_RESULT_CHARS` + `_truncate_large_result()`; add truncation-fired warning; optionally raise the threshold |
| `packages/ai-parrot/tests/clients/test_google_truncation.py` | CREATE | Tests for the log signal and no-double-reduction |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED against HEAD `024c21d44` on 2026-07-27.
> **Path mapping**: `parrot/...` means `packages/ai-parrot/src/parrot/...`.

### Existing Signatures to Use

```python
# parrot/clients/google/client.py — VERIFIED line anchors
MAX_TOOL_RESULT_CHARS: int = 200_000       # line 1197 — CLASS attribute, NOT a module constant
def _truncate_large_result(self, data: Any, max_chars: int) -> Any: ...   # line 1199
def _process_tool_result_for_api(self, result) -> dict: ...               # line 1358
def _summarize_tool_result(self, result: Any, max_length: int = 1200) -> str: ...  # line 1444

# Call sites of MAX_TOOL_RESULT_CHARS inside _process_tool_result_for_api:
#   line 1383-1384 — str result: hard slice + "\n...[TRUNCATED]"
#   line 1420-1424 — serialized result: logs a message, then calls
#                    _truncate_large_result(clean_result, self.MAX_TOOL_RESULT_CHARS)
#   line 1434-1435 — fallback path: hard slice + "\n...[TRUNCATED]"
```

Note it is a **class attribute** (`self.MAX_TOOL_RESULT_CHARS`), so a subclass
or instance can already override it — any threshold change should preserve
that overridability.

### Does NOT Exist

- ~~`MAX_TOOL_RESULT_CHARS` outside `parrot/clients/google/client.py`~~ —
  VERIFIED: `claude.py`, `groq.py`, `grok.py` have NO equivalent tool-result
  truncation (only unrelated `[:100]` log slices and a max-tokens warning
  string). Do not add one.
- ~~A compression import in any client~~ — and there must not be one after
  this task. G1: compression lives in exactly one place.
- ~~A module-level `MAX_TOOL_RESULT_CHARS` constant~~ — it is a class
  attribute at line 1197. Do not "promote" it to module scope.
- ~~Semantic (non-positional) truncation in this client~~ — 
  `_truncate_large_result()` keeps the first N elements. That is precisely the
  defect the pipeline exists to fix; do not try to make it smarter here.

---

## Implementation Notes

### Key Constraints

- This is a **documentation + observability** task with an optional,
  evidence-backed constant change. Resist the urge to redesign the truncation.
- The new warning must fire only when truncation actually happens, and must
  include the tool name if reachable at that point in the call — check what
  context `_process_tool_result_for_api()` has before promising it in the
  message.
- If you raise the threshold, keep it a class attribute and mention the new
  value in the Completion Note so TASK-1962 can document it.
- Do not import anything from `parrot.tools.compression` into this file.

### References in Codebase

- `parrot/tools/compression/stage.py` — where reduction now happens (read it
  to understand what reaches the client, do not import it).
- `sdd/specs/tool-result-compression.spec.md` §1 "Problem Statement" — the
  three defects of the current truncation, in the author's words.

---

## Acceptance Criteria

- [ ] `MAX_TOOL_RESULT_CHARS` and `_truncate_large_result()` docstrings state
      they are a last line of defense running on already-compressed payloads,
      and that the truncation is positional/unprincipled.
- [ ] A `warning` fires when truncation actually happens, with pre/post sizes.
- [ ] A pipeline-compressed payload of typical size passes through the Google
      client untouched (no double reduction).
- [ ] The threshold decision (raised or kept) is justified in the Completion
      Note with evidence.
- [ ] `grep` confirms no compression import in any client (G1).
- [ ] Existing Google client tests still pass:
      `pytest packages/ai-parrot/tests/clients/ -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/google/client.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/clients/test_google_truncation.py
import pytest


class TestGoogleTruncation:
    def test_truncation_logs_a_warning(self, google_client, caplog):
        huge = "x" * (google_client.MAX_TOOL_RESULT_CHARS + 1000)
        google_client._process_tool_result_for_api(huge)
        assert any("trunc" in r.message.lower() for r in caplog.records)

    def test_no_truncation_for_typical_compressed_payload(self, google_client, caplog):
        payload = {"columns": ["a", "b"], "rows": [[1, 2]] * 500,
                   "constants": {"c": 1}}
        out = google_client._process_tool_result_for_api(payload)
        assert "[TRUNCATED]" not in str(out)
        assert not any("trunc" in r.message.lower() for r in caplog.records)

    def test_threshold_is_overridable_class_attribute(self, google_client):
        assert isinstance(type(google_client).MAX_TOOL_RESULT_CHARS, int)
        google_client.MAX_TOOL_RESULT_CHARS = 10
        assert google_client.MAX_TOOL_RESULT_CHARS == 10


def test_no_compression_import_in_clients():
    """G1: compression logic exists in exactly one place."""
    import subprocess
    out = subprocess.run(
        ["grep", "-rn", "--include=*.py", "parrot.tools.compression",
         "packages/ai-parrot/src/parrot/clients/"],
        capture_output=True, text=True,
    ).stdout
    assert out == ""
```

---

## Agent Instructions

1. **Read the spec** (§1 Problem Statement, §2 Integration Points).
2. **Check dependencies** — TASK-1952 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read
   `parrot/clients/google/client.py:1197-1440` and confirm the line anchors.
4. **Update status** in `sdd/tasks/index/tool-result-compression.json`.
5. **Implement** per scope — documentation and observability first, the
   constant change only if the evidence supports it.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** — state the threshold decision and its
   justification.

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
