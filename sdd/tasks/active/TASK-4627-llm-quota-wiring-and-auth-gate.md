# TASK-4627: Wire the quota + auth-gate the public LLM opt-in (closes the ledger issue)

**Feature**: FEAT-728 — FormBuilder LLM-validation enforcement policy + LLM quota
**Spec**: `sdd/specs/formbuilder-llm-validation-enforcement.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4625, TASK-4626
**Assigned-to**: unassigned

**Discovered-from**: `issue:44941ecac8cc`

---

## Context

Spec §3 Module 4 (wiring half) and §1's security gap. This task is what
actually closes ledger issue `44941ecac8cc`: `POST …/validate` is mounted
`tenant="public"` (`api/routes.py:419`) and a public form's URLs are
auth-exempt, so `?llm_validation=true` buys an anonymous caller one LLM call
per request with no quota. The audit for this feature found the broader half
the issue does not mention: `POST …/data` is public too (`api/routes.py:428`)
and runs the check with **no opt-in at all** whenever the form enables
`llm_validation` on any field (`api/handlers.py:262-281`).

Depends on TASK-4625 because it edits the same two handlers (serialized by
design), and on TASK-4626 for `LLMQuota`.

---

## Scope

- Add `llm_quota: LLMQuota | None = None` to `setup_form_api`, build a default
  instance when omitted, stash it as `app["llm_quota"]`, and hand it to the
  handler.
- `validate`: ignore the `llm_validation` opt-in for an unauthenticated caller
  and report `plausibility: {"status": "skipped", "reason": "unauthenticated_opt_in"}`;
  for an authenticated caller charge the quota and answer `429` +
  `Retry-After` when it is exhausted.
- `submit_data`: charge the quota before the pipeline may call the LLM. On
  exhaustion, answer `429` + `Retry-After` under `review`/`reject` (fail
  closed, nothing stored) and proceed with a skipped report
  (`reason="rate_limited"`) under `annotate`.
- Tests for both paths, both policies and both auth states.

**NOT in scope**: the limiter itself (TASK-4626); the gate (TASK-4624); the
`422` mapping (TASK-4625); a Redis backend; raising the `403` alternative that
spec §7 explicitly rejected.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Auth gate on the opt-in, quota charge on both paths, `429` replies |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `llm_quota` kwarg, default instance, `app["llm_quota"]` stash |
| `packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py` | CREATE | Auth-gate and quota tests across both endpoints |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from ..services.llm_quota import LLMQuota, QuotaDecision     # created by TASK-4626
# already present in handlers.py / routes.py — do not re-add:
from aiohttp import web
# JSONResponse is the response helper used by `validate` (verified: api/handlers.py:1187);
# `submit_data` uses its own local `_reply(...)` closure (verified: api/handlers.py:1786).
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(                                     # line 192
    app: web.Application,
    *,
    client: "AbstractClient | None" = None,             # line 196
    ...,
    public_base_url: str | None = None,                 # line 213
    teams_renderer: "AbstractFormRenderer | None" = None,   # line 214  <-- kwarg anchor (1 occurrence)
) -> None:                                              # line 215
    ...
    _stash_without_clobbering(app, "rest_resolver", resolver)       # line 308  (stash idiom)
    app["submission_pipeline"] = handler._build_submission_pipeline()   # line 365  <-- stash anchor
    ...
    app.router.add_post(f"{tp}/forms/{{form_uid}}/validate",
        _wrap_auth(handler.validate, tenant="public"))              # lines 417-420
    app.router.add_post(f"{tp}/forms/{{form_uid}}/data",
        _wrap_auth(handler.submit_data, tenant="public"))           # lines 426-429

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    def _build_submission_pipeline(self, form: FormSchema | None = None) -> "SubmissionPipeline":   # line 262
    def _extract_session_id(self, request) -> str | None:   # session detection at line 577
    async def validate(self, request: web.Request) -> web.Response:
        #  :1157  llm_opt_in = request.query.get("llm_validation", "").lower() == "true"
        #  :1161  pipeline = self._build_submission_pipeline(form if llm_opt_in else None)
        #  :1184  payload: dict[str, Any] = {"is_valid": is_valid, "errors": errors}
        #  :1186      payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)
    async def submit_data(self, request: web.Request) -> web.Response:
        #  :1767  pipeline = self._build_submission_pipeline(form)
        #  :1789  except PlausibilityBlocked as exc: -> _reply(..., 503, {"Retry-After": "30"})  (2 in file)
    # NOTE: line numbers shift by TASK-4625's edits to the same handlers — re-grep the anchors.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/llm_quota.py (after TASK-4626)
class QuotaDecision(BaseModel):
    allowed: bool; retry_after_s: int
class LLMQuota:
    def __init__(self, backend=None, *, enabled=True, limit=10, window_s=60.0, trust_forwarded_for=False) -> None
    def identity(self, request) -> str
    async def acquire(self, request, *, tenant: str | None, form_uid: str) -> QuotaDecision

# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py:13
def public_form_paths(form_uid, tenant, base_path="/api/v1") -> list[str]
    # the five auth-exempt globs — why an anonymous caller reaches /validate and /data at all
```

