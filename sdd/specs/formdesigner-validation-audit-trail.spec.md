---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [parrot-formdesigner, docs]
tags: [formdesigner, audit-trail, validation, llm-validation, compliance]
---

# Feature Specification: FormDesigner validation audit trail

**Feature ID**: FEAT-732
**Date**: 2026-10-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` validates every submission on two paths — a deterministic
validator (`FormValidator`) and an optional LLM answer-plausibility checker
(`AnswerPlausibilityChecker`). The record it leaves behind has two holes, stated
verbatim as reported:

> 1. **El resultado determinista no se almacena.** Solo se guarda que pasó
>    (`is_valid`). Qué reglas corrieron y qué comprobaron no queda escrito. Para
>    una disputa de facturación eso es "pasó la validación", no "pasó estas 14
>    comprobaciones".
> 2. **El modelo puede quedar sin identificar.** `LLMValidationConfig.model` es
>    `str | None`, y cuando es `None` se usa el modelo por defecto del cliente —
>    con lo que `report.model` queda `null`. Ahí el registro no dice qué modelo
>    respondió. Para un equipo financiero eso es precisamente el agujero que
>    Eduardo anticipa.

Both are confirmed in the code at `ca9938444`:

- `ValidationResult` (`services/validators.py:160-177`) carries only `is_valid`,
  `errors`, `sanitized_data`, `extra_data`. `FormValidator.validate_field`
  returns `list[str]` — the checks that **pass** are never materialised as data
  at any point. `SubmissionPipeline.submit` persists
  `FormSubmission(is_valid=True, …)` (`services/submission_pipeline.py:331-343`)
  and nothing more. Neither is it recorded which `required` the rule resolution
  *relaxed* (`RuleEvaluator.resolve` → `resolution.required`,
  `services/validators.py:291-307`), which is the single most contested fact in a
  dispute over a form that was submitted without a field filled in.
- All four `PlausibilityReport(...)` constructors in `services/plausibility.py`
  (lines 184, 189, 215, 242) pass `model=cfg.model`, including the `status="ok"`
  path, so the stored report echoes what was *requested*, never what answered.

This is a follow-on to FEAT-728 (plausibility enforcement policy), already
merged and closed. FEAT-728 decided *what to do* with a verdict; FEAT-732 makes
the verdict and the deterministic pass **reconstructable after the fact**.

### Goals

- G1. Persist a deterministic validation trace for every submission that the
  shared `SubmissionPipeline` commits: which named checks ran, against which
  field, with which outcome.
- G2. Make the trace *reconstructable*: a reader can re-derive which checks those
  were and against which exact ruleset, without access to this session.
- G3. Record the effective LLM identity (model + provider + usage) of every
  plausibility report whose status is `ok`.
- G4. Keep a `status="ok"` plausibility report from ever being persisted as an
  unidentified success.
- G5. Bound the stored trace so a large form cannot overflow the row, with
  truncation that is explicit rather than silent.
- G6. Expose the trace only through an authenticated, permission-gated read —
  never to a public form client.
- G7. Change no existing public signature: `FormValidator.validate_field` keeps
  its `list[str]` return and every current caller keeps working.

### Non-Goals (explicitly out of scope)

- NG1. **Persisting a trace for validate-only callers.** Four call sites run
  `FormValidator.validate` outside the pipeline and never write a
  `FormSubmission`: `renderers/telegram/router.py:414` and `:463`,
  `ui/telegram.py:117`, `ui/handlers.py:282`, plus the MS Teams presets in
  `packages/ai-parrot-integrations/.../msteams/dialogs/presets/{base,wizard,wizard_summary}.py`.
  They will *produce* a trace (it rides on `ValidationResult`) but nothing
  persists it, because they persist nothing. Routing those channels through
  `SubmissionPipeline` is a separate feature — see §7 Known Risks R1, which this
  spec pins with a test rather than papering over.
- NG2. No new database column and no migration. The trace lands in the existing
  `context` JSONB.
- NG3. No change to the `on_implausible` policy matrix or the wire shapes FEAT-728
  documented in `docs/formdesigner-llm-validation-enforcement.md`. This binds the new
  `PlausibilityReport` fields too: `resolved_model`, `provider` and `usage` are
  persisted, but stay **off** every client-facing dump (see §7 R10).
- NG4. No change to the meaning of `PlausibilityReport.model`. It stays "what the
  config requested" (documented, published); the effective identity arrives in
  new fields.
- NG5. No retention, export or redaction policy for the trace. It inherits the
  lifetime of the submission row.

---

## 2. Architectural Design

### Overview

Two independent closures over the same record, plus one read path.

**A. The deterministic trace — an explicit collector, never an implicit one.**
A new `ValidationTraceCollector` is passed down as an *optional keyword
argument*: `FormValidator.validate(form, data, …, trace=collector)` forwards it
to each `validate_field(field, value, …, trace=collector)` call, including
`validate_field`'s own recursive call for a voice envelope
(`services/validators.py:414-421`). Each named check calls
`collector.record(...)` next to where it already decides. No `ContextVar`: a
ContextVar would make the trace an invisible side effect of an async call tree
that already fans out into remote and cross-field callbacks, and would silently
bind the wrong collector under concurrency. The finished trace lands on a new
`ValidationResult.trace` field, so `ValidationResult` is the **single handoff** —
the pipeline never re-derives anything.

**B. Stable check identity.** Every check is recorded under a stable `CheckId`
enum value, never a function name and never the error string. Error strings are
localised and already change with `locale`; function names are an implementation
detail that refactors rename. Each record carries an outcome of `pass` / `fail` /
`skip`, and a `skip` carries *why* it was skipped — an auditor needs to tell "the
pattern passed" from "the pattern never applied because the optional answer was
empty" from "we never got to the pattern because coercion returned early".

**C. Reconstructability — fingerprint plus two version numbers.** The trace
header carries three independent identifiers, because they fail independently:

| Field | Answers | Why not the others |
|---|---|---|
| `form_version` | "which schema version did the author publish?" | Author-controlled free string (`FormSchema.version` default `"1.0"`, `core/schema.py:467`); an author can change rules without touching it |
| `schema_fingerprint` | "which exact ruleset ran?" | sha256 over the canonical validation-relevant subset of the schema — changes whenever a constraint does, whatever the author called the version |
| `ruleset_version` | "which validator code ran?" | The `parrot-formdesigner` distribution version; a fingerprint is identical across a validator bugfix that changed the outcome |

`schema_fingerprint` is produced by **one** canonical serializer that walks the
*validator's own* traversal, not `FormSchema.iter_fields_recursive()`. These two
traversals genuinely differ: `FormValidator.validate` builds its field list from
`_collect_fields` per section (`services/validators.py:267-270`) and deliberately
excludes each ARRAY field's `item_template` from the per-field loop — the comment
at `services/validators.py:340-356` is explicit that `item_template` ids are
folded in only for the extras diff and "NOT via `all_fields` itself, which must
stay exactly the set the main per-field validate/coerce loop above already
iterated". A fingerprint built on the wrong traversal would hash rules that never
ran, or omit rules that did.

**D. Three detail levels.** A new, **separate** `FormSchema.audit_trail` block —
deliberately not a field on `LLMValidationConfig`, so switching the LLM check off
can never switch deterministic auditing off with it:

- `summary` (**default**): header + fingerprint + per field the list of `CheckId`s
  that ran, and every failure in full. This is what turns "pasó la validación"
  into "pasó estas 14 comprobaciones".
- `full` (opt-in): every check as its own record, with the bound that was applied
  and its outcome.
- `off`: today's behaviour — no collector is constructed, no cost is paid.

**E. The cap.** The trace is serialized and capped **before** it is merged into
`context`, by `cap_trace()`. The pipeline merges `context` with
`llm_validation` and the storage layer then `json.dumps`es the whole blob
unbounded (`services/submissions.py:331`), so capping after the merge would be
capping the wrong object. The cap reserves room for the header and the truncation
metadata, drops field entries in a deterministic order, and records
`truncated: true` with `omitted_fields` / `omitted_checks` counts — so a short
trace is never mistaken for a complete one. The cap's default is resolved **per
detail level** (64 KiB for `summary`, 256 KiB for `full`), because a single flat
default either truncates the opt-in forensic level on an ordinary large form or
over-provisions the common one — see the measurements in §7 R6.

**F. Effective LLM identity.** `AnswerPlausibilityChecker.check` already holds the
response object. `AIMessage.model` and `AIMessage.provider` are **required** `str`
fields (`packages/ai-parrot/src/parrot/models/responses.py:138-139`) and
`AIMessage.usage` is a required `CompletionUsage`
(`responses.py:143`, type at `packages/ai-parrot/src/parrot/models/basic.py:48`). `client.model`, by contrast,
can be `None` (`packages/ai-parrot/src/parrot/clients/base.py:424`), so the
response — never the client — is the source of truth. New fields
`resolved_model`, `provider`, `usage` are read off it. An `ok` response whose
effective model is absent or empty is **not persisted as a success**: it is routed
through the existing `_fail()` / `on_error` path, so a form configured
`on_error: "block"` refuses rather than storing an unattributable pass, and a form
configured `on_error: "skip"` records a `skipped` report with an explicit reason.
A `skipped` or `blocked` report legitimately has no effective model — no call was
made — and its `reason` already says so.

**G. The read path fails closed.** A new authenticated endpoint returns only the
audit projection. It does **not** reuse `_rbac_shadow_gate`
(`api/handlers.py:2220-2284`): that gate returns silently — i.e. **allows** — when
`self._rbac_service is None` (line 2239) and again when resolution raises (line
2254), and it only denies at all when `rbac_enforcing` is `True`, which defaults
to `False` (`api/routes.py:212`). Fail-open is the correct default for the
pre-existing routes it protects and the wrong default for an audit record. A new
sibling `_rbac_require` denies with `403` when the service is missing, when
resolution raises, or when the permission is absent — regardless of
`rbac_enforcing`, which exists to avoid breaking routes that shipped before RBAC,
not routes that ship after it.

The gate also requires a **minimum scope of `CLIENT`**:
`has_permission("read_form_audit", scope=RBACScope.CLIENT)`. That is enforceable
today exactly as written, because `has_permission` genuinely compares scope
*levels* (`services/rbac.py:182-208`, `_SCOPE_ORDER` at `:84`) — an `own`- or
`team`-scoped grant therefore cannot read another subject's audit record, while a
`client`- or `global` grant can. What `has_permission` does **not** do is evaluate
a resource: `_compile_scope_to_policy` hardcodes `resources=["form:*"]`
(`services/rbac.py:298`), so there is no submission- or form-level condition in the
policy at all. Row identity is therefore checked by the handler: the tenant comes
from `_get_tenant` (already validated by `requires_tenant` before the handler
runs, `api/handlers.py:397-409`) and the row's `form_uid` must equal the path's.
A mismatch is a **404**, not a 403, and it is evaluated *after* the permission
gate — otherwise the endpoint would confirm which submission ids exist to a caller
with no permission at all.

Scoping by *submission ownership* is deliberately not attempted. `FormSubmission.user_id`
is `None` unless the form declares a `metadata` block: `submit_data` passes
`user_id=None` (`api/handlers.py:1841`) and the pipeline calls `enrich_submission`
only `if form.metadata:` (`services/submission_pipeline.py:346`). An `own`-scoped
rule would therefore deny every audit read on the majority of forms, public ones
included, because those rows have no owner to compare against.

### Component Diagram

```
FormValidator.validate(form, data, trace=collector)
  ├─ _detect_circular_dependencies ──┐
  ├─ validate_rules ─────────────────┤
  ├─ RuleEvaluator.resolve ──────────┤ record(CheckId, outcome)
  └─ validate_field(…, trace=) ──────┘        │
       required · relation_shape · coerce ·   ▼
       constraints · type · option_set ·  ValidationTraceCollector
       cross_field · async_validator ·        │
       remote_response · rest                 │ .finish(detail, fingerprint)
                                              ▼
                                      ValidationResult.trace
                                              │
