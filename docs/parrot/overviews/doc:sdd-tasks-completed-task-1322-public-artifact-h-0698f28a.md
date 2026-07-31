---
type: Wiki Overview
title: 'TASK-1322: Public artifact HTML route + CSP headers'
id: doc:sdd-tasks-completed-task-1322-public-artifact-html-serving-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 5 from the spec. Clients (browser iframes, embeds, dashboards)
relates_to:
- concept: mod:parrot.handlers.artifacts
  rel: mentions
- concept: mod:parrot.handlers.csp
  rel: mentions
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.outputs.formats.infographic_html
  rel: mentions
- concept: mod:parrot.storage.artifacts
  rel: mentions
- concept: mod:parrot.storage.models
  rel: mentions
---

# TASK-1322: Public artifact HTML route + CSP headers

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 5)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1321
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

Module 5 from the spec. Clients (browser iframes, embeds, dashboards)
fetch the rendered infographic HTML from a public, signature-only route.
This task introduces:

1. The new `GET /api/v1/artifacts/public/{signature}/{artifact_id}.html`
   route.
2. Signature validation (sigv4 — delegated to S3 by issuing a 302
   redirect to the presigned URL, OR proxied through our handler with
   in-app signature checking — see *Implementation Notes*).
3. Full CSP header set on the response.
4. Reading `INFOGRAPHIC_FRAME_ANCESTORS` (CSV env var, default `'self'`).
5. Updating `ArtifactDetailView.get` so `?format=html` or
   `Accept: text/html` returns the frozen HTML.

---

## Scope

- Register the new public route in `parrot/handlers/artifacts.py` (or
  wherever the existing artifact routes are wired — look for the existing
  `web.get("/api/v1/artifacts/...")` block).
- Implement the view class (e.g. `ArtifactPublicHTMLView`). Two viable
  designs (pick one and document):
  - **A** — Issue a `302` redirect to the S3 presigned URL produced by
    `ArtifactStore.get_public_url`. Simpler; S3 enforces sigv4. CSP
    headers ride on the 302 + a `Content-Security-Policy: frame-ancestors`
    response header issued before the redirect.
  - **B** — Verify the signature query parameters in-app and stream the
    HTML from `Artifact.definition.html` (or re-render from
    `definition.blocks` for legacy artifacts). More code, but you control
    CSP without trusting S3.
  - **Recommendation**: design **B** — control over CSP outweighs the
    extra code. The signature *we* validate can be a stand-alone HMAC
    over `{artifact_id, expiry}` derived from `INFOGRAPHIC_SIGNING_KEY`
    (NEW env var), separate from the S3 presigned URL produced in
    TASK-1321. Document the choice in the route's docstring.
- Update `ArtifactDetailView.get` to honour `?format=html` /
  `Accept: text/html` for session-scoped requests too.
- Build the CSP header from the artifact's `definition.metadata.js_bundles`
  (when present) plus the `INFOGRAPHIC_FRAME_ANCESTORS` env var.
  - `default-src 'self'`
  - `script-src 'self' 'unsafe-inline' <cdn origins from js_bundles[scope='cdn']>`
  - `style-src 'self' 'unsafe-inline'`
  - `img-src 'self' data:`
  - `frame-ancestors <env list space-separated, default 'self'>`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: no-referrer`
- Tests covering CSP, env var override, signature tamper / expiry, legacy
  fallback (re-render from blocks when `definition.html` is missing).

**NOT in scope**:
- Per-tenant CSP configuration (explicitly non-goal in spec).
- Cache headers / CDN tuning.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/artifacts.py` | MODIFY | New `ArtifactPublicHTMLView`; update `ArtifactDetailView.get`; route registration. |
| `packages/ai-parrot/src/parrot/handlers/__init__.py` (or `routes.py`) | MODIFY | Register new public route. |
| `packages/ai-parrot/src/parrot/handlers/csp.py` | CREATE | Small helper module: `build_csp_headers(*, js_bundles, frame_ancestors_env)` returning a dict[str, str]. |
| `packages/ai-parrot/tests/unit/handlers/test_artifact_html_serving.py` | CREATE | CSP + signature + env tests. |
| `packages/ai-parrot/tests/unit/handlers/test_csp_helper.py` | CREATE | Direct unit tests for the CSP builder. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.handlers.artifacts import ArtifactDetailView
# verified: packages/ai-parrot/src/parrot/handlers/artifacts.py

