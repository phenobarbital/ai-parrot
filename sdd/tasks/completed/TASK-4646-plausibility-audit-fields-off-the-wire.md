# TASK-4646: Keep the plausibility audit fields off every client-facing response

**Feature**: FEAT-732 — FormDesigner validation audit trail
**Spec**: `sdd/specs/formdesigner-validation-audit-trail.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4645
**Assigned-to**: unassigned

---

## Context

TASK-4645 adds `resolved_model`, `provider` and `usage` to `PlausibilityReport`. Those
fields belong to the **audit record**, but the report is `model_dump`ed straight onto the
wire in four places. Left alone, every public form client would learn the vendor, the
model and the token usage of each call — and the FEAT-728 wire shapes would change,
which spec NG3 forbids. This task adds one `wire_report()` helper that excludes the
audit-only fields and switches the four client-facing dumps to it, while persistence
(`services/submission_pipeline.py:327`) keeps the full dump. Implements spec §7 R10.

`Field(exclude=True)` was considered and rejected: it would also strip the fields from the
persistence dump, which is the one place they are needed.

---

## Scope

- Add `PLAUSIBILITY_AUDIT_FIELDS` and `wire_report()` to `core/llm_validation.py`.
- Replace the four client-facing `model_dump` calls with `wire_report(...)`, keeping each
  site's existing dump arguments exactly (`mode="json"`, and `exclude_none=True` where it
  is there today).
- Leave the persistence dump at `services/submission_pipeline.py:327` **untouched**.
- Write tests proving the fields are absent from all four responses **and** present in the
  stored context.

**NOT in scope**:
- `services/submission_pipeline.py` — its `model_dump` is the persistence path (keep it).
- `api/handlers.py:2214` — that dumps an `ImportDiffReport`, not a plausibility report.
- `audio/engine.py:1086` — it builds the context handed *to* the pipeline, which then
  overwrites `ctx["llm_validation"]` with its own full dump; it is not a client response.
- `pipeline.attach_verdicts` — it copies `PlausibilityVerdict`s, which carry no identity.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | `PLAUSIBILITY_AUDIT_FIELDS` + `wire_report()` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Three wire dumps → `wire_report()` |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | Client-submit summary → `wire_report()` |
| `packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py` | CREATE | Helper unit tests |
| `packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py` | MODIFY | Append wire-vs-storage tests for validate / 422 / 200 |
| `packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py` | MODIFY | Append a client-submit summary test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.llm_validation import PlausibilityReport   # verified: core/llm_validation.py:70
# api/audio_ws.py:90 already has: from ..core.llm_validation import LLMValidationConfig, PlausibilityReport
# api/handlers.py has NO module-level llm_validation import (only local ones at :271, :1147)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class PlausibilityReport(BaseModel): ...               # line 70 — after TASK-4645 it has resolved_model/provider/usage
def implausible_fields(report: PlausibilityReport) -> list[str]: ...   # line 92 — last function in the file

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
from ..core.events import FormEventAbort, FormEventName   # line 20 — module-level core imports live here
#   line 1243 (validate)   payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)
#   line 1869 (submit 422) "plausibility": exc.report.model_dump(mode="json", exclude_none=True),
#   line 1896 (submit 200) body_out["plausibility"] = outcome.plausibility.model_dump(mode="json", exclude_none=True)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py
from ..core.llm_validation import LLMValidationConfig, PlausibilityReport   # line 90
#   line 1257 (client-submit) summary = state.plausibility.model_dump(mode="json") if state.plausibility is not None else None
#                              NOTE: no exclude_none here — keep it that way
```

### Does NOT Exist
- ~~`PlausibilityReport.wire_dump()`~~ / ~~`.to_wire()`~~ — no such method; this task adds a
  module-level function `wire_report()`, not a method.
- ~~`PLAUSIBILITY_AUDIT_FIELDS`~~ / ~~`wire_report`~~ — this task adds them.
- ~~a shared "public serializer" for reports~~ — none exists; every site calls `model_dump`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#PlausibilityReport",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#implausible_fields"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the constant and helper at the end of `core/llm_validation.py` — *why*: one place
   decides what is audit-only, so a fourth field later is a one-line change.
2. Switch the four wire sites — *why*: spec NG3/R10; preserve each site's other dump
   arguments so the existing wire shape is byte-identical.
3. Append the tests — *why*: they must prove both halves (absent on the wire, present in
   storage), or a regression that drops the fields from storage would pass.

### `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def implausible_fields(report: PlausibilityReport) -> list\[str\]:' core/llm_validation.py)
# APPEND at end of file, after the whole `implausible_fields` function (verified: core/llm_validation.py:92)


#: Fields that belong to the audit record only (FEAT-732). Persisted with the
#: report, never sent to a form client — they name the vendor, the model and
#: the token usage of the call (spec §7 R10).
PLAUSIBILITY_AUDIT_FIELDS: frozenset[str] = frozenset({"resolved_model", "provider", "usage"})


def wire_report(report: PlausibilityReport, **dump_kwargs: Any) -> dict[str, Any]:
    """Dump `report` for a client-facing response, without the audit-only fields.

    Args:
        report: The plausibility report to serialize.
        **dump_kwargs: Forwarded to ``model_dump`` unchanged (``mode``,
            ``exclude_none``…). An ``exclude`` set is honoured and widened.

    Returns:
        The dumped report minus ``PLAUSIBILITY_AUDIT_FIELDS``.
    """
    exclude = set(PLAUSIBILITY_AUDIT_FIELDS) | set(dump_kwargs.pop("exclude", None) or ())
    return report.model_dump(exclude=exclude, **dump_kwargs)
