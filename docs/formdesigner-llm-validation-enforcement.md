# FormBuilder — LLM answer-plausibility enforcement

> **Feature**: FEAT-728
> **Package**: `parrot-formdesigner` >= 1.3.0
> **Builds on**: FEAT-649's plausibility checker (see [`audio-form-voice-modes.md`](audio-form-voice-modes.md))

This document describes what happens when the LLM judges an answer implausible,
and the quota that bounds every LLM-backed form call.

---

## 1. The two knobs, kept apart

FEAT-728 introduces two independent knobs on `LLMValidationConfig`. They are
**never interchangeable** — confusing them is the original problem this
feature resolves.

| Knob | Fires when | Values | Default |
|------|------------|--------|---------|
| `on_error` | the LLM is unavailable, times out, or returns unparsable output | `skip`, `block` | `skip` |
| `on_implausible` | an answer was judged implausible by the model | `annotate`, `review`, `reject` | `annotate` |

- **`on_error`** governs *LLM unavailability*. Under `skip`, the check is
  skipped and the submission proceeds; under `block`, the submission fails
  with `503 PLAUSIBILITY_UNAVAILABLE`. This is unchanged from FEAT-649.
- **`on_implausible`** governs *implausible answers*. The three policies are
  described in §2 below.

---

## 2. Policy matrix

The enforcement policy lives on the form (`FormSchema.llm_validation.on_implausible`)
and is evaluated inside `SubmissionPipeline` before any data is persisted.
Every channel (HTTP, A2UI, Teams, audio) inherits the same rule.

| Policy | No flagged fields | Flagged fields, no ack | Flagged fields, with ack |
|--------|-------------------|------------------------|--------------------------|
| `annotate` (default) | store, 200 | store, 200 — FEAT-649 behaviour | store, 200 |
| `review` | store, 200 | **refuse**, 422 `PLAUSIBILITY_REVIEW` | store, 200 (ack recorded) |
| `reject` | store, 200 | **refuse**, 422 `PLAUSIBILITY_REJECTED` | **refuse** — ack never bypasses |

The reconfirmation flag (`plausibility_ack`) is read from `?plausibility_ack=true`
or a body field `plausibility_ack: true`. It is popped from the body before
validation so it is never reported as an unknown field.

---

## 3. What trips the gate

A field is flagged (and therefore subject to the policy above) when either:

1. `verdict.plausible == false`, **or**
2. `verdict.confidence < report.threshold`

The threshold travels on the `PlausibilityReport` itself (set by
`AnswerPlausibilityChecker.check`), so no config lookup is needed at the gate.

Fields that are **never checked** (excluded at check time):

- `PASSWORD`, `HIDDEN`, `FILE`, `IMAGE_DROPZONE`, `CREDIT_CARD`, `SIGNATURE`
- Fields with `field.llm_validation = false`
- Any field on a form with `llm_validation.enabled = false`

Reports whose status is not `"ok"` (i.e., `"skipped"` or `"blocked"`) return
no flagged fields — they stay on the `on_error` path, never the enforcement
gate.

---

## 4. Wire shapes

### 4.1 `422` — refused (review/reject)

```json
{
  "is_valid": false,
  "code": "PLAUSIBILITY_REVIEW",
  "errors": {
    "field_id_1": ["reason from LLM or default message"],
    "field_id_2": ["another reason"]
  },
  "plausibility": {
    "status": "ok",
    "threshold": 0.7,
    "items": {
      "field_id_1": { "plausible": false, "confidence": 0.3, "reason": "odd" },
      "field_id_2": { "plausible": true, "confidence": 0.65, "reason": null }
    }
  }
}
```

- `code` is `"PLAUSIBILITY_REVIEW"` for the `review` policy,
  `"PLAUSIBILITY_REJECTED"` for `reject`.
- `errors` has the same shape as per-field validation errors, so a client
  that already renders validation errors renders these identically.
- The `plausibility` block contains the full report for client-side review.

### 4.2 Clearing a `review` refusal

To clear a `review` refusal, the client re-submits the same data with the
reconfirmation flag:

```json
POST /api/v1/{tenant}/forms/{form_uid}/data
{
  "field_id_1": "answer",
  "field_id_2": "answer",
  "plausibility_ack": true
}
```

