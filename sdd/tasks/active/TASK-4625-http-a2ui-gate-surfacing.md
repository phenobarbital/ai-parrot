# TASK-4625: Surface the gate on HTTP and A2UI (ack flag + 422 mapping)

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4624
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. TASK-4624 makes the pipeline refuse an implausible
submission; this task is how a client learns about it and clears it. The
reconfirmation flag is read exactly where the existing `llm_validation` flag is
read — popped off the body before visit-context extraction, or it would be
reported as an undeclared field under `unknown_fields=reject`. The dry-run
(`/validate`) and the commit (`/data`) must answer with the same code and the
same `errors`, which is why both call `gate_for()` rather than re-deriving the
decision.

---

## Scope

- Add `FormAPIHandler._plausibility_ack(request, body)`.
- `submit_data`: read the ack, pass `plausibility_ack=` to `pipeline.submit()`,
  and map `ImplausibleSubmission` to a `422` carrying `code`, `errors` and the
  report (A2UI: the same `422` through `a2ui_wire.validation_errors`).
- `validate`: apply `gate_for()` to the dry-run so it reports the same
  `code`/`errors` the commit would, including the A2UI branch.
- Extend `tests/formdesigner/test_http_plausibility.py` with the round-trip,
  the `reject` path, the A2UI envelopes and the unknown-field guard.

**NOT in scope**: the quota and the auth gate on the opt-in (TASK-4627 — it
touches the same file and therefore runs after this task); the audio channel
(TASK-4628); any change to `SubmissionPipeline` (TASK-4624 owns it); the
`PlausibilityBlocked` → `503` behaviour, which stays exactly as it is.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Ack helper, `submit_data` wiring + mapping, `validate` dry-run mapping |
| `packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py` | MODIFY | Round-trip, reject, A2UI and unknown-field tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# inside handlers.py the pipeline exceptions are imported LOCALLY, per handler
# (verified: api/handlers.py:1153-1154 in validate, :1764-1765 in submit_data):
from ..services.plausibility import PlausibilityBlocked
from ..services.submission_pipeline import ImplausibleSubmission, SubmitSinkError, ValidationFailed
#   ImplausibleSubmission added by TASK-4624 (services/submission_pipeline.py __all__)
# already available at module scope, do not re-import:
from ..api import a2ui_wire            # used as a2ui_wire.* — verified: api/handlers.py:1180-1183
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    async def validate(self, request: web.Request) -> web.Response:
        #  :1153  from ..services.plausibility import PlausibilityBlocked        (2 occurrences in file)
        #  :1157  llm_opt_in = request.query.get("llm_validation", "").lower() == "true"
        #  :1158  if isinstance(body, dict) and body.pop("llm_validation", None) is True:
        #  :1159      llm_opt_in = True
        #  :1160  data, visit_context = self._extract_visit_context(form, body)   (2 occurrences in file)
        #  :1161  pipeline = self._build_submission_pipeline(form if llm_opt_in else None)
        #  :1163  result, plausibility = await pipeline.validate(...)
        #  :1166  except PlausibilityBlocked as exc: -> JSONResponse(..., status=503)   (2 in file)
        #  :1173  errors = dict(result.errors)
        #  :1177  is_valid = not errors                                          (1 occurrence)
        #  :1179  if a2ui_surface_id is not None:
        #  :1181      return a2ui_wire.a2ui_response([], status=200)
        #  :1182      return a2ui_wire.a2ui_response(a2ui_wire.validation_errors(a2ui_surface_id, errors), status=422)
        #  :1184  payload: dict[str, Any] = {"is_valid": is_valid, "errors": errors}   (1 occurrence)
        #  :1186      payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)
        #  :1187  return JSONResponse(payload, status=200 if is_valid else 422)
    async def submit_data(self, request: web.Request) -> web.Response:
        #  :1724  data, visit_context = self._extract_visit_context(form, body)   (2 occurrences in file)
        #  :1767  pipeline = self._build_submission_pipeline(form)                (1 occurrence)
        #  :1768  outcome = await pipeline.submit(form, data, tenant=..., ...)
        #  :1785  except ValidationFailed as exc:                                 (1 occurrence)
        #  :1786      return _reply({"is_valid": False, "errors": exc.errors}, status=422)
        #  :1789  except PlausibilityBlocked as exc: -> _reply(..., status=503)   (2 in file)
        #  :1810      body_out["plausibility"] = outcome.plausibility.model_dump(mode="json", exclude_none=True)
    def _extract_session_id(self, request) -> str | None:
        #  :577   if "session" in request:   — how a navigator session is detected

# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
def validation_errors(surface_id: str, errors: dict[str, list[str] | str]) -> list[dict[str, Any]]:   # line 222
def a2ui_response(envelopes, status: int = 200) -> web.Response:   # verified in use: api/handlers.py:1181

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py (after TASK-4624)
class ImplausibleSubmission(Exception):
    policy: Literal["review", "reject"]; fields: list[str]
    report: PlausibilityReport; errors: dict[str, list[str]]
    @property
    def code(self) -> str
class SubmissionPipeline:
    def gate_for(self, form, report, *, ack: bool = False) -> ImplausibleSubmission | None
    async def submit(self, form, data, *, ..., plausibility_ack: bool = False, ...) -> SubmitOutcome
```

### Does NOT Exist

- ~~`_reply` in `validate`~~ — `_reply(...)` is a local closure of
  `submit_data` only. In `validate` the response helper is `JSONResponse(...)`
  (verified: api/handlers.py:1187). Do not cross them.
- ~~`request.query.getone`~~ / ~~`request.query.get("plausibility_ack", False)`~~
  — follow the existing idiom exactly:
  `request.query.get("<flag>", "").lower() == "true"` (api/handlers.py:1157).
- ~~`a2ui_wire.plausibility_errors()`~~ / ~~`a2ui_wire.gate_errors()`~~ — the
  only per-field error builder is `validation_errors()` (a2ui_wire.py:222).
- ~~`AuthContext.is_authenticated`~~ — `AuthContext` carries *outbound*
  credentials (`services/auth_context.py:40-44`); it says nothing about the
  caller. (Authentication is TASK-4627's concern anyway.)
- ~~`outcome.gate`~~ / ~~`SubmitOutcome.rejected`~~ — the refusal arrives as an
  exception, never on the outcome.
- ~~`ImplausibleSubmission.status_code`~~ — the exception carries `code` (a
  string); the HTTP status (`422`) is chosen here, at the handler.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._build_submission_pipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#validation_errors",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py#SubmissionPipeline.submit"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Pop before extract.** `_plausibility_ack` must run *before*
  `self._extract_visit_context(form, body)` on both handlers, or the flag lands
  in `result.extra_data` and a `unknown_fields=reject` form answers `422
  __unknown__` instead of accepting the reconfirmation (spec AC8).
- **One decision, two call sites.** `validate` must call
  `pipeline.gate_for(form, plausibility, ack=...)`; it must not compare
  confidences itself (spec AC10).
- **`422`, not `400`/`409`.** The gate is a validation-class refusal and reuses
  `ValidationFailed`'s status and body keys so existing clients render it.
- The `except ImplausibleSubmission` branch in `submit_data` must sit **before**
  any broad `except`, and next to `except ValidationFailed` (`:1785`) for
  readability.
- Never log answer values or verdict reasons.

### References in Codebase

- `api/handlers.py:1155-1164` — the `llm_validation` flag's pop-before-extract
  handling: copy it exactly for `plausibility_ack`.
- `api/handlers.py:1179-1183` — the existing A2UI 422 branch in `validate`.
- `api/handlers.py:1785-1793` — `submit_data`'s `except` ladder.

---

## Implementation Blueprint

### Steps (in order)

1. Add the `_plausibility_ack` static helper next to the other request helpers
   — *why*: both handlers need it and the flag has two spellings (query + body).
2. Wire it into `validate` and apply `gate_for()` to the dry-run — *why*: AC10
   requires the dry-run and the commit to agree, and the dry-run is what a
   renderer calls before enabling its submit button.
3. Wire it into `submit_data` and add the `except ImplausibleSubmission` branch
   — *why*: this is the path that must not store (AC5/AC7).
4. Extend `test_http_plausibility.py` — *why*: it already owns the FEAT-649
   HTTP matrix and the `annotate` regression test (AC3).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 1 of 4)

```python
# occurrences: 1 (verified: grep -c '    def _build_submission_pipeline(self, form: FormSchema | None = None) -> "SubmissionPipeline":' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below the body of `_build_submission_pipeline` (verified: api/handlers.py:262, body ends at :290)

    @staticmethod
    def _plausibility_ack(request: web.Request, body: Any) -> bool:
        """Read the plausibility reconfirmation flag (FEAT-728).

        Accepts ``?plausibility_ack=true`` or a body ``plausibility_ack: true``,
        and POPS the body key so it is never judged as an undeclared answer —
        the same handling the ``llm_validation`` flag gets
        (verified: api/handlers.py:1157-1159).

        Args:
            request: The inbound request (query string).
            body: The parsed JSON body, mutated in place when it is a dict.

        Returns:
            True when the client reconfirmed the flagged answers.
        """
        ack = request.query.get("plausibility_ack", "").lower() == "true"
        if isinstance(body, dict) and body.pop("plausibility_ack", None) is True:
            ack = True
        return ack
