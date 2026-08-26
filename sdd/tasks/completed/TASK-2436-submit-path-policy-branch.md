# TASK-2436: Policy branch in `submit_data` — capture, cap, reject, forward, notify

**Feature**: FEAT-458 — Unknown-Field Capture Policy for Form Submissions
**Spec**: `sdd/specs/formdesigner-unknown-fields-capture.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2432, TASK-2433, TASK-2434, TASK-2435
**Assigned-to**: unassigned
**Implements**: Spec section 3 Modules 5 and 7

---

## Context

Where the feature becomes real. Everything before this task is inert plumbing:
the enum exists, the diff is computed, the column is there — but nothing reads the
policy. After this task, `drop` behaves exactly as today (loudly, via a debug log),
`keep` captures within a cap, and `reject` fails the submission.

> ⚠️ **BLOCKED ON FEAT-457** (`formbuilder-formschema-persistency`, 15 tasks, all
> `in-progress` as of 2026-08-24). FEAT-457/TASK-2428 *"Replace the block at
> `api/handlers.py:1615-1622`"* with a sink branch — the exact storage call site
> this task extends. Do NOT start until FEAT-457 has merged to `dev`, then write
> against the rewritten block: attach `extra_data` to the `FormSubmission` BEFORE
> the branch so both arms (generic storage and sink) carry it.

Implements spec section 3 Modules 5 and 7 (Module 7's forwarder merge is folded in
here — it is one line inside the same policy branch, and splitting it would put two
tasks in the same function).

---

## Scope

- In `submit_data` (`api/handlers.py:1440`), after the validation block (`:1549`)
  and the existing `not result.is_valid` early return (`:1552-1565`), branch on
  `form.unknown_fields`:
  - **`REJECT`** and `result.extra_data` non-empty → dispatch `onError`
    best-effort, then return `422` with
    `{"is_valid": False, "errors": {"__unknown__": [<offending key names>]}}`,
    mirroring the shape and the dispatch order of `:1552-1565`.
  - **`KEEP`** → call `enforce_extras_cap(result.extra_data)`; on
    `ExtrasCapExceeded` dispatch `onError` best-effort and return `422` naming the
    exceeded limit, its actual value and its maximum. Within the cap, set
    `extra_data=result.extra_data or None` on the `FormSubmission` construction at
    `:1572-1580` — **`None`, never `{}`** (spec AC23).
  - **`DROP`** → do not attach anything; when `result.extra_data` is non-empty emit
    `self.logger.debug` recording the form and the number of discarded keys.
- Compute the effective forward/notify payload once — `{**result.sanitized_data,
  **(result.extra_data or {})}` under `KEEP`, plain `result.sanitized_data`
  otherwise — and use it at:
  - the forwarder call (`:1629`, currently `forward(result.sanitized_data, form.submit)`);
  - the `onAfterSubmit` dispatch (`:1664`, currently `payload=submission.data`).
- Add a comment at the forwarder call site recording that the storage/wire
  asymmetry (split at rest, flat on the wire) is **deliberate**, so it is not
  "corrected" later.
- Update the `submit_data` docstring flow list (`:1443-1454`) to describe the branch.
- Write unit tests in `packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py`.

**NOT in scope**: The dry-run `validate` route (TASK-2437). `save_partial` — it
keeps its existing `unknown field_id` reject (`:601-603`) verbatim under every
policy (spec AC17). Sink mapping (TASK-2438). The JSON Schema renderer (TASK-2439).
Any change to `FormValidator` — it must stay policy-blind.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Policy branch, forwarded body, `onAfterSubmit` payload, docstring |
| `packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references. Do NOT invent an import or attribute.

### Verified Imports

```python
# NEW imports this task adds:
from ..core.schema import UnknownFieldsPolicy          # TASK-2432
from ..services.unknown_fields import ExtrasCapExceeded, enforce_extras_cap  # TASK-2433

# Already imported INSIDE submit_data at :1456-1462 (local imports, keep the style):
from ..services.metadata_enricher import MetadataResolutionError, enrich_submission
from ..services.submissions import FormSubmission
```