SubmissionPipeline.submit ────────────────────┤
  └─ cap_trace() ──→ ctx["validation"] ──→ FormSubmission.context (JSONB)
                     ctx["llm_validation"] ──→ (+ resolved_model/provider/usage)
                                              │
                              ┌───────────────┴───────────────┐
                        generic storage                  sink (mapper
                        (submissions.py)                 carries `context`)
                                              │
GET …/data/{submission_id}/audit ──→ _rbac_require (fail closed) ──→ audit projection
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormValidator.validate` / `.validate_field` | extends (additive kwarg) | `trace=` keyword only; return types unchanged |
| `ValidationResult` | extends | new optional `trace` field |
| `RuleEvaluator.resolve` → `RuleResolution` | reads | `.visible` / `.required` dicts recorded as resolution checks (`services/rule_evaluator.py:70-71`) |
| `FormSchema` | extends | new `audit_trail: AuditTrailConfig \| None` beside `llm_validation` (`core/schema.py:491`) |
| `PlausibilityReport` | extends | `resolved_model`, `provider`, `usage` added; `model` untouched |
| `AnswerPlausibilityChecker.check` | modifies | reads identity off the response; routes an unidentified `ok` through `_fail()` |
| `SubmissionPipeline.submit` | modifies | writes `ctx["validation"]` beside the existing `ctx["llm_validation"]` (`services/submission_pipeline.py:327`) |
| `AudioFormSession` | modifies | parity: the audio path's own `context["llm_validation"]` write (`audio/engine.py:1086`) |
| `FormSubmission.context` | uses | existing free-form JSONB; already selected back (`services/submissions.py:416`) and already carried into sink payloads (`services/sinks/mapper.py:62,84`) |
| `FormSubmissionStorage.get_submission` | uses | the read endpoint's lookup (`services/submissions.py:420-440`) |
| `_wrap_auth` | uses | `tenant="required"` (the default) — never `"public"` (`api/routes.py:85`) |
| `RBACService.resolve` / `RBACContext.has_permission` | uses | behind the new fail-closed gate (`services/rbac.py:467`, `:182`) |

### Data Models

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py  (new)

class AuditDetail(str, Enum):
    """How much deterministic validation evidence to retain."""

    OFF = "off"
    SUMMARY = "summary"
    FULL = "full"


class CheckId(str, Enum):
    """Stable identifier for one deterministic validation check.

    Values are a published contract: they are persisted into submission rows
    and read back by auditors, so they are NEVER derived from a helper name or
    from a localised error message, and an existing value is never renamed.
    """

    # form level — both are early returns in FormValidator.validate
    FORM_CIRCULAR_DEPENDENCIES = "form.circular_dependencies"
    FORM_RULE_INTEGRITY = "form.rule_integrity"
    # rule resolution — what the form actually showed and actually demanded
    RESOLUTION_VISIBLE = "resolution.visible"
    RESOLUTION_REQUIRED = "resolution.required"
    # field level
    FIELD_VOICE_ENVELOPE = "field.voice_envelope"
    FIELD_REQUIRED = "field.required"
    FIELD_RELATION_SHAPE = "field.relation_shape"
    FIELD_COERCE = "field.coerce"
    FIELD_TYPE = "field.type"
    FIELD_OPTION_SET = "field.option_set"
    FIELD_CROSS_FIELD = "field.cross_field"
    FIELD_ASYNC_VALIDATOR = "field.async_validator"
    FIELD_REMOTE_RESPONSE = "field.remote_response"
    FIELD_REST = "field.rest"
    # FieldConstraints bounds
    CONSTRAINT_MIN_LENGTH = "constraint.min_length"
    CONSTRAINT_MAX_LENGTH = "constraint.max_length"
    CONSTRAINT_MIN_VALUE = "constraint.min_value"
    CONSTRAINT_MAX_VALUE = "constraint.max_value"
    CONSTRAINT_PATTERN = "constraint.pattern"
    CONSTRAINT_MIN_ITEMS = "constraint.min_items"
    CONSTRAINT_MAX_ITEMS = "constraint.max_items"
    CONSTRAINT_ALLOWED_MIME_TYPES = "constraint.allowed_mime_types"


class CheckOutcome(str, Enum):
    """Result of one recorded check."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


class SkipReason(str, Enum):
    """Why a check did not run. A skip is evidence, not an absence of evidence."""

    NOT_APPLICABLE = "not_applicable"      # the constraint/option set is not declared
    EMPTY_OPTIONAL = "empty_optional"      # optional field arrived empty — validation short-circuits
    EARLY_RETURN = "early_return"          # an earlier check returned before this one
    NOT_DISPLAYED = "not_displayed"        # rule resolution hid the field, so required was relaxed
    NO_MIME_SIDECHANNEL = "no_mime_sidechannel"  # allowed_mime_types with no resolvable MIME
    WRONG_VALUE_SHAPE = "wrong_value_shape"      # bound declared but the coerced value cannot carry it


class CheckRecord(BaseModel):
    """One check, as retained under ``full`` detail."""

    check: CheckId
    outcome: CheckOutcome
    bound: str | None = None          # the bound applied, e.g. "max_length=120"
    skip_reason: SkipReason | None = None
    message: str | None = None        # the error text, on FAIL only


class FieldTrace(BaseModel):
    """Per-field evidence."""

    field_id: str
    required_effective: bool
    visible_effective: bool
    checks_ran: list[CheckId] = Field(default_factory=list)   # always populated
    records: list[CheckRecord] = Field(default_factory=list)  # `full` detail only
    failures: list[CheckRecord] = Field(default_factory=list)  # every detail level


# Per-detail cap defaults. `full` gets four times the room because it is the
# opt-in level that exists for disputes: a truncated forensic trace on an
# 80-field contract form is the exact failure this feature removes. Measured
# sizes behind these numbers are in §7 R6.
DEFAULT_MAX_BYTES: dict[AuditDetail, int] = {
    AuditDetail.OFF: 0,
    AuditDetail.SUMMARY: 65_536,     # 64 KiB — covers 239-352 fields
    AuditDetail.FULL: 262_144,       # 256 KiB — covers 235-440 fields
}


class AuditTrailConfig(BaseModel):
    """Per-form deterministic-audit settings (``FormSchema.audit_trail``)."""

    detail: AuditDetail = AuditDetail.SUMMARY
    max_bytes: int | None = Field(default=None, ge=1024, le=1_048_576)
    """Hard cap on the serialized trace. ``None`` resolves per `detail` via
    ``DEFAULT_MAX_BYTES`` — an explicit value always wins, in either direction."""

    @property
    def effective_max_bytes(self) -> int:
        """Return `max_bytes`, or the `DEFAULT_MAX_BYTES` entry for `detail`."""


class ValidationTrace(BaseModel):
    """Deterministic validation evidence for one submission."""

    trace_schema: int = 1              # versioned independently of everything else
    detail: AuditDetail
    form_uid: uuid.UUID
    form_id: str
    form_version: str                  # author-controlled
    schema_fingerprint: str            # "sha256:<hex>" over the validation subset
    ruleset_version: str               # parrot-formdesigner distribution version
    locale: str
    validated_at: datetime
    duration_ms: int
    checks_run: int
    checks_failed: int
    is_valid: bool
    form_checks: list[CheckRecord] = Field(default_factory=list)
    fields: list[FieldTrace] = Field(default_factory=list)
    truncated: bool = False
    omitted_fields: int = 0
    omitted_checks: int = 0
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py  (modified)

class PlausibilityReport(BaseModel):
    """Outcome of one plausibility batch."""

    status: Literal["ok", "skipped", "blocked"]
    reason: str | None = None
    model: str | None = None            # UNCHANGED: what the config requested
    resolved_model: str | None = None   # NEW: what actually answered (AIMessage.model)
    provider: str | None = None         # NEW: AIMessage.provider
    usage: dict[str, Any] | None = None  # NEW: AIMessage.usage, JSON-dumped
    threshold: float
    latency_ms: int | None = None
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)
```

### New Public Interfaces

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py  (new)

class ValidationTraceCollector:
    """Accumulates deterministic validation evidence for one `validate` call."""

    def __init__(self, *, detail: AuditDetail, locale: str, clock: Callable[[], datetime] | None = None) -> None:
        """Build a collector. `detail` must not be ``OFF`` — callers skip construction instead."""

    def record_form(self, check: CheckId, outcome: CheckOutcome, *, message: str | None = None) -> None:
        """Record a form-level check (circular dependencies, rule integrity)."""

    def record_resolution(self, field_id: str, *, visible: bool, required: bool) -> None:
        """Record what the rule resolution decided for one field, before any value check."""

    def record(
        self,
        field_id: str,
        check: CheckId,
        outcome: CheckOutcome,
        *,
        bound: str | None = None,
        skip_reason: SkipReason | None = None,
        message: str | None = None,
    ) -> None:
        """Record one field-level check. Idempotent per (field_id, check): the last write wins."""

    def finish(
        self, form: FormSchema, *, fingerprint: str, ruleset_version: str, is_valid: bool
    ) -> ValidationTrace:
        """Seal the collector into a `ValidationTrace`, applying `detail` projection."""


