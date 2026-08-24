---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Web-Automation Real-Browser Fixture-Site Integration Tests

**Feature ID**: FEAT-455
**Date**: 2026-08-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

> **Origin**: FEAT-453 (Business Browser Automation) declared AC-17/AC-20 and
> named four Integration Tests (`sdd/specs/web-automation-infra.spec.md` §4/§5)
> that were never built — every task in that feature disclosed the gap
> individually, and the feature's own code-review remediation pass
> (TASK-2397 completion-note addendum) explicitly deferred it here rather
> than improvising real-browser test infrastructure during a review pass.
> This spec is that deferred follow-up.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-453 shipped `BusinessAutomationToolkit`, the closed `session_actions`
dispatch (form auth, cookies, uploads/downloads, human-in-the-loop waits),
and the bank-statement ingestion pipeline — all validated today only against
**mocked** drivers/executors. Two acceptance criteria from that spec are
consequently only partially met:

- **AC-17**: "All integration tests pass, none contacting `app.hooba.com`."
  — no such integration-test layer exists at all.
- **AC-20**: a `SmokeCheck` "runs on schedule and alerts on failure (verified
  against the fixture site)" — `test_smoke.py`'s own completion note
  discloses this was verified only by directly invoking the registered
  job's callback against a mocked `FlowExecutor.run()`, never a fixture
  site.

