# Serving FormDesigner forms from a Teams agent

`TeamsFormDesignerMixin` adds `/getform` and `/listforms` plus the equivalent `formdesigner_get_form` and `formdesigner_list_forms` tools to a Teams agent. The mixin sends picker and form cards, keeps multi-section answers in a short-lived wizard, and forwards only the terminal signed submission with the speaking user's Navigator bearer token.

## Quick start

```python
from parrot.bots import Agent
from parrot.integrations.msteams.formdesigner_mixin import TeamsFormDesignerMixin


class MyAgent(TeamsFormDesignerMixin, Agent):
    pass
```

```yaml
msteams:
  forms-agent:
    chatbot_id: my-agent
    formdesigner_mode: remote
    formdesigner_base_url: https://forms.example.com
    formdesigner_tenant: acme
    formdesigner_allowed_hosts: [forms.example.com]
    formdesigner_submit_secret: ${FORMS_SUBMIT_SECRET}
    formdesigner_tenant_map:
      "11111111-2222-3333-4444-555555555555": acme
```

## Modes

Remote mode reads forms over HTTP. The FormDesigner server renders and signs the Teams envelope, and must expose `GET …/render/teams?with_meta=true` with `section_index` support for wizards.

Local mode reads an in-process `FormRegistry`. The agent renders and signs with `formdesigner_public_url` and `formdesigner_submit_secret`; it also requires a `LocalFormAuthorizer` before any lookup or listing.

## Configuration

| Field | Env var | Mode | Default | Purpose |
|---|---|---|---|---|
| `formdesigner_mode` | `{NAME}_FORMDESIGNER_MODE` | both | `remote` | Select `remote` HTTP reads or `local` registry reads. |
| `formdesigner_base_url` | `{NAME}_FORMDESIGNER_BASE_URL` | remote | unset | FormDesigner read/render origin. |
| `formdesigner_tenant` | `{NAME}_FORMDESIGNER_TENANT` | both | unset | Last-resort FormDesigner tenant slug. |
| `formdesigner_public_url` | `{NAME}_FORMDESIGNER_PUBLIC_URL` | local | unset | Public origin placed into local envelopes. |
| `formdesigner_render_timeout` | — | remote | `15.0` | Read/render HTTP timeout in seconds. |
| `formdesigner_api_base_path` | `{NAME}_FORMDESIGNER_API_BASE_PATH` | both | `/api/v1` | FormDesigner API base path. |
| `formdesigner_allowed_hosts` | `{NAME}_FORMDESIGNER_ALLOWED_HOSTS` | both | unset | Envelope submission-host allowlist. |
| `formdesigner_submit_secret` | `{NAME}_FORMDESIGNER_SUBMIT_SECRET` | both | unset | Required HMAC signing secret for local rendering and terminal-envelope verification. |
| `formdesigner_submit_token` | `{NAME}_FORMDESIGNER_SUBMIT_TOKEN` | legacy submit fallback | unset | Legacy wrapper bearer setting; form serving uses the speaking user's bearer instead. |
| `formdesigner_submit_timeout` | — | both | `15.0` | Submission POST timeout in seconds. |
| `formdesigner_tenant_map` | — | both | empty | FEAT-733 AAD tenant GUID-to-FormDesigner-slug map. |

## Tenant resolution

The mixin resolves tenants in this order: mapped activity AAD GUID, mapped cached session AAD GUID, then `formdesigner_tenant`. A raw AAD GUID is never used as a FormDesigner tenant.

## Prerequisites

FEAT-729 must provide `/login` and a per-user Navigator bearer; there is no service-token fallback. FEAT-733 must configure `formdesigner_tenant_map` and mandatory envelope signatures.

## Limits (v1)

Forms are available only in 1:1 chats. Wizard state is process-local, so a multi-worker deployment must restart the flow when a worker misses state. Upload fields cannot be completed in an Adaptive Card and instead link the user to the web form.