def schema_fingerprint(form: FormSchema) -> str:
    """Return ``"sha256:<hex>"`` over the validation-relevant subset of `form`.

    Walks the SAME field set `FormValidator.validate` iterates — per-section
    `_collect_fields`, ARRAY `item_template` excluded — so the hash covers
    exactly the rules that ran. Serializes canonically (sorted keys, no
    whitespace, UTF-8) over: field_id, field_type, required, constraints,
    option values, relation mode/cardinality, declared rules, and the form's
    `unknown_fields` policy. Deterministic across processes and runs.
    """


def cap_trace(trace: ValidationTrace, *, max_bytes: int) -> dict[str, Any]:
    """Serialize `trace` to a JSON-safe dict within `max_bytes` of UTF-8 JSON.

    Reserves room for the header and the truncation counters, then drops field
    entries in a deterministic order (fields with no failure first, by
    `field_id`), setting `truncated` and the `omitted_*` counters. Failures are
    dropped last — a trace that omits a failure is worse than useless. Never
    returns a payload larger than `max_bytes`.

    Callers pass `AuditTrailConfig.effective_max_bytes`, never the raw
    `max_bytes` field, which may be `None`.
    """
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py  (modified)

    async def get_submission_audit(self, request: web.Request) -> web.Response:
        """GET the audit projection of one submission. Authenticated, never public.

        Returns 200 with `{submission_id, form_uid, form_version, is_valid,
        validation, llm_validation}` — the trace and the plausibility report
        only, never the submitted answers.

        Order is part of the contract: the permission gate runs FIRST, then the
        lookup. 403 when the caller lacks `read_form_audit` at `CLIENT` scope or
        wider; 404 when no row matches `submission_id` in the resolved tenant, or
        when the row's `form_uid` differs from the path's. A caller without the
        permission therefore learns nothing about which submission ids exist.
        """

    async def _rbac_require(
        self, request: web.Request, codename: str, *, scope: RBACScope | None = None
    ) -> None:
        """Fail-CLOSED permission gate — the audit sibling of `_rbac_shadow_gate`.

        Raises `web.HTTPForbidden` when the RBAC service is unavailable, when
        resolution raises, or when the permission is absent at `scope` or wider,
        independent of `self.rbac_enforcing`. Deliberately NOT
        `_rbac_shadow_gate`, which allows in all three of those cases
        (handlers.py:2239, 2254, 2271).

        Takes `scope`, not a `resource` string: `RBACContext.has_permission`
        accepts `(codename, scope)` only and evaluates no resource
        (services/rbac.py:182), so a `resource=` parameter would be a promise the
        RBAC layer cannot keep. Row identity is the caller's job.

        `RBACScope` is imported INSIDE the method body, matching the existing
        idiom at handlers.py:2487 — the module imports only `RBACService`, and
        only under TYPE_CHECKING (handlers.py:103).
        """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: audit-trail core models | yes | Full model set and every `CheckId` / `SkipReason` value fixed in §2 Data Models; new file; export list fixed | — |
| M2: collector, fingerprint, cap | yes | Signatures and semantics fixed in §2 New Public Interfaces; traversal rule and canonical-serialization fields enumerated | — |
| M3: validator instrumentation | no | Which `CheckId` attaches at which existing branch is mechanical, but the `skip` semantics at each of the six early-return branches is a judgement call per branch | — |
| M4: effective LLM identity | yes | Field names, source attributes and the unidentified-`ok` → `_fail()` routing all fixed | — |
| M5: pipeline + audio persistence | yes | Cap-before-merge order and the `ctx["validation"]` key fixed; mirrors the existing `ctx["llm_validation"]` write exactly | — |
| M6: audit read endpoint | no | Route, auth mode and fail-closed semantics are fixed, but the RBAC resource string and the projection's exact tenant check need design judgement | — |
| M7: docs + version | yes | Doc path and version bump fixed | — |

### Module 1: Audit-trail core models
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py` (new)
- **Responsibility**: Declare `AuditDetail`, `CheckId`, `CheckOutcome`, `SkipReason`,
  `CheckRecord`, `FieldTrace`, `AuditTrailConfig` (with `DEFAULT_MAX_BYTES` and
  `effective_max_bytes`), `ValidationTrace`. Add `FormSchema.audit_trail` and
  export the new names from `core/__init__.py`.
- **Depends on**: nothing in this spec (root module).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py  (new)
  # Full model bodies are fixed verbatim in §2 Data Models.

  # packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py  (modifies core/schema.py:491)
  class FormSchema(BaseModel):
      llm_validation: LLMValidationConfig | None = None  # verified: core/schema.py:491
      # FEAT-732 — deterministic audit trail. SEPARATE from llm_validation on
      # purpose: turning the LLM check off must never turn auditing off.
      audit_trail: AuditTrailConfig | None = None
  ```

### Module 2: Collector, fingerprint and cap
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py` (new)
- **Responsibility**: `ValidationTraceCollector`, `schema_fingerprint()`,
  `cap_trace()`. Export from `services/__init__.py`.
- **Depends on**: Module 1.
- **Interface Skeleton**: as written verbatim in §2 New Public Interfaces.

### Module 3: Validator instrumentation
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` (modify)
- **Responsibility**: Add `ValidationResult.trace`; add the `trace=` keyword to
  `validate` and `validate_field`; record each named check at the branch that
  already decides it, including each early return as a `skip`/`fail`; record the
  rule resolution per field; build the fingerprint and seal the collector.
- **Depends on**: Modules 1, 2.
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
  class ValidationResult(BaseModel):  # modifies validators.py:160
      is_valid: bool                                        # verified: validators.py:174
      errors: dict[str, list[str]]                          # verified: validators.py:175
      sanitized_data: dict[str, Any]                        # verified: validators.py:176
      extra_data: dict[str, Any] = Field(default_factory=dict)  # verified: validators.py:177
      trace: ValidationTrace | None = None
      """Deterministic evidence, or ``None`` when auditing is off / no collector was passed."""

  class FormValidator:
      async def validate(  # modifies validators.py:221
          self,
          form: FormSchema,
          data: dict[str, Any],
          *,
          locale: str = "en",
          auth_context: AuthContext | None = None,
          location_vars: dict[str, Any] | None = None,
          visit_context: dict[str, Any] | None = None,
          trace: ValidationTraceCollector | None = None,
      ) -> ValidationResult:
          """<unchanged contract, plus: when `trace` is given, the returned
          ValidationResult carries a sealed ValidationTrace. The two early
          returns (__circular__, __rules__) seal the trace too, with the
          failing form-level check recorded and every field check skipped as
          EARLY_RETURN.>"""

      async def validate_field(  # modifies validators.py:367
          self,
          field: FormField,
          value: Any,
          *,
          all_data: dict[str, Any] | None = None,
          locale: str = "en",
          auth_context: AuthContext | None = None,
          required: bool | None = None,
          trace: ValidationTraceCollector | None = None,
      ) -> list[str]:
          """<unchanged contract and return type. `trace` is forwarded to the
          recursive voice-envelope call at validators.py:414.>"""
  ```

### Module 4: Effective LLM identity
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (modify)
- **Responsibility**: Add `resolved_model`, `provider`, `usage` to
  `PlausibilityReport`; read them off the response in
  `AnswerPlausibilityChecker.check`; route an `ok` response with no effective
  model through `_fail()` so it meets `on_error` instead of being persisted.
- **Depends on**: nothing in this spec (root module — runs in parallel with M1).
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py  (modifies llm_validation.py:78)
  # PlausibilityReport as fixed verbatim in §2 Data Models.

  # packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
  class AnswerPlausibilityChecker:
      @staticmethod
      def _identity(response: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
          """Extract (resolved_model, provider, usage) from an AIMessage-shaped response.

          Reads `response.model` / `.provider` / `.usage` — all required fields on
          AIMessage (responses.py:138-139, basic.py:48). Returns `(None, None, None)`
          when the response does not carry them, which `check()` then treats as an
          LLM failure rather than an unattributable success.
          """
  ```

### Module 5: Pipeline and audio persistence
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` (modify)
- **Responsibility**: Construct the collector when `form.audit_trail.detail` is not
  `off`, pass it into the `submit()` call of `validator.validate`, and write the
  capped trace into `ctx["validation"]` beside the existing `ctx["llm_validation"]`.
  The cap runs **before** the merge into `context`. The audio channel inherits this
  write with **no** audio edit: server-mode audio submits through
  `SubmissionPipeline.submit` (`api/audio_ws.py:1192`), which merges the incoming
  context with `ctx = dict(context or {})` (`services/submission_pipeline.py:325`).
  `pipeline.validate()` (the prepare step) does **not** build a collector — its
  result is never persisted, so a trace there is pure cost (amended at task time).
- **Depends on**: Modules 2, 3, 4.
- **Interface Skeleton** *(signatures + docstrings only)*:
  ```python
  # packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
  class SubmissionPipeline:
      @staticmethod
      def _audit_config(form: FormSchema) -> AuditTrailConfig:
          """Return the form's audit config, or the default when absent."""

      def _new_collector(self, form: FormSchema, *, locale: str) -> ValidationTraceCollector | None:
          """Build a collector, or `None` when detail is OFF (no cost paid)."""
      # validate()  — NOT modified: the prepare step is never persisted, so it builds no collector
      # submit()    — modifies submission_pipeline.py:266 (same) and :327 (writes ctx["validation"])
  ```

### Module 6: Audit read endpoint
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (modify)
- **Responsibility**: `GET {tp}/forms/{form_uid}/data/{submission_id}/audit`,
  registered with `_wrap_auth(..., tenant="required")` (the default — never
  `"public"`), gated by the new fail-closed `_rbac_require` on codename
  `read_form_audit` at a minimum scope of `RBACScope.CLIENT`, returning only the
  audit projection. Permission gate first, then lookup; a `form_uid` mismatch is
  a 404. No policy is seeded — the codename is declared as a constant and granted
  through the existing `POST /org/users/{user_id}/assign` (`api/routes.py:552-555`).
- **Depends on**: Modules 1, 5.
- **Interface Skeleton**: as written verbatim in §2 New Public Interfaces.

### Module 7: Documentation and version
- **Path**: `docs/formdesigner-validation-audit-trail.md` (new),
  `docs/formdesigner-llm-validation-enforcement.md`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` (modify)