Or as a query parameter:

```
POST /api/v1/{tenant}/forms/{form_uid}/data?plausibility_ack=true
```

When the flag is present and the policy is `review`, the gate passes and the
submission is stored with `context["llm_validation"]["acknowledged"] = true`.
The flag is **never stored** as an answer — it is popped before the visit
context is extracted.

### 4.3 `429` — rate limited

```json
{
  "error": "Answer plausibility check rate limited",
  "code": "PLAUSIBILITY_RATE_LIMITED"
}
```

With the `Retry-After` header (seconds until the oldest request in the window
expires):

```
Retry-After: 12
```

**Policy-dependent behaviour under quota exhaustion:**

- `annotate` → the check is skipped (`plausibility.status = "skipped"`,
  `reason = "rate_limited"`) and the submission proceeds. Under `annotate`
  the verdict never changed the outcome, so skipping is safe.
- `review` / `reject` → `429` is returned, nothing is stored. Failing closed
  is the point: otherwise an attacker burns the quota and walks garbage past
  a `reject` gate.
- `/validate` with the LLM opt-in → `429` regardless of policy.

### 4.4 `503` — LLM unavailable (unchanged)

When the LLM is unreachable, times out, or returns unparsable output, the
behaviour is governed by `on_error` (not `on_implausible`):

```json
{
  "error": "Answer plausibility check unavailable: <reason>",
  "code": "PLAUSIBILITY_UNAVAILABLE"
}
```

With `Retry-After: 30`. This is FEAT-649 behaviour and is unchanged by
FEAT-728.

---

## 5. Configuring a form

### 5.1 LLMValidationConfig reference

```json
{
  "llm_validation": {
    "enabled": true,
    "threshold": 0.7,
    "on_error": "skip",
    "on_implausible": "review",
    "model": null,
    "timeout_s": 8.0,
    "max_fields": 50,
    "exclude_field_types": ["password", "hidden", "file", "image_dropzone", "credit_card", "signature"]
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `false` | Whether any field on this form participates in plausibility checking |
| `threshold` | `float` | `0.7` | Minimum confidence to consider an answer plausible (0.0–1.0) |
| `on_error` | `Literal["skip", "block"]` | `"skip"` | What to do when the LLM is unavailable |
| `on_implausible` | `Literal["annotate", "review", "reject"]` | `"annotate"` | What to do with an implausible answer |
| `model` | `str \| null` | `null` | Override the default LLM model for this form |
| `timeout_s` | `float` | `8.0` | LLM call timeout in seconds |
| `max_fields` | `int` | `50` | Maximum fields sent to the LLM in one batch |
| `exclude_field_types` | `list[FieldType]` | (see above) | Field types never sent to the LLM |

**Note**: The policy (`on_implausible`) is **per-form**. The per-field
`field.llm_validation` opt-in still decides *what* is checked; the form-level
policy decides *what is done* with the result. There is no per-field policy
override.

### 5.2 Quota knobs (server-side)

The quota is configured at server startup, not in form schema. A tenant must
not be able to raise its own limit.

```python
from parrot_formdesigner.services.llm_quota import LLMQuota

llm_quota = LLMQuota(
    enabled=True,
    limit=10,           # max calls per window
    window_s=60.0,      # window size in seconds
    trust_forwarded_for=False,
)

setup_form_api(app, registry, llm_quota=llm_quota)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | `bool` | `true` | Disable quota entirely (allows unlimited calls) |
| `limit` | `int` | `10` | Maximum LLM calls per identity in the window |
| `window_s` | `float` | `60.0` | Sliding window size in seconds |
| `trust_forwarded_for` | `bool` | `false` | Whether to trust `X-Forwarded-For` for identity |

To disable the quota entirely:

```python
llm_quota = LLMQuota(enabled=False)
```

---

## 6. Quota details

### 6.1 Key format

The quota key is `{tenant}:{form_uid}:{identity}`, where identity is resolved
in this order:

1. **Authenticated session**: the navigator session id (from `request["session"]["id"]`)
2. **Forwarded for** (only if `trust_forwarded_for=True`): the first hop of
   `X-Forwarded-For` — never the full chain, because proxies collapse
   identities
3. **Client IP**: `request.remote`
4. **Literal `"anonymous"`**: when everything above is `None`

