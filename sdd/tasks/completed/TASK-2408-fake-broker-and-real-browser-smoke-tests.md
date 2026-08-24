# TASK-2408: `fake_broker` fixture + real-browser smoke tests

**Feature**: FEAT-455 — Web-Automation Real-Browser Fixture-Site Integration Tests
**Spec**: `sdd/specs/web-automation-fixture-site-tests.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2407
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** (AC-17: `test_authenticated_flow_end_to_end`,
`test_stub_regression_full_plan`).

FEAT-453 closed the executor's stub-return-`True` defect (Module 2 of that
feature) and proved it via mocked-driver regression tests
(`test_stub_closure_regression.py`). This task proves the SAME dispatch
path against a **real** Chromium instance and the **real**
`local_fixture_site` (TASK-2407) — the class of regression a mock cannot
catch (a selector that doesn't exist on a real page, a cookie the browser
actually refuses, a form that submits differently than the mock assumed).

It also relocates the `fake_broker` construction pattern already proven
in `test_authenticate_broker.py` (TASK-2389) into a shared fixture, since
this task's `test_authenticated_flow_end_to_end` needs a real
`credential_provider`-backed login against the fixture site.

Implements spec **Module 2**.

---

## Scope

- Implement a shared `fake_broker` fixture: a real `CredentialBroker`
  (`parrot.auth.broker.CredentialBroker`) with one registered
  `CredentialResolver` that always resolves to a static test credential —
  copy the `_StaticResolver`/`CredentialBroker.register()` pattern from
  `test_authenticate_broker.py` verbatim rather than inventing a
  `from_config()`/vault-based construction (see Codebase Contract).
- Implement a `real_playwright_driver` fixture: yields a started
  `PlaywrightDriver(PlaywrightConfig(headless=True))`, guarantees `.quit()`
  in a `finally`/fixture-teardown block, and **skips** (not fails) the
  test when Chromium is not installed.
- Implement `test_authenticated_flow_end_to_end`: against
  `local_fixture_site`, a real `Authenticate` step with
  `credential_provider` set resolves via `fake_broker` (through
  `BusinessAutomationToolkit._credential_resolver_from_broker()` — call
  the real production adapter, do not re-implement the
  `(username, password)` mapping in the test), logs in, navigates to
  `/dashboard`, and asserts the "Welcome, testuser" text is extracted —
  proving the session survives across the plan's steps.
- Implement `test_stub_regression_full_plan`: a single `ScrapingPlan`
  exercising the **5 of 8** FEAT-453 Module 2 action types that can
  genuinely produce a real, checkable effect through `PlaywrightDriver`
  specifically — `authenticate`, `get_cookies`, `set_cookies`,
  `await_human` (DOM `condition_type`, not `"manual"` — no channel needed),
  `await_browser_event` — against `local_fixture_site`'s routes.
- Implement 3 **separate, dedicated** tests honestly documenting the
  current (non-real-effect) behavior of the remaining 3 action types
  against `PlaywrightDriver` — see the "SCOPE CORRECTION" Codebase
  Contract entry below for the full, empirically-verified rationale for
  each. **Do not fold these into the main plan** — mixing a
  known-to-fail step into the same plan as the 5 working ones only
  obscures which failures are expected vs. regressions:
  - `test_upload_file_known_limitation_with_playwright` — a real
    Playwright browser attempting `exec_upload_file` against a real
    `<input type="file">` element returns `False` (Playwright's `.fill()`
    hard-rejects file inputs; `exec_upload_file` catches this cleanly).
  - `test_wait_for_download_known_limitation_with_playwright` —
    `exec_wait_for_download` times out (returns `False`) because
    `PlaywrightDriver` has no download-handling wiring at all; nothing a
    real browser click/navigate does ever reaches the filesystem path this
    action polls.
  - `test_await_keypress_is_not_a_browser_action` — proves `driver` truly
    plays no role (the real driver's `current_url` is unchanged
    before/after) while the console-stdin interaction is simulated via the
    same `select.select`/`sys.stdin` monkeypatch pattern FEAT-453's own
    mocked-driver tests already use for this action.
- Guard all four real-browser tests (or a shared autouse fixture) to skip
  cleanly when Chromium is not installed — verify the skip actually skips,
  not errors, by simulating a missing-binary environment during review
  (e.g. temporarily pointing `PLAYWRIGHT_BROWSERS_PATH` at an empty
  directory).

**NOT in scope**: `test_expense_import_resumes_from_checkpoint` and
`test_submit_gate_end_to_end` (TASK-2409 — they need the full
`ExecutionPlanToolkit`/`ToolManager`/`WorkingMemoryToolkit` stack, not just
a driver + site + broker); modifying any FEAT-453 production code — the
3 known limitations above are documented, not fixed, here (see "SCOPE
CORRECTION" below for the 2 concrete follow-up bugs recommended instead:
`PlaywrightDriver.fill()` needs a file-input special case calling
`set_input_files()`; `PlaywrightDriver` needs `expect_download()`/
`save_as()` wiring for `wait_for_download` to ever work against it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py` | CREATE | Shared `fake_broker` fixture |
| `packages/ai-parrot-tools/tests/scraping/fixtures/real_driver.py` | CREATE | `real_playwright_driver` fixture with skip guard |
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | CREATE | `test_authenticated_flow_end_to_end`, `test_stub_regression_full_plan`, and the 3 documented-limitation tests |
| `packages/ai-parrot-tools/tests/scraping/fixtures/local_site.py` | MODIFY | Add a minimal `GET /upload` route rendering a real `<input type="file">` form — TASK-2407 only built the `POST /upload` handler; a real browser needs a page to interact with. See "SCOPE CORRECTION" below. |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, checked on
> `dev` immediately after FEAT-453 merged (PR #1225). Use these exact
> imports and signatures. **DO NOT** invent, guess, or assume anything not
> listed here. If you need something absent, VERIFY it exists with
> `grep`/`read` and update this section FIRST.

### Verified Imports

```python
from parrot.auth.broker import CredentialBroker                        # verified: parrot/auth/broker.py:326
from parrot.auth.credentials import CredentialResolver, NeedsAuth       # verified: parrot/auth/credentials.py
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver   # verified: scraping/drivers/playwright_driver.py:15
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig   # verified: scraping/drivers/playwright_config.py:10
from parrot_tools.scraping.executor import execute_plan_steps          # verified: scraping/executor.py:53 — accepts credential_resolver/channel kwargs (FEAT-453 remediation)
from parrot_tools.scraping.plan import ScrapingPlan                    # verified: used throughout scraping tests
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker  # verified: business_automation/toolkit.py — module-level function, not a method
```

### Existing Signatures to Use

```python
# ALREADY-PROVEN fake_broker construction pattern — copy this, do not
# invent from_config()/vault-based construction:
# packages/ai-parrot-tools/tests/scraping/test_authenticate_broker.py:23-90 (TASK-2389)
class _StaticResolver(CredentialResolver):
    def __init__(self, username: str, password: str) -> None: ...
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...  # returns an object with .username/.password
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...       # raise NotImplementedError — never called on a hit

broker = CredentialBroker(audit_ledger=AsyncMock())          # or a real AuditLedger; AsyncMock is fine for a test fixture
broker.register("acme", _StaticResolver("test-user", "test-pass"), auth_kind="static_key")

# packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py (FEAT-453 remediation)
def _credential_resolver_from_broker(broker: CredentialBroker, user_id: str) -> CredentialResolverFn:
    """Adapts broker.resolve(provider, "business_automation", user_id) into
    the (username, password) shape exec_authenticate expects. Handles
    dict/tuple/opaque-string secret shapes and NeedsAuth misses. USE THIS
    directly in the fake_broker fixture's resolver-building helper rather
    than re-implementing the adaptation."""

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):
    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None: ...  # line 30
    async def start(self) -> None: ...   # line 41 — launches real Chromium
    # AbstractDriver interface (inherited) includes navigate/fill/click/
    # execute_script/get_page_source/quit — verify each exact method name
    # against drivers/abstract.py before use; do not assume names from
    # session_actions.py's mocked-driver tests carry over exactly.
```

### Does NOT Exist

- ~~a `_StaticSecret`-shaped (attribute-style `.username`/`.password`)
  resolver result works with `_credential_resolver_from_broker()`~~ —
  **contract correction, verified by reading `toolkit.py:49-115` directly**:
  the real adapter only handles `secret` being a `dict`
  (`{"username": ..., "password": ...}`), a 2-`tuple`/`list`, or a plain
  `str` (opaque secret, mapped to `(None, secret)`). It does **not**
  inspect `.username`/`.password` attributes. `test_authenticate_broker.py`'s
  own `_StaticSecret`/`_BrokerWrapper.as_resolver()` is a **separate,
  bespoke adapter** (attribute-based) that this task does NOT reuse — this
  task's scope explicitly calls for using the real production
  `_credential_resolver_from_broker()` instead. Therefore this task's
  `_StaticResolver.resolve()` must return a **dict**
  (`{"username": "test-user", "password": "test-pass"}`), not a
  `_StaticSecret` object, or `_credential_resolver_from_broker()` will hit
  its "unrecognized secret shape" branch and fail closed (`None`) —
  silently breaking `TestFakeBroker::test_resolves_deterministically`'s
  own expected `("test-user", "test-pass")` result.
- ~~a `from_config()`/vault-backed `fake_broker`~~ — the proven pattern uses
  the plain `CredentialBroker(audit_ledger=...)` constructor + `.register()`
  directly; do not build a fake vault.
- ~~any existing test in this repo launching a real Playwright browser
  against a real `aiohttp_server`-bound URL~~ — this task's two tests are
  the first. Treat every assumption about real-browser-vs-fixture-site
  interaction as unverified until actually run — do not assume the mocked
  `AbstractDriver` tests' exact call sequences carry over unchanged.
- ~~a production-code change needed to make `credential_resolver`/`channel`
  reach `execute_plan_steps`~~ — already wired by FEAT-453's own
  remediation; this task is a pure consumer.

### SCOPE CORRECTION (verified empirically during implementation, user-approved)

The task's original assumption — "all 8 formerly-stubbed action types
produce real effects through `PlaywrightDriver`" — is **false for 3 of the
8**, confirmed by actually running each against a real headless Chromium
instance (not just reading source):

1. **`upload_file`**: `exec_upload_file` (session_actions.py:758) calls
   `driver.fill(selector, path)`. `PlaywrightDriver.fill()`
   (playwright_driver.py:105-110) forwards directly to Playwright's
   `Locator.fill()`, which **hard-rejects file inputs**:
   ```
   Error Locator.fill: Error: Input of type "file" cannot be filled
   ```
   (reproduced directly against a real Chromium `<input type="file">`).
   `exec_upload_file`'s own docstring already discloses this design gap:
   *"mirrors Selenium's send_keys... this action is effectively
   Selenium-oriented until a native per-driver upload hook exists."*
   `SeleniumDriver.fill()` (`element.send_keys(value)`) would actually
   work for a file input — `PlaywrightDriver.fill()` does not special-case
   it. The function's own `try/except` catches this and returns `False`
   cleanly (never a crash), but never a real effect via Playwright.
   **Recommended follow-up bug**: `PlaywrightDriver.fill()` should detect
   a file input (e.g. via `locator.evaluate("el => el.type")`) and call
   `locator.set_input_files(value)` instead of `.fill(value)`.
2. **`wait_for_download`**: `exec_wait_for_download` (session_actions.py:780)
   polls a real filesystem directory (`Path.home()/Downloads` or
   `action.download_path`) for a stabilized file — `driver` is
   accepted-but-unused. `grep -n download
   packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/
   playwright_driver.py` returns **nothing** — no `expect_download()`/
   `save_as()` wiring anywhere. Reproduced directly: `page.goto()` on a
   download-triggering URL raises `net::ERR_ABORTED` (Playwright
   intercepts it as a download internally); even a successful
   click-triggered download is captured in Playwright's own download
   object, never written to the filesystem path this action polls, unless
   something explicitly calls `download.save_as(path)` — nothing in
   `PlaywrightDriver` does. **Recommended follow-up bug**: `PlaywrightDriver`
   needs a `page.expect_download()` context around `click()`/`navigate()`
   (or a dedicated download-aware method) that saves to a configurable
   path matching `WaitForDownload.download_path`'s convention.
3. **`await_keypress`**: `exec_await_keypress` (session_actions.py:515)
   reads real OS stdin via `select.select([sys.stdin], ...)` — this is
   architecturally a console-only mechanism, not a browser action;
   `driver` is accepted-but-unused for signature parity only. There is no
   "real browser effect" this action can ever produce, regardless of
   which driver is configured — this is not a defect to fix, just a
   fundamental scope mismatch with "real-browser regression test."

**User-approved resolution (option a)**: `test_stub_regression_full_plan`
covers only the 5 genuinely real-browser-testable action types
(`authenticate`, `get_cookies`, `set_cookies`, `await_human`,
`await_browser_event`). The other 3 get dedicated, honestly-named tests
that verify and document their CURRENT behavior against `PlaywrightDriver`
(a clean, non-crashing `False`/timeout for the first two; proof that
`driver` plays no role for the third) — never silently skipped, never
misrepresented as passing/working, and no out-of-scope production code is
touched. File the 2 concrete `PlaywrightDriver` bugs above as separate
follow-up SDD tasks if/when real-browser upload/download support is
prioritized.

---

## Implementation Notes

### Pattern to Follow

Wrap every real-browser test body in `try/finally` (or use a fixture with
`yield` + teardown) around `PlaywrightDriver.start()`/`.quit()` — a leaked
browser process across a test failure is a known Playwright/pytest
footgun. Keep every real-browser test's timeout bounded and generous
(these are inherently slower/flakier than mocked tests).

### Key Constraints

- **Skip, don't fail, without Chromium.** Verify the skip guard actually
  skips in a simulated missing-binary environment before considering this
  task done.
- **No real third-party site** — every browser navigation targets
  `local_fixture_site` only.
- **Reuse the production adapter.** `_credential_resolver_from_broker()`
  already exists and is tested in isolation (TASK-2397's remediation); do
  not duplicate its `(username, password)`-mapping logic in this task's
  test fixtures.

### References in Codebase

- `packages/ai-parrot-tools/tests/scraping/test_authenticate_broker.py` —
  the `fake_broker` pattern to relocate/generalize.
- `packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py`
  — the mocked-driver regression this task's real-browser test
  complements (do not duplicate its assertions verbatim; this task proves
  the same dispatch path against real effects).
- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`
  — the full `AbstractDriver` interface `PlaywrightDriver` implements.

---

## Acceptance Criteria

- [ ] `fake_broker` resolves its one provider deterministically via
      `CredentialBroker.resolve()` — no network I/O — confirmed by a
      dedicated fixture-level test.
- [ ] `test_authenticated_flow_end_to_end` passes against a real headless
      Chromium instance and `local_fixture_site` — no mocked driver.
- [ ] `test_stub_regression_full_plan` passes; each of the **5**
      real-browser-testable action types (`authenticate`, `get_cookies`,
      `set_cookies`, `await_human`, `await_browser_event`) is asserted to
      have produced a real, checkable effect (see SCOPE CORRECTION for why
      3 of the original 8 are covered by separate tests instead).
- [ ] `test_upload_file_known_limitation_with_playwright` passes: asserts
      `exec_upload_file` returns `False` against a real Playwright file
      input, with the Playwright rejection reproduced (not just assumed).
- [ ] `test_wait_for_download_known_limitation_with_playwright` passes:
      asserts `exec_wait_for_download` returns `False` (short bounded
      timeout) since nothing reaches its polled filesystem path via
      `PlaywrightDriver`.
- [ ] `test_await_keypress_is_not_a_browser_action` passes: asserts the
      real driver's state (e.g. `current_url`) is unchanged after the
      action, proving `driver` plays no role, with stdin simulated via the
      established monkeypatch pattern.
- [ ] All four real-browser tests skip cleanly (not error) in a simulated
      no-Chromium environment.
- [ ] No test in this task's files contacts any host other than
      `local_fixture_site`.
- [ ] `ruff check` clean on every new/modified file.

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot.auth.broker import CredentialBroker
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker


class TestFakeBroker:
    async def test_resolves_deterministically(self, fake_broker):
        resolver = _credential_resolver_from_broker(fake_broker, "test-user-id")
        from types import SimpleNamespace
        result = await resolver(SimpleNamespace(credential_provider="acme"))
        assert result == ("test-user", "test-pass")


class TestAuthenticatedFlowEndToEnd:
    async def test_login_survives_across_flow_nodes(
        self, local_fixture_site, fake_broker, real_playwright_driver
    ):
        ...  # build a plan with an authenticate step (credential_provider="acme")
             # followed by a navigate-to-dashboard step; assert the extracted
             # text contains "Welcome, testuser"


class TestStubRegressionFullPlan:
    async def test_all_eight_actions_produce_real_effects(
        self, local_fixture_site, real_playwright_driver
    ):
        ...  # build a plan touching all 8 action types against
             # local_fixture_site's routes; assert real effects per action
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-fixture-site-tests.spec.md` — especially §3 Module 2 and §6 Codebase Contract.
2. **Check dependencies** — verify TASK-2407 is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-fixture-site-tests.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2408-fake-broker-and-real-browser-smoke-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (autonomous, via /sdd-start)
**Date**: 2026-08-24
**Notes**: Implemented all three planned files plus one necessary addition:

- `fake_broker` fixture (`tests/business_automation/fixtures/broker.py`,
  new `fixtures/__init__.py` package marker alongside it): a real
  `CredentialBroker(audit_ledger=AsyncMock())` + `.register("acme",
  _StaticDictResolver(...), auth_kind="static_key")`, relocating
  `test_authenticate_broker.py`'s proven construction pattern. Its
  resolver returns a **dict** (`{"username": ..., "password": ...}`), not
  an attribute-based `_StaticSecret` object — see the Codebase Contract
  correction below for why.
- `real_playwright_driver` fixture (`tests/scraping/fixtures/real_driver.py`):
  starts a real headless `PlaywrightDriver`, guarantees `.quit()`, and
  `pytest.skip()`s (verified via a simulated `PLAYWRIGHT_BROWSERS_PATH`
  pointing at an empty directory — all 8 real-browser tests skipped
  cleanly, 2 non-browser tests still ran).
- `test_fixture_site_integration.py`: `TestFakeBroker` (unit-level),
  `TestAuthenticatedFlowEndToEnd` (real login, real session survival —
  works exactly as scoped), `TestStubRegressionFullPlan` (scaled to 2
  action types, see below), `TestSeleniumStyleScriptIncompatibilityWithPlaywright`
  (3 tests, one consolidated class — see below), `TestUploadFileKnownLimitation`,
  `TestWaitForDownloadKnownLimitation`, `TestAwaitKeypressIsNotABrowserAction`,
  `TestNoThirdPartyContact`. 10 tests total, all passing.
- **Necessary addition beyond the original file list**: `fixtures/local_site.py`
  gained a `GET /upload` route (`_handle_upload_get`) rendering a real
  `<input type="file">` form. TASK-2407 only built the `POST /upload`
  API handler; a real browser needs an actual page with a file input
  element to target via `exec_upload_file`'s selector, not just an API
  endpoint. Minimal, additive, does not change any existing route's
  behavior — all 11 of TASK-2407's own tests still pass unchanged.

**MAJOR scope correction, discovered empirically while implementing (user
consulted twice, both times explicitly approved the resulting scope
reduction — see the two STOP-and-report exchanges in this session)**:
Of the original 8 formerly-stubbed FEAT-453 Module 2 action types, only
**2** (`authenticate`, `set_cookies`) were found to produce a genuine,
independently-verifiable real effect through `PlaywrightDriver`
specifically. The other 6 fall into three *distinct*, empirically-verified
(never assumed) incompatibility classes:

1. **Systemic root cause (3 action types)** — `get_cookies`, `await_human`
   (selector condition), `await_browser_event`. Each calls
   `driver.execute_script()` with a Selenium-oriented JS snippet: a bare,
   unwrapped top-level `return` statement (`exec_get_cookies`:
   `"return document.cookie;"`, session_actions.py:302;
   `_check_human_condition`: `"return document.querySelectorAll(...).length;"`,
   :444; `_check_browser_event_ready`:
   `"try{return ...}catch(e){return ...}"`, :672) and, for
   `await_human`, additionally Selenium's `arguments[0]` convention.
   Selenium's `execute_script` implicitly wraps any script body in a
   function (bare `return` is legal there); Playwright's `page.evaluate()`
   does not, raising `SyntaxError: Illegal return statement` — reproduced
   directly against a real page for all three snippets, both in isolation
   and via the actual `exec_*` functions. None crash: each catches the
   exception and returns its documented safe-failure value
   (`{"cookies": []}` / `False` / `False`), so this is a **silent, complete
   loss of functionality** against `PlaywrightDriver`, invisible without a
   real browser. `_BROWSER_EVENT_JS` (the *inject* script) is, by contrast,
   correctly IIFE-wrapped and works fine — only the later polling/clear
   scripts in each of the three functions lack that wrapper.
   **Consolidated into ONE test class**
   (`TestSeleniumStyleScriptIncompatibilityWithPlaywright`, 3 test methods,
   one shared docstring) rather than 3 near-duplicate classes, per explicit
   user direction (option "consolidate" over "same pattern, wider net").
   **Recommended follow-up bug** (one ticket covering all three): wrap
   `_check_human_condition`'s selector-count script, `_check_browser_event_ready`'s
   polling/clear scripts, and `exec_get_cookies`'s cookie-read script each
   in an IIFE (`(() => { ...; return X; })()`), and replace
   `arguments[0]` with a Playwright-compatible arg-passing convention
   (e.g. a function literal taking a parameter).
2. **`upload_file`** — a *different*, unrelated root cause: Playwright's
   `Locator.fill()` hard-rejects file inputs
   (`Error: Input of type "file" cannot be filled`, reproduced directly).
   `exec_upload_file`'s own docstring already discloses this design gap
   ("Selenium-oriented until a native per-driver upload hook exists").
   **Recommended follow-up bug**: `PlaywrightDriver.fill()` should detect
   a file input and call `locator.set_input_files(value)` instead.
3. **`wait_for_download`** — a *third*, unrelated root cause:
   `PlaywrightDriver` has zero download-handling wiring (`grep -n download`
   on the driver source returns nothing); a real `page.goto()` on a
   download-triggering URL raises `net::ERR_ABORTED`, and even a
   click-triggered download is captured only in Playwright's internal
   download object, never reaching the filesystem path `exec_wait_for_download`
   polls. **Recommended follow-up bug**: `PlaywrightDriver` needs
   `page.expect_download()` + `download.save_as(path)` wiring around
   `click()`/`navigate()`.

`await_keypress` was never a "limitation" to begin with — it reads real OS
stdin via `select.select`, architecturally unrelated to any driver;
`TestAwaitKeypressIsNotABrowserAction` proves `driver.current_url` is
unchanged before/after, using the exact `select`/`sys.stdin` monkeypatch
pattern `test_session_actions_waits.py` already established.

`TestStubRegressionFullPlan` verifies `set_cookies` via the fixture site's
own `/cookie-check` HTTP route (the real `Cookie` header the browser sends
on a subsequent, unrelated request) rather than via `get_cookies` — which
is itself one of the broken action types — giving a reliable,
independent verification channel for a real browser-side cookie write.

**Secondary Codebase Contract correction (fake_broker credentials)**:
this task's own Test Specification scaffold's `fake_broker` resolved to
`("test-user", "test-pass")` — a placeholder pair that does **not** match
`local_fixture_site.TEST_USERNAME`/`TEST_PASSWORD` (`"testuser"`/`"testpass123"`,
concrete values that didn't exist yet when this task was originally
written, before TASK-2407 was implemented). Since a real end-to-end login
against `local_fixture_site` needs the SAME credential, `fake_broker` now
imports and resolves to `local_site.TEST_USERNAME`/`TEST_PASSWORD`
directly, and `TestFakeBroker::test_resolves_deterministically` checks
against those real values instead of the stale placeholder.

Full regression: `packages/ai-parrot-tools/tests/scraping/` (828 tests,
same 7 pre-existing/unrelated `CrawlEngine`/FEAT-013 failures) and
TASK-2407's own `test_local_fixture_site.py` (11/11, unaffected by the
GET /upload addition). `ruff check` clean on every new/modified file. Skip
guard verified via a simulated missing-Chromium environment
(`PLAYWRIGHT_BROWSERS_PATH` pointed at an empty directory) — all 8
real-browser tests skipped cleanly, the 2 non-browser tests
(`TestFakeBroker`, `TestNoThirdPartyContact`) still ran and passed.

**Deviations from spec**: The scope reduction from "8 action types produce
real effects" to "2 action types produce real effects + 6 documented via
3 distinct incompatibility classes" is the central deviation — explicitly
surfaced to and approved by the user in two separate STOP-and-report
exchanges during implementation (the second one specifically because a
NEW instance of the systemic root cause, `get_cookies`, was discovered
while fixing the first-reported set — the user was told this expanded
scope honestly before proceeding, not after). No FEAT-453 production code
was modified; 3 concrete follow-up bugs are recommended above (2 for
`PlaywrightDriver`, 1 consolidated for the bare-return/`arguments[N]` JS
pattern) rather than filed as separate SDD tasks here, per this task's own
scope boundary.
