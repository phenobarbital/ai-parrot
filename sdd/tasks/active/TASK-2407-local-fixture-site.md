# TASK-2407: `local_fixture_site` fixture

**Feature**: FEAT-455 — Web-Automation Real-Browser Fixture-Site Integration Tests
**Spec**: `sdd/specs/web-automation-fixture-site-tests.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** (Goals: AC-17/AC-20 real-browser coverage).

FEAT-453's own spec named a `local_fixture_site` fixture in its Test Data
section but no task ever built it — every browser-facing test in that
feature runs against a mocked `AbstractDriver`. This task builds the real,
locally-bound HTTP server the rest of FEAT-455's tests need: a login flow,
a post-login dashboard, an upload target, a download target, and a cookie
echo page — all served by a real `aiohttp.web.Application` bound to a real
port via the `aiohttp_server` pytest fixture (already a root
`pyproject.toml` dev-dependency).

Implements spec **Module 1**.

---

## Scope

- Implement `local_fixture_site` as an `async` pytest fixture depending on
  `aiohttp_server`, returning the bound `TestServer` (callers use
  `server.make_url(path)` for a real, connectable URL).
- Routes:
  - `GET /login` — a real HTML `<form>` with `#username`/`#password`
    fields and a submit button.
  - `POST /login` — validates against one hardcoded test credential
    (`testuser`/`testpass123` — never a real secret, this is a fixture),
    issues a signed session cookie on success, redirects to `/dashboard`;
    renders the login form again with an error message on failure.
  - `GET /dashboard` — requires the session cookie from `/login`; renders
    a distinct, greppable string (e.g. `"Welcome, testuser"`) so tests can
    assert the session survived navigation.
  - `POST /upload` — accepts a multipart file upload, echoes the uploaded
    filename and byte count in the response body.
  - `GET /download/<name>` — serves a small, fixed-content file (e.g.
    `report.pdf`, a few KB of deterministic bytes) with
    `Content-Disposition: attachment`.
  - `GET /cookie-check` — renders `document.cookie`'s server-observed
    value (i.e. echoes the `Cookie` request header) as page text, for the
    cookie-roundtrip (`get_cookies`/`set_cookies`) assertion.
- Write a standalone test proving every route works via a plain
  `aiohttp.ClientSession` (no browser) BEFORE any browser test in
  TASK-2408/2409 relies on it — this task's own acceptance criteria, not
  deferred to later tasks.
- Anonymized-fixtures convention (FEAT-453): use a generic "acme-books"
  brand in any rendered copy — never a real product/vendor name.