### Does NOT Exist

- ~~`_wrap_auth(handler.validate, tenant="required")` as the fix~~ — flipping
  the mount would break every public form's pre-submit validation. The fix is
  inside the handler: ignore the LLM *opt-in*, keep the endpoint public.
- ~~a `403` for the anonymous opt-in~~ — spec §7 rejects it explicitly
  (breaks renderers that always send the flag). Return the normal
  `200`/`422` with a skipped report.
- ~~`request["user"]`~~ / ~~`AuthContext.is_authenticated`~~ — not verified
  accessors; the only verified session check is `"session" in request`
  (api/handlers.py:577).
- ~~`app["rate_limiter"]`~~ — the stash key is `app["llm_quota"]` (spec AC14).
- ~~`os.environ` in routes.py~~ — `setup_form_api` takes **no** env-read
  configuration (verified: no `os.environ`/`getenv` in `api/routes.py`). Pass
  the quota as a kwarg.
- ~~`LLMQuota` read from `form.llm_validation`~~ — forbidden by spec AC14.
- ~~`web.HTTPTooManyRequests`~~ — both handlers return response objects
  (`JSONResponse` / `_reply`), they do not raise aiohttp exceptions.

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
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.validate",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._build_submission_pipeline",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py#public_form_paths"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Fail closed where it matters.** Under `review`/`reject` an exhausted quota
  must answer `429`, never store: otherwise an attacker burns the quota and
  walks garbage past the gate. Under `annotate` the verdict never changed the
  outcome, so skipping the check and storing is correct.
- **Charge exactly once per request**, and only when an LLM call is actually
  possible (form enables `llm_validation` on some field; for `/validate` also
  the opt-in). Charging a form with the feature off would rate-limit innocent
  traffic.
- **The 429 body follows the 503 precedent** (`api/handlers.py:1789-1793`):
  `{"error": …, "code": …}` plus a `Retry-After` header.
- **No env reads.** Configuration arrives through `setup_form_api`.
- Protection is **on by default**: `llm_quota=None` builds `LLMQuota()`. Opting
  out is explicit (`LLMQuota(enabled=False)`).
- Line numbers in the contract above predate TASK-4625's edits to the same
  handlers — re-grep every anchor before attaching.

### References in Codebase

- `api/handlers.py:1789-1793` — the `503 PLAUSIBILITY_UNAVAILABLE` reply with
  `Retry-After`: the shape the `429` mirrors.
- `api/routes.py:308` — `_stash_without_clobbering` idiom; `:365` — how
  `app["submission_pipeline"]` is published.

---

## Implementation Blueprint

### Steps (in order)

1. Add the `llm_quota` kwarg, default instance and stash in `routes.py` —
   *why*: the handler needs the object before either endpoint can charge it,
   and `app["llm_quota"]` is what tests and hosts inspect (AC14).
2. Add the auth gate to `validate` — *why*: it is the ledger issue's literal
   fix and it must not change the endpoint's public mount.
3. Add the quota charge to `validate`'s opt-in branch — *why*: an authenticated
   tenant still needs a ceiling.
4. Add the quota charge to `submit_data` with the policy-dependent consequence
   — *why*: this is the path the ledger issue missed, and the fail-closed rule
   is the whole point.
5. Write `test_llm_quota_http.py` — *why*: four behaviours (anon-ignored,
   auth-charged, 429-under-enforcing, skipped-under-annotate) that no other
   test file covers.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY — 1 of 2)