### Existing Signatures to Use

```python
# api/handlers.py:1440
async def submit_data(self, request: web.Request) -> web.Response: ...

# The exact structure this task edits, verified line by line:
#  :1443-1454  docstring flow list — must be updated
#  :1465-1475  form load, tenant assert, enforce_membership_unless_public
#              (route ALSO mounted tenant="public" — unauthenticated reachability)
#  :1484       data, visit_context = self._extract_visit_context(form, body)
#  :1498-1520  optional merge_partials merge
#  :1528-1541  onBeforeSubmit dispatch; `resolution.payload` may REPLACE data (:1540)
#  :1549       result = await self.validator.validate(form, data, visit_context=visit_context)
#  :1552-1565  not result.is_valid -> onError best-effort, then:
#                  return JSONResponse({"is_valid": False, "errors": result.errors}, status=422)
#  :1572-1580  submission = FormSubmission(
#                  submission_id=str(uuid.uuid4()), form_uid=form.form_uid,
#                  form_id=form.form_id, form_version=form.version,
#                  data=result.sanitized_data, is_valid=True,
#                  created_at=datetime.now(timezone.utc),
#              )
#  :1586-1608  enrich_submission + MetadataResolutionError -> 422
#  :1610-1613  if extra_flat: submission.data = {**submission.data, **extra_flat}
#  :1615-1622  if self._submission_storage is not None: await ...store(submission)
#              ^^^ FEAT-457/TASK-2428 REPLACES this block with a sink branch
#  :1624-1631  forwarder block:
#                  fwd_result = await self._forwarder.forward(result.sanitized_data, form.submit)   # :1629
#  :1658-1665  await dispatch("onAfterSubmit", ..., payload=submission.data)   # :1664
#  :1668-1675  success response: submission_id, is_valid, forwarded, forward_status, forward_error

# api/handlers.py:390 — runs BEFORE validation; strips the reserved envelope key,
# with a documented collision guard for a form declaring a real `visit_context` field.
def _extract_visit_context(self, form, body) -> tuple[dict[str, Any], dict[str, Any] | None]: ...

# api/handlers.py:601-603 — save_partial's existing strict reject. LEAVE UNCHANGED.
#   field_errors[field_id] = ["unknown field_id"]

# services/validators.py:87 (after TASK-2434)
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]
    sanitized_data: dict[str, Any]
    extra_data: dict[str, Any]        # NEW — reported, not judged

# services/forwarder.py:61 — signature UNCHANGED; only the argument gets wider
async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult: ...

# services/unknown_fields.py (TASK-2433)
MAX_EXTRA_KEYS: int = 256
MAX_EXTRA_BYTES: int = 256 * 1024
class ExtrasCapExceeded(ValueError):
    limit: Literal["keys", "bytes"]
    actual: int
    maximum: int
def enforce_extras_cap(extras, *, max_keys=MAX_EXTRA_KEYS, max_bytes=MAX_EXTRA_BYTES) -> None: ...

# services/validators.py:158,164 — the existing reserved form-level error keys.
# `__unknown__` follows this convention (resolved).
#   errors["__circular__"] = circular_errors
#   errors["__rules__"] = rule_errors
```

### Does NOT Exist

- ~~`form.unknown_fields`~~ before TASK-2432 lands — verify it exists first.
- ~~`result.extra_data`~~ before TASK-2434 lands — verify it exists first.
- ~~`FormSubmission.extra_data`~~ before TASK-2435 lands — verify it exists first.
- ~~A per-form cap override~~ / ~~a `FormAPIHandler` cap constructor argument~~ —
  resolved: module-level constants only. Do NOT add a knob.
- ~~A per-offending-key error shape for `reject`~~ — resolved: use the reserved
  `__unknown__` key whose value is the list of offending key names.