from parrot.storage.artifacts import ArtifactStore
# verified: packages/ai-parrot/src/parrot/storage/artifacts.py:22

from parrot.storage.models import Artifact, ArtifactType
# verified (in use): parrot/handlers/infographic.py:201

from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer
# verified: packages/ai-parrot/src/parrot/outputs/formats/infographic_html.py:582
# Use the sync helper:
#   html = InfographicHTMLRenderer().render_to_html(infographic_response, theme=...)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/artifacts.py
class ArtifactDetailView(BaseView):
    async def get(self) -> web.Response: ...
    async def put(self) -> web.Response: ...
    async def delete(self) -> web.Response: ...
```

### Does NOT Exist
- ~~`ArtifactPublicHTMLView`~~ — created by this task.
- ~~Route `/api/v1/artifacts/public/{signature}/{artifact_id}.html`~~ —
  created by this task.
- ~~`INFOGRAPHIC_FRAME_ANCESTORS` env var~~ — read at request time; no
  config schema change required (read via `os.getenv` or `navconfig`,
  matching whatever pattern other handlers use).
- ~~`build_csp_headers` helper~~ — created by this task in
  `parrot/handlers/csp.py`.

---

## Implementation Notes

### Signature scheme (design B)

```python
import hashlib, hmac, time
from base64 import urlsafe_b64encode, urlsafe_b64decode

def _sign(artifact_id: str, expiry: int, key: bytes) -> str:
    msg = f"{artifact_id}|{expiry}".encode()
    return urlsafe_b64encode(hmac.new(key, msg, hashlib.sha256).digest()).decode()

def _verify(artifact_id: str, expiry: int, sig: str, key: bytes) -> bool:
    if expiry < int(time.time()):
        return False
    expected = _sign(artifact_id, expiry, key)
    return hmac.compare_digest(expected, sig)
```

The `{signature}` URL segment then carries both the HMAC and the expiry
(e.g. `f"{expiry}.{sig}"` base64url-joined). Document the format clearly.

### Legacy artifact fallback

Some pre-existing artifacts saved by `_auto_save_infographic_artifact` do
NOT carry `definition.html`. Fall back to:

```python
infographic_response = InfographicResponse.model_validate(definition["blocks_envelope"])
html = InfographicHTMLRenderer().render_to_html(infographic_response,
                                                theme=definition.get("theme"))
```

Only for legacy artifacts. New artifacts (TASK-1323) always populate
`definition.html`.

### CSP builder pattern

```python
# parrot/handlers/csp.py
from typing import Iterable, Mapping
from parrot.models.infographic import JSBundle


def build_csp_headers(
    *,
    js_bundles: Iterable[JSBundle] = (),
    frame_ancestors: str = "'self'",
) -> Mapping[str, str]:
    cdn_origins = " ".join(
        sorted({_origin_of(b.url) for b in js_bundles
                if b.scope == "cdn" and b.url})
    )
    script_src = "'self' 'unsafe-inline'"
    if cdn_origins:
        script_src = f"{script_src} {cdn_origins}"

    csp = (
        f"default-src 'self'; "
        f"script-src {script_src}; "
        f"style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data:; "
        f"frame-ancestors {frame_ancestors}; "
    )
    return {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }
```

### Reading the env var

```python
import os
raw = os.getenv("INFOGRAPHIC_FRAME_ANCESTORS", "'self'")
ancestors = " ".join(p.strip() for p in raw.split(",") if p.strip())
```

### Key Constraints
- CSP MUST be set via HTTP response header, NEVER `<meta http-equiv>`.
- The `Accept: text/html` content-negotiation lives on the existing
  `ArtifactDetailView.get` for the session-scoped path too.
- Async-first throughout.
- Use `self.logger.info(...)` for issuance, `self.logger.warning(...)`
  for tampered signatures.

---

## Acceptance Criteria

- [ ] `GET /api/v1/artifacts/public/{sig}/{artifact_id}.html` returns the
      HTML for a valid signature, with CSP / X-Content-Type-Options /
      Referrer-Policy headers as specified.
- [ ] `frame-ancestors` is built from `INFOGRAPHIC_FRAME_ANCESTORS` CSV env.
- [ ] Without the env var, `frame-ancestors 'self'`.
- [ ] Tampered signature → `403`.
- [ ] Expired signature (`expiry` in the past) → `403`.
- [ ] `script-src` includes the `https://cdn.example` origin when the
      artifact's template declares a `JSBundle(scope='cdn', url=...)`.