```python
# occurrences: 1 (verified: grep -c '    teams_renderer: "AbstractFormRenderer | None" = None,' packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py)
# AFTER — insert below `    teams_renderer: "AbstractFormRenderer | None" = None,` in setup_form_api's signature (verified: api/routes.py:214)
    llm_quota: "LLMQuota | None" = None,
```

```python
# occurrences: 1 (verified: grep -c '    app["submission_pipeline"] = handler._build_submission_pipeline()' packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py)
# AFTER — insert below `    app["submission_pipeline"] = handler._build_submission_pipeline()` (verified: api/routes.py:365)

    # FEAT-728 — bound every LLM-backed form call. On by default: public /validate and /data
    # are auth-exempt for public forms (services/public_forms.py:13), so an unbounded
    # plausibility check is an unauthenticated LLM spend (ledger issue:44941ecac8cc).
    # Opt out explicitly with LLMQuota(enabled=False).
    quota = llm_quota if llm_quota is not None else LLMQuota()
    handler.llm_quota = quota
    _stash_without_clobbering(app, "llm_quota", quota)
```

**Why**: following `submission_pipeline`'s publication point keeps all handler
collaborators stashed in one place, and `_stash_without_clobbering` is the
file's idiom for "ensure the key exists without overwriting a host's object".
Import `LLMQuota` in the module's existing import block (or under
`TYPE_CHECKING` plus a local import, matching how the file handles its other
service types).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 1 of 3 — `validate` auth gate)

```python
# occurrences: 1 (verified: grep -c '        llm_opt_in = request.query.get("llm_validation", "").lower() == "true"' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below the three opt-in lines (verified: api/handlers.py:1157-1159), BEFORE
#         `data, visit_context = self._extract_visit_context(form, body)` (:1160)

        # FEAT-728 / ledger issue:44941ecac8cc — a public form's /validate is auth-exempt
        # (services/public_forms.py:13), so an anonymous opt-in would be an unauthenticated
        # LLM spend. Ignore the flag rather than 403: a renderer that always sends it keeps
        # working and spends nothing (spec §7 rejects the 403 alternative).
        opt_in_skipped: str | None = None
        if llm_opt_in and "session" not in request:
            llm_opt_in = False
            opt_in_skipped = "unauthenticated_opt_in"
        elif llm_opt_in:
            decision = await self._llm_quota().acquire(
                request, tenant=tenant, form_uid=str(form_uid)
            )
            if not decision.allowed:
                return JSONResponse(
                    {"error": "Answer plausibility check rate limited", "code": "PLAUSIBILITY_RATE_LIMITED"},
                    status=429,
                    headers={"Retry-After": str(decision.retry_after_s)},
                )
```

```python
# occurrences: 1 (verified: grep -c '            payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below `            payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)` (verified: api/handlers.py:1186)
        elif opt_in_skipped is not None:
            payload["plausibility"] = {"status": "skipped", "reason": opt_in_skipped}
```

**Why**: clearing `llm_opt_in` is enough to stop the LLM call, because
`:1161` already builds a checker-less pipeline when the flag is false — no other
branch needs to know. The `elif` keeps the explicit skip visible to the client
without inventing a second response key. `FILL IN` below covers how `tenant` /
`form_uid` are named in this handler's scope.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 2 of 3 — helper)

```python
# occurrences: 1 (verified: grep -c '    def _build_submission_pipeline(self, form: FormSchema | None = None) -> "SubmissionPipeline":' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# AFTER — insert below the body of `_build_submission_pipeline` (verified: api/handlers.py:262, body ends at :290)

    def _llm_quota(self) -> "LLMQuota":
        """The quota set by ``setup_form_api``, or a default one for standalone handlers.

        Built lazily so a handler constructed directly in a test still charges a
        real (empty) quota instead of crashing on a missing attribute.
        """
        quota = getattr(self, "llm_quota", None)
        if quota is None:
            from ..services.llm_quota import LLMQuota  # noqa: PLC0415 — lazy, mirrors this file's style

            quota = LLMQuota()
            self.llm_quota = quota
        return quota
```

**Why**: `setup_form_api` assigns `handler.llm_quota`, but `FormAPIHandler` is
also instantiated directly (by tests and by hosts that mount routes
themselves), so the accessor must tolerate the attribute being absent — the
same defensive shape `_get_llm_client` uses (`api/handlers.py:198-216`).

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY — 3 of 3 — `submit_data`)

