# Infographic Render Endpoint — Reference

**Feature**: FEAT-327
**Module**: `parrot/handlers/infographic.py`, `parrot/handlers/infographic_render.py`,
`parrot/handlers/render_jobs.py` (`ai-parrot-server`)
**Class**: `InfographicTalk(AgentTalk)` — deterministic, bot-less branch

---

## Overview

`POST /api/v1/agents/infographic/render` renders an infographic
**deterministically** — no bot, no LLM anywhere in the path. Any HTTP caller
(external agent, service, or script) sends datasets + a pre-registered
template + a [`SectionDescriptor`](#the-sectiondescriptor-contract) and gets
back rendered HTML, or a JSON reference to a persisted artifact.

Same datasets + template + descriptor ⇒ same HTML (modulo artifact
ids/timestamps/URLs — see [Determinism](#determinism)).

This extends the existing `InfographicTalk` handler (which already serves
`POST /api/v1/agents/infographic/{agent_id}` for the LLM-driven path,
plus `templates`/`themes` discovery) with one new resource:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/agents/infographic/render` | Deterministic render (this doc) |
| `GET` | `/api/v1/agents/infographic/render/jobs/{job_id}` | Async job status polling |

The literal `render` resource is registered **before** the `{agent_id}`
catch-all, so it is never swallowed by agent-id matching.

---

## Deployment Prerequisites

The render endpoint uses a **server-owned** `InfographicToolkit` — separate
from the per-agent toolkits the LLM path configures — that MUST be told
where its HTML template sources live, or every render request fails with
`TEMPLATE_ENGINE_UNSET` (mapped to `5xx`):

- **`INFOGRAPHIC_RENDER_TEMPLATE_DIRS`** (env var, comma-separated
  directories; `parrot/conf.py`) — deployment-wide default.
- **`app["infographic_render_template_dirs"]`** — per-app override, set
  before `on_startup` completes (same convention as `app["artifact_store"]`).

If BOTH are empty, the server logs a loud warning the first time the
toolkit is built (not per-request) — check logs for
`"NO template_dirs configured"` if every render 500s.

Also requires **`app["artifact_store"]`** (standard FEAT-103 wiring,
`manager.py`'s `on_startup`) when any request sets `persist: true`
(the default) — without it, `persisted` is always `false` regardless of
what the caller asked for, and a warning is logged per request.

---

## Request

### JSON body (small/medium datasets)

```json
{
  "datasets": {
    "revenue": {
      "orient": "records",
      "data": [{"month": "2026-01", "actual": 120000, "budget": 110000}]
    }
  },
  "template": "budget_variance",
  "descriptor": {
    "template": "budget_variance",
    "mode": "data-splice",
    "splice_marker_id": "report-data",
    "sections": [
      {
        "name": "hero",
        "target": "/hero",
        "datasets": ["revenue"],
        "columns": {"revenue": ["month", "actual", "budget"]},
        "shape": "records"
      }
    ]
  },
  "theme": null,
  "marker_id": "report-data",
  "agent_id": null,
  "session_id": null,
  "persist": true,
  "public": false,
  "async": false
}
```

```bash
curl -X POST https://your-host/api/v1/agents/infographic/render \
  -H "Content-Type: application/json" \
  -H "Accept: text/html" \
  -H "Authorization: Bearer $TOKEN" \
  -d @render_request.json
```

### Multipart body (large dataframes, dtype-preserving)

One JSON part named `request` (the same body shape as above, with the
large dataset's value set to `null`) plus one part per dataset named
`dataset:<name>` — Parquet (preferred; preserves dtypes via `pyarrow`) or
CSV, selected by `Content-Type`/filename.

```bash
curl -X POST https://your-host/api/v1/agents/infographic/render \
  -H "Authorization: Bearer $TOKEN" \
  -F 'request={"datasets":{"revenue":null},"template":"budget_variance","descriptor":{...},"persist":true};type=application/json' \
  -F 'dataset:revenue=@revenue.parquet;type=application/vnd.apache.parquet'
```

A dataset declared as `null` with NO matching `dataset:<name>` part is a
`400` (transport error). A dataset genuinely missing from the descriptor's
requirements is instead a `422` (validation gate — see below).

### Fields

| Field | Type | Notes |
|---|---|---|
| `datasets` | `{name: {orient, data} \| null}` | `null` ⇒ hydrated from a `dataset:<name>` multipart part |
| `template` | `str` | **Pre-registered name only** — inline template HTML is rejected (stored-XSS vector) |
| `descriptor` | `SectionDescriptor` | FEAT-326 model — reused, never redefined |
| `theme` | `str \| null` | Optional registered theme |
| `marker_id` | `str` | Data-splice marker id (ignored for jinja mode; `descriptor.splice_marker_id` wins when set) |
| `agent_id` / `session_id` | `str \| null` | Attribution — system defaults (`"_anon"` / a fresh UUID) when absent |
| `persist` | `bool` (default `true`) | Persist the render as an artifact (awaited) |
| `public` | `bool` (default `false`) | Two-behavior URL rule — see below |
| `async` | `bool` (default `false`) | `true` ⇒ `202` + job polling instead of a synchronous render |

### The `SectionDescriptor` contract

`descriptor` is the FEAT-326 `SectionDescriptor` (`parrot.tools.infographic_sections`) —
it declares which data fills each template section, and drives **fail-fast,
aggregating** validation (§ below) before anything renders. See
[`docs/toolkits/infographic_toolkit.md`](../toolkits/infographic_toolkit.md)
for the full model reference; it is imported here unchanged.

**Payload assembly (v1 scope)**: a section may name at most ONE dataset
alias — the assembler slices it to `columns[alias]` (or every column) and
shapes it per `section.shape` (`records`/`table`/`mapping`/`scalar`).
Sections naming more than one dataset alias need a bespoke transformer and
are rejected loudly (`400`) rather than guessed.

---

## Response

### Content negotiation

Priority: `?format=` query param > `Accept` header > default `text/html`
(reuses the existing handler's `_negotiate_accept()`).

- `Accept: text/html` → the rendered HTML body, `Content-Type: text/html`,
  header `X-Artifact-Persisted: true|false`.
- `Accept: application/json` (or `?format=json`) → a `RenderResponse`:

```json
{
  "artifact_id": "infographic-3f9a2b1c8d4e",
  "url": "https://s3.example.com/...&signature=...",
  "url_note": null,
  "template": "budget_variance",
  "sections_validated": 1,
  "persisted": true,
  "timings": {
    "validate_datasets": 0.0012,
    "assemble_and_validate_shape": 0.0004,
    "render": 0.0031,
    "persist": 0.0087,
    "resolve_url": 0.0021
  }
}
```

`url_note` is set whenever `url` is `null`, explaining why — the spec's
"explanatory field" (§2 Overview).

### The URL two-behavior rule

`RenderResponse.url`/`url_note` are resolved as follows. **`persist=false`
ALWAYS wins**: nothing is ever published anywhere (not even under
`public=true`) when the caller asked not to persist — `persist=false`
means "do not retain this," and honoring `public=true` on top of that
would silently override that intent.

| `persist` | `public` | Backend / outcome | `url` / `url_note` |
|---|---|---|---|
| `false` | *(either)* | — | `url: null` — `url_note` explains persistence was skipped (or explicitly overridden by `persist=false`, when `public=true` was also set) |
| `true` | `true` | — | The HTML is ALSO written under the server's `STATIC_DIR` (`parrot/conf.py`) and `url` is the resulting `/static/<file>.html` path — served by the app's own `add_static("/static/", ...)` route. **Irreversible-ish**: the file remains until cleaned up; `STATIC_DIR` content is world-readable by definition. |
| `true` | `false` | Artifact offloaded (S3/overflow) | ALWAYS a presigned URL (`ArtifactStore.get_public_url()`) — infographics are **never** hosted on public S3. |
| `true` | `false` | Local backend or inline artifact | `url: null` — `url_note` says to use the artifacts handler (`GET /api/v1/artifacts/{artifact_id}`) with `artifact_id` from this response. |

### Error taxonomy

| Status | When |
|---|---|
| `400` | Malformed JSON/multipart part (named in the response), or a `null` dataset with no matching multipart part |
| `403` | PBAC policy denial (only when PBAC is configured for the deployment) |
| `404` | `template` is not a registered name |
| `413` | Total request body exceeds the size cap (default **50 MB**, configurable) — enforced for BOTH the JSON and multipart transports |
| `422` | The FEAT-326 validation gate failed — **every** missing dataset/column across **every** section, aggregated into ONE response |
| `5xx` | Persistence failure, or a template registry misconfiguration (see Known Limitation below) |

```json
// 422 example — one response, every deficit
{
  "error": "sections_unmet",
  "detail": {
    "sections": [
      {"section": "hero", "missing_datasets": ["revenue"], "missing_columns": {}}
    ]
  }
}
```

---

## Determinism

Rendering never calls an LLM. Given identical datasets + template +
descriptor, the **rendered HTML content** is byte-identical across calls.
Artifact ids, timestamps, and URLs legitimately differ per call by design —
they are excluded from the determinism guarantee (compare the HTML, not the
`RenderResponse` envelope).

---

## Async mode — job lifecycle

`"async": true` (or `?async=true` in the body) returns immediately:

```json
// 202 Accepted
{"job_id": "3f9a2b1c8d4e5f6a"}
```

Poll for the result:

```bash
curl https://your-host/api/v1/agents/infographic/render/jobs/3f9a2b1c8d4e5f6a \
  -H "Authorization: Bearer $TOKEN"
```

```json
// 200 — while running
{"job_id": "...", "status": "running", "result": null, "error": null,
 "created_at": "2026-07-24T18:00:00+00:00", "deadline": "2026-07-24T18:10:00+00:00"}

// 200 — terminal
{"job_id": "...", "status": "done", "result": { /* RenderResponse */ },
 "error": null, "created_at": "...", "deadline": "..."}
```

- **Job store**: Redis (`REDIS_HISTORY_URL`), multi-worker safe — the job
  created by one worker is pollable from any other.
- **TTL**: terminal jobs (`done`/`failed`) expire after **1 day**. Polling an
  expired or unknown `job_id` returns `404`.
- **Watchdog**: a `running` job carries a `deadline` (created at enqueue
  time, stamped fresh when the render actually starts); if a worker dies
  mid-render, the next poll past `deadline` flips the job to `failed`
  (`error.code: "watchdog_timeout"`) — no background daemon required.
  Default max-runtime: **10 minutes**, kept behind a single resolver
  function so a resource-aware computation can replace the constant later
  without an API change.
- Render task exceptions ALWAYS land in the job record as a structured
  `failed` error — they never disappear silently.

---

## Limits

| Limit | Default | Notes |
|---|---|---|
| Total body size | 50 MB | Enforced BEFORE buffering (chunked reads abort mid-part on cap overrun) |
| Job TTL (terminal) | 86 400 s (1 day) | Redis TTL |
| Max render runtime (watchdog) | 600 s (10 min) | Constant, behind `resolve_max_runtime_seconds()` |

---

## Known Limitation

`template` is checked for existence against
`parrot.helpers.infographics.get_template` (the block-spec metadata
registry used by the LLM path) — this is a **different** registry from the
server-owned `InfographicToolkit`'s own Jinja `template_dirs`/`templates`
registry actually used to render. A name that passes the `404` check can
still fail to render (surfaced as `5xx`) if the render toolkit's own
registry does not know it. Reconciling the two registries is a follow-up,
cross-cutting concern.

---

## See Also

- [`docs/toolkits/infographic_toolkit.md`](../toolkits/infographic_toolkit.md) —
  `InfographicToolkit` / `SectionDescriptor` reference (FEAT-197/326).
- `sdd/specs/infographic-render-endpoint.spec.md` — full design record (FEAT-327).
