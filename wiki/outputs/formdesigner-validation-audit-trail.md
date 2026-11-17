# FormDesigner — validation audit trail

> **Feature**: FEAT-732
> **Package**: `parrot-formdesigner` >= 1.3.0
> **Builds on**: FEAT-728 ([`formdesigner-llm-validation-enforcement.md`](formdesigner-llm-validation-enforcement.md))

This document describes the validation audit trail in `parrot-formdesigner`. The audit trail provides deterministic, tamper-evident evidence of validation checks executed during form submissions, recorded per submission in PostgreSQL.

---

## 1. What gets recorded, and where

Deterministic validation evidence is saved in the existing PostgreSQL JSONB column `FormSubmission.context["validation"]`.

- **No schema migration or DDL changes required**: uses the existing `context` JSONB column.
- **Trace model**: `ValidationTrace` sealed model containing metadata, form-level checks, and per-field traces.
- **No trace persisted for validate-only / transient paths**: validate-only endpoints (e.g. preview, Telegram bot, `ui/` handlers, MS Teams presets, audio client-submit) persist no trace because no submission row is created.

---

## 2. Detail levels and the size cap

Audit collection detail is configured per form schema via `FormSchema.audit_trail`:

```json
{
  "audit_trail": {
    "detail": "summary",
    "max_bytes": 65536
  }
}
```

### Detail levels (`AuditDetail`)

- **`summary`** (default): Records metadata, check summary counts, list of check IDs run per field (`checks_ran`), and full `CheckRecord` objects only for **failing** checks (`failures`).
- **`full`** (opt-in): Records everything in `summary` plus full `CheckRecord` entries for every passing or skipped check (`records`). Intended for dispute resolution and high-compliance forms.
- **`off`**: Disables audit collection entirely (`context["validation"]` is `null`). Note: there is no `audit_trail.enabled` boolean flag; use `"detail": "off"`.

### Size cap (`max_bytes`)

To prevent unbounded JSON payload growth in `context["validation"]`:

- Default cap for `summary`: **64 KiB** (`65,536` bytes). Measured coverage: ~239–352 fields before truncation.
- Default cap for `full`: **256 KiB** (`262,144` bytes). Measured coverage: ~235–440 fields before truncation.
- Explicit `max_bytes` setting (range: 1,024 to 1,048,576 bytes) overrides the default cap.

### Truncation behavior

When the serialized JSON trace exceeds the effective byte cap, whole field traces are dropped:
1. Fields with no failures are dropped first, in `field_id` order (`omitted_fields` and `omitted_checks` count what was dropped).
2. Fields with failures are dropped only after every passing field is gone.
3. If the form-level header still does not fit, form-level failure messages are blanked.
4. When truncation occurs, the top-level flag `truncated: true` is set.

---

## 3. Reading a trace — the three identifiers

Every `ValidationTrace` includes three distinct version identifiers to ensure exact reproducibility and audit verification:

1. **`form_version`**: The author-defined version string from `FormSchema.version` (e.g. `"2.1.0"`).
2. **`schema_fingerprint`**: A deterministic hash (`sha256:` prefix) computed over the validation-relevant subset of `FormSchema`. Guarantees that changes to field validation rules or required flags invalidate matching traces even if `form_version` was not bumped.
3. **`ruleset_version`**: The installed version of `parrot-formdesigner` (e.g. `"1.3.0"`) that executed the validation.

---

## 4. Check reference

`checks_run` and each field's `checks_ran` count every non-skipped record, including the two always-passing `resolution.visible` / `resolution.required` records written per field.

The table below lists every `CheckId` enum value defined in `parrot_formdesigner.core.audit_trail`. These identifiers are stable contract strings recorded in the trace.

