# TASK-4682: FormDesigner read client (M1)

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-734 lets a Teams agent serve FormDesigner forms. Today the bot only ever
*posts* to FormDesigner (`formdesigner_submit.post_submission`); nothing in the
repo *reads* a form. This task builds that read client — spec §3 **Module 1** —
plus the shared models every later task imports (`FormDescriptor`,
`RenderedCard`, the `FormReader` protocol and the `parse_form_ref` helper).

It is a leaf: it depends on nothing in this feature and runs in wave 1.

---

## Scope

- Create `formdesigner_client.py` with: `MAX_RESPONSE_BYTES`, `FormDesignerError`,
  `FormDescriptor`, `RenderedCard`, the structural `FormReader` Protocol,
  `parse_form_ref()`, and `FormDesignerClient` (`list_forms`, `get_form`,
  `get_form_by_slug`, `render_teams`, `close`).
- Every request: `allow_redirects=False`, bounded body (`MAX_RESPONSE_BYTES`),
  `Authorization: Bearer <token>` only when a token is given, per-call
  `aiohttp.ClientTimeout(total=timeout)`.
- `render_teams(section_index=N)` adds `section_index=N` to the query and then
  REQUIRES the response metadata to echo `section_index == N` plus an int
  `total_sections` and a str `form_version`; otherwise raise `FormDesignerError`
  (an old server that ignores the query must never pass as a section server).
- Write `tests/msteams/test_formdesigner_client.py` with the five M1 tests of
  spec §4 plus `parse_form_ref` and section-metadata tests.

**NOT in scope**: the local (in-process) reader (TASK-4690), the server's
`section_index` support (TASK-4685), any Teams/Bot Framework code, cards.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py` | CREATE | FormDesignerClient, models, FormReader, parse_form_ref |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_client.py` | CREATE | M1 unit tests (fake aiohttp server) |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import aiohttp                                            # already a dependency (formdesigner_submit.py uses it)
from pydantic import BaseModel, Field                     # pydantic v2
from parrot_formdesigner.core.schema import FormSchema    # verified: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:426
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py
MAX_RESPONSE_BYTES: int = 1_048_576                                       # line 25 — mirror the value, do not import
async def post_submission(...) -> SubmitOutcome:                          # line 73
#   lines 93-110: the chunked bounded-read loop (read(65536) until EOF or cap) — COPY this pattern;
#   a single resp.content.read(n) can silently truncate.

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                                              # line 426
    form_uid: uuid.UUID                                                   # line 482
    form_id: str                                                          # line 483 (the slug)
    version: str = "1.0"                                                  # line 484
    sections: list[FormSection]                                           # line 487
    published_version: str | None = None                                  # line 498

# Server routes the client calls (packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py)
#   GET {tp}/forms                                  line 383  tenant="required"  -> {"forms": [ {form_uid, form_id, title, description, version, source, created_at} ]}
#                                                              supports ?slug=<form_id>  (handlers.py:851)
#   GET {tp}/forms/{form_uid}                       lines 393-396 tenant="public" -> FormSchema JSON
#   GET {tp}/forms/{form_uid}/render/{format}       lines 416-418 tenant="public"
#       ?with_meta=true -> {"content", "content_type", "content_encoding", "warnings", "metadata"}  (api/render.py:215-236)
#       unknown format  -> 415 {"supported": [...]}                        (api/render.py:184-188)
#   {tp} == f"{api_base_path}/{tenant}"
```

### Does NOT Exist
- ~~A FormDesigner read client anywhere in the repo~~ — this task creates the first one.
- ~~`FormDesignerClient.get_session()` / a public session accessor~~ — the mixin owns its own POST session (TASK-4691); do not add one.
- ~~`?section_index=` support on today's server~~ — TASK-4685 adds it; tests here use a fake aiohttp server.
- ~~`requests` / `httpx`~~ — banned (TID251); aiohttp only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_client.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py#post_submission",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSchema"
  ]
}
```

---

## Implementation Notes

- `RenderedCard.content` is a dict (Teams cards are JSON); if the server returns
  `content_encoding == "base64"` that is not a Teams card — raise `FormDesignerError`.
- `FormDescriptor.title` / `.description` arrive already resolved to strings from
  the server (`list_forms` handler); accept `str | dict` defensively by
  coercing a dict to its `"en"` value or first value — FILL IN in the blueprint.
- `self.logger = logging.getLogger(__name__)`; never log the bearer.
- Tests: `pytest-aiohttp` is installed and the package runs `asyncio_mode = "auto"`
  (`packages/ai-parrot-integrations/pyproject.toml:148`); use the `aiohttp_server`
  fixture with a tiny `web.Application` that records request headers/queries.

---

## Implementation Blueprint

