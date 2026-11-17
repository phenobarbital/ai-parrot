# FormDesigner — public response controls

> **Feature**: FEAT-730
> **Package**: `parrot-formdesigner`
> Public forms are Google-Forms-style: anyone with the link can open and answer them.
> `is_public` stays the **auth grant**; `public_access` is the **response policy**.

---

## 1. `FormSchema.public_access`

A typed block on `FormSchema` (not `meta`). `None` means no policy — behaviour is exactly
as before. Wire keys are the snake_case names below.

| Field | Type | Meaning |
|---|---|---|
| `accepting_responses` | `bool` (default `true`) | Manual open/closed switch. `false` ⇒ closed. |
| `closes_at` | timezone-aware `datetime` \| `null` | Closes when `now >= closes_at`. Naive values are rejected; stored normalized to UTC. |
| `max_responses` | `int >= 1` \| `null` | Cap on responses (revision-chain roots only). |
| `unique_key_field` | `field_id` \| `null` | One response per value of this field. Must be a scalar field of the form (not GROUP / ARRAY / FILE / IMAGE / IMAGE_DROPZONE / MULTI_UPLOAD / SIGNATURE). |
| `completion` | `CompletionAction` \| `null` | What the respondent sees after submitting: `{mode: "message" \| "redirect", message?, redirect_url?}`. `redirect_url` must be an absolute `https://` URL with a host; `mode="redirect"` requires it. |

Schema validation also rejects `max_responses` / `unique_key_field` on a form that declares
`persistence` — counting is only atomic over `FormSubmissionStorage`. Closing (`accepting_responses`,
`closes_at`) works with any storage.

Import from `parrot_formdesigner.core`: `PublicAccessConfig`, `CompletionAction`, `AvailabilityState`,
`RejectionReason`, `evaluate_open`, `normalize_key_value`.

---

## 2. Enforcement

Enforced by `SubmissionPipeline.submit`, i.e. on **REST `POST …/data`** and the **audio WebSocket**.
Hosts that call `FormSubmissionStorage.store()` directly are not subject to it.

1. **Closed check (no lock).** First thing in `submit`, before `onBeforeSubmit`, validation or any LLM
   plausibility call. A closed form raises `SubmissionRejected("form_closed")`; nothing is stored and
   `onError` is not dispatched.
2. **Guarded store (atomic).** When `max_responses` or `unique_key_field` is set and the form uses the
   generic store, the pipeline calls `FormSubmissionStorage.store_guarded(...)`. In ONE transaction it
   takes `pg_advisory_xact_lock(hashtextextended(form_uid::text, 0))`, counts, checks the key and
   INSERTs — so concurrent submits can neither exceed the cap nor store a duplicate key.
   - A "response" is a revision-chain root: `COALESCE(root_submission_id, submission_id) = submission_id`.
     Revisions never consume the cap.
   - A blank/missing key value (`None`, `""`, whitespace, `[]`, `{}`) is never checked.
   - Strings compare as `lower(btrim(data->>key)) = lower(btrim(value))`; other JSON values as `data->key = value::jsonb`.
   - A counting policy with no `submission_storage` configured answers 501.

Refusals are controlled flows (`SubmissionRejected(reason, message, field_id=None)`), never routed to `onError`.

---

## 3. HTTP

**409 on `POST …/data`**

```json
{"error": "...", "reason": "form_closed | response_limit_reached | duplicate_response", "field_id": "email"}
```

`field_id` is present only for `duplicate_response`.

**`GET /{tenant}/forms/{form_uid}/availability`** — lets a client render the closed state without submitting:

```json
{"accepting": false, "reason": "form_closed | response_limit_reached | null", "completion": {...} | null}
```

A form without `public_access` answers `{"accepting": true, "reason": null, "completion": null}`.
Private forms answer like `GET …/forms/{form_uid}` (tenant membership required).

**Auth-exempt globs.** `public_form_paths()` now returns seven patterns per public form: the previous five
plus `…/availability` and `…/fields/*/file-upload`.

**File upload without login.** The upload route is public-mode; the handler still enforces tenant
membership on private forms. On a public form the blob tenant is always the URL tenant — the
`X-Parrot-Tenant` header is ignored, because anybody can call a public form. Thumbnails stay authenticated.

**Audio WebSocket.** `SubmissionRejected` surfaces as `IOFailed(code="FORM_CLOSED" | "RESPONSE_LIMIT_REACHED" | "DUPLICATE_RESPONSE")`.

---

## 4. Host integration

```python
from parrot_formdesigner.api import setup_form_api, SubmittedEvent

async def on_submitted(event: SubmittedEvent) -> None:
    ...  # index the response, notify, etc.

setup_form_api(app, registry, on_submitted=on_submitted, tenant_scoped_submissions=True)
```

- `on_submitted` is awaited after a successful REST `/data` store (not on 4xx/5xx, not when nothing was
  stored). Any exception is logged and swallowed — the submit already succeeded. Not called from the audio WS.
- `SubmittedEvent` fields: `submission_id`, `form_uid`, `form_id`, `form_version`, `tenant`, `is_public`,
  `created_at`. There is **no** `anonymous` field — public is public, no caller distinction.
- `tenant_scoped_submissions` (default `False`): when `True`, generic `/data` submissions are stored under
  the URL tenant (and `availability` counts there). Default keeps today's behaviour.

**Deploy note.** Existing public forms need nothing: without `public_access` and with the flag off,
behaviour is unchanged.