```

**Why this shape**: a `@staticmethod` because it touches no handler state, and
mutating `body` in place is what makes "pop before extract" possible without
returning a second value. Keep the two spellings: the query flag serves plain
HTML renderers, the body flag serves A2UI/JSON clients that cannot set a query.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 2 of 4 — `validate`)

```python
# occurrences: 2 (verified: grep -c '        data, visit_context = self._extract_visit_context(form, body)' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# FILL IN: disambiguate — this is the `validate` copy at api/handlers.py:1160, identified by the
#          three lines ABOVE it. Attach the new line between :1159 and :1160:
#              llm_opt_in = request.query.get("llm_validation", "").lower() == "true"
#              if isinstance(body, dict) and body.pop("llm_validation", None) is True:
#                  llm_opt_in = True
#          + INSERT HERE
#              data, visit_context = self._extract_visit_context(form, body)
        ack = self._plausibility_ack(request, body)
```

```python
# occurrences: 1 (verified: grep -c '        is_valid = not errors' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `        is_valid = not errors` (verified: api/handlers.py:1177)

        # FEAT-728 — the dry-run reports the gate the commit would apply (AC10).
        gate = pipeline.gate_for(form, plausibility, ack=ack) if is_valid else None
        if gate is not None:
            is_valid = False
            errors.update(gate.errors)
```

```python
# occurrences: 1 (verified: grep -c '        payload: dict[str, Any] = {"is_valid": is_valid, "errors": errors}' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `        payload: dict[str, Any] = {"is_valid": is_valid, "errors": errors}` (verified: api/handlers.py:1184)
        if gate is not None:
            payload["code"] = gate.code
```

**Why**: computing the gate only when `is_valid` keeps a deterministic `422`
from being relabelled with a plausibility code, and folding `gate.errors` into
the existing `errors` dict means the A2UI branch at `:1182` and the JSON branch
at `:1187` both pick it up with no further change — the A2UI envelopes come for
free. Do NOT move the A2UI branch.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 3 of 4 — `submit_data`)

```python
# occurrences: 2 (verified: grep -c '        data, visit_context = self._extract_visit_context(form, body)' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# FILL IN: disambiguate — this is the `submit_data` copy at api/handlers.py:1724, identified by the
#          comment block immediately above it ("Split off an optional caller-supplied store
#          context…", :1720-1723). Insert the new line directly ABOVE that comment block so the
#          flag is popped before the body is treated as answers:
        plausibility_ack = self._plausibility_ack(request, body)
```

```python
# occurrences: 1 (verified: grep -c '        pipeline = self._build_submission_pipeline(form)' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — add the new keyword to the `pipeline.submit(...)` call that follows (verified: api/handlers.py:1767-1780);
#         insert it directly below `                merge_session_id=None,  # partial cleanup stays here: …`
                plausibility_ack=plausibility_ack,
```

```python
# occurrences: 1 (verified: grep -c '            return _reply({"is_valid": False, "errors": exc.errors}, status=422)' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `            return _reply({"is_valid": False, "errors": exc.errors}, status=422)` (verified: api/handlers.py:1786), i.e. a new except branch after `except ValidationFailed`
        except ImplausibleSubmission as exc:
            # FEAT-728 — nothing was stored; `review` is clearable with plausibility_ack=true.
            return _reply(
                {
                    "is_valid": False,
                    "code": exc.code,
                    "errors": exc.errors,
                    "plausibility": exc.report.model_dump(mode="json", exclude_none=True),
                },
                status=422,
            )
```

**Why**: the new branch sits between `ValidationFailed` and `SubmitSinkError`,
so the ladder reads in refusal order; `_reply` (not `JSONResponse`) is required
here because it is `submit_data`'s local response helper and carries the
lifecycle `user_message` handling. Also extend the local import at `:1765` to
bring in `ImplausibleSubmission`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 4 of 4 — local import)

```python
# occurrences: 1 (verified: grep -c '        from ..services.submission_pipeline import SubmitSinkError, ValidationFailed' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# REPLACE the line `        from ..services.submission_pipeline import SubmitSinkError, ValidationFailed` (verified: api/handlers.py:1765)
        from ..services.submission_pipeline import ImplausibleSubmission, SubmitSinkError, ValidationFailed