- ~~`SubmissionForwarder.forward(data, submit_action, extras=...)`~~ — the
  signature is two positional arguments (`services/forwarder.py:61`). Do NOT add a
  parameter; widen the dict you pass.
- ~~A truncation path~~ — `enforce_extras_cap` raises or returns `None`. There is
  no "trim to fit" behaviour to call.
- ~~`self._sink_factory`~~ — planned by FEAT-457/TASK-2428, not landed. Verify the
  post-FEAT-457 shape of `:1615-1622` before editing around it.

---

## Implementation Notes

### Pattern to Follow

```python
# api/handlers.py — after the `not result.is_valid` early return (:1565).
# The ORDER of these two facts is load-bearing and already guaranteed by the
# code above: `result.extra_data` was computed from `data` AFTER
# _extract_visit_context (:1484) and AFTER onBeforeSubmit may have replaced the
# payload (:1540). Do not move this branch earlier.

policy = form.unknown_fields
extras: dict[str, Any] = {}

if result.extra_data:
    if policy is UnknownFieldsPolicy.REJECT:
        _exc = ValueError(f"Unknown fields rejected: {sorted(result.extra_data)}")
        try:
            await dispatch("onError", form=form, request=request, tenant=tenant,
                           auth_context=_auth_ctx, error=_exc)
        except Exception as _meta_exc:
            self.logger.exception("onError handler raised during unknown-field reject: %s", _meta_exc)
        return JSONResponse(
            {"is_valid": False, "errors": {"__unknown__": sorted(result.extra_data)}},
            status=422,
        )
    if policy is UnknownFieldsPolicy.KEEP:
        try:
            enforce_extras_cap(result.extra_data)
        except ExtrasCapExceeded as exc:
            ...  # onError best-effort, then 422 naming exc.limit / exc.actual / exc.maximum
        extras = result.extra_data
    else:  # DROP — today's behaviour, but no longer silent
        self.logger.debug(
            "Discarded %d undeclared field(s) for form %s (unknown_fields=drop)",
            len(result.extra_data), form.form_id,
        )

# ... FormSubmission(..., extra_data=extras or None)   # None, never {} (AC23)

# Storage/wire asymmetry is DELIBERATE: extras are stored in their own column but
# flat-merged on the wire, because the integrator's contract is its own payload
# shape. Declared answers win a key collision.
outbound = {**result.sanitized_data, **extras} if extras else result.sanitized_data
```

### Key Constraints

- **`extras or None`**, never `{}` (spec AC23). A `keep` form that received nothing
  stores SQL `NULL`.
- **Declared answers win collisions** in the merge — `{**sanitized_data, **extras}`
  would let an extra overwrite an answer. Extras cannot collide with a declared
  `field_id` by construction (that is what made them extras), so ordering is
  defensive, not load-bearing; keep `sanitized_data` last if you prefer explicitness
  and document the reasoning either way.
- **Mirror the existing failure shape.** Every early `422` in this function
  dispatches `onError` best-effort inside its own `try/except` first, and lets the
  original status stand. Do not invent a new error style, and do not let an
  `onError` handler's own exception escape.
- `FormEventAbort` from `onBeforeSubmit` is handled at `:1543-1548` and must keep
  bypassing `onError` — do not route the new rejections through that path.
- Keep the local-import style used inside this function (`:1456-1462`).
- `self.logger` only — no `print`.

### References in Codebase

- `api/handlers.py:1552-1565` — the error path to mirror exactly.
- `api/handlers.py:1596-1608` — a second instance of the same pattern (metadata).
- `api/handlers.py:1610-1613` — the `extra_flat` merge; note it targets `data` and
  is a DIFFERENT concept (server-resolved metadata). Leave it alone.
- `services/validators.py:156-166` — the `__circular__`/`__rules__` reserved-key
  convention `__unknown__` follows.

---

## Acceptance Criteria

- [ ] `drop` + extras → `200`, `extra_data IS NULL`, `data` unchanged, and a debug
      log records the discarded count (spec AC1, AC20).
