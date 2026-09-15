# FormDesigner → MS Teams: Adaptive Card renderer and bot submit path (FEAT-551)

## What it does

FormDesigner can export any `FormSchema` as an MS Teams Adaptive Card via the `teams` render
format. Unlike the default `adaptive` renderer, the `teams` renderer never sends the answers
itself — it returns JSON only. The terminal Submit action of the card carries a signed routing
envelope (`_formdesigner`); the MS Teams bot (`ai-parrot-integrations`) reads that envelope out
of the incoming `Action.Submit` activity, verifies it, and forwards the answers to the same
FormDesigner REST endpoint a web submitter would hit:

```
FormDesigner API                         MS Teams
─────────────────                         ────────
GET .../render/teams?with_meta=true  ──►  render the card in a message
                                           user fills the card, taps Submit
Action.Submit activity               ◄──  Bot Framework delivers activity.value
verify envelope + POST .../data      ──►  MSTeamsAgentWrapper._handle_formdesigner_submit
200/422/403 JSON                     ◄──
send_card(build_reply_card(...))     ──►  confirmation/error card back to the user
```

## Rendering a form

```
GET {base_path}/{tenant}/forms/{form_uid}/render/teams
GET {base_path}/{tenant}/forms/{form_uid}/render/teams?with_meta=true
```

The `teams` format is only registered when a public base URL is configured — either via the
`FORMDESIGNER_PUBLIC_URL` environment variable, or by passing `public_base_url=` to
`setup_form_api()`:

```python
from parrot_formdesigner.api.routes import setup_form_api

setup_form_api(app, registry, public_base_url="https://forms.example.com")
```

Without a configured URL, `"teams"` is absent from `supported_formats()` and the render
endpoint answers `415` for it, exactly like any other unregistered format. `?with_meta=true`
returns a JSON envelope of the render result — `{"content", "content_type", "warnings",
"metadata"}` — instead of the raw card body; the default (no query param) response is
unchanged for every other renderer.

## The `_formdesigner` envelope

The terminal Submit action's `data` carries a `TeamsSubmitEnvelope`:

```json
{
  "_action": "submit",
  "_formdesigner": {
    "v": 1,
    "wire": "legacy",
    "form_uid": "5b1f5b3a-8f2e-4b1a-9b3a-1a2b3c4d5e6f",
    "tenant": "navigator",
    "form_version": "1.0",
    "is_public": true,
    "submit_url": "https://forms.example.com/api/v1/navigator/forms/5b1f.../data",
    "form_url": "https://forms.example.com/navigator/forms/5b1f...",
    "sig": "9f2c...a1b3"
  }
}
```

`sig` is the HMAC-SHA256 hex digest of the envelope's canonical JSON (every field except `sig`,
keys sorted, compact separators), computed with `TeamsSubmitEnvelope.sign()` when the renderer
is configured with a `signing_secret`. `sig` is omitted (`null`) when no secret is configured.

## Bot configuration

`MSTeamsAgentConfig` gains four fields for FormDesigner card submissions:

| Field | Env fallback | Meaning |
|---|---|---|
| `formdesigner_allowed_hosts` | `{NAME}_FORMDESIGNER_ALLOWED_HOSTS` (comma-separated) | Host allowlist for `submit_url`. Empty/unset disables the whole branch. |
| `formdesigner_submit_token` | `{NAME}_FORMDESIGNER_SUBMIT_TOKEN` | Bearer token sent to the FormDesigner API (needed for private forms). |
| `formdesigner_submit_secret` | `{NAME}_FORMDESIGNER_SUBMIT_SECRET` | HMAC secret; when set, every envelope must carry a valid `sig`. |
| `formdesigner_submit_timeout` | — | Seconds before the forwarding POST gives up (default `15.0`). |

`{NAME}` is the bot's configured name, upper-cased (same convention as the existing Jira OAuth
fields on `MSTeamsAgentConfig`).

## Security model

`verify_envelope()` (`parrot.integrations.msteams.formdesigner_submit`) enforces, in this fixed
order:

1. **https only** — `submit_url` must use the `https` scheme.
2. **Host allowlist** — `submit_url`'s host must exactly match (case-insensitively) an entry in
   `formdesigner_allowed_hosts`.
3. **Path/tenant/uid match** — `submit_url`'s path must equal
   `{api_base_path}/{tenant}/forms/{form_uid}/data` built from the envelope's own fields (never
   trusted verbatim from the activity).
4. **Signature** — when `formdesigner_submit_secret` is configured, the envelope's `sig` must
   verify against it.

`post_submission()` never follows redirects (`allow_redirects=False`), bounds the response body
size, and never raises into the bot adapter — HTTP/timeout errors come back as
`SubmitOutcome(status=0, error=...)`. A `formdesigner_submit_token` (Bearer) is required for
private forms, since the bot's request carries no navigator-auth session.

## Teams limitations

> "Adaptive Cards within Teams don't provide support for file or image uploads." — Microsoft

Because of this, `TeamsFormRenderer` degrades every upload-type field (`FILE`, `IMAGE`,
`IMAGE_DROPZONE`, `MULTI_UPLOAD`) explicitly: an instruction text plus an `Action.OpenUrl` to
the served web form page, and a `RenderWarning(renderer="teams")` — never a silent
`Input.Text`. Teams cards also cap out at Adaptive Card schema 1.6, and Teams ignores most
`StyleSchema` presentation hints (colors, fonts) — only structural layout carries over.

## Duplicate submissions

The wrapper keeps a best-effort, in-process TTL cache (`RecentActivityCache`) keyed on the Bot
Framework `activity.id`, so a retried delivery of the same Submit doesn't double-forward. This
is process-local — a server-side idempotency key on the FormDesigner API itself is a follow-up,
not covered by this feature.

## Walkthrough

1. Render the form: `GET .../forms/{form_uid}/render/teams` and post the returned Adaptive Card
   JSON to a Teams conversation (however your integration delivers proactive/interactive cards).
2. The user fills the card and taps Submit.
3. Bot Framework delivers an `Action.Submit` activity; `MSTeamsAgentWrapper._handle_card_submission`
   detects the `_formdesigner` key and routes to `_handle_formdesigner_submit` — never to
   dialogs, never to the slash-command router.
4. The envelope is verified, the answers are extracted (every key except `_action` and
   `_formdesigner`), and forwarded to `POST .../forms/{form_uid}/data` over the bot's shared
   `aiohttp.ClientSession`.
5. The outcome (200/422/403/timeout/...) is mapped to a small Adaptive Card via
   `build_reply_card()` and sent back to the user with `send_card()`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `GET .../render/teams` → `415` | No `FORMDESIGNER_PUBLIC_URL` / `public_base_url` configured — `"teams"` was never registered. |
| `TeamsRenderConfigError` (renderer raises / `400` from the render dispatcher) | No tenant resolvable (`tenant=` kwarg and `form.tenant` both empty), or no public base URL when building the envelope. |
| Bot replies "Form submissions are not enabled for this bot." | `formdesigner_allowed_hosts` is empty/unset on the bot's `MSTeamsAgentConfig`. |
| Bot replies with a rejection message instead of forwarding | `verify_envelope()` failed — check scheme/host/path/signature, in that order. |
| Submit route on a private form returns `403` | The caller has no tenant membership; configure `formdesigner_submit_token` and enable it on the private form's route. |
