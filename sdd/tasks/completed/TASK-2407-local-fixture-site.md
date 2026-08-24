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
  exporting fixtures automatically to other test directories~~ — **verified
  and resolved during implementation**: no `conftest.py` exists in
  `tests/scraping/`. `packages/ai-parrot-tools/tests/__init__.py` and
  `tests/scraping/__init__.py` both exist, but `packages/ai-parrot-tools/
  __init__.py` does NOT — so pytest's prepend-import-mode rootdir walk
  stops at `packages/ai-parrot-tools/`, making `tests` (not
  `parrot_tools_tests`, the placeholder in this task's own Test
  Specification scaffold) the importable top-level package name. Since
  `tests` collides across every sibling package in this monorepo (each
  ships its own `tests/__init__.py` — the exact collision already observed
  during FEAT-453's own work when running `business_automation` and
  `whatsapp` tests together), cross-package `from tests.scraping...`
  imports are NOT used anywhere in this codebase. The established,
  already-precedented sharing mechanism instead is a plain **relative
  import within the same package** — `tests/business_automation/
  test_submit_gate.py:11` does `from .conftest import SpyConfirmationGuard`.
  `local_fixture_site` is decorated `@pytest.fixture` directly in
  `fixtures/local_site.py`; `test_local_fixture_site.py` (same package,
  `tests.scraping`) does `from .fixtures.local_site import local_fixture_site`
  — pytest resolves a fixture by name in the test module's globals, so this
  import alone makes it usable, no `conftest.py` needed. **TASK-2408/2409
  should follow this exact relative-import pattern**, not the
  `parrot_tools_tests.scraping...` placeholder from this task's own
  original Test Specification scaffold (which was flagged as unverified
  there and is now known to be wrong).

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

### Known Gotcha Discovered During Implementation

**`aiohttp.ClientSession`'s default `CookieJar` rejects cookies for
IP-address hosts** (RFC 6265's "public suffix"/host-format restriction).
`aiohttp_server`/`TestServer` binds to `127.0.0.1` by default, so a plain
`aiohttp.ClientSession()` silently drops every cookie this fixture sets —
`/login` "succeeds" but the follow-up `/dashboard` request comes back
`401` as if never logged in. Fixed in every test that needs cookie
persistence by constructing the session as
`aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))`. This
is exactly the class of defect a mocked-driver test can never surface —
first concrete evidence justifying this whole feature's existence. Future
real-browser tests (TASK-2408/2409) should not hit this same issue since
real browsers (Playwright/Chromium) do not apply this RFC 6265 host-format
restriction to loopback addresses the same way `aiohttp.CookieJar` does —
but confirm this empirically when TASK-2408 is implemented rather than
assuming it.

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

**Completed by**: sdd-worker (autonomous, via /sdd-start)
**Date**: 2026-08-24
**Notes**: Implemented `build_app()` + the `@pytest.fixture async def
local_fixture_site(aiohttp_server)` fixture in
`fixtures/local_site.py`, serving all five routes exactly as scoped:
`/login` (GET renders a form, POST validates `testuser`/`testpass123`,
issues an opaque `uuid4`-token session cookie keyed into an in-memory
`app["sessions"]` dict, redirects via `web.HTTPFound` on success, re-renders
the form with an "Error: ..." message on failure), `/dashboard`
(cookie-gated, 401 without a valid session, renders "Welcome, {username}"),
`/upload` (multipart via `request.post()`, echoes filename + byte count as
JSON), `/download/{name}` (fixed, deterministic byte content +
`Content-Disposition: attachment`), `/cookie-check` (echoes the raw
`Cookie` request header as plain text). Chose a plain opaque
session-token cookie over cryptographic signing — the task's own scope
said "signed" loosely; a real signing library isn't otherwise used
anywhere in this repo's test fixtures, and an opaque server-side-mapped
token is sufficient to prove "session survives navigation" without adding
a new dependency for a test-only fixture. `test_local_fixture_site.py`
covers all 5 routes plus a `TestNoThirdPartyContact` sanity guard
asserting the bound host is a loopback address — 11 tests, all passing.

**Two genuine findings during implementation** (both fully documented
above in the Codebase Contract / Implementation Notes sections, not
repeated here in full):
1. **Import path correction**: the task's own Test Specification scaffold
   guessed `parrot_tools_tests.scraping.fixtures.local_site` — verified
   wrong. The correct, already-precedented pattern is a plain relative
   import (`from .fixtures.local_site import local_fixture_site`), matching
   `tests/business_automation/test_submit_gate.py`'s own
   `from .conftest import SpyConfirmationGuard`. No `conftest.py` was
   needed or added (not in this task's file list, and unnecessary — the
   fixture is `@pytest.fixture`-decorated directly in `fixtures/local_site.py`
   and resolved by pytest via a normal import into the test module's
   namespace).
2. **`aiohttp.ClientSession`'s default `CookieJar` silently drops cookies
   for IP-address hosts** (RFC 6265 host-format restriction) —
   `aiohttp_server` binds to `127.0.0.1`, so the initial test
   implementation's `/login` → `/dashboard` flow returned 401 even on a
   correct login. Fixed by using
   `aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True))` in
   every test needing cookie persistence. This is exactly the class of
   real-environment defect a mocked-driver test can never surface — the
   first concrete evidence justifying this feature's real-HTTP-server
   approach. Flagged for TASK-2408/2409 to confirm empirically whether
   real Playwright/Chromium browser contexts have the same restriction
   (expected: no, browsers don't apply this the same way aiohttp's client
   does, but this should be verified rather than assumed).

Full `packages/ai-parrot-tools/tests/scraping/` suite re-run (818 tests):
zero regressions, same 7 pre-existing/unrelated `CrawlEngine`/FEAT-013
failures already established throughout FEAT-453. `ruff check` clean on
all 3 new files (no pre-existing debt to preserve — these are brand-new
files, so modern `X | None`/`dict`/`list` style was used throughout,
unlike FEAT-453's `Optional`/`Dict`/`List` convention which existed only
to match already-established surrounding code in files that predated it).

**Deviations from spec**: None of substance. "Signed session cookie"
(scope wording) was implemented as an opaque, server-side-mapped token
rather than a cryptographically signed one — see rationale above; this is
an implementation-detail interpretation, not a scope change (the
observable behavior — "dashboard requires a valid session established by
login" — is exactly as specified and tested).