- **Responsibility**: Document the three detail levels, the trace shape, every
  `CheckId` value, the three identifiers and why they are three, the cap and its
  truncation markers, the read endpoint and its permission. Add the new
  `PlausibilityReport` fields to the FEAT-728 doc's wire-shape section. Bump
  `__version__` to `1.3.0`.
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_audit_detail_default_is_summary` | M1 | `AuditTrailConfig()` defaults to `summary`; absent block on the form resolves to the same |
| `test_check_id_values_are_stable` | M1 | Every `CheckId` value matches a frozen literal list — guards the published contract against a rename |
| `test_audit_trail_independent_of_llm_validation` | M1 | `llm_validation.enabled=False` with no `audit_trail` block still traces |
| `test_fingerprint_deterministic_across_runs` | M2 | Same form → identical hash; dict ordering in `meta` does not change it |
| `test_fingerprint_changes_with_constraint` | M2 | Changing `max_length` changes the hash while `form.version` stays `"1.0"` |
| `test_fingerprint_excludes_array_item_template` | M2 | The hash covers the validator's traversal, not `iter_fields_recursive` (validators.py:340-356) |
| `test_cap_default_per_detail` | M1 | `max_bytes=None` resolves to 64 KiB under `summary` and 256 KiB under `full`; an explicit value wins in both directions |
| `test_cap_trace_respects_max_bytes` | M2 | 200 fields × 8 checks capped to `max_bytes`; UTF-8 length asserted |
| `test_cap_trace_marks_truncation` | M2 | `truncated=True` and `omitted_fields`/`omitted_checks` non-zero when it cuts |
| `test_cap_trace_drops_failures_last` | M2 | A failing field survives a cap that drops passing fields |
| `test_summary_lists_checks_ran` | M3 | `summary` detail populates `checks_ran` per field and omits per-check `records` |
| `test_full_records_bound_per_check` | M3 | `full` detail carries `bound="max_length=120"` on the pattern/length records |
| `test_relaxed_required_is_recorded` | M3 | A field hidden by rule resolution records `RESOLUTION_VISIBLE=False`, `required_effective=False` and `FIELD_REQUIRED` skipped `NOT_DISPLAYED` |
| `test_empty_optional_skips_downstream` | M3 | An unanswered optional field skips every post-required check as `EMPTY_OPTIONAL` |
| `test_circular_early_return_seals_trace` | M3 | `__circular__` return still yields a trace with `FORM_CIRCULAR_DEPENDENCIES` failed |
| `test_rules_early_return_seals_trace` | M3 | Same for `__rules__` |
| `test_remote_response_early_return_recorded` | M3 | REMOTE_RESPONSE records `FIELD_REMOTE_RESPONSE` and nothing downstream |
| `test_rest_early_return_recorded` | M3 | Same for REST |
| `test_voice_envelope_recursion_keeps_trace` | M3 | The recursive call at validators.py:414 records against the same field_id, once |
| `test_validate_field_signature_unchanged` | M3 | `validate_field` without `trace=` returns `list[str]` and records nothing |
| `test_resolved_model_from_response` | M4 | `cfg.model=None` + response `model="x"` → `model=None`, `resolved_model="x"` |
| `test_model_field_meaning_unchanged` | M4 | `cfg.model="y"` → `report.model == "y"` exactly as before |
| `test_ok_without_model_routes_to_on_error` | M4 | `on_error="skip"` → `status="skipped"` with a reason; `on_error="block"` → `PlausibilityBlocked` |
| `test_skipped_report_has_no_resolved_model` | M4 | No call made ⇒ `resolved_model is None` and `reason` explains it |
| `test_usage_is_json_safe` | M4 | `usage` survives `model_dump(mode="json")` and `json.dumps` |
| `test_rbac_require_fails_closed_no_service` | M6 | `_rbac_service is None` → 403, unlike `_rbac_shadow_gate` (handlers.py:2239) |
| `test_rbac_require_fails_closed_on_exception` | M6 | Resolution raising → 403, unlike handlers.py:2254 |
| `test_rbac_require_ignores_shadow_mode` | M6 | `rbac_enforcing=False` still denies |
| `test_rbac_require_rejects_narrow_scope` | M6 | An `own`- or `team`-scoped `read_form_audit` grant → 403; `client` and `global` → allowed (`rbac.py:182-208`) |
| `test_rbac_require_takes_scope_not_resource` | M6 | The signature is `(request, codename, *, scope)`; no `resource=` parameter exists, since `has_permission` evaluates none |

### Integration Tests

| Test | Description |
|---|---|
| `test_submit_persists_validation_trace` | HTTP submit with `audit_trail` default → `context["validation"]` present, `checks_run > 0`, fingerprint set, beside an intact `context["llm_validation"]` |
| `test_submit_audit_off_writes_nothing` | `detail: off` → no `validation` key; `context` byte-identical to today |
| `test_trace_survives_generic_storage_roundtrip` | `store()` then `get_submission()` returns the trace unchanged through the JSONB codec |
| `test_trace_reaches_sink_payloads` | `context` carries the trace into both tabular and document sink payloads (sinks/mapper.py:62,84) |
| `test_audio_channel_trace_parity` | The audio path writes `context["validation"]` with the same shape as HTTP (engine.py:1086) |
| `test_cap_applied_before_context_merge` | A form large enough to exceed `max_bytes` stores a truncated trace and a complete `llm_validation` |
| `test_audit_endpoint_requires_auth` | Unauthenticated GET → 401/403; the route is not a public-form glob |
| `test_audit_endpoint_returns_projection_only` | 200 body carries `validation` + `llm_validation` and **no** submitted answers |
| `test_audit_endpoint_denies_without_permission` | Authenticated without `read_form_audit` → 403 even at `rbac_enforcing=False` |
| `test_audit_endpoint_404_unknown_submission` | Unknown `submission_id` → 404, after the permission gate, never before |
| `test_audit_endpoint_404_on_form_uid_mismatch` | A real `submission_id` under a different `form_uid` → 404, not 200 and not 403 |
| `test_audit_endpoint_gate_precedes_lookup` | A caller with no permission gets 403 for both an existing and a non-existent `submission_id` — the response does not disclose existence |
| `test_audit_endpoint_full_detail_not_truncated_at_80_fields` | An 80-field form under `full` stores a complete trace with `truncated=false` — the case a flat 64 KiB cap would have cut |
| `test_validate_only_callers_produce_no_persisted_trace` | Pins NG1: the Telegram router and `ui/handlers` validate paths persist nothing, so nobody later reads coverage into them |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/unit/test_llm_validation_policy.py
- packages/parrot-formdesigner/tests/unit/test_core_models.py
- packages/parrot-formdesigner/tests/unit/services/test_validator_extra_data.py
- packages/parrot-formdesigner/tests/unit/services/test_validator_visibility.py
- packages/parrot-formdesigner/tests/unit/services/test_rule_evaluator.py
- packages/parrot-formdesigner/tests/unit/test_submissions.py
- packages/parrot-formdesigner/tests/unit/test_submission_metadata_storage.py
- packages/parrot-formdesigner/tests/test_submission_jsonb_shape.py
- packages/parrot-formdesigner/tests/test_store_context_http.py
- packages/parrot-formdesigner/tests/unit/test_rbac_service.py
- packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py
- packages/parrot-formdesigner/tests/formdesigner/test_http_plausibility.py
- packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline.py
- packages/parrot-formdesigner/tests/formdesigner/test_plausibility_enforcement.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_plausibility_policy.py
- packages/parrot-formdesigner/tests/formdesigner/test_llm_quota_http.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_v2_integration.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py
- packages/parrot-formdesigner/tests/formdesigner/test_submission_pipeline_parity.py
- packages/parrot-formdesigner/tests/formdesigner/test_validator_envelope_any_type.py
- packages/parrot-formdesigner/tests/unit/services/test_rule_validation.py
- packages/parrot-formdesigner/tests/unit/services/test_validator_relation.py
- packages/parrot-formdesigner/tests/unit/services/test_validators_rest.py
- packages/parrot-formdesigner/tests/unit/test_api_feat302.py
- packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py
- packages/parrot-formdesigner/tests/test_submit_merge.py
- packages/parrot-formdesigner/tests/unit/test_audit_trail_models.py
- packages/parrot-formdesigner/tests/formdesigner/test_plausibility_identity.py
- packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py
- packages/parrot-formdesigner/tests/unit/services/test_validation_trace.py
- packages/parrot-formdesigner/tests/unit/services/test_validator_trace_form.py
- packages/parrot-formdesigner/tests/unit/services/test_validator_trace_fields.py
- packages/parrot-formdesigner/tests/formdesigner/test_pipeline_validation_trace.py
- packages/parrot-formdesigner/tests/unit/api/test_submission_audit_endpoint.py
- packages/parrot-formdesigner/tests/unit/test_audit_trail_docs.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def audited_form() -> FormSchema:
    """A form with one required pattern-constrained TEXT, one optional numeric
    bounded field, one SELECT, and one field hidden by a rule — so a single
    submission exercises required, coerce, pattern, bounds, option_set and a
    relaxed required in one trace."""


@pytest.fixture
def wide_form() -> FormSchema:
    """200 constrained fields — the cap fixture. Deliberately above any
    plausible `max_bytes` so truncation is exercised, not approximated."""


@pytest.fixture
def identified_client() -> Any:
    """Fake client whose `ask` returns an AIMessage-shaped object with
    model="fake-model-1", provider="fake", usage=CompletionUsage(...)."""


@pytest.fixture
def unidentified_client() -> Any:
    """Fake client returning a parseable batch but NO model attribute — the
    fixture for the `ok`-without-identity → on_error path."""
```

---

## 5. Acceptance Criteria

- [ ] **AC1** — A submission committed through `SubmissionPipeline.submit` on a form
  with no `audit_trail` block stores `context["validation"]` carrying
  `trace_schema`, `detail="summary"`, `schema_fingerprint`, `ruleset_version`,
  `form_version`, `checks_run`, `checks_failed` and a `fields[]` entry per
  validated field with its `checks_ran`.