```
**Why**: a function, not a method, keeps `PlausibilityReport` a plain data model. `Any` is
already imported by TASK-4645 (it widened the `typing` import for `usage`).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..core.events import FormEventAbort, FormEventName' api/handlers.py)
# AFTER — insert below `from ..core.events import FormEventAbort, FormEventName` (verified: api/handlers.py:20)
from ..core.llm_validation import wire_report
```
```python
# Each line below: occurrences 1 — verified with grep -c on the verbatim text.
# line 1243 — REPLACE
            payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)
# WITH
            payload["plausibility"] = wire_report(plausibility, mode="json", exclude_none=True)

# line 1869 — REPLACE
                    "plausibility": exc.report.model_dump(mode="json", exclude_none=True),
# WITH
                    "plausibility": wire_report(exc.report, mode="json", exclude_none=True),

# line 1896 — REPLACE
            body_out["plausibility"] = outcome.plausibility.model_dump(mode="json", exclude_none=True)
# WITH
            body_out["plausibility"] = wire_report(outcome.plausibility, mode="json", exclude_none=True)
```
**Why**: a module-level import is safe — `core/llm_validation.py` imports only `core.types`
at runtime (its `schema` import is `TYPE_CHECKING`-only), so no cycle.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from ..core.llm_validation import LLMValidationConfig, PlausibilityReport' api/audio_ws.py)
# REPLACE line 90 with:
from ..core.llm_validation import LLMValidationConfig, PlausibilityReport, wire_report

# occurrences: 1 (verified: grep -c 'summary = state.plausibility.model_dump(mode="json") if state.plausibility is not None else None' api/audio_ws.py)
# REPLACE line 1257 with:
        summary = wire_report(state.plausibility, mode="json") if state.plausibility is not None else None
```
**Why**: keep `mode="json"` and **no** `exclude_none` — that is this site's existing shape.

### FILL IN checklist
- [ ] `test_plausibility_wire_report.py` — bodies; bounded by NG3.
- [ ] `test_http_plausibility.py` — appended class; bounded by R10 (absent on wire, present in storage).
- [ ] `test_audio_ws_adapter.py` — appended test; bounded by R10.

---

## Acceptance Criteria

- [ ] `wire_report(r, mode="json")` never contains `resolved_model`, `provider` or `usage`,
      and equals `r.model_dump(mode="json")` minus exactly those keys.
- [ ] An extra `exclude=` passed to `wire_report` is honoured, not replaced.
- [ ] HTTP submit 200, HTTP 422 refusal and HTTP validate responses carry none of the three
      fields, while `storage.store`'s submission has `context["llm_validation"]["resolved_model"] == "fake-model-1"`.
- [ ] The audio client-submit `plausibility_summary` carries none of the three fields.
- [ ] `services/submission_pipeline.py` is not modified.
- [ ] `ruff check` clean on the touched source files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py
from parrot_formdesigner.core.llm_validation import PLAUSIBILITY_AUDIT_FIELDS, PlausibilityReport, wire_report

def _report() -> PlausibilityReport:
    return PlausibilityReport(status="ok", threshold=0.7, resolved_model="m", provider="p",
                              usage={"input_tokens": 3}, latency_ms=5, items={})

def test_audit_fields_excluded(): ...       # FILL IN: no key of PLAUSIBILITY_AUDIT_FIELDS in wire_report(_report(), mode="json")
def test_other_fields_identical(): ...      # FILL IN: == model_dump(mode="json") minus the three keys
def test_extra_exclude_is_widened(): ...    # FILL IN: wire_report(r, mode="json", exclude={"latency_ms"}) drops latency_ms too
```
```python
# APPEND to packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py
# Reuse make_handler, _form, _request, _json, FakeLLM, _OK, _LOW from this module.
class TestAuditFieldsStayOffTheWire:
    """FEAT-732 R10 — persisted, never sent to the form client."""

    async def test_submit_200_omits_identity_but_storage_keeps_it(self, make_handler): ...
    async def test_validate_omits_identity(self, make_handler): ...         # body {"name": "Ann", "llm_validation": True}
    async def test_review_422_omits_identity(self, make_handler): ...      # LLMValidationConfig(enabled=True, on_implausible="review") + FakeLLM(_LOW)
```
```python
# APPEND to packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py, as a
# sibling of test_client_data_carries_verdicts_and_summary (line 498) in the same class —
# copy its body, but build the state report with resolved_model="m", provider="p",
# usage={"input_tokens": 1}, and assert none of the three keys is in ready["plausibility_summary"].
```

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug formdesigner-validation-audit-trail --feature-id FEAT-732`
2. **Read the spec** — §1 NG3, §7 R10.
3. **Check dependencies** — TASK-4645 must be `done` (it adds the three fields and the `Any` import).
4. **Verify the Codebase Contract** — re-run every `grep -c`.
5. **Update status** → `"in-progress"` in the per-spec index.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only the six listed files.
9. **Close** — `scripts/sdd/close_task.sh TASK-4646 formdesigner-validation-audit-trail verified`.
10. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker orchestrator; implemented by seat gpt-5.6-terra (codex), attempt 1 (uid 6a8592265ea1451483e57f18854555c9), duration 187s
**Date**: 2026-10-23
**Notes**: wire_report() strips audit-only plausibility fields from client responses; handlers.py/audio_ws.py use it. Merge-tier validation green. Orchestrator diff review: no fixes needed. Closed with close_task.sh (engine exposes no durable review-evidence ref for finalize_task).

**Deviations from spec**: none