### Steps (in order)
1. Write the models + `FormReader` + `parse_form_ref` block — *why*: TASK-4688/4689/4690 import these names verbatim, so they must exist exactly as spelled.
2. Write `FormDesignerClient` with one private `_request_json()` doing the bounded read — *why*: one choke point guarantees `allow_redirects=False` and the size cap on every call.
3. Implement the four public reads on top of `_request_json()` — *why*: keeps endpoints declarative and testable.
4. Write the tests against a fake `aiohttp_server` — *why*: proves headers, redirects and the cap on the wire, not on mocks.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_client.py` (CREATE) — part 1
```python
"""FormDesigner read client (FEAT-734 M1): list, fetch and render forms over aiohttp."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import quote

import aiohttp
from pydantic import BaseModel, Field

from parrot_formdesigner.core.schema import FormSchema  # verified: core/schema.py:426

MAX_RESPONSE_BYTES: int = 1_048_576  # mirrors formdesigner_submit.py:25


class FormDesignerError(Exception):
    """A FormDesigner read failed (HTTP status, timeout, oversize or malformed body)."""

    def __init__(self, message: str, *, status: int = 0) -> None:
        super().__init__(message)
        self.status = status  # 0 == the request never completed


class FormDescriptor(BaseModel):
    """One row of GET {tp}/forms (handlers.py:851) — the picker's choice source."""

    form_uid: uuid.UUID
    form_id: str
    title: str
    description: str | None = None
    version: str | None = None
    source: str | None = None
    created_at: datetime | None = None


class RenderedCard(BaseModel):
    """`?with_meta=true` envelope (render.py:215-236), or the local render's equivalent."""

    content: dict[str, Any]
    content_type: str
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormReader(Protocol):
    """Structural read surface shared by FormDesignerClient and LocalFormReader (spec §3 Delivery contracts)."""

    async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]: ...

    async def get_form(self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None) -> FormSchema: ...

    async def get_form_by_slug(self, *, tenant: str, slug: str, bearer_token: str | None) -> FormDescriptor | None: ...


def parse_form_ref(ref: str | uuid.UUID) -> uuid.UUID | str:
    """UUID-shaped -> form_uid, anything else -> slug (spec §8 open question, decided here)."""
    if isinstance(ref, uuid.UUID):
        return ref
    text = str(ref).strip()
    try:
        return uuid.UUID(text)
    except ValueError:
        return text