```python
# occurrences: 1 (verified: grep -c '        pipeline = self._build_submission_pipeline(form)' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py)
# BEFORE — insert ABOVE `        pipeline = self._build_submission_pipeline(form)` (verified: api/handlers.py:1767)

        # FEAT-728 — charge the quota only when an LLM call is actually possible, then let the
        # form's policy decide the consequence: fail CLOSED under review/reject (otherwise an
        # attacker burns the quota and walks garbage past the gate), skip under annotate (where
        # the verdict never changed the outcome anyway).
        plausibility_override: "PlausibilityReport | None" = None
        if any(llm_validation_enabled(form, f) for f in form.iter_fields_recursive()):
            decision = await self._llm_quota().acquire(request, tenant=tenant, form_uid=str(form_uid))
            if not decision.allowed:
                policy = form.llm_validation.on_implausible if form.llm_validation else "annotate"
                if policy != "annotate":
                    return _reply(
                        {"error": "Answer plausibility check rate limited", "code": "PLAUSIBILITY_RATE_LIMITED"},
                        status=429,
                        headers={"Retry-After": str(decision.retry_after_s)},
                    )
                # FILL IN: build the skipped report to pass through as `plausibility=` so the
                #          response and the stored context both say why the check did not run
                #          — bounded by AC12 (reason="rate_limited", threshold from the form's
                #          config or LLMValidationConfig() default)
```

```python
# occurrences: 1 (verified: grep -c '                plausibility_ack=plausibility_ack,' packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py — present after TASK-4625)
# AFTER — add the override to the same `pipeline.submit(...)` call (verified: api/handlers.py:1768-1781)
                plausibility=plausibility_override,
```

**Why**: passing a pre-built `skipped` report as `plausibility=` reuses the
pipeline's existing "a report supplied by the caller is used as-is" branch
(`services/submission_pipeline.py:187-189`), so the LLM is not called and the
stored `context["llm_validation"]` still explains itself — no new pipeline
parameter needed. `llm_validation_enabled` and `PlausibilityReport` must be
imported where this handler can see them (the file already imports
`llm_validation_enabled` locally inside `_build_submission_pipeline` at
`:270` — add a module-level or local import here as the `FILL IN` notes).

### `packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py` (CREATE)

```python
"""Auth gate + LLM quota over the public form endpoints (FEAT-728, TASK-4627)."""

from __future__ import annotations

import pytest
from parrot_formdesigner.services.llm_quota import LLMQuota, QuotaDecision


class ExhaustedQuota:
    """Backend that always denies — the simplest way to test the consequences."""

    def __init__(self, retry_after_s: int = 30) -> None:
        self.calls: list[str] = []
        self._retry = retry_after_s

    async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
        self.calls.append(key)
        return QuotaDecision(allowed=False, retry_after_s=self._retry)


class TestValidateAuthGate:
    async def test_anonymous_opt_in_ignored_no_llm_call(self, make_handler) -> None:
        """No session + ?llm_validation=true -> zero LLM calls, reason=unauthenticated_opt_in."""
        # FILL IN: assert FakeLLM.calls == [] and payload["plausibility"]["reason"] — AC11

    async def test_authenticated_opt_in_runs_once(self, make_handler) -> None:
        # FILL IN: request with a "session" key -> exactly one LLM call — bounded by AC11

    async def test_authenticated_opt_in_429_when_exhausted(self, make_handler) -> None:
        # FILL IN: ExhaustedQuota -> 429 + Retry-After, no LLM call — bounded by AC12


class TestSubmitQuota:
    async def test_enforcing_policy_429_nothing_stored(self, make_handler) -> None:
        """review/reject + exhausted quota must fail closed."""
        # FILL IN: parametrize over review|reject; assert 429 and empty storage — AC12

    async def test_annotate_proceeds_with_skipped_report(self, make_handler) -> None:
        # FILL IN: 200, plausibility.status == "skipped", reason == "rate_limited",
        #          stored context carries it, FakeLLM.calls == [] — bounded by AC12

    async def test_quota_not_charged_when_feature_disabled(self, make_handler) -> None:
        # FILL IN: a form with llm_validation off -> backend.calls == [] — bounded by AC12

    async def test_key_includes_tenant_and_form_uid(self, make_handler) -> None:
        # FILL IN: inspect ExhaustedQuota.calls[0] — bounded by AC12


class TestWiring:
    def test_setup_form_api_publishes_llm_quota(self) -> None:
        # FILL IN: app["llm_quota"] is an LLMQuota — bounded by AC14

    def test_explicit_quota_is_not_clobbered(self) -> None:
        # FILL IN: passing llm_quota=LLMQuota(enabled=False) survives setup — AC14
```

