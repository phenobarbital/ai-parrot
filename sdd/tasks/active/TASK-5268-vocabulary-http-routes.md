# TASK-5268: Read-only vocabulary HTTP routes (version, snapshot, export)

**Feature**: FEAT-824 — Ontology backend: PostgreSQL OntologyStore + SurrealDB programme
**Spec**: `sdd/specs/ontology-backend.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5261, TASK-5262
**Assigned-to**: unassigned

---

## Context

Spec Module 11 (HTTP half). Three read-only aiohttp routes that feed `HttpSnapshotSource`
(TASK-5263) and let operators fetch exports, following the `register_routes(app, prefix)` shape and
the session check of `concept_catalog/http.py`. Mounting them in a server app is out of scope (the
catalog routes are not mounted anywhere either).

---

## Scope

- `vocabulary/http.py` with `get_version`, `get_snapshot`, `get_export`, `register_routes`
  (spec lines 988–998), under `{prefix}/vocabularies/{ontology_id}/…`, default prefix `/api/ontology`.
- Handlers read `request.app["ontology_store"]` (a `PostgresOntologyStore`).
- `get_version` → `{"ontology_id", "version", "checksum"}` (checksum of that version, from `load_version`
  or a direct read; 404 for an unknown ontology).
- `get_snapshot[?version=N]` → build on demand with `load_version` + `build_snapshot` into
  `ONTOLOGY_SNAPSHOT_DIR` (reuse an existing file), stream it as `application/vnd.sqlite3`
  (`web.FileResponse`); unknown version → 404.
- `get_export[?as_of=N&fmt=turtle|jsonld]` → `text/turtle` or `application/ld+json`; bad `fmt` → 400.
- Auth (spec line 996–998): no session → 401; ontology id `tenant.<id>` requires the session's
  `tenant_id == <id>` or `"topic_admin"` in the session's groups → else 403. Non-tenant ontologies
  need only a session.
- Map `OntologyNotFound`/`OntologyVersionNotFound` → 404; never leak tracebacks.
- `test_vocabulary_http.py`.

**NOT in scope**: write routes; mounting in `ai-parrot-server`; rate limiting.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/http.py` | CREATE | routes |
| `packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_http.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound  # TASK-5253
from parrot.knowledge.ontology.vocabulary.settings import resolve_ontology_settings                   # TASK-5254
from parrot.knowledge.ontology.vocabulary.snapshot import build_snapshot, snapshot_path               # TASK-5262
# tests:
from aiohttp.test_utils import TestClient, TestServer
```

### Existing Signatures to Use
```python
# parrot/knowledge/ontology/concept_catalog/http.py:45-67  (session pattern)
def _check_role(request, allowed_roles) -> str:
    session = request.get("session", {}) or {}
    user_roles = set(session.get("groups", []) or [])
    tenant_id = session.get("tenant_id") or request.rel_url.query.get("tenant")
    if not session: raise web.HTTPUnauthorized(reason="Authentication required.")
# concept_catalog/http.py:371-391 — def register_routes(app, prefix="/api/ontology"): base = f"{prefix}/concepts"; app.router.add_get(...)
# TASK-5261: PostgresOntologyStore.version / export(ontology_id, fmt, *, as_of) / load_version(ontology_id, version=None) -> VersionContent
```

### Does NOT Exist
- ~~a `tenant` query parameter override for vocabulary access~~ — unlike `_check_role`, do NOT accept
  `?tenant=`; only the session decides the tenant.
- ~~`pytest-aiohttp` fixtures~~ — use `TestServer`/`TestClient` directly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/vocabulary/http.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_http.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. `_authorize(request, ontology_id)` helper — *why*: one place for 401/403 rules.
2. The three handlers and `register_routes`.
3. Tests with a fake store (no DB) plus the real `build_snapshot`.

### `.../vocabulary/http.py` (CREATE)
```python
"""Read-only HTTP routes of the ontology vocabulary store (FEAT-824)."""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from parrot.knowledge.ontology.vocabulary.exceptions import OntologyNotFound, OntologyVersionNotFound

logger = logging.getLogger("parrot.knowledge.ontology.vocabulary.http")
_ADMIN_GROUP = "topic_admin"


def _authorize(request: web.Request, ontology_id: str) -> None:
    """401 without a session; 403 for another tenant's 'tenant.<id>' ontology unless topic_admin."""
    session: dict[str, Any] = request.get("session", {}) or {}
    if not session:
        raise web.HTTPUnauthorized(reason="Authentication required.")
    # FILL IN: tenant rule per Scope (session tenant only; no query override).


async def get_version(request: web.Request) -> web.Response:
    """GET {prefix}/vocabularies/{ontology_id}/version → {"ontology_id", "version", "checksum"}"""
    # FILL IN
    raise NotImplementedError


async def get_snapshot(request: web.Request) -> web.StreamResponse:
    """GET {prefix}/vocabularies/{ontology_id}/snapshot[?version=N] → the SQLite file, built on demand and cached."""
    # FILL IN
    raise NotImplementedError


async def get_export(request: web.Request) -> web.Response:
    """GET {prefix}/vocabularies/{ontology_id}/export[?as_of=N&fmt=turtle|jsonld]"""
    # FILL IN
    raise NotImplementedError


def register_routes(app: web.Application, prefix: str = "/api/ontology") -> None:
    """Register the three routes; handlers read request.app['ontology_store']."""
    base = f"{prefix}/vocabularies/{{ontology_id}}"
    app.router.add_get(f"{base}/version", get_version)
    app.router.add_get(f"{base}/snapshot", get_snapshot)
    app.router.add_get(f"{base}/export", get_export)
```

### `.../vocabulary/test_vocabulary_http.py` (CREATE) — required cases
```python
# app with a middleware that sets request["session"] from a header, app["ontology_store"] = fake store
async def test_http_auth_401_without_session(): ...
async def test_http_auth_403_other_tenant(): ...      # session tenant "a", GET tenant.b → 403; topic_admin → 200
async def test_version_payload(): ...
async def test_snapshot_streams_sqlite(tmp_path, monkeypatch): ...   # ONTOLOGY_SNAPSHOT_DIR=tmp_path; body starts with b"SQLite format 3"
async def test_export_bad_format_400(): ...
async def test_unknown_ontology_404(): ...
```

### FILL IN checklist
- [ ] `_authorize` tenant rule; three handlers.
- [ ] tests (fake store returns a `VersionContent` built from golden v1 for the snapshot case).

---

## Acceptance Criteria

- [ ] 401 without a session; 403 for another tenant's ontology; 200 for `topic_admin`.
- [ ] `/snapshot` returns a valid SQLite file built from `load_version`, cached under `ONTOLOGY_SNAPSHOT_DIR`.
- [ ] Typed store errors map to 404; bad parameters to 400.
- [ ] `ruff check` passes; aiohttp only.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/vocabulary/test_vocabulary_http.py -q`

---

## Agent Instructions

1. Work in the feature worktree; confirm TASK-5261 and TASK-5262 are `done`.
2. Mark `in-progress`; implement; run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
3. Commit only the listed files; close with `parrot sdd task close TASK-5268 ontology-backend verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