```
**Why this shape**: the model fields are the spec §2 Data Models verbatim; `FormReader` is the protocol spec §3 says M1 defines so the toolkit can take either the HTTP client or the local adapter. `parse_form_ref` resolves the "slug vs uid" open question by UUID shape — put it here so `/getform` and the toolkit agree.

### `formdesigner_client.py` (CREATE) — part 2 (append)
```python
class FormDesignerClient:
    """Async read client for the FormDesigner REST surface (one lazily created session)."""

    def __init__(
        self,
        base_url: str,
        *,
        api_base_path: str = "/api/v1",
        timeout: float = 15.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        """`base_url` is the public FormDesigner origin; trailing slashes stripped."""
        self.base_url = base_url.rstrip("/")
        self.api_base_path = "/" + api_base_path.strip("/") if api_base_path.strip("/") else ""
        self.timeout = timeout
        self._session = session
        self._owns_session = session is None
        self.logger = logging.getLogger(__name__)

    def _forms_url(self, tenant: str, *parts: str) -> str:
        tail = "".join(f"/{quote(p, safe='')}" for p in parts)
        return f"{self.base_url}{self.api_base_path}/{quote(tenant, safe='')}/forms{tail}"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def _request_json(self, url: str, *, bearer_token: str | None, params: dict[str, str] | None = None) -> Any:
        """GET `url`; return parsed JSON for a 200. Raise FormDesignerError otherwise."""
        headers = {"Accept": "application/json"}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        session = await self._get_session()
        # FILL IN: session.get(url, params=params, headers=headers, allow_redirects=False,
        #   timeout=aiohttp.ClientTimeout(total=self.timeout)); chunked bounded read copied from
        #   formdesigner_submit.py:93-110 (cap MAX_RESPONSE_BYTES -> FormDesignerError("response too large", status=resp.status));
        #   non-200 (incl. 3xx, since redirects are off) -> FormDesignerError(status=resp.status);
        #   aiohttp.ClientError / asyncio.TimeoutError -> FormDesignerError(type(exc).__name__, status=0);
        #   invalid JSON -> FormDesignerError(status=resp.status). Never log the bearer.
        raise NotImplementedError

    async def list_forms(self, *, tenant: str, bearer_token: str | None) -> list[FormDescriptor]:
        """GET {api}/{tenant}/forms -> {"forms": [...]}; an empty list is not an error."""
        body = await self._request_json(self._forms_url(tenant), bearer_token=bearer_token)
        # FILL IN: validate body is a dict with a list "forms"; build FormDescriptor per row
        #   (coerce dict-valued title/description to str); malformed -> FormDesignerError(status=200)
        raise NotImplementedError

    async def get_form(self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None) -> FormSchema:
        """GET {api}/{tenant}/forms/{form_uid} (routes.py:393)."""
        body = await self._request_json(self._forms_url(tenant, str(form_uid)), bearer_token=bearer_token)
        # FILL IN: FormSchema.model_validate(body); ValidationError -> FormDesignerError(status=200)
        raise NotImplementedError

    async def get_form_by_slug(self, *, tenant: str, slug: str, bearer_token: str | None) -> FormDescriptor | None:
        """GET {api}/{tenant}/forms?slug=<slug>; None when the filter matches nothing."""
        # FILL IN: same parsing as list_forms with params={"slug": slug}; return the first row or None
        raise NotImplementedError

    async def render_teams(
        self, *, tenant: str, form_uid: uuid.UUID, bearer_token: str | None, section_index: int | None = None
    ) -> RenderedCard:
        """GET …/render/teams?with_meta=true[&section_index=N]; 415 -> FormDesignerError(status=415)."""
        params = {"with_meta": "true"}
        if section_index is not None:
            params["section_index"] = str(section_index)
        body = await self._request_json(
            self._forms_url(tenant, str(form_uid), "render", "teams"), bearer_token=bearer_token, params=params
        )
        # FILL IN: content_encoding == "base64" or non-dict content -> FormDesignerError; build RenderedCard;
        #   when section_index is not None, require metadata section_index == section_index, int total_sections,
        #   str form_version — else FormDesignerError("server does not support section rendering", status=200)
        raise NotImplementedError

    async def close(self) -> None:
        """Close the session when this client owns it."""
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
```
**Why this shape**: the endpoint paths and the 415 behaviour are fixed by spec §3 M1; `quote(..., safe='')` stops a tenant/slug from injecting path segments. Do not add a fallback that retries a section render as a whole form — spec M1 forbids it.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_client.py` (CREATE)
```python
"""FEAT-734 M1 — FormDesignerClient against a fake aiohttp server."""
import uuid

import pytest
from aiohttp import web

from parrot.integrations.msteams.formdesigner_client import (
    MAX_RESPONSE_BYTES, FormDesignerClient, FormDesignerError, parse_form_ref,
)

UID = uuid.UUID("f0000000-0000-0000-0000-000000000001")


@pytest.fixture
def seen() -> list:
    return []


async def _server(aiohttp_server, seen, handler):
    app = web.Application()
    async def _record(request):
        seen.append({"path": request.path, "query": dict(request.query), "auth": request.headers.get("Authorization")})
        return await handler(request)
    app.router.add_get("/{tail:.*}", _record)
    return await aiohttp_server(app)


async def test_client_list_forms_parses_descriptors(aiohttp_server, seen):
    """{"forms": [...]} -> FormDescriptors; an empty list is not an error."""
    # FILL IN
async def test_client_list_forms_sends_bearer(aiohttp_server, seen):
    """Authorization present with a token, absent with None."""
    # FILL IN
async def test_client_render_teams_with_meta(aiohttp_server, seen):
    """?with_meta=true -> RenderedCard incl. metadata["envelope"]."""
    # FILL IN
async def test_client_render_teams_415_raises(aiohttp_server, seen):
    # FILL IN: FormDesignerError with .status == 415
async def test_client_no_redirects_and_bounded_body(aiohttp_server, seen):
    """A 302 is an error (not followed); a body > MAX_RESPONSE_BYTES is refused."""
    # FILL IN
async def test_client_section_render_requires_matching_metadata(aiohttp_server, seen):
    """Missing/mismatched section_index metadata -> FormDesignerError (old server)."""
    # FILL IN
def test_parse_form_ref_uuid_vs_slug():
    assert parse_form_ref(str(UID)) == UID
    assert parse_form_ref("store-visit") == "store-visit"
```
**Why**: real HTTP proves `allow_redirects=False` and the cap; these names are the spec §4 M1 rows.

### FILL IN checklist
- [ ] `FormDesignerClient._request_json` — bounded read + error mapping; bounded by formdesigner_submit.py:93-110 and AC "allow_redirects=False; oversized body refused"
- [ ] `list_forms` / `get_form_by_slug` — row parsing; bounded by `FormDescriptor` fields (spec §2)
- [ ] `get_form` — `FormSchema.model_validate`
- [ ] `render_teams` — base64 refusal + section metadata check; bounded by spec §3 M1 docstring
- [ ] six test bodies

---

## Acceptance Criteria

- [ ] All names above importable from `parrot.integrations.msteams.formdesigner_client`.
- [ ] Bearer header only when a token is given; never logged.
- [ ] Redirects are not followed; bodies over `MAX_RESPONSE_BYTES` are refused.
- [ ] 415 surfaces as `FormDesignerError(status=415)`.
- [ ] A section render whose metadata does not echo the requested `section_index` raises.
- [ ] `ruff check` clean; no `requests`/`httpx` import.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_client.py -q`


---

## Test Specification

See the test-file block in the blueprint: one test per spec §4 M1 row
(`test_client_list_forms_parses_descriptors`, `test_client_list_forms_sends_bearer`,
`test_client_render_teams_with_meta`, `test_client_render_teams_415_raises`,
`test_client_no_redirects_and_bounded_body`) plus
`test_client_section_render_requires_matching_metadata` and
`test_parse_form_ref_uuid_vs_slug`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4682 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


### Completion Note
Implemented by the sdd-coder pool; merged to the feature branch, file-fidelity gate green, merge-tier validation green, review recorded (0 corrections).