- [ ] `keep` + extras within cap → `200`, extras verbatim in `extra_data`, and no
      undeclared key present in `data` (spec AC4).
- [ ] `keep` + no extras → `extra_data is None`, not `{}` (spec AC23).
- [ ] `keep` + 257 keys → `422` naming the exceeded limit; nothing stored (spec AC5).
- [ ] `keep` + 256 keys exactly → `200`, stored unmodified (spec AC6).
- [ ] `reject` + extras → `422` with `errors["__unknown__"]` listing the offending
      keys, `onError` dispatched first, nothing stored (spec AC7).
- [ ] `reject` + exact payload → `200`.
- [ ] An `onError` handler that itself raises does not change the `422` returned.
- [ ] `keep`: forwarded body == `{**sanitized_data, **extras}`; `drop`: forwarded
      body == `sanitized_data` exactly (spec AC12).
- [ ] `keep`: `onAfterSubmit` payload == `{**submission.data, **extra_data}`;
      `drop`: == `submission.data` (spec AC21).
- [ ] The reserved `visit_context` envelope key never appears in `extra_data`; a
      form declaring a real `visit_context` field keeps it as an answer (spec AC10).
- [ ] A payload replaced by `onBeforeSubmit` with declared fields yields no extras
      (spec AC11).
- [ ] `save_partial` is untouched and still returns `["unknown field_id"]` under
      every policy (spec AC17).
- [ ] The `submit_data` docstring flow list describes the branch.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py -v`
- [ ] No regression: `pytest packages/parrot-formdesigner/tests/ -k "submit or handler" -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/api/test_submit_unknown_fields.py
import pytest


class TestDropPolicy:
    async def test_extras_discarded(self, client, drop_form):
        resp = await client.post(f"/api/v1/forms/{drop_form.form_uid}/submit",
                                 json={"name": "Ana", "junk": 1})
        assert resp.status == 200
        assert (await stored(drop_form)).extra_data is None

    async def test_logs_discarded_count(self, client, drop_form, caplog):
        await client.post(f"/api/v1/forms/{drop_form.form_uid}/submit",
                          json={"name": "Ana", "junk": 1})
        assert "Discarded 1 undeclared field" in caplog.text


class TestKeepPolicy:
    async def test_persists_extras_and_keeps_data_pure(self, client, keep_form):
        resp = await client.post(f"/api/v1/forms/{keep_form.form_uid}/submit",
                                 json={"name": "Ana", "legacy_id": 42})
        assert resp.status == 200
        sub = await stored(keep_form)
        assert sub.extra_data == {"legacy_id": 42}
        assert "legacy_id" not in sub.data

    async def test_no_extras_is_none(self, client, keep_form):
        await client.post(f"/api/v1/forms/{keep_form.form_uid}/submit", json={"name": "Ana"})
        assert (await stored(keep_form)).extra_data is None

    async def test_over_cap_rejected(self, client, keep_form):
        payload = {"name": "Ana", **{f"k{i}": i for i in range(257)}}
        resp = await client.post(f"/api/v1/forms/{keep_form.form_uid}/submit", json=payload)
        assert resp.status == 422
        body = await resp.json()
        assert "keys" in str(body).lower()
        assert await stored(keep_form) is None

    async def test_at_cap_accepted(self, client, keep_form):
        payload = {"name": "Ana", **{f"k{i}": i for i in range(256)}}
        assert (await client.post(f"/api/v1/forms/{keep_form.form_uid}/submit",
                                  json=payload)).status == 200