- [ ] **AC2** — `detail: "off"` stores no `validation` key and leaves `context`
  byte-identical to the pre-FEAT-732 output for the same submission.
- [ ] **AC3** — `detail: "full"` stores one `CheckRecord` per check with the bound
  that was applied and a `pass`/`fail`/`skip` outcome; every `skip` carries a
  `skip_reason`.
- [ ] **AC4** — A field the rule resolution hid records `visible_effective=False`,
  `required_effective=False` and `FIELD_REQUIRED` skipped as `NOT_DISPLAYED` — the
  relaxation is visible in the record, not inferred from its absence.
- [ ] **AC5** — Both early returns (`__circular__`, `__rules__`) still produce a
  sealed trace naming the failed form-level check.
- [ ] **AC6** — `schema_fingerprint` is byte-stable across processes for an
  unchanged form, changes when any constraint/required/option/rule changes, and is
  computed over the validator's own traversal (ARRAY `item_template` excluded).
- [ ] **AC7** — `ruleset_version`, `form_version` and `schema_fingerprint` are three
  distinct stored fields; a validator-code bump changes `ruleset_version` alone.
- [ ] **AC8** — The serialized `validation` payload never exceeds
  `audit_trail.effective_max_bytes` UTF-8 bytes; when it would, `truncated=true`
  and the `omitted_fields`/`omitted_checks` counters are non-zero, and no
  `failures` entry is dropped while a passing field entry remains.
- [ ] **AC8b** — `max_bytes=None` resolves to 64 KiB under `summary` and 256 KiB
  under `full`; an explicit `max_bytes` overrides both, up or down. An 80-field form
  under `full` is stored complete (`truncated=false`).
- [ ] **AC9** — The cap is applied before the trace is merged into `context`, so
  `context["llm_validation"]` is never truncated by it.
- [ ] **AC10** — `PlausibilityReport.model` keeps its current meaning and value for
  every input that produces a value today.
- [ ] **AC11** — A `status="ok"` report carries a non-empty `resolved_model` and
  `provider`, read from the response, plus a JSON-safe `usage`.
- [ ] **AC12** — A response that parses but carries no effective model never yields
  `status="ok"`: it goes through `on_error` — `skipped` with an explicit reason
  under `skip`, `PlausibilityBlocked` under `block`.
- [ ] **AC13** — A `skipped`/`blocked` report has `resolved_model is None` and a
  `reason` that states why no call was made.
- [ ] **AC14** — The audio channel stores a `context["validation"]` of the same
  shape as the HTTP channel for an equivalent submission.
- [ ] **AC15** — The trace survives a `store()` → `get_submission()` round trip
  unchanged, and reaches both tabular and document sink payloads.
- [ ] **AC16** — `GET {tp}/forms/{form_uid}/data/{submission_id}/audit` is
  registered with `tenant="required"`, returns only `{submission_id, form_uid,
  form_version, is_valid, validation, llm_validation}`, and carries no submitted
  answer.
- [ ] **AC17** — The endpoint returns 403 when the caller lacks `read_form_audit`,
  when the grant is narrower than `CLIENT` scope, when `rbac_service` is `None`,
  and when RBAC resolution raises — in all four cases regardless of
  `rbac_enforcing`.
- [ ] **AC17b** — The permission gate runs before the lookup: a caller without the
  permission receives 403 for an existing and for a non-existent `submission_id`
  alike. A `submission_id` that exists under a different `form_uid` returns 404.
- [ ] **AC18** — `FormValidator.validate_field` called without `trace=` returns
  `list[str]` and behaves exactly as before; `api/handlers.py:743` is unchanged in
  behaviour.
- [ ] **AC19** — No new DB column and no migration: `git diff` touches no DDL.
- [ ] **AC20** — A test pins NG1: the validate-only callers persist no trace, and
  the spec's boundary is asserted rather than assumed.
- [ ] **AC21** — `docs/formdesigner-validation-audit-trail.md` documents the three
  detail levels, every `CheckId`, the three identifiers, the cap markers and the
  endpoint permission; `docs/formdesigner-llm-validation-enforcement.md` gains the
  new `PlausibilityReport` fields.
- [ ] **AC22** — The Validation Contract tests pass, and `ruff check` is clean on
  every touched file.
- [ ] **AC23** — No policy is seeded by this feature. The `read_form_audit` codename
  is a declared constant, and `docs/formdesigner-validation-audit-trail.md` documents
  the grant through the existing `POST /org/users/{user_id}/assign` — including that
  the endpoint 403s until an operator grants it, which is the intended failure.

---

## 6. Codebase Contract

> Verified against `ca9938444` on 2026-10-23.

### Verified Imports