Nothing in the current test suite proves that the corrected `session_actions`
dispatch (the very defect FEAT-453 Module 2 exists to fix — the executor
used to silently `return True` for eight action types without doing
anything) actually drives a **real** browser against a **real** HTTP
response. A regression that only breaks under a real page load (a selector
that doesn't exist, a cookie the browser actually refuses to set, a form
that doesn't submit the way the mock assumed) would currently ship
undetected.

### Goals

- Build the two fixtures FEAT-453's own spec named but never built:
  `local_fixture_site` (a real, locally-bound HTTP server — login, dashboard,
  upload/download, and cookie pages) and `fake_broker` (a real
  `CredentialBroker` with one deterministic `static_key` resolver — no
  external network, no real secrets).
- Implement the four Integration Tests FEAT-453's spec named:
  `test_authenticated_flow_end_to_end`, `test_stub_regression_full_plan`,
  `test_expense_import_resumes_from_checkpoint`, `test_submit_gate_end_to_end`.
- Prove, with a **real** `PlaywrightDriver` (Chromium, headless) against the
  **real** local fixture site, that: a login flow survives across
  `FlowNode`s; all eight formerly-stubbed action types (Module 2) produce
  real effects; a mid-run kill + resume via
  `make_import_progress_listener()` (FEAT-453 AC-12 remediation) does not
  duplicate a registration; a `SUBMIT` operation genuinely pauses for
  confirmation and completes only after approval.
- **No test may contact any real third-party site** (matching FEAT-453's own
  "never Hooba" convention) — every browser interaction targets the local
  fixture site only.

### Non-Goals (explicitly out of scope)

- Re-litigating or modifying any FEAT-453 production code. This spec is
  test-only; if a real-browser test uncovers a genuine defect in
  `session_actions.py`/`executor.py`/`toolkit.py`, that is a **new**,
  separately-filed bug, not silently patched here.
- CI runner provisioning (installing Playwright browser binaries in CI) is
  assumed already solved by the existing `scraping` extra
  (`playwright>=1.52`) and is out of this spec's scope — Module 2 below
  documents the `pytest.mark.skipif`-style guard needed if browsers are not
  present, but does not change any CI workflow file.
- A generic, reusable "real browser test harness" for the rest of the
  `parrot_tools.scraping` package — scoped strictly to the four named
  FEAT-453 tests. A broader harness is a separate, larger initiative if
  ever needed.
- Firefox/WebKit coverage. Chromium only, matching every other real-browser
  precedent already installed in this environment.

---

## 2. Architectural Design

### Overview

Two independent, additive test-infrastructure pieces, composed by the four
named tests:

1. **`local_fixture_site`** — a `pytest-aiohttp` `aiohttp_server` fixture
   (already a root `pyproject.toml` dev-dependency and already used
   elsewhere in this repo — see Codebase Contract) serving a handful of
   static/dynamic HTML routes: `/login` (form auth), `/dashboard` (post-login
   landing page, used to prove session survival), `/upload` (file upload
   target), `/download/<name>` (file download target), and `/cookie-check`
   (reads/echoes `document.cookie` for the cookie-roundtrip assertion).
2. **`fake_broker`** — a real `parrot.auth.broker.CredentialBroker` built via
   its plain `CredentialBroker(audit_ledger=...)` constructor + `.register()`
   (not `from_config()`'s factory/vault machinery — see Codebase Contract
   correction below), with one always-succeeding
   `CredentialResolver.resolve()` implementation returning a static
   `(username, password)`-bearing secret object. No network, no vault, no
   real secret material. This exact pattern **already exists** in
   `test_authenticate_broker.py` (TASK-2389) scoped to that one file —
   Module 2 relocates/generalizes it into a shared fixture rather than
   inventing a new construction path.
3. The four integration tests wire a **real** `PlaywrightDriver` (or a raw
   Playwright `Browser`, per which layer each test targets — see Module
   Breakdown) against `local_fixture_site`'s bound URL, and — for the two
   harder tests — a real `ExecutionPlanToolkit`/`ToolManager`/
   `WorkingMemoryToolkit` stack (mirroring
   `packages/ai-parrot/tests/tools/execution_plan/test_integration.py`'s
   existing pattern) around a real `BusinessAutomationToolkit`.

### Component Diagram

```
local_fixture_site (aiohttp_server)
        ▲
        │ real HTTP
        │
PlaywrightDriver (real Chromium) ──▶ execute_plan_steps / FlowExecutor
        │                                    │
        │                          BusinessAutomationToolkit.run_operation()
        │                                    │
fake_broker (real CredentialBroker) ─────────┘ (credential_resolver)
        │
ExecutionPlanToolkit + ToolManager + WorkingMemoryToolkit
        │
        └──▶ make_import_progress_listener() (AC-12 resume check)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PlaywrightDriver` (`parrot_tools.scraping.drivers.playwright_driver`) | uses, real instance | `.start()`/`.quit()` lifecycle around each test |
| `execute_plan_steps` / `FlowExecutor` (`parrot_tools.scraping`) | exercises, unmodified | the exact dispatch path FEAT-453 Module 2 closed |
| `BusinessAutomationToolkit` (`parrot_tools.business_automation.toolkit`) | exercises, unmodified | real `credential_broker=fake_broker`, real `plans_dir` fixtures |
| `make_import_progress_listener` (`parrot_tools.business_automation.ingest`) | exercises, unmodified | the FEAT-453 AC-12 remediation's own public hook |
| `CredentialBroker.from_config` (`parrot.auth.broker`) | uses, real instance | `static_key` resolver strategy, fake vault |
| `ExecutionPlanToolkit` (`parrot.tools.execution_plan.toolkit`) | uses, real instance | mirrors `test_integration.py`'s existing construction pattern |
| `ConfirmationGuard` (`parrot.auth.confirmation`) | exercises, unmodified | real SUBMIT-gate pause/approve cycle |

### Data Models

No new production data models — this spec is test-only. The fixture site's
routes are plain `aiohttp.web` handlers; `fake_broker`'s fake vault is a
private test-only class, not a Pydantic model.

### New Public Interfaces

```python
# packages/ai-parrot-tools/tests/scraping/fixtures/local_site.py  (NEW)
@pytest.fixture
async def local_fixture_site(aiohttp_server) -> "TestServer":
    """Real local HTTP server: /login, /dashboard, /upload, /download/<name>,
    /cookie-check. Returns the aiohttp TestServer; callers use
    `server.make_url(path)` for a real, connectable URL."""

# packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py  (NEW)
@pytest.fixture
def fake_broker() -> "CredentialBroker":
    """A real CredentialBroker with one static_key provider ('acme') backed
    by an in-memory fake vault pre-seeded with a deterministic test
    credential. No network, no real secret material."""
```

---

## 3. Module Breakdown

### Module 1: `local_fixture_site` fixture
- **Path**: `packages/ai-parrot-tools/tests/scraping/fixtures/local_site.py`
- **Responsibility**: A real, locally-bound `aiohttp.web.Application` serving
  the five routes named above. Session state (login → dashboard) tracked via
  a signed cookie the fixture itself issues on successful `/login` POST — no
  external session store.
- **Depends on**: `pytest-aiohttp`'s `aiohttp_server` fixture (already a
  root dev-dependency — see Codebase Contract).