```

**Why**: `submit_data` imports its pipeline exceptions locally (that is the
file's existing pattern, kept so tests can rebind the module); `validate` needs
no new import because it only calls `pipeline.gate_for()`.

### `packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'class TestBlockMode:' packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py)
# AFTER — insert below the body of `class TestBlockMode:` (verified: that file)


class TestEnforcementPolicy:
    """FEAT-728 — the gate on HTTP and A2UI."""

    async def test_annotate_low_confidence_still_200(self, make_handler) -> None:
        """Regression: today's behaviour is the default (AC3)."""
        # FILL IN: reuse the existing low-confidence fixture shape — bounded by AC3

    async def test_review_422_then_ack_200(self, make_handler) -> None:
        """422 PLAUSIBILITY_REVIEW with per-field errors, then plausibility_ack=true stores."""
        # FILL IN: assert code, errors keys, nothing stored on the first call, stored on the
        #          second, and context["llm_validation"]["acknowledged"] — bounded by AC7

    async def test_reject_422_even_with_ack(self, make_handler) -> None:
        # FILL IN: both calls 422 PLAUSIBILITY_REJECTED, storage empty — bounded by AC7

    async def test_ack_query_flag_accepted(self, make_handler) -> None:
        # FILL IN: ?plausibility_ack=true via request.query — bounded by AC7

    async def test_ack_not_reported_as_unknown_field(self, make_handler) -> None:
        """unknown_fields=reject must not see plausibility_ack."""
        # FILL IN — bounded by AC8

    async def test_validate_dry_run_matches_submit(self, make_handler) -> None:
        # FILL IN: same payload -> same code and errors from /validate and /data — AC10

    async def test_validate_a2ui_review_envelopes(self, make_handler) -> None:
        # FILL IN: one error envelope per flagged field + the trailing updateDataModel — AC9
```

**Why this shape**: the file already owns `FakeLLM`, `_form`, `_request` and
`make_handler` (verified: that file, lines 25-60) — reuse them; a new fixture
set here would drift from the FEAT-649 tests that guard the same handlers.

### FILL IN checklist

- [ ] `handlers.py::validate` — disambiguate the `_extract_visit_context` anchor (2 occurrences; the `validate` copy is at `:1160`); bounded by the Codebase Contract
- [ ] `handlers.py::submit_data` — disambiguate the same anchor (`:1724` copy) and place the pop above the visit-context comment block; bounded by AC8
- [ ] `test_http_plausibility.py::TestEnforcementPolicy::*` — 7 bodies; bounded by AC3, AC7, AC8, AC9, AC10

---

## Acceptance Criteria

- [ ] `POST …/data` answers `422` with `{"is_valid": false, "code": "PLAUSIBILITY_REVIEW"|"PLAUSIBILITY_REJECTED", "errors": {<field_id>: [<reason>]}, "plausibility": {…}}` (spec AC7).
- [ ] Re-submitting with `plausibility_ack=true` (query or body) stores under `review` and still refuses under `reject` (spec AC7).
- [ ] `plausibility_ack` never appears in `extra_data`, including under `unknown_fields=reject` (spec AC8).
- [ ] The A2UI refusal is delivered through `a2ui_wire.validation_errors()` at `422`: one `error` envelope per flagged field plus the trailing `updateDataModel` (spec AC9).
- [ ] `POST …/validate` reports the same `code`/`errors` the commit would for the same payload and policy (spec AC10).
- [ ] With policy `annotate` the HTTP behaviour is unchanged, including `TestValidateOptIn::test_low_confidence_keeps_200` (spec AC3).
- [ ] The `PlausibilityBlocked` → `503 PLAUSIBILITY_UNAVAILABLE` behaviour is untouched on both handlers.
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_validate_a2ui.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_a2ui.py -q`

---

## Test Specification

See the MODIFY block above. Reuse the file's existing `FakeLLM` /
`make_handler` fixtures; assert on storage emptiness, not only on status codes
— a `422` that still wrote a row would pass a status-only assertion.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§3 Module 3, §7 "Dry-run / commit drift")
3. **Check dependencies** — `TASK-4624` must be `"done"`; `ImplausibleSubmission`
   and `gate_for` must exist before you start.
4. **Verify the Codebase Contract** — re-run every `grep -c`. Two anchors have
   2 occurrences; use the quoted context to attach to the right copy. A count of
   `0` means the anchor moved: stop and report the drift.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`. Tests inside a
   worktree need `PYTHONPATH=packages/parrot-formdesigner/src`.
7. **Verify** the Validation Commands pass
8. **Commit the code** — stage only the two files this task lists
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4625 formbuilder-llm-validation-enforcement verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
