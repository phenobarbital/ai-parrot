# TASK-2565: Agents + transport — artifact v2 call sites, non-stream envelope passthrough

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2562
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G5, G9). The FEAT-224 inline minting block in
`bots/data.py` is replaced by the TASK-2562 `attach_structured_artifact()`
helper; DatabaseAgent's STRUCTURED_TABLE path starts minting artifacts too
(closing the FEAT-224 gap); the non-stream handler returns `a2ui_envelope`
whenever the response carries one, not only for `output_mode == A2UI`.

---

## Scope

- `parrot/bots/data.py`: replace the inline FEAT-224 block (`:2095-2135`) with
  a call to `attach_structured_artifact(response, output_mode)`. Behaviour
  with an envelope present → v2 entries; without → identical v1 entries
  (the helper's fallback reproduces the block).
- `parrot/bots/database/agent.py` (`:613-619`): after setting
  `response.output_mode = OutputMode.STRUCTURED_TABLE`, call
  `attach_structured_artifact(response, OutputMode.STRUCTURED_TABLE)`.
- `handlers/agent.py` non-stream path (`:2819-2827`): include `a2ui_envelope`
  in the JSON body whenever `getattr(response, "a2ui_envelope", None)` is not
  `None` — widen the current `output_mode == OutputMode.A2UI` gate. Stream
  path (`:2703-2705`) is already ungated — do NOT touch it.
- Unit tests (spec §4 Module-6 rows).

**NOT in scope**: the helper itself (TASK-2562), the satellite hook
(TASK-2563), docs (TASK-2566).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | inline block → helper call |
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | mint on STRUCTURED_TABLE |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | non-stream envelope passthrough |
| `packages/ai-parrot/tests/bots/test_structured_artifact_v2.py` | CREATE | PandasAgent + DatabaseAgent minting |
| `packages/ai-parrot-server/tests/handlers/test_structured_envelope_passthrough.py` | CREATE | stream/non-stream handler tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core dev @ 8b40e0c
from parrot.models.outputs import OutputMode                       # models/outputs.py:33
from parrot.models.responses import AIMessage                       # artifacts :206, artifact_id :214, a2ui_envelope :222
# from this feature (TASK-2562):
from parrot.outputs.a2ui.artifacts import attach_structured_artifact
```

### Existing Signatures to Use
```python
# dev bots/data.py — the block to REPLACE, verified 2026-08-29 @ 8b40e0c:
#   :2099  _STRUCTURED_ARTIFACT_TYPE = {STRUCTURED_CHART:"chart", STRUCTURED_MAP:"map", STRUCTURED_TABLE:"table"}
#   :2104  _art_type = _STRUCTURED_ARTIFACT_TYPE.get(output_mode)
#   :2113  _art_id = f"{_mode_str}-{uuid.uuid4().hex[:8]}"
#   :2128  response.artifact_id = _art_id
#   (strips "data"/"datasets"; appends to response.artifacts)
# dev bots/data.py :329-350 — _STRUCTURED_OUTPUT_ROUTER phrasing map (depends on output_mode staying STRUCTURED_*)

# dev bots/database/agent.py
#   :613  if output_mode == OutputMode.STRUCTURED_TABLE:
#   :619      response.output_mode = OutputMode.STRUCTURED_TABLE      (no artifact minting today)

# dev server handlers/agent.py
#   stream :2703-2705 (NOT gated — leave unchanged):
#     a2ui_envelope = getattr(ai_message, 'a2ui_envelope', None)
#     if a2ui_envelope is not None: envelope['a2ui_envelope'] = a2ui_envelope
#   non-stream :2819-2827 (GATED — widen):
#     if getattr(response, "output_mode", None) == OutputMode.A2UI:
#         return self.json_response({... "a2ui_envelope": getattr(response, "a2ui_envelope", None) ...})  # :2826
```

### Does NOT Exist
- ~~`attach_structured_artifact` on dev today~~ — arrives with TASK-2562; verify it is merged before starting.
- ~~artifact minting in `database/agent.py`~~ — this task adds it.
- ~~non-stream `a2ui_envelope` for STRUCTURED_* responses~~ — this task adds it.

---

## Implementation Notes

### Key Constraints
- `bots/data.py` replacement must be behaviour-preserving when no envelope
  exists (the FEAT-224 parity suites are the gate, AC-2).
- Do NOT flip `output_mode` anywhere — the A2UI JSON body shape for
  `output_mode == A2UI` stays as-is; STRUCTURED_* responses gain the
  `a2ui_envelope` key in their existing body shape.
- Keep the helper call defensive (it never raises) — no new try/except needed
  at call sites beyond what exists.

### References in Codebase
- `handlers/agent.py:2703-2705` — the ungated stream pattern to mirror
- FEAT-224 tests under `packages/ai-parrot/tests/bots/` — parity baseline

---

## Acceptance Criteria

- [ ] PandasAgent STRUCTURED_* → `artifacts[0]` has `schemaVersion=2`, `surfaceId`; `response.artifact_id` set (AC-6)
- [ ] DatabaseAgent STRUCTURED_TABLE mints exactly one artifact entry (AC-6)
- [ ] Non-stream JSON body includes `a2ui_envelope` for `output_mode=structured_chart`; A2UI-mode body unchanged (AC-10)
- [ ] Stream final dict still carries `a2ui_envelope` (unchanged) (AC-10)
- [ ] FEAT-224 parity suites pass (AC-2)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/bots -k "structured or artifact" -v` + server handler tests; ruff clean

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_structured_artifact_v2.py
async def test_pandasagent_artifact_v2(): ...
async def test_dbagent_structured_table_mints_artifact(): ...
# packages/ai-parrot-server/tests/handlers/test_structured_envelope_passthrough.py
async def test_nonstream_handler_returns_envelope_for_structured(): ...
async def test_stream_handler_unchanged(): ...
```

---

## Agent Instructions

1. Verify TASK-2562 is in `sdd/tasks/completed/`.
2. Re-verify the line anchors above (files are hot); update contract first if drifted.
3. Implement, run parity suites, move to completed, update index, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-29
**Notes**: `bots/data.py` — replaced the FEAT-224 inline block (verified at
`:2095-2135` against merged `dev` before editing, matching the contract)
with a single call to `attach_structured_artifact(response, output_mode)`
plus a preserved info-level log line. `bots/database/agent.py` — added
the same call right after `response.output_mode = OutputMode.STRUCTURED_TABLE`
(`:614-620`), exactly as specified. `handlers/agent.py` — widened the
non-stream JSON body to include `a2ui_envelope` whenever
`getattr(response, "a2ui_envelope", None) is not None`, leaving the
`output_mode == A2UI` branch's own dedicated shape and the (already-ungated)
stream path both untouched. **Process note**: my first pass ran a blanket
`ruff check --fix` across these three large, lint-debt-heavy files and it
auto-fixed hundreds of unrelated pre-existing findings (UP006/UP007 etc.)
throughout each file — caught before committing via `git diff --stat`
showing 100+ line diffs against a ~10-line intended change; reverted with
`git checkout --` and reapplied only the exact intended edits via targeted
`Edit` calls. Lesson for future tasks: never run `ruff --fix` (or any
autofix) on a whole pre-existing file with known lint debt — scope it to
new code only, or diff before/after.

New `test_structured_artifact_v2.py` (5 tests: import-wiring checks for
both agent modules + `attach_structured_artifact` v2/fallback/no-op
scenarios matching each agent's exact response shape) and
`test_structured_envelope_passthrough.py` (4 tests, source-inspection
style matching `test_agent_a2ui_stream.py`'s own established convention for
this Cython-adjacent handler file) all pass. Regression: 57 passed in
`tests/bots -k "structured or artifact"`, 166 passed in
`tests/bots/database`, 393 passed + the same 2 pre-existing failures
(confirmed via `git stash`, unrelated — a stale single-vs-double-quote
string-literal assertion in `test_agent_a2ui_stream.py` predating this
task) in `tests/handlers`; 506 passed in `tests/outputs/a2ui` + this
task's new bots test. ruff clean on every line added (verified via
line-scoped `grep` against ruff's output, since the surrounding files
carry substantial pre-existing lint debt left untouched).

**Deviations from spec**: none in the code changes themselves. One
observation for the record: at the exact call site specified in
`bots/database/agent.py` (`:614-620`, immediately after
`response.output_mode = OutputMode.STRUCTURED_TABLE`), `response.output`
is still the raw `QueryResponse` pydantic model (not yet the rendered
config dict) — the actual `StructuredTableRenderer` pass runs later,
downstream, as a separate explicit step (confirmed by the existing
`test_db_agent_structured_table_via_renderer` test's own docstring:
"Simulate what DatabaseAgent sets... then render separately"). The
`attach_structured_artifact` call at this exact site is therefore a
guaranteed no-op in the current pipeline (its own `isinstance(content,
dict)` guard prevents any incorrect mint) — the wiring is correct and
matches the task's literal instruction precisely, but closing the FEAT-224
gap for DatabaseAgent functionally requires the renderer to have already
run by the time some call site invokes the helper. Flagging this for the
spec/PR reviewer rather than silently "fixing" it by relocating the call
outside this task's specified scope.