class TestRejectPolicy:
    async def test_extras_rejected_with_reserved_key(self, client, reject_form):
        resp = await client.post(f"/api/v1/forms/{reject_form.form_uid}/submit",
                                 json={"name": "Ana", "junk": 1, "other": 2})
        assert resp.status == 422
        assert (await resp.json())["errors"]["__unknown__"] == ["junk", "other"]

    async def test_on_error_dispatched_first(self, client, reject_form, spy_dispatch):
        await client.post(f"/api/v1/forms/{reject_form.form_uid}/submit",
                          json={"name": "Ana", "junk": 1})
        assert "onError" in spy_dispatch.events

    async def test_clean_payload_succeeds(self, client, reject_form):
        assert (await client.post(f"/api/v1/forms/{reject_form.form_uid}/submit",
                                  json={"name": "Ana"})).status == 200


class TestOrderingAndWire:
    async def test_visit_context_not_captured(self, client, keep_form):
        await client.post(f"/api/v1/forms/{keep_form.form_uid}/submit",
                          json={"name": "Ana", "visit_context": {"store_groups": [1]}})
        assert (await stored(keep_form)).extra_data is None

    async def test_extras_computed_after_on_before_submit(self, client, keep_form_with_hook):
        """A hook replacing the payload with declared fields yields no extras."""
        await client.post(f"/api/v1/forms/{keep_form_with_hook.form_uid}/submit",
                          json={"junk": 1})
        assert (await stored(keep_form_with_hook)).extra_data is None

    async def test_forward_body_flat_merges(self, client, keep_form_with_endpoint, spy_forwarder):
        await client.post(f"/api/v1/forms/{keep_form_with_endpoint.form_uid}/submit",
                          json={"name": "Ana", "legacy_id": 42})
        assert spy_forwarder.last_payload == {"name": "Ana", "legacy_id": 42}

    async def test_on_after_submit_sees_merged_view(self, client, keep_form, spy_dispatch):
        await client.post(f"/api/v1/forms/{keep_form.form_uid}/submit",
                          json={"name": "Ana", "legacy_id": 42})
        assert spy_dispatch.payload_for("onAfterSubmit") == {"name": "Ana", "legacy_id": 42}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-unknown-fields-capture.spec.md` for full context.
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code: confirm each import
   still resolves and each listed signature still has the listed attributes. Line
   numbers were verified on `dev` at `72490fa14` (2026-08-24) and WILL drift once
   FEAT-456/FEAT-457 land — re-`grep` rather than trusting a number.
4. **Update status** in `sdd/tasks/index/formdesigner-unknown-fields-capture.json` → `"in-progress"`.
5. **Implement** following the scope and contract above. Nothing outside scope.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-26
**Notes**: FEAT-457 had already merged (verified `form.persistence`/sink
branch present at `api/handlers.py`). Added local imports
(`UnknownFieldsPolicy`, `ExtrasCapExceeded`, `enforce_extras_cap`) inside
`submit_data`, matching its existing local-import style. Inserted the
policy branch after the `not result.is_valid` early return and before the
`FormSubmission` construction: `reject` + extras → `onError` best-effort
then `422` with `errors["__unknown__"]` (sorted offending keys); `keep` →
`enforce_extras_cap()`, `422` naming `exc.limit`/`exc.actual`/`exc.maximum`
on `ExtrasCapExceeded`, else `extras = result.extra_data`; `drop` → debug
log with the discarded count. `FormSubmission(..., extra_data=extras or
None)`. Computed `outbound = {**result.sanitized_data, **extras} if
extras else result.sanitized_data` and used it for the forwarder call
(AC12). Computed a SEPARATE `after_submit_payload = {**submission.data,
**extras} if extras else submission.data` for the `onAfterSubmit` dispatch
(AC21) — deliberately NOT reusing `outbound`, because `submission.data`
can differ from `result.sanitized_data` after metadata-enrichment's
`extra_flat` merge (`:1610-1613`-equivalent), and AC21 is stated in terms
of `submission.data` while AC12 is stated in terms of `sanitized_data` —
matching the pre-existing (pre-FEAT-458) asymmetry between the two call
sites rather than "fixing" it. Added the deliberate-asymmetry comment at
the forwarder call site and updated the `submit_data` docstring flow list
with a `4a.` step. 17 new unit tests in
`tests/unit/api/test_submit_unknown_fields.py` (mocked-handler pattern
from `tests/unit/test_submit_path_branch.py`; 3 tests use the REAL
`FormValidator` — not mocked — to prove the visit_context/onBeforeSubmit
wiring inside `submit_data` itself, matching the spec's own Module-5 unit
test table), all passing. Full-suite regression diff (`git stash`
before/after on the complete `pytest packages/parrot-formdesigner/tests/`
run): 114 pre-existing failures, byte-identical set before and after —
zero new failures, zero fixed. `ruff check` on `handlers.py`: 0 new
findings beyond the pre-existing 46 (confirmed via normalized before/after
diff); the 2 new `TRY401` occurrences on my added `self.logger.exception(
"... %s", _meta_exc)` calls are the file's own established pattern,
repeated verbatim per the task's "mirror the existing failure shape"
instruction — not a new category of finding.

**Deviations from spec**: Three files NOT listed in this task's Files
table required a mechanical one-line fixture fix, per the task's own "No
regression" acceptance criterion:
`tests/integration/test_lifecycle_events_submit.py` and
`tests/integration/test_lifecycle_events_e2e.py` each build their
mocked `ValidationResult` via `MagicMock(spec=ValidationResult)` without
setting `.extra_data`; since `spec=` only allows reading attributes that
are explicitly set OR resolvable via `dir()` on the class, and pydantic
v2 model fields are not class-level descriptors, reading the now-required
`result.extra_data` in the new policy branch raised
`AttributeError: Mock object has no attribute 'extra_data'` on every
pre-existing test using that helper. Added `validation_result.extra_data
= {}` / `vr.extra_data = {}` next to the existing `.sanitized_data`
assignment in each helper — same rationale and pattern as TASK-2435's
`test_submission_revisions.py` fix. Swept the whole test tree for any
other `MagicMock(spec=ValidationResult)` site — these two were the only
ones. Verified via `git stash` that these were the only NEW failures
introduced (before this fix: 4 new failures in these two files; after:
0), and that the pre-existing `test_persistence_wiring.py` failures (2)
predate this task entirely and are unrelated.

### Post-completion addendum (adversarial code review, 2026-08-26)

An independent adversarial review (codex) found and I confirmed by live
reproduction: `policy is UnknownFieldsPolicy.REJECT` / `is
UnknownFieldsPolicy.KEEP` in the policy branch silently fail when
`form.unknown_fields` is a raw `str` rather than the enum member —
reproducible via `form.model_copy(update={"unknown_fields": "reject"})`,
which pydantic v2 does not re-validate. No shipped call site actually
triggers this today, but it is one PATCH-policy endpoint away from a real
bug, and the codebase's own established convention elsewhere compares
str-Enum fields with `==`, never `is`.

Fixed in commit `d09f2ac9b`: both comparisons switched to `==`. New test:
`test_reject_fires_when_policy_is_a_raw_string` in
`test_submit_unknown_fields.py`.

Also fixed (found independently while verifying the review, not part of
its findings): `test_on_after_submit_sees_merged_view_under_keep` and
`test_on_after_submit_unchanged_under_drop` did a test-body-local `import
parrot_formdesigner.api.handlers as hm` and patched that reference. An
unrelated pre-existing test
(`tests/unit/api/test_no_navigator_auth_fails_at_import.py`)
unconditionally pops `parrot_formdesigner.api.*` from `sys.modules`
elsewhere in the same directory's suite with no restoration (no
`monkeypatch.setitem`), so when the FULL `tests/unit/api/` directory runs
in one process, a test-time-local import can resolve to a stale module
object relative to `FormAPIHandler` (imported at file-collection time),
making the monkeypatch a silent no-op — the two tests passed in isolation
and via this task's own literal AC command (`pytest ... -k "submit or
handler"`) but failed only in the full-directory run. Switched both to the
file's existing top-level `handlers_module` reference, matching the
pattern every other test in the file already used.