### Module 2: `fake_broker` fixture + real-browser smoke tests
- **Path**: `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py`
  (fixture — relocates/generalizes the `_StaticResolver`/`_BrokerWrapper`/
  `CredentialBroker.register()` pattern already proven in
  `test_authenticate_broker.py`, see Codebase Contract) +
  `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py`
  (tests: `test_authenticated_flow_end_to_end`, `test_stub_regression_full_plan`)
- **Responsibility**: The shared `fake_broker` fixture (real
  `CredentialBroker`, in-memory static resolver — no factory/vault
  machinery needed). The two integration tests that need only a real
  driver + real site + real broker (no full agent stack): login survives
  across `FlowNode`s, and a plan exercising all eight formerly-stubbed
  action types produces real effects against the fixture site.
- **Depends on**: Module 1. Guard with a `pytest.mark.skipif` (or an
  autouse fixture that skips) when Playwright's Chromium binary is not
  installed — do not fail the whole suite in an environment that never
  ran `playwright install chromium`.

### Module 3: End-to-end resume + submit-gate tests
- **Path**: `packages/ai-parrot-tools/tests/business_automation/test_fixture_site_e2e.py`
- **Responsibility**: `test_expense_import_resumes_from_checkpoint` (real
  `ExecutionPlanToolkit` + `make_import_progress_listener` + a simulated
  mid-run kill) and `test_submit_gate_end_to_end` (real `ConfirmationGuard`
  + a scripted approving `HumanChannel`/`HumanInteractionManager`, a real
  `BusinessAutomationToolkit.run_operation()` call against the fixture
  site).
- **Depends on**: Modules 1 and 2. This is the harder module — it wires the
  full stack `test_integration.py` already demonstrates for
  `ExecutionPlanToolkit` alone, plus `BusinessAutomationToolkit` and a real
  browser on top.

---

## 4. Test Specification

### Unit Tests

N/A — this spec adds integration tests and their fixtures only; no new
production unit-testable logic.

### Integration Tests

| Test | Module | Description |
|---|---|---|
| `test_authenticated_flow_end_to_end` | M2 | Against `local_fixture_site`: login → navigate → extract, asserting the session survives across `FlowNode`s (real cookie, real Playwright context) |
| `test_stub_regression_full_plan` | M2 | A plan using all 8 formerly-stubbed action types (`authenticate`, `upload_file`, `wait_for_download`, `get_cookies`, `set_cookies`, `await_human` DOM-condition, `await_keypress`, `await_browser_event`) completes with real, observable effects against the fixture site |
| `test_expense_import_resumes_from_checkpoint` | M3 | Kill mid-import (simulate by raising after N rows), re-run `build_import_plan()` for the same statement, confirm no duplicate registration via `make_import_progress_listener`'s manifest |
| `test_submit_gate_end_to_end` | M3 | A SUBMIT operation pauses via `ConfirmationGuard`, a scripted `HumanChannel` approves, the operation then completes against the fixture site |

### Test Data / Fixtures