```python
from parrot_formdesigner.core.llm_validation import (  # verified: core/llm_validation.py:28,48,70,81
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,                   # verified: core/llm_validation.py:81
    implausible_fields,                       # verified: core/llm_validation.py:92
)
from parrot_formdesigner.core.schema import FormField, FormSchema  # verified: core/schema.py:411
from parrot_formdesigner.core.types import FieldType               # verified: core/types.py:16
from parrot_formdesigner.services.validators import FormValidator, ValidationResult  # verified: services/__init__.py:32
from parrot_formdesigner.services.rule_evaluator import RuleEvaluator, RuleResolution  # verified: services/__init__.py:31
from parrot_formdesigner.services.submissions import (  # verified: services/__init__.py:26
    CORE_METADATA_COLUMNS,
    FormSubmission,
    FormSubmissionStorage,
)
from parrot_formdesigner.services.plausibility import (  # verified: services/plausibility.py:166,51
    AnswerPlausibilityChecker,
    PlausibilityBlocked,
)
from parrot_formdesigner.services.rbac import RBACScope, RBACService  # verified: services/rbac.py:67,313
from parrot.models.responses import AIMessage      # verified: packages/ai-parrot/src/parrot/models/responses.py:93
from parrot.models.basic import CompletionUsage    # verified: packages/ai-parrot/src/parrot/models/basic.py:48
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py
class ValidationResult(BaseModel):                       # line 160
    is_valid: bool                                       # line 174
    errors: dict[str, list[str]]                         # line 175
    sanitized_data: dict[str, Any]                       # line 176
    extra_data: dict[str, Any] = Field(default_factory=dict)   # line 177

class FormValidator:                                     # line 200
    def __init__(self) -> None: ...                      # line 217
    async def validate(
        self, form: FormSchema, data: dict[str, Any], *, locale: str = "en",
        auth_context: AuthContext | None = None,
        location_vars: dict[str, Any] | None = None,
        visit_context: dict[str, Any] | None = None,
    ) -> ValidationResult: ...                           # line 221
    async def validate_field(
        self, field: FormField, value: Any, *, all_data: dict[str, Any] | None = None,
        locale: str = "en", auth_context: AuthContext | None = None,
        required: bool | None = None,
    ) -> list[str]: ...                                  # line 367
    async def _validate_remote_response(self, field, value, label, *, auth_context=None) -> list[str]: ...  # line 1117
    def _validate_rest_field(self, field, value, label, required=None) -> list[str]: ...                    # line 1192
    def _validate_relation_shape(self, field, value, label) -> list[str]: ...                               # line 539
    def _coerce_value(self, value: Any, field: FormField) -> Any: ...                                       # line 655
    def _validate_by_type(self, value, field, label) -> list[str]: ...                                      # line 942
    async def _run_cross_field_validation(self, field, value, all_data, label, locale) -> list[str]: ...     # line 1257
    async def _run_async_validator(self, field, value, all_data, label, locale) -> list[str]: ...            # line 1297
    def _collect_fields(self, section: FormSection) -> list[FormField]: ...                                  # line 1337
    def _declared_field_ids_for_extras(self, all_fields: list[FormField]) -> set[str]: ...                   # line 1402
    def validate_rules(self, form: FormSchema) -> list[str]: ...                                             # line 1445
    def _detect_circular_dependencies(self, form: FormSchema) -> list[str]: ...                              # line 1626

# Key control-flow facts the trace must mirror:
#   line 256 — circular check, early `return ValidationResult(is_valid=False, …)` on failure
#   line 262 — rule-integrity check, same early-return shape
#   line 287 — RuleEvaluator().resolve(...) -> RuleResolution
#   line 297 — effective_required = resolution.required.get(fid, field.required) and resolution.visible.get(fid, True)
#   line 357 — declared_ids = self._declared_field_ids_for_extras(all_fields)   (extras only; NOT the validated set)
#   line 400 — REMOTE_RESPONSE: `return await self._validate_remote_response(...)`  (early return)
#   line 404 — REST: `return self._validate_rest_field(...)`                        (early return)
#   line 414 — voice envelope: recursive `await self.validate_field(...)`           (trace must be forwarded)
#   line 434 — required-and-empty: `return errors`  (guard at :432)                 (early return)
#   line 438 — not-required-and-empty: `return errors`  (guard at :437)             (early return)
#   line 451 — relation shape failure: `return relation_errors`  (guard at :448)    (early return)
#   line 458 — coercion failure: `return errors`  (call at :455, except at :456)    (early return)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/rule_evaluator.py
class RuleResolution(BaseModel):                         # line 53
    visible: dict[str, bool] = {}                        # line 70
    required: dict[str, bool] = {}                       # line 71
class RuleEvaluator:
    async def resolve(self, form, data, *, locale, location_vars=None, visit_context=None) -> RuleResolution: ...  # line 578

# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class LLMValidationConfig(BaseModel):                    # line 28
    enabled: bool = False
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    on_error: Literal["skip", "block"] = "skip"
    on_implausible: Literal["annotate", "review", "reject"] = "annotate"
    model: str | None = None                             # the reported gap
    timeout_s: float = Field(default=8.0, gt=0.0)
    max_fields: int = Field(default=50, ge=1)
    exclude_field_types: list[FieldType] = Field(default_factory=...)
class PlausibilityReport(BaseModel):                     # line 70
    status: Literal["ok", "skipped", "blocked"]
    reason: str | None = None
    model: str | None = None
    threshold: float
    latency_ms: int | None = None
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)   # line 78

# packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
class AnswerPlausibilityChecker:                         # line 166
    def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None: ...  # line 172
    async def check(self, form, scalars, *, locale, fields=None) -> PlausibilityReport: ...           # line 177
    def _parse(self, response: Any) -> PlausibilityBatch: ...                                         # line 219
    def _fail(self, reason: str) -> PlausibilityReport: ...                                           # line 238
#   line 183 — `if not targets:` → PlausibilityReport(status="ok", …, model=cfg.model, items={})
#   line 185 — `if self._client is None:` → self._fail("no LLM client configured")
#   line 215-217 — the ok return: PlausibilityReport(status="ok", threshold=…, model=cfg.model, latency_ms=…, items=…)
#   line 242-244 — _fail's skipped return

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
class SubmissionPipeline:                                # line 126
    async def validate(self, form, data, *, locale, auth_context, llm_validation=False,
                       visit_context=None, quota_check=None) -> tuple[ValidationResult, PlausibilityReport | None]: ...  # line 209
    async def submit(self, form, data, *, tenant, user_id, locale, context, extra_data,
                     auth_context, merge_session_id, plausibility=None, plausibility_ack=False,
                     request=None, visit_context=None, submission_id=None, quota_check=None) -> SubmitOutcome: ...       # line 230
    def gate_for(self, form, report, *, ack=False) -> ImplausibleSubmission | None: ...  # line 154
    def attach_verdicts(self, data, report) -> dict[str, Any]: ...                       # line 463
#   line 221 — the validate() call to self.validator.validate(...)
#   line 266 — the submit() call to self.validator.validate(...)
#   line 327 — ctx["llm_validation"] = plausibility.model_dump(mode="json")
#   line 331 — FormSubmission(... is_valid=True ... context=ctx or None)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py
class FormSubmission(BaseModel):                         # line 50
    context: dict[str, Any] | None = None                # line 118
class FormSubmissionStorage:
    async def get_submission(self, submission_id: str, *, tenant: str | None = None) -> FormSubmission | None: ...  # line 420
#   line 331 — context_json = json.dumps(submission.context) if submission.context is not None else None  (UNBOUNDED)
#   line 416 — context=_load_json(row["context"])

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                             # line 411
    form_uid: uuid.UUID = Field(default_factory=uuid.uuid4)   # line 465
    version: str = "1.0"                                 # line 467
    metadata: list[FormMetadataField] | None = None      # line 476
    persistence: FormPersistenceConfig | None = None     # line 485
    unknown_fields: UnknownFieldsPolicy = UnknownFieldsPolicy.DROP   # line 487
    llm_validation: LLMValidationConfig | None = None    # line 491

# packages/parrot-formdesigner/src/parrot_formdesigner/services/rbac.py
class RBACScope(str, Enum): OWN/TEAM/CLIENT/GLOBAL       # line 67
_SCOPE_ORDER = [OWN, TEAM, CLIENT, GLOBAL]               # line 84 — 0 narrowest .. 3 widest
def _scope_level(scope: RBACScope) -> int: ...           # line 87
class PermissionRecord(BaseModel):                       # line 135
    user_id: str; codename: str; scope: RBACScope; program_id: int; policy_name: str; tenant: str
class RBACContext(BaseModel):                            # line 162
    permissions: list[PermissionRecord]                  # line 179
    def has_permission(self, codename: str, scope: RBACScope | None = None) -> bool: ...   # line 182
    #   lines 200-208 — a grant at scope S satisfies a required S' iff level(S') <= level(S).
    #   SCOPE LEVELS DO WORK. A `resource` is NEVER evaluated — there is no such parameter.
def _compile_scope_to_policy(user_id, *, program_id, codename, scope, tenant) -> Policy: ...  # line 261
    #   line 298 — resources=["form:*"]  HARDCODED; no submission/form condition ever lands in the policy
    #   line 303 — enforcing=False       every compiled policy is created in shadow mode
class RBACService:                                       # line 313
    async def create_policy(self, policy: Policy) -> Policy: ...                           # line 341
    async def assign_role(self, user_id, *, program_id, codename, scope, tenant) -> PermissionRecord: ...  # line 414
    async def resolve(self, user_id, *, program_id, tenant) -> RBACContext: ...            # line 467
    #   line 496 — `if policy.name.startswith(f"user__{user_id}__")` — ONLY per-user compiled
    #     policies are projected into `permissions`. A hand-written or group-scoped policy row
    #     is INVISIBLE to has_permission, so seeding a generic policy accomplishes nothing.
    #   lines 501-503 — codename and scope are parsed back out of the policy NAME

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
    async def _rbac_shadow_gate(self, request: web.Request, codename: str) -> None: ...    # line 2220
#   line 2239 — `if self._rbac_service is None: return`   (ALLOWS — fail open)
#   line 2254 — `except Exception: ... return`            (ALLOWS — fail open)
#   line 2271 — `if self.rbac_enforcing:` …  else WOULD-DENY (shadow)
    rbac_enforcing: bool = False                                                            # line 158
    def _get_tenant(self, request: web.Request) -> str: ...                                 # line 397
    #   lines 398-409 — the tenant is declared in the URL and already validated + authorized
    #     by `requires_tenant` (api/tenant.py) BEFORE the handler body runs
    async def submit_data(self, request: web.Request) -> web.Response: ...                  # line 1673
    #   line 1841 — pipeline.submit(..., user_id=None, ...)   HTTP submit never sets an owner
    async def assign_user_role(self, request: web.Request) -> web.Response: ...             # line 2442
    #   the grant path; itself gated on `manage_roles` (privilege check ~line 2513)
#   line 103  — `from ..services.rbac import RBACService` is TYPE_CHECKING-only
#   line 2487 — `from ..services.rbac import RBACScope` is a LOCAL import inside the
#     method body. New code needing RBACScope follows that idiom, not a top-level import.
#   line 743 — errors = await self.validator.validate_field(field, value, all_data=answers)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def _wrap_auth(handler: _Handler, *, tenant: str = "required") -> _Handler: ...  # line 85
def setup_form_api(app, registry, *, ..., rbac_service=None, rbac_enforcing=False, ...): ...  # line 193
#   line 212 — rbac_enforcing: bool = False
#   line 367 — app["submission_pipeline"] = handler._build_submission_pipeline()
#   line 422 — add_post(f"{tp}/forms/{{form_uid}}/validate", _wrap_auth(handler.validate, tenant="public"))
#   line 432 — add_post(f"{tp}/forms/{{form_uid}}/data", _wrap_auth(handler.submit_data, tenant="public"))
#   lines 552-555 — add_post("/org/users/{user_id}/assign", _wrap_auth(handler.assign_user_role, tenant="none"))
#     The grant path for `read_form_audit` EXISTS and is routed; nothing new is needed for it.

# packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py
#   line 346 — `if form.metadata:` guards the enrich_submission call, so FormSubmission.user_id
#     stays None on every form without a declared `metadata` block (see handlers.py:1841)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/metadata_enricher.py
#   line 93  — base_user_id = _user_attr(request, "user_id") or _user_attr(request, "id")
#   line 218 — user_id=base_user_id      the ONLY place a submission acquires an owner

# packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/mapper.py
#   line 62, 84 — "context" is listed in both payload column sets (tabular + document)

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):                              # line 93
    model: str = Field(description="The model used for generation")      # line 138  (REQUIRED)
    provider: str = Field(description="The LLM provider …")              # line 139  (REQUIRED)
    usage: CompletionUsage = Field(...)                                  # line 143  (REQUIRED)
    structured_output: Optional[Any] = None                              # used by _parse today

# packages/ai-parrot/src/parrot/clients/base.py
    self.model: str = kwargs.get("model", None)          # line 424 — CAN BE None; not a source of truth

# packages/parrot-formdesigner/src/parrot_formdesigner/version.py
__version__ = "1.2.4"      # current; FEAT-732 targets 1.3.0
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AuditTrailConfig` | `FormSchema` | new optional field beside `llm_validation` | `core/schema.py:491` |
| `ValidationTraceCollector` | `FormValidator.validate` | `trace=` keyword | `services/validators.py:221` |
| `ValidationTraceCollector` | `FormValidator.validate_field` | `trace=` keyword, incl. the recursive call | `services/validators.py:367,414` |
| `ValidationTraceCollector.record_resolution` | `RuleResolution.visible/.required` | dict reads | `services/rule_evaluator.py:70-71`; consumed at `services/validators.py:297` |
| `schema_fingerprint` | `FormValidator._collect_fields` | same traversal, not `iter_fields_recursive` | `services/validators.py:267-270,340-356` |
| `ValidationResult.trace` | `SubmissionPipeline.submit` | attribute read | `services/submission_pipeline.py:266` |
| `cap_trace` | `ctx["validation"]` | called before the `context` merge | `services/submission_pipeline.py:327` |
| `PlausibilityReport.resolved_model` | `AIMessage.model` | attribute read off the response | `services/plausibility.py:216`; `parrot/models/responses.py:138` |
| unidentified-`ok` path | `AnswerPlausibilityChecker._fail` | existing `on_error` routing | `services/plausibility.py:238` |
| `get_submission_audit` | `FormSubmissionStorage.get_submission` | method call | `services/submissions.py:420` |
| `get_submission_audit` route | `_wrap_auth(..., tenant="required")` | route registration | `api/routes.py:85`, pattern at `:432` |
| `_rbac_require` | `RBACService.resolve` + `RBACContext.has_permission` | method calls, fail closed | `services/rbac.py:467,182` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot_formdesigner.core.audit_trail`~~ — created by this feature (M1).
- ~~`parrot_formdesigner.services.validation_trace`~~ — created by this feature (M2).
- ~~`FormSchema.audit_trail`~~ — not a field today; added by M1.
- ~~`ValidationResult.trace`~~ — not a field today; added by M3.
- ~~`ValidationResult.checks`~~ / ~~`.trace_id`~~ / ~~`.audit`~~ — no such attribute, under any name.
- ~~`PlausibilityReport.resolved_model` / `.provider` / `.usage`~~ — not fields today; added by M4.
- ~~`FormValidator.validate(..., trace=)`~~ / ~~`validate_field(..., trace=)`~~ — the keyword does not exist yet.
- ~~`FormValidator.get_checks()`~~ / ~~`.last_trace`~~ — no such method or attribute; there is no per-instance
  state to read a trace from, and adding one would be wrong (a single `FormValidator`
  serves concurrent requests — see `api/routes.py:367`, one pipeline per app).
- ~~a `ContextVar` for the active collector~~ — none exists and none is to be added (§2 A).
- ~~`FormSubmission.validation_trace`~~ / ~~a `validation_trace` column~~ — no column, no migration (NG2).
- ~~`FormSubmissionStorage.store_audit()`~~ / ~~`.get_audit()`~~ — do not exist; the trace rides in `context`.
- ~~a submission read route~~ — `api/routes.py` registers **no** GET for submissions today;
  `grep -n submission api/routes.py` returns only wiring lines, never a route. M6 adds the first one.
- ~~`handler.get_submission`~~ / ~~`handler.list_submissions`~~ — no such handler methods.
- ~~`_rbac_require`~~ — does not exist; only the fail-OPEN `_rbac_shadow_gate` (`handlers.py:2220`).
- ~~`RBACContext.has_permission(resource=...)`~~ — the signature is `(codename, scope=None)` only
  (`services/rbac.py:182`); it evaluates **no** resource, so resource scoping must be done
  by the caller, not delegated to it. `_rbac_require` therefore takes `scope=`, never
  `resource=`.
- ~~a seeding hook / default-policy bootstrap for RBAC~~ — none exists, and a seeded policy
  would not work: `resolve()` projects only `user__{user_id}__*` policies
  (`services/rbac.py:496`). Grants go through `assign_role` / `assign_user_role` only.
- ~~a group- or role-based path into `RBACContext.permissions`~~ — `resolve()` reads
  `auth.user_groups` into `RBACContext.groups` (`services/rbac.py:524-525`) but **never**
  turns a group into a `PermissionRecord`.
- ~~`AuditTrailConfig.max_bytes` as a plain required `int`~~ — it is `int | None`; callers
  read `effective_max_bytes`, which resolves the per-detail default.
- ~~`AbstractClient.resolved_model`~~ / ~~`.effective_model`~~ — do not exist. `client.model`
  exists but can be `None` (`clients/base.py:424`).
- ~~`AIMessage.model_name`~~ / ~~`.llm`~~ — the field is `model` (`responses.py:138`).
- ~~`PlausibilityItemOut.model`~~ — the per-item LLM output carries no model
  (`services/plausibility.py:34-39`).

### Edit Sites (Blueprint Anchors)

> Verified against `ca9938444` (2026-10-23). `/sdd-task` MUST re-run `grep -c`
> per row — this table saves the search, not the check.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/audit_trail.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validation_trace.py` | CREATE | — | — | — |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | MODIFY | `    llm_validation: LLMValidationConfig \| None = None` | `core/schema.py:491` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | `    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)` | `core/llm_validation.py:78` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/__init__.py` | MODIFY | `from .llm_validation import (` | `core/__init__.py:60` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `    extra_data: dict[str, Any] = Field(default_factory=dict)` | `services/validators.py:177` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `        circular_errors = self._detect_circular_dependencies(form)` | `services/validators.py:256` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `        rule_errors = self.validate_rules(form)` | `services/validators.py:262` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `        declared_ids = self._declared_field_ids_for_extras(all_fields)` | `services/validators.py:357` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `    async def validate_field(` | `services/validators.py:367` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/validators.py` | MODIFY | `        label = _resolve_localized(field.label, locale) or field.field_id` | `services/validators.py:396` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `        if not targets:` | `services/plausibility.py:183` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `            status="ok", threshold=cfg.threshold, model=cfg.model, latency_ms=latency_ms, items=verdicts` | `services/plausibility.py:216` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `    def _fail(self, reason: str) -> PlausibilityReport:` | `services/plausibility.py:238` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/submission_pipeline.py` | MODIFY | `                ctx["llm_validation"] = plausibility.model_dump(mode="json")` | `services/submission_pipeline.py:327` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            payload["plausibility"] = plausibility.model_dump(mode="json", exclude_none=True)` | `api/handlers.py:1243` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `                    "plausibility": exc.report.model_dump(mode="json", exclude_none=True),` | `api/handlers.py:1869` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `            body_out["plausibility"] = outcome.plausibility.model_dump(mode="json", exclude_none=True)` | `api/handlers.py:1896` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/audio_ws.py` | MODIFY | `        summary = state.plausibility.model_dump(mode="json") if state.plausibility is not None else None` | `api/audio_ws.py:1257` | 1 |

`audio/engine.py:1086` was listed here at spec time and is **not** an edit site:
see §3 Module 5. Editing it would add a second writer of the same key.
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | `    async def _rbac_shadow_gate(` | `api/handlers.py:2220` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `        _wrap_auth(handler.submit_data, tenant="public"),` | `api/routes.py:433` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/__init__.py` | MODIFY | `from .validators import FormValidator, ValidationResult` | `services/__init__.py:32` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/version.py` | MODIFY | `__version__ = "1.2.4"` | `version.py:5` | 1 |
| `docs/formdesigner-validation-audit-trail.md` | CREATE | — | — | — |
| `docs/formdesigner-llm-validation-enforcement.md` | MODIFY | `## 4. Wire shapes` | `docs/formdesigner-llm-validation-enforcement.md:71` | 1 |

Anchors with `is_required = field.required if required is None else required`
(`validators.py:393` **and** `:1247`) are **ambiguous — do not use that line as an
anchor**. Attach to `async def validate_field(` (:367) or
`label = _resolve_localized(...)` (:396) instead, both unique.
Likewise `errors: list[str] = []` occurs **8 times** in `validators.py` and must
never be used as a bare anchor.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 for every model; `str`-valued `Enum`s so the JSONB round trip is
  readable and stable.
- Async-first; the collector is pure in-memory bookkeeping and must do no I/O.
- `self.logger` (`logging.getLogger(__name__)`), never `print`.
- Google-style docstrings, strict type hints, 120 columns, `black` + `ruff`.
- `aiohttp` only — the read endpoint is an aiohttp handler registered through
  `_wrap_auth`, exactly like its neighbours.
- Mirror the existing `ctx["llm_validation"]` write rather than inventing a second
  persistence idiom (`services/submission_pipeline.py:327`).
- Additive-only signatures: new parameters are keyword-only with a `None` default.

### Known Risks / Gotchas

- **R1 — Channel coverage is not uniform, and the spec says so.** Telegram
  (`renderers/telegram/router.py:414,463`, `ui/telegram.py:117`), `ui/handlers.py:282`
  and the MS Teams presets call `FormValidator.validate` directly and never write a
  `FormSubmission`, so they inherit a trace object but persist nothing. Mitigation:
  NG1 states the boundary, and AC20 pins it with a test so a later reader cannot
  mistake "a trace exists in memory" for "a trace is on the record".
- **R2 — The fingerprint traversal is a real trap.** `FormValidator` and
  `FormSchema.iter_fields_recursive` walk different field sets, and
  `AnswerPlausibilityChecker.eligible_fields` already uses the latter
  (`services/plausibility.py:95`). Hashing the wrong one yields a fingerprint that
  certifies rules which never ran. Mitigation: one canonical serializer in M2,
  pinned by `test_fingerprint_excludes_array_item_template`.
- **R3 — `_rbac_shadow_gate` fails open in three places** (`handlers.py:2239`,
  `:2254`, `:2271`). Reusing it for the audit read would ship an endpoint that
  serves audit records to anyone whenever RBAC is unconfigured, which is the
  default. Mitigation: a separate `_rbac_require`; AC17 tests all three paths.
- **R4 — `RBACContext.has_permission` evaluates no resource** — it matches a
  codename and an optional scope only (`services/rbac.py:182`), and
  `_compile_scope_to_policy` hardcodes `resources=["form:*"]` (`:298`). Resolved
  (§8 Q1): the gate requires `CLIENT` scope or wider — scope *levels* do work
  (`:84`, `:182-208`) — and the handler checks row identity itself (tenant +
  `form_uid`, mismatch ⇒ 404). Ownership scoping is **not** attempted, because
  `FormSubmission.user_id` is `None` on any form without a `metadata` block
  (`api/handlers.py:1841`, `services/submission_pipeline.py:346`), so an `own` rule
  would deny every audit read on most forms.
- **R4b — only per-user compiled policies are visible to `resolve()`.** It projects
  a policy into `permissions` únicamente when the name starts with
  `user__{user_id}__` (`services/rbac.py:496`). A hand-written or group-scoped
  policy row is invisible to `has_permission`, so "seed a policy" is not an
  available strategy without changing `resolve()`. Resolved (§8 Q2): nothing is
  seeded; the grant goes through `assign_user_role`
  (`POST /org/users/{user_id}/assign`, `api/routes.py:552-555`, itself gated on
  `manage_roles`), and the doc says so.
- **R5 — `context` is serialized unbounded today** (`services/submissions.py:331`).
  The cap must therefore be enforced on the trace before the merge; capping later,
  or trusting the storage layer, caps nothing.
- **R6 — Cost on wide forms, measured not guessed.** `summary` is the default
  precisely so the common case stores field→`CheckId[]` lists rather than a record
  per check. Serialized UTF-8 JSON of the §2 shapes (header alone: 671 bytes):

  | fields | summary / 4 checks | summary / 8 | full / 4 | full / 8 |
  |---|---|---|---|---|
  | 50 | 9,872 | 14,222 | 30,322 | 56,222 |
  | 100 | 19,072 | 27,772 | 59,972 | 111,772 |
  | 200 | 37,472 | 54,873 | 119,272 | 222,873 |

  Fields that fit a candidate cap: **64 KiB** → summary 239–352, full **58–109**;
  **256 KiB** → summary 964–1418, full 235–440. A flat 64 KiB would therefore have
  truncated `full` on an ordinary 80-field form — which is why the default is
  per-detail (§2 E). Numbers reproduced by the script recorded with this feature's
  design research. The `wide_form` fixture must still exceed whichever cap the test
  sets, so truncation is exercised rather than approximated.
- **R7 — Localised error text must not leak into check identity.** `CheckRecord.message`
  may carry the localised message, but `CheckId` never derives from it, or the same
  submission traced in `es` and `en` would produce different "checks".
- **R8 — Audio parity comes through the pipeline, not the engine.** `audio/engine.py:1086`
  writes `context["llm_validation"]` into the context it *hands to* the pipeline; it
  persists nothing itself. Server-mode audio commits through
  `SubmissionPipeline.submit` (`api/audio_ws.py:1192`), so AC14 holds by
  construction and the engine is left untouched. Client-submit mode
  (`_do_client_submit`) is validate-only — the host persists — and falls under NG1.
- **R10 — The new report fields would leak through four client-facing dumps.**
  `PlausibilityReport` is `model_dump`ed straight onto the wire at `api/handlers.py:1243`
  (validate), `:1869` (422 refusal), `:1896` (submit 200) and `api/audio_ws.py:1257`
  (client-submit summary). Adding `resolved_model`/`provider`/`usage` would publish
  the vendor, the model and token usage to public form clients and break NG3.
  Mitigation: a `wire_report()` helper in `core/llm_validation.py` excludes the
  audit-only fields; those four sites call it, persistence keeps the full dump.
  `Field(exclude=True)` was rejected: it would also drop the fields from the
  persistence dump at `services/submission_pipeline.py:327`, which is the one place
  they are needed.
- **R9 — The `version.py` / docs mismatch.** `docs/formdesigner-llm-validation-enforcement.md`
  already claims `parrot-formdesigner >= 1.3.0` while `version.py` still reads
  `1.2.4`. M7 bumps to `1.3.0`, which makes the existing doc true rather than
  introducing a new inconsistency.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | None. `hashlib`, `json`, `datetime` and `enum` are stdlib; Pydantic v2 and aiohttp are already direct dependencies. |

---

## 8. Open Questions

None open. All three were resolved on 2026-10-23 before task decomposition.

- [x] **Q1** — How far should resource scoping go on the audit read for v1?
  *Resolved*: tenant + `form_uid` checked by the handler, **plus** a minimum RBAC
  scope of `CLIENT` on the permission, so an `own`/`team` grant cannot read another
  subject's audit record. Ownership filtering on `user_id` was rejected on evidence:
  that column is `None` on any form without a `metadata` block
  (`api/handlers.py:1841`, `services/submission_pipeline.py:346`), so an `own` rule
  would deny every audit read on most forms, public ones included. Escalated from
  design review S10, now closed. → §2 G, §3 M6, §7 R4, §5 AC17/AC17b.
- [x] **Q2** — Should the `read_form_audit` permission be seeded by this feature?
  *Resolved*: **no**. The codename is declared as a constant and documented; an
  operator grants it through the existing `POST /org/users/{user_id}/assign`
  (`api/routes.py:552-555`, gated on `manage_roles`). The endpoint 403s until then,
  and that is the intended failure. Seeding was also found not to be available as
  posed: `RBACService.resolve` projects only policies named `user__{user_id}__*`
  (`services/rbac.py:496`), so a seeded or group-scoped policy row would be
  invisible to `has_permission`. → §3 M6, §7 R4b, §5 AC23.
- [x] **Q3** — Confirm the `max_bytes` default. *Resolved*: the default is resolved
  **per detail level** — 64 KiB for `summary`, 256 KiB for `full` — after measuring
  the serialized shapes. A flat 64 KiB covers `summary` to 239–352 fields but cuts
  `full` at 58–109, i.e. it would truncate the forensic level on an ordinary
  80-field form. An explicit `max_bytes` still overrides either way. → §2 E, §2 Data
  Models `DEFAULT_MAX_BYTES`, §7 R6, §5 AC8/AC8b.

Resolved before drafting (decided by the product owner; carried into the body, not
re-opened):

- [x] Granularity of the deterministic trace — *Resolved*: three levels,
  `summary` default + `full` opt-in + `off`, with a schema fingerprint for
  reconstructability and a hard size cap. → §2 D/C/E, §5 AC1–AC3, AC6–AC8.
- [x] Where the trace is persisted — *Resolved*: `context["validation"]` as JSONB,
  symmetric with the existing `context["llm_validation"]`; no migration, no new
  column. → §2 Overview, NG2, §5 AC1/AC19.
- [x] How to identify the model that answered — *Resolved*: do **not** change the
  meaning of `PlausibilityReport.model`; add `resolved_model`, `provider` and
  `usage` read off the response `AIMessage`. → §2 F, NG4, §5 AC10–AC13.
- [x] Whether the trace is exposed on the wire — *Resolved*: not in the submit or
  validate responses; authenticated, permission-gated read by `submission_id`.
  → §2 G, §5 AC16/AC17.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the accepted design intent
> (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-732/design_research/`
>
> Note on provenance: this run had no `sdd/proposals/*.{brainstorm,proposal}.md`
> to read from — the design intent came from the reporter's own problem statement
> plus the four product decisions, rendered into the neutral brief verbatim. No
> draft, reasoning or preferred conclusion of the spec author was in the brief.
> All 11 suggestions' `affected_paths` passed containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Route all committed channels through `SubmissionPipeline` (architecture) | CONFIRM (as a scope boundary) | Verified: Telegram, `ui/handlers` and the MS Teams presets do call `FormValidator` directly and persist nothing. Re-routing them is a separate feature; the honest move is to declare the boundary and test it rather than claim parity | §1 NG1, §7 R1, §5 AC20 |
| S2 | Separate deterministic-trace configuration model (api) | CONFIRM | Folding the setting into `LLMValidationConfig` would make `enabled: false` silently disable deterministic auditing — exactly the coupling the feature exists to break | §2 D, M1 |
| S3 | Make `ValidationResult` the sole trace handoff (architecture) | CONFIRM | Removes the pipeline's second source of truth; also matches the already-fixed constraint that the collector is an explicit keyword, forwarded through the recursive voice call | §2 A, M3 |
| S4 | Stable check identifiers, not helper names or error text (api) | CONFIRM | Error strings are localised and helper names get refactored; either would make the record unstable across a `locale` change. Drove the `CheckId` enum and `skip`/`pass`/`fail` + `SkipReason` semantics | §2 B, Data Models, §7 R7 |
| S5 | Version both the fingerprint and the validator ruleset (risk) | CONFIRM | `form.version` is an author-controlled free string and a validator bugfix changes outcomes without changing any schema. Three independent identifiers is the only way to tell those apart | §2 C, §5 AC7 |
| S6 | Centralize canonical fingerprint with the validation traversal (architecture) | CONFIRM | Verified the two traversals genuinely differ (`validators.py:267-270` vs `iter_fields_recursive`, with the explicit comment at `:340-356`), and `plausibility.py:95` already uses the other one | §2 C, M2, §7 R2, AC6 |
| S7 | Cap the serialized trace deterministically before persistence (risk) | CONFIRM | Verified `submissions.py:331` dumps `context` unbounded, so a post-merge cap caps nothing. Fixed the cap point, the ordering, and "failures dropped last" | §2 E, M2 `cap_trace`, AC8/AC9 |
| S8 | Resolve effective LLM identity from the response (api) | CONFIRM | Matches the fixed decision, and adds the part it did not cover: an `ok` with no effective model must route through `on_error` rather than persist an unattributable success | §2 F, M4, AC12 |
| S9 | Dedicated authenticated submission-audit read contract (architecture) | CONFIRM | Verified `api/routes.py` registers no submission GET at all, and `get_submission` already exists — so the endpoint is new work, and the projection must exclude answers | §2 G, M6, AC16 |
| S10 | Do not rely on RBAC shadow checks for audit authorization (risk) | CONFIRM (escalation now resolved) | The fail-open paths are confirmed at `handlers.py:2239/2254/2271`, so a separate fail-closed gate is adopted outright. Its further ask — scope the resource — was escalated as §8 Q1 and resolved on 2026-10-23: `CLIENT`-minimum scope plus handler-side tenant/`form_uid` identity. Its suggestion to carry `submission_id`/`form_uid` *in the RBAC resource* is the one part REJECTED: `has_permission` accepts `(codename, scope)` only and evaluates no resource (`rbac.py:182`), so a `resource=` parameter would be a promise the layer cannot keep | §2 G, §7 R4, AC17/AC17b |
| S11 | Contract tests for trace completeness and cross-channel parity (testing) | CONFIRM | Its branch list (early returns, relaxed required, the three detail modes, cap markers, the three sink families, missing-model, allow/deny reads) is more complete than the draft test table and was folded in wholesale | §4 Unit + Integration Tests |

Summary: **11** confirmed · **0** rejected · **1** escalated and since resolved
(S10's scoping depth → §8 Q1, closed 2026-10-23). One sub-point of S10 — carrying
the resource inside the RBAC check — was rejected on evidence; see its row.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-732
  (`.claude/worktrees/feat-FEAT-732-formdesigner-validation-audit-trail`, created from
  `origin/dev` by `python -m scripts.sdd.ensure_worktree`). The `sdd-coder` engine
  gives each task its own sub-worktree inside it.
- **Module dependency graph**:
  - M1 and M4 are independent roots — M4 touches only `core/llm_validation.py` and
    `services/plausibility.py`, neither of which M1 needs. They run concurrently.
  - M2 → M1 (imports `AuditDetail`, `CheckId`, `ValidationTrace`).
  - M3 → M1, M2 (imports `ValidationTraceCollector`, `schema_fingerprint`).
  - M5 → M2 (`cap_trace`), M3 (`ValidationResult.trace`), M4 (the new report fields).
  - M6 → M1 (the trace model for the projection), M5 (something must be stored first).
  - M7 → M1–M6 (documents the finished surface).
- **Shared files** (their tasks serialize):
  - `core/__init__.py` — M1 and M4 both extend the export list.
  - `services/__init__.py` — M2 and M3 both extend the export list.
  - `services/validators.py` — every M3 task (4 distinct anchors in one file).
  - `services/plausibility.py` — every M4 task (3 anchors).
- **Exclusive resources**: `version.py` (M7) — one bump, never concurrent.
- **Cross-feature dependencies**: none. FEAT-728 is already merged
  (`2bfaf7ea3`, PR #1783). No open spec touches `services/validators.py`,
  `services/plausibility.py` or `services/submission_pipeline.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-23 | Jesus Lara | Initial draft — two audit-trail gaps closed; four product decisions carried in; 11 design-review suggestions triaged |
| 0.2 | 2026-10-23 | Jesus Lara | §8 Q1–Q3 resolved: `CLIENT`-minimum scope + handler-side row identity (ownership filtering rejected on evidence); no policy seeded; per-detail cap defaults after measuring serialized sizes |
| 0.3 | 2026-10-23 | Jesus Lara | Task-time amendments from verification: audio parity via the pipeline (engine.py not edited); prepare-step `validate()` builds no collector; R10 — new report fields kept off four wire dumps via `wire_report()`; two Validation Contract paths corrected, two touched suites added |