**NOT in scope**: the `fake_broker` fixture (TASK-2408); any test that
launches a real browser against this site (TASK-2408/2409 — this task
proves the site works via a plain HTTP client only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/scraping/fixtures/local_site.py` | CREATE | `local_fixture_site` fixture + route handlers |
| `packages/ai-parrot-tools/tests/scraping/fixtures/__init__.py` | CREATE | Package marker (if the directory doesn't already exist as a package) |
| `packages/ai-parrot-tools/tests/scraping/test_local_fixture_site.py` | CREATE | Plain-HTTP-client tests proving every route works |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, checked on
> `dev` immediately after FEAT-453 merged (PR #1225). Use these exact
> imports and signatures. **DO NOT** invent, guess, or assume anything not
> listed here. If you need something absent, VERIFY it exists with
> `grep`/`read` and update this section FIRST.

### Verified Imports

```python
from aiohttp import web                                    # verified: used throughout parrot_tools.scraping/etc.
# aiohttp_server is a pytest-aiohttp fixture — no import needed, request it
# as a normal pytest fixture parameter. pytest-aiohttp>=1.1.0 is a root
# pyproject.toml dev-dependency (verified: pyproject.toml:73).
```

### Existing Signatures to Use

```python
# ALREADY-PROVEN aiohttp_server usage pattern — copy this shape, do not
# invent a different one:
# packages/ai-parrot-tools/tests/rss/test_fetcher.py:56-73
async def test_fetch_page_aiohttp_happy_path(aiohttp_server):
    async def handler(request):
        return web.Response(text="...", content_type="text/html")

    app = web.Application()
    app.router.add_get("/path", handler)
    server = await aiohttp_server(app)
    # server.make_url("/path") -> a real, connectable yarl.URL
```

### Does NOT Exist

- ~~a `local_fixture_site` fixture anywhere in the repo today~~ — confirmed
  absent via `grep -rn "local_fixture_site" packages/*/tests/`; net-new.
- ~~a shared `conftest.py` under `packages/ai-parrot-tools/tests/scraping/`
  exporting fixtures automatically to other test directories~~ — verify
  this before assuming: if TASK-2408/2409's test files live in a
  *different* test directory (e.g. `tests/business_automation/`), they
  will need an explicit import of this fixture module, not automatic
  pytest fixture discovery across package boundaries. Confirm pytest's
  actual conftest discovery rules for this repo's layout before writing
  TASK-2408/2409's imports.

---

## Implementation Notes

### Pattern to Follow

The route handlers are plain `aiohttp.web` view functions — no need for
`web.View` classes or middleware; a session cookie set via
`resp.set_cookie(...)` and read via `request.cookies.get(...)` is
sufficient (do not build a real session-store abstraction — this is a test
fixture, not production code).

### Key Constraints

- **No real third-party site.** Every route here is fully self-contained;
  nothing proxies or redirects to an external host.
- **Deterministic content.** Every response body must be exact-match
  assertable (fixed strings/byte content), not randomly generated, so
  downstream browser tests can make precise assertions.
- **Anonymized branding**, matching FEAT-453's own convention (never a real
  product/vendor name in any rendered page).

### References in Codebase

- `packages/ai-parrot-tools/tests/rss/test_fetcher.py` — `aiohttp_server`
  usage pattern to copy.
- `packages/ai-parrot-tools/tests/rss/test_toolkit.py::feed_server` —
  a second precedent for the same pattern, slightly more elaborate.
- `packages/ai-parrot-tools/tests/business_automation/fixtures/acme-books/`
  — the existing anonymized-fixtures directory convention (FEAT-453
  TASK-2391) to match in spirit (never Hooba, always "acme-books"-style).

---

## Acceptance Criteria

- [ ] `local_fixture_site` binds a real local port (via `aiohttp_server`)
      and serves all five routes.
- [ ] A plain `aiohttp.ClientSession` GET/POST round-trip against each
      route passes, asserted in `test_local_fixture_site.py`, with no
      browser involved.
- [ ] `/login` → `/dashboard` session survives a second GET request using
      the cookie jar from the first (proves the cookie mechanism itself
      works before any browser test relies on it).
- [ ] `/download/<name>` content is byte-exact and deterministic across
      repeated requests.
- [ ] No route in this fixture site contacts any host other than itself.
- [ ] `ruff check` clean on every new file.

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import aiohttp
import pytest
from parrot_tools_tests.scraping.fixtures.local_site import local_fixture_site  # adjust import per actual package layout chosen


class TestLocalFixtureSite:
    async def test_login_success_sets_cookie_and_redirects(self, local_fixture_site):
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                local_fixture_site.make_url("/login"),
                data={"username": "testuser", "password": "testpass123"},
            )
            assert resp.status == 200
            text = await resp.text()
            assert "Welcome, testuser" in text or resp.url.path == "/dashboard"

    async def test_login_failure_shows_error(self, local_fixture_site):
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                local_fixture_site.make_url("/login"),
                data={"username": "wrong", "password": "wrong"},
            )
            text = await resp.text()
            assert "error" in text.lower()

    async def test_dashboard_requires_session(self, local_fixture_site):
        async with aiohttp.ClientSession() as session:
            resp = await session.get(local_fixture_site.make_url("/dashboard"))
            assert resp.status in (401, 403, 302)

    async def test_download_is_deterministic(self, local_fixture_site):
        async with aiohttp.ClientSession() as session:
            a = await (await session.get(local_fixture_site.make_url("/download/report.pdf"))).read()
            b = await (await session.get(local_fixture_site.make_url("/download/report.pdf"))).read()
            assert a == b
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-fixture-site-tests.spec.md` — especially §2 Architectural Design and §6 Codebase Contract.
2. **Check dependencies** — none for this task.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-fixture-site-tests.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2407-local-fixture-site.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