```python
@pytest.fixture
async def local_fixture_site(aiohttp_server) -> TestServer: ...

@pytest.fixture
def fake_broker() -> CredentialBroker: ...

@pytest.fixture
def real_playwright_driver():
    """Yields a started PlaywrightDriver(PlaywrightConfig(headless=True));
    guaranteed .quit() in a finally block. Skips (not fails) the test if
    Chromium is not installed."""
```

> **No test may contact any real third-party site.** Every browser
> interaction in this spec's tests targets `local_fixture_site` only.

---

## 5. Acceptance Criteria

- [ ] `local_fixture_site` binds a real local port and serves all five
      routes; a plain `aiohttp.ClientSession` GET/POST round-trip against
      each route passes before any browser test relies on it.
- [ ] `fake_broker` resolves its one `static_key` provider deterministically
      via `CredentialBroker.resolve()` — no network I/O, confirmed by a
      dedicated unit-level fixture test.
- [ ] `test_authenticated_flow_end_to_end` passes against a real headless
      Chromium instance and `local_fixture_site` — no mocked driver.
- [ ] `test_stub_regression_full_plan` passes; each of the 8 action types is
      asserted to have produced a real, checkable effect (not merely
      "returned True").
- [ ] `test_expense_import_resumes_from_checkpoint` passes: after a
      simulated mid-run kill, re-running `build_import_plan()` for the same
      statement digest registers each remaining row exactly once — total
      registrations across both runs equals the original row count.
- [ ] `test_submit_gate_end_to_end` passes: the operation is provably paused
      (no browser action beyond the confirmation point until approval is
      recorded) and completes only after the scripted approval.
- [ ] No test in this spec's new files contacts any host other than
      `local_fixture_site`'s bound `127.0.0.1` address.
- [ ] Tests skip (not fail) cleanly in an environment without Chromium
      installed, verified by temporarily renaming `~/.cache/ms-playwright`
      or an equivalent CI-safe simulation during review.