**Why this shape**: `ExhaustedQuota` as a backend (not a mock of `LLMQuota`)
keeps the test honest about the real key-building path, which is what AC12's
key assertion checks. Reuse `make_handler` / `FakeLLM` / `_request` from
`tests/formdesigner/test_http_plausibility.py` (verified: that file, lines
25-60) — `_request` needs a `session`-bearing variant for the authenticated
cases.

### FILL IN checklist

- [ ] `handlers.py::validate` — the in-scope names for `tenant` / `form_uid` in this handler (read the surrounding lines; do not assume); bounded by the Codebase Contract
- [ ] `handlers.py::submit_data` — build the `skipped` / `rate_limited` `PlausibilityReport` and import `PlausibilityReport` + `llm_validation_enabled` into scope; bounded by AC12
- [ ] `routes.py` — place the `LLMQuota` import consistently with the file's other service imports; bounded by the Codebase Contract
- [ ] `test_llm_quota_http.py::*` — 9 bodies; bounded by AC11, AC12, AC14
- [ ] Re-grep every anchor: TASK-4625 edited both handlers, so the line numbers in this task's contract have shifted

---

## Acceptance Criteria

- [ ] An unauthenticated caller's `llm_validation` opt-in on `/validate` performs **zero** LLM calls, and the reply carries `plausibility.status == "skipped"` with `reason == "unauthenticated_opt_in"`; an authenticated caller's opt-in still runs exactly one call (spec AC11).
- [ ] The endpoint stays mounted `tenant="public"` — public-form validation keeps working without auth.
- [ ] Every LLM-backed path charges `LLMQuota.acquire()` before the call, including the public submit (spec AC12).
- [ ] Exhaustion answers `429` + `Retry-After` under `review`/`reject` and on the `/validate` opt-in, with nothing stored; under `annotate` it answers `200` with a skipped report (`reason="rate_limited"`) and no LLM call (spec AC12).
- [ ] A form with `llm_validation` disabled is never charged.
- [ ] `setup_form_api(llm_quota=…)` is honoured; omitted, a default `LLMQuota()` is built; `app["llm_quota"]` is published and an explicitly passed instance is not clobbered (spec AC14).
- [ ] Nothing reads quota settings from `FormSchema` / `LLMValidationConfig` (spec AC14).
- [ ] Ledger issue `44941ecac8cc` is closed by `/sdd-done` through this task's **Discovered-from** line (spec AC18).
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py`

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_route_tenant_coverage.py -q`

---

## Test Specification

See the CREATE block above. Assert on `FakeLLM.calls` emptiness for every
"must not spend" case — a status-code-only assertion would pass while the LLM
was still called.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug formbuilder-llm-validation-enforcement --feature-id FEAT-728`)
2. **Read the spec** at the path listed above (§1's security gap, §3 Module 4, §7's rejected `403`)
3. **Check dependencies** — `TASK-4625` and `TASK-4626` must both be `"done"`.
4. **Verify the Codebase Contract** — TASK-4625 edited both handlers, so
   **re-grep every anchor** and use the fresh line numbers. A count of `0`
   means the anchor moved: stop and report the drift.
5. **Check known issues** for the files you touch:
   `wikitoolkit ledger context packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`
6. **Update status** → `"in-progress"` (set `started_at`), commit only the index
7. **Implement** from the blueprint; complete every `# FILL IN:`. Tests inside a
   worktree need `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Verify** the Validation Commands pass
9. **Commit the code** — stage only the three files this task lists
10. **Close the task**: `scripts/sdd/close_task.sh TASK-4627 formbuilder-llm-validation-enforcement verified`
11. **Fill in the Completion Note** below, then commit the staged SDD state.
    Do NOT run `ledger close` yourself — `/sdd-done` closes
    `issue:44941ecac8cc` by evidence through the **Discovered-from** line.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