### 6.2 Gotcha: the quota is per worker

The quota uses an in-process sliding window (`InProcessSlidingWindow`). With
**N gunicorn workers**, the effective limit is **N × configured limit**.

For example, with `limit=10` and `window_s=60.0`:

- 1 worker: 10 calls / minute / identity
- 4 workers: 40 calls / minute / identity

This is a known limitation (spec §8 Q2). The `LLMQuotaBackend` Protocol exists
exactly to allow a shared backend (e.g., Redis) to be plugged in later.

### 6.3 Gotcha: proxies collapse anonymous identities

When `trust_forwarded_for=False` (the default), every client behind the same
proxy shares one identity (`request.remote`). This prevents a client from
minting unlimited identities by sending a custom `X-Forwarded-For` header.

When `trust_forwarded_for=True`, only the **first hop** is used (the leftmost
IP in the comma-separated list), not the full chain. This is deliberate:
the rightmost IP is the client's visible IP, and trusting the full chain
would allow any client to spoof their identity.

---

## 7. Voice (audio) channel

### 7.1 Server mode (default)

In server mode, the audio engine runs the full submission pipeline after the
user confirms a REVIEW turn. The engine passes `plausibility_ack=True`
automatically, so:

- `annotate` / `review`: behaves exactly as before FEAT-728 (flagged fields
  are stored, REVIEW phase is entered)
- `reject`: surfaces as `IOFailed(PLAUSIBILITY_REJECTED)` — the user cannot
  override a rejection

### 7.2 Client-submit mode

In client-submit mode (`_do_client_submit`), the handler validates but
**persists nothing**. It returns the sanitized data and the plausibility
summary to the client, which must then POST to `/data` itself.

**Gotcha: client-submit mode needs the ack**

When the client POSTs to `/data` after a `review` decision, it **must** include
`plausibility_ack=true` (or `?plausibility_ack=true`). Otherwise, answers the
user already reconfirmed by voice are refused with `422 PLAUSIBILITY_REVIEW`.

The client receives `plausibility_summary` in the `_submit_done` response,
which it can use to decide whether to re-confirm or show the errors.

---

## 8. Security notes

### 8.1 Public forms and the LLM opt-in

Public forms (`is_public=True`) expose five URL patterns without authentication
(`services/public_forms.py:13-52`):

- `GET /{tenant}/forms/{form_uid}`
- `GET /{tenant}/forms/{form_uid}/schema`
- `GET /{tenant}/forms/{form_uid}/render/*`
- `POST /{tenant}/forms/{form_uid}/data`
- `POST /{tenant}/forms/{form_uid}/validate`

The `/validate` endpoint accepts an LLM opt-in (`?llm_validation=true` or
`llm_validation: true` in the body). For **unauthenticated callers**, this
opt-in is **ignored** — the response comes back with:

```json
{
  "plausibility": {
    "status": "skipped",
    "reason": "unauthenticated_opt_in"
  }
}
```

This allows a public renderer that always sends the flag to keep working
without spending LLM calls. A `403` was considered and rejected: it would
break existing public form integrations that expect a `200`/`422` response.

### 8.2 LLM opt-in is ignored for unauthenticated callers

The LLM check is completely skipped for anonymous callers, with the reason
`"unauthenticated_opt_in"` in the response. This closes ledger issue
`44941ecac8cc`.

---

## 9. What is NOT provided

- **Per-field policy override** — the policy is form-level; `field.llm_validation`
  only controls *whether* a field is checked, not *what happens* when it fails.
- **A "held / pending submission" state** — nothing is stored on a refusal.
- **A Redis-backed quota** — only the in-process implementation ships.
  The `LLMQuotaBackend` Protocol exists for a future shared backend.
- **Factual correctness checking** — the system prompt forbids it, and the
  gate acts on pertinence verdicts only.

---

## 10. Related documentation

- [`audio-form-voice-modes.md`](audio-form-voice-modes.md) — FEAT-649's
  plausibility checker, the foundation this feature builds on
- [`formdesigner-unknown-fields-capture.md`](formdesigner-unknown-fields-capture.md) —
  another per-form policy page, used as the structural reference for this doc
- [`formdesigner-autonomous-persistence.md`](formdesigner-autonomous-persistence.md) —
  sink/persistence documentation