- [ ] `ruff check` clean on every new file (matching the pyupgrade-style
      debt convention already established by FEAT-453's own files).
- [ ] FEAT-453's spec (`sdd/specs/web-automation-infra.spec.md`) AC-17 and
      AC-20 are re-evaluated as MET once this feature merges — noted in
      this feature's own completion note, not by editing the FEAT-453 spec
      itself (specs are not modified post-approval).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry below was read
> directly from source on `dev` at the point this spec was written
> (immediately after FEAT-453 merged, PR #1225). Re-verify line numbers
> before implementing — this spec was authored in the same session as
> FEAT-453's own merge and may drift as other work lands on `dev`.

### Verified Imports

```python
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver  # verified: scraping/drivers/playwright_driver.py:15
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig  # verified: scraping/drivers/playwright_config.py:10
from parrot_tools.scraping.executor import execute_plan_steps               # verified: scraping/executor.py:53 (now accepts credential_resolver/channel kwargs — FEAT-453 remediation)
from parrot_tools.scraping.flow_executor import FlowExecutor                # verified: scraping/flow_executor.py:40 (now accepts credential_resolver/channel kwargs)
from parrot_tools.business_automation.toolkit import BusinessAutomationToolkit  # verified: business_automation/toolkit.py:41
from parrot_tools.business_automation.ingest import (                       # verified: business_automation/ingest.py
    build_import_plan, make_import_progress_listener, ImportPlanBundle,
)
from parrot.auth.broker import CredentialBroker                             # verified: parrot/auth/broker.py:326
from parrot.auth.credentials import CredentialResolver, NeedsAuth           # verified: parrot/auth/credentials.py (CredentialResolver ABC), :82 (NeedsAuth)
from parrot.auth.confirmation import ConfirmationGuard, InMemoryConfirmationWindowStore  # verified: already used by toolkit.py
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit        # verified: parrot/tools/execution_plan/toolkit.py:61
from parrot.tools.working_memory.tool import WorkingMemoryToolkit           # verified: parrot/tools/working_memory/tool.py:44
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):                      # line 15
    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None: ...  # line 30
    async def start(self) -> None: ...   # line 41 — launches real Chromium via playwright.async_api

# packages/ai-parrot/src/parrot/auth/broker.py
class CredentialBroker:                                       # line 326
    def __init__(self, audit_ledger: Optional[AuditLedger] = None,
                 identity_mapper: Optional[CanonicalIdentityMapper] = None) -> None: ...
    def register(self, provider: str, resolver: CredentialResolver,
                 auth_kind: str = "oauth2") -> None: ...       # line 375 — direct registration, no factory/vault needed
    async def resolve(self, provider: str, channel: str, user_id: str,
                       **ctx: Any) -> "ResolvedCredential | NeedsAuth": ...  # line 451

# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...     # returns the secret object, or None on a miss
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...

# ALREADY-PROVEN fake_broker construction pattern (relocate/generalize this,
# do not invent a different one) — packages/ai-parrot-tools/tests/scraping/
# test_authenticate_broker.py:23-90 (TASK-2389):
#   1. A tiny `_StaticResolver(CredentialResolver)` whose `resolve()` always
#      returns a `_StaticSecret(username, password)`-shaped object.
#   2. `broker = CredentialBroker(audit_ledger=AsyncMock())`
#      `broker.register("acme", _StaticResolver("test-user", "test-pass"), auth_kind="static_key")`
#   3. A thin wrapper's `.as_resolver()` adapts `broker.resolve(provider,
#      channel, user_id)` into the `CredentialResolverFn` shape
#      `Callable[[Authenticate], Awaitable[Optional[Tuple[str, str]]]]`
#      `BusinessAutomationToolkit`'s own `_credential_resolver_from_broker()`
#      (toolkit.py) already does this same adaptation for production code —
#      the test fixture can call that real adapter directly instead of
#      duplicating the wrapper logic.

# packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py
class BusinessAutomationToolkit(AbstractToolkit):              # line 41 (FEAT-453)
    def __init__(self, plans_dir, browser=None, credential_broker=None,
                 human_manager=None, checkpoint_dir=None,
                 credential_user_id: str = "gestoria",
                 human_channel=None, **kwargs) -> None: ...    # FEAT-453 remediation signature

# packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py
def make_import_progress_listener(operation: str, digest: str) -> Callable[[str, str, Dict[str, Any]], None]: ...
    # FEAT-453 AC-12 remediation — sync (event, node_id, info) callback,
    # pass to ExecutionPlanToolkit(on_node_event=...) or
    # AgentsFlow.add_node_event_listener(...)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `local_fixture_site` | `PlaywrightDriver`/`execute_plan_steps` | real HTTP navigation | `aiohttp_server` fixture — precedent at `packages/ai-parrot-tools/tests/rss/test_fetcher.py:56-73` (binds a real port, `server.make_url(path)` gives a connectable URL) |
| `fake_broker` | `BusinessAutomationToolkit(credential_broker=...)` | `credential_broker` kwarg | `toolkit.py`'s `_credential_resolver_from_broker()` adapter (FEAT-453 remediation) |
| `ExecutionPlanToolkit` construction pattern | `WorkingMemoryToolkit` + `ToolManager` | constructor kwargs | `packages/ai-parrot/tests/tools/execution_plan/test_integration.py` (existing, full end-to-end construction pattern to mirror) |

### Does NOT Exist (Anti-Hallucination)

- ~~no `fake_broker` exists anywhere~~ — **correction**: one already exists,
  scoped to `test_authenticate_broker.py` only (TASK-2389) — see the
  Codebase Contract's "ALREADY-PROVEN fake_broker construction pattern"
  above. Module 2 relocates/generalizes it into a shared fixture; it does
  **not** invent a `from_config()`/vault-backed construction (an earlier
  draft of this spec assumed that path before this file was found — do not
  resurrect it).
- ~~a `local_fixture_site` fixture anywhere in the repo today~~ — confirmed
  absent via `grep -rn "local_fixture_site" packages/*/tests/`; net-new per
  this spec.
- ~~any existing test in this repo launching a real Playwright/Selenium
  browser against a real `aiohttp_server`-bound URL~~ — `test_fetcher.py`'s
  `test_fetch_page_js_shell_triggers_selenium` looks similar but mocks
  `_fetch_with_selenium` (`AsyncMock`); it does not launch a real browser.
  This spec's Module 2/3 tests are the first such tests in the codebase —
  treat every assumption about how a real Playwright session behaves
  against this fixture site as unverified until the fixture is actually
  built and run, not as already-proven by any existing precedent.
- ~~`FlowExecutor`/`execute_plan_steps` needing any NEW parameter for this
  spec~~ — `credential_resolver`/`channel` already exist (FEAT-453
  remediation); this spec's tests are pure consumers, no production code
  changes.
- ~~a `resume_from` parameter on `ExecutionPlanToolkit.plan_execute`~~ —
  still does not exist (FEAT-399's deliberate `checkpoint=False`,
  unchanged by FEAT-453). `test_expense_import_resumes_from_checkpoint`
  proves resumability via `make_import_progress_listener`'s manifest, not
  via any `ExecutionPlanToolkit`-native resume mechanism.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- `aiohttp_server` fixture usage: mirror
  `packages/ai-parrot-tools/tests/rss/test_toolkit.py::feed_server` for the
  server-construction/route-registration pattern.
- `ExecutionPlanToolkit` + `ToolManager` + `WorkingMemoryToolkit`
  construction: mirror
  `packages/ai-parrot/tests/tools/execution_plan/test_integration.py`
  exactly — do not invent a different wiring pattern.
- Real-browser lifecycle: always `try/finally` (or a fixture with
  `yield`/teardown) around `PlaywrightDriver.start()`/`.quit()` — a leaked
  browser process across test failures is a known pytest/Playwright
  footgun.
- Anonymized-fixtures convention (FEAT-453): the local site's copy/labels
  use a generic "acme-books"-style placeholder brand, never a real product
  or vendor name.

### Known Risks / Gotchas
- **CI browser availability**: if the CI runner never executed
  `playwright install chromium`, these tests must skip cleanly, not fail
  the build. Verify the skip guard actually skips (not errors) by
  simulating a missing-binary environment during review.
- **Flakiness**: real browser + real HTTP server tests are inherently
  slower and more flake-prone than mocked tests. Keep timeouts generous
  but bounded; do not let a hung real browser stall CI indefinitely — every
  test needs an explicit `asyncio.wait_for`/pytest timeout ceiling.
- **`ExecutionPlanToolkit`'s `soft_timeout`** (default 60s) may return a
  `RunningSummary` instead of a completed manifest for a slow real-browser
  run — `test_expense_import_resumes_from_checkpoint`/
  `test_submit_gate_end_to_end` must poll `plan_status(run_id)` rather than
  assume synchronous completion (see `test_integration.py`'s own handling
  of this).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pytest-aiohttp` | `>=1.1.0` | already a root dev-dependency; provides `aiohttp_server` |
| `playwright` | `>=1.52` (already in the `scraping` extra) | real Chromium launch |

---

## 8. Open Questions

- [ ] Should `test_expense_import_resumes_from_checkpoint`'s "mid-run kill"
      be simulated by raising inside a monkeypatched row-handler after N
      rows, or by actually `asyncio.CancelledError`-ing the background task
      and re-entering? The former is far less flaky; recommend it unless
      review disagrees. — *Owner: implementing agent, confirm in the
      task's Completion Note either way.*
- [ ] Should this spec's new fixtures also be exposed for reuse from
      `WebScrapingToolkit`'s own test suite (broader value) or kept
      scoped to these four named tests only (smaller footprint, per this
      spec's Non-Goals)? Default: keep scoped; revisit only if a concrete
      second consumer appears. — *Owner: implementing agent.*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-24 | Jesus Lara (sdd-worker) | Initial draft — filed as FEAT-453's deferred AC-17/AC-20 follow-up |