- [ ] Legacy artifact (no `definition.html`) falls back to re-render via
      `InfographicHTMLRenderer.render_to_html`.
- [ ] `pytest packages/ai-parrot/tests/unit/handlers/test_artifact_html_serving.py packages/ai-parrot/tests/unit/handlers/test_csp_helper.py -v` passes.
- [ ] `ruff check` clean on all touched files.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/handlers/test_csp_helper.py
from parrot.handlers.csp import build_csp_headers
from parrot.models.infographic import JSBundle


def test_default_frame_ancestors_self():
    hdrs = build_csp_headers()
    assert "frame-ancestors 'self'" in hdrs["Content-Security-Policy"]


def test_env_provided_ancestors():
    hdrs = build_csp_headers(frame_ancestors="https://a.example https://b.example")
    csp = hdrs["Content-Security-Policy"]
    assert "frame-ancestors https://a.example https://b.example" in csp


def test_cdn_origin_added_to_script_src():
    bundles = [JSBundle(name="echarts", scope="cdn",
                        url="https://cdn.example/echarts.min.js",
                        sri_hash="sha384-AAA")]
    hdrs = build_csp_headers(js_bundles=bundles)
    assert "https://cdn.example" in hdrs["Content-Security-Policy"]


def test_static_headers_present():
    hdrs = build_csp_headers()
    assert hdrs["X-Content-Type-Options"] == "nosniff"
    assert hdrs["Referrer-Policy"] == "no-referrer"
```

```python
# packages/ai-parrot/tests/unit/handlers/test_artifact_html_serving.py
import time, pytest

# Use the existing aiohttp test_client fixture or AgentTalk test harness.

async def test_valid_signature_returns_html(public_app_client, persisted_html_artifact):
    sig = _sign_for(persisted_html_artifact.id, expiry=int(time.time()) + 600)
    resp = await public_app_client.get(
        f"/api/v1/artifacts/public/{sig}/{persisted_html_artifact.id}.html"
    )
    assert resp.status == 200
    assert resp.content_type == "text/html"
    csp = resp.headers["Content-Security-Policy"]
    assert "frame-ancestors" in csp
    assert "default-src 'self'" in csp


async def test_tampered_signature_403(public_app_client, persisted_html_artifact):
    resp = await public_app_client.get(
        f"/api/v1/artifacts/public/deadbeef/{persisted_html_artifact.id}.html"
    )
    assert resp.status == 403


async def test_expired_signature_403(public_app_client, persisted_html_artifact):
    sig = _sign_for(persisted_html_artifact.id, expiry=int(time.time()) - 1)
    resp = await public_app_client.get(
        f"/api/v1/artifacts/public/{sig}/{persisted_html_artifact.id}.html"
    )
    assert resp.status == 403


async def test_env_frame_ancestors_applied(public_app_client, persisted_html_artifact,
                                            monkeypatch):
    monkeypatch.setenv("INFOGRAPHIC_FRAME_ANCESTORS",
                       "https://a.example,https://b.example")
    sig = _sign_for(persisted_html_artifact.id, expiry=int(time.time()) + 600)
    resp = await public_app_client.get(
        f"/api/v1/artifacts/public/{sig}/{persisted_html_artifact.id}.html"
    )
    assert "frame-ancestors https://a.example https://b.example" in \
        resp.headers["Content-Security-Policy"]


async def test_legacy_artifact_fallback(public_app_client, persisted_legacy_artifact):
    # Artifact whose definition lacks 'html' but has 'blocks' should re-render.
    sig = _sign_for(persisted_legacy_artifact.id, expiry=int(time.time()) + 600)
    resp = await public_app_client.get(
        f"/api/v1/artifacts/public/{sig}/{persisted_legacy_artifact.id}.html"
    )
    assert resp.status == 200
```

---

## Agent Instructions

1. Read `packages/ai-parrot/src/parrot/handlers/artifacts.py` end-to-end —
   the new view should mimic the existing `ArtifactDetailView` style.
2. Look for the route table registration (search for
   `"/api/v1/artifacts"` in the handlers module + the app bootstrap).
3. Pick design A or B (recommended B); document the rationale at the top
   of the new view's class docstring.
4. Build the CSP helper first; unit test it; then plug into the view.
5. Add the `?format=html` / `Accept: text/html` support to
   `ArtifactDetailView.get` so session-scoped clients can also get the
   raw HTML (without re-implementing CSP — reuse the helper).
6. Run `pytest packages/ai-parrot/tests/unit/handlers/ -v`.
7. Move to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