| Check ID | What it checks | Bound format / Notes |
|---|---|---|
| `form.circular_dependencies` | Form-level validation for circular rule dependencies | String / rule count |
| `form.rule_integrity` | Form-level check for broken or invalid rule references | String / rule count |
| `resolution.visible` | Evaluates rule visibility condition for a field | Boolean expression |
| `resolution.required` | Evaluates rule dynamic requirement condition for a field | Boolean expression |
| `field.voice_envelope` | Validates voice/audio envelope metadata | Envelope requirements |
| `field.required` | Checks if a required field contains a non-empty value | `true` |
| `field.relation_shape` | Validates shape and structure of relational reference fields | Relation spec |
| `field.coerce` | Coerces input value to the declared field data type | Target type name |
| `field.type` | Validates value matches the field type specification | Type name |
| `field.option_set` | Validates value is within allowed select/dropdown options | Option count / values |
| `field.cross_field` | Validates cross-field rule dependencies and constraints | Expression |
| `field.async_validator` | Executes asynchronous field validation logic | Validator name |
| `field.remote_response` | Validates response from remote external endpoint validator | Remote URL |
| `field.rest` | Validates custom REST endpoint validator response | Endpoint specification |
| `constraint.min_length` | Minimum string or array length | `min_length: N` |
| `constraint.max_length` | Maximum string or array length | `max_length: N` |
| `constraint.min_value` | Minimum numeric value | `min_value: N` |
| `constraint.max_value` | Maximum numeric value | `max_value: N` |
| `constraint.pattern` | Regular expression pattern match | Regex string |
| `constraint.min_items` | Minimum array item count | `min_items: N` |
| `constraint.max_items` | Maximum array item count | `max_items: N` |
| `constraint.allowed_mime_types` | File upload MIME type restriction | `[mime/type, ...]` |

---

## 5. Skip reasons

When a declared check does not run, a record with `outcome: "skip"` and a `skip_reason` is generated. A skip is recorded evidence (not missing evidence). Undeclared checks are never recorded.

| Skip Reason | Description |
|---|---|
| `not_applicable` | Check was declared on field schema, but does not apply to this instance |
| `empty_optional` | Field is optional and arrived empty — remaining validation short-circuits |
| `early_return` | An earlier check returned error/fatal before this check could execute |
| `not_displayed` | Dynamic visibility rules hidden this field, so requirement was relaxed |
| `no_mime_sidechannel` | `allowed_mime_types` check skipped because no resolvable MIME type sidechannel existed |
| `wrong_value_shape` | Bound was declared but coerced value shape cannot carry evaluation |

*Note on early returns*: Form-level early returns carry `fields: []` in the trace to indicate no field-level checks were evaluated before the early exit.

---

## 6. LLM identity in the record

For LLM plausibility checks (FEAT-728), LLM execution metadata is persisted separately under `context["llm_validation"]`.

- **Persisted fields**: `resolved_model` (actual LLM model that answered), `provider` (e.g. OpenAI/Anthropic), and `usage` (token count details).
- **Client isolation**: These fields are **never** returned to standard form client submit responses.
- **`model` field distinction**: The `model` field in config retains its meaning as the *requested* model override (`null` if system default was requested).
- **No-call response**: If no fields were eligible for LLM evaluation, `resolved_model` is `null`.

---

## 7. Reading the audit trail — endpoint and permission

### Read endpoint

```
GET /{base}/{tenant}/forms/{form_uid}/data/{submission_id}/audit
```

### Permission requirement

Reading submission audit records requires the `read_form_audit` permission at `client` scope or wider.

- **Default policy**: Permission `read_form_audit` is **never seeded by default**. Until explicitly granted, calls to the endpoint return `403 Forbidden`.
- **Grant path**: Assign permission using the organization user management endpoint:
  ```http
  POST /{base}/org/users/{user_id}/assign
  Content-Type: application/json

  {
    "codename": "read_form_audit",
    "scope": "client",
    "program_id": "<program_id>"
  }
  ```

### Response Status Codes

- `200 OK`: Returns `submission_id`, `form_uid`, `form_version`, `is_valid`, `validation` (the stored `ValidationTrace`) and `llm_validation`.
- `403 Forbidden`: Requesting user lacks `read_form_audit` permission.
- `404 Not Found`: The submission does not exist for the tenant, or belongs to a different form.
- `501 Not Implemented`: The form persists to its own sink; read the trace from that sink's context column.
- `503 Service Unavailable`: Submission storage is not configured.

---

## 8. What is NOT covered

- **Transient validate-only channels**: Telegram bot inputs, `ui/` handlers, MS Teams presets, and audio client-submit calls persist no trace.
- **Sink-persisted forms**: FEAT-457 sink-persisted submissions return `501 Not Implemented` on the audit read endpoint.
- **YAML-defined forms**: YAML form loader does not yet parse or load `audit_trail` configuration.
- **ARRAY `item_template` rules**: Array item validation rules are not currently validated on submit and will not appear in the audit trace.
