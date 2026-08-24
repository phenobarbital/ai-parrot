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
  exercising all eight action types Module 2 of FEAT-453 closed
  (`authenticate`, `upload_file`, `wait_for_download`, `get_cookies`,
  `set_cookies`, `await_human` with a DOM `condition_type` — not
  `"manual"`, no channel needed for this test, `await_keypress`,
  `await_browser_event`) against `local_fixture_site`'s routes, asserting
  each step produced a real, checkable effect (not merely a return value).
- Guard both tests (or a shared autouse fixture) to skip cleanly when
  Chromium is not installed — verify the skip actually skips, not errors,
  by simulating a missing-binary environment during review (e.g.
  temporarily pointing `PLAYWRIGHT_BROWSERS_PATH` at an empty directory).

**NOT in scope**: `test_expense_import_resumes_from_checkpoint` and
`test_submit_gate_end_to_end` (TASK-2409 — they need the full
`ExecutionPlanToolkit`/`ToolManager`/`WorkingMemoryToolkit` stack, not just
a driver + site + broker); modifying any FEAT-453 production code (if this
task's real-browser tests uncover a genuine defect in
`session_actions.py`/`executor.py`, file it as a separate bug, do not
silently patch it here).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/business_automation/fixtures/broker.py` | CREATE | Shared `fake_broker` fixture |
| `packages/ai-parrot-tools/tests/scraping/fixtures/real_driver.py` | CREATE | `real_playwright_driver` fixture with skip guard |
| `packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py` | CREATE | `test_authenticated_flow_end_to_end`, `test_stub_regression_full_plan` |

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
- [ ] `test_stub_regression_full_plan` passes; each of the 8 action types
      is asserted to have produced a real, checkable effect.
- [ ] Both tests skip cleanly (not error) in a simulated no-Chromium
      environment.
- [ ] No test in this task's files contacts any host other than
      `local_fixture_site`.
- [ ] `ruff check` clean on every new file.

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
