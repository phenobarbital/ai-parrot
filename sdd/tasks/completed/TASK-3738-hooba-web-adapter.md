# TASK-3738: HoobaWebAdapter (private catalog, context-cookie session recovery, navigation-only runs) + seed_catalog

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3734, TASK-3736
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (adapter half), U1 and design research S8. The Playwright
operativa stays private: real selectors live in a catalog outside the repo, located by
`HOOBA_CATALOG_DIR`. The package ships only the adapter and a `seed_catalog()` helper
that writes the login and navigation actions into a user-supplied directory. Session
recovery runs the private `hooba-login` action and exports cookies at browser-context
level (`driver.get_cookies`, HttpOnly included) — never via `document.cookie`.

---

## Scope

- `hooba/web.py`: `HoobaWebAdapter` (lazy `WebBrowsingToolkit`, `recover_session`, `run_navigation`, `close`) and `seed_catalog`.
- `tests/hooba/test_web.py` with a fake toolkit/driver (no browser) and a tmp catalog for `seed_catalog`.

**NOT in scope**: HoobaToolkit wiring (TASK-3742); real-browser test (TASK-3744, opt-in).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/web.py` | CREATE | HoobaWebAdapter + seed_catalog |
| `packages/ai-parrot-tools/tests/hooba/test_web.py` | CREATE | adapter + seed tests without a browser |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot_tools.browsing import WebBrowsingToolkit                            # verified: browsing/__init__.py:32
from parrot_tools.scraping.session_actions import CredentialResolverFn          # verified: session_actions.py:65
from parrot_tools.scraping.drivers.abstract import AbstractDriver               # verified: browsing/toolkit.py:34
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
class WebBrowsingToolkit(WebScrapingToolkit):                                 # line 64
    def __init__(self, catalog_dir="browsing_catalog", user_data_dir=None, profile_directory=None,
                 browser_channel=None, max_loop_iterations=50, credential_resolver=None, human_channel=None,
                 session_based=True, headless=False, confirm_runs=True, **kwargs)   # lines 124-160
    #   driver_type= / browser= go through **kwargs to WebScrapingToolkit (see untracked hooba_agent.py usage)
    async def _ensure_session_driver(self) -> AbstractDriver                  # lines 164-174 — ASYNC (starts lazily)
    async def close_browser(self) -> Dict[str, Any]                           # lines 176-188
    async def register_site(self, base_url, name=None, title="", description="", aliases=None) -> Dict   # lines 192-222
    async def get_site_action(self, site, action) -> Dict[str, Any]          # lines 256-267 — model_dump incl. "kind"
    async def save_site_action(self, site, name, description, steps=None, kind="operation", params=None,
                               compose=None, requires=None, title="", tags=None, version="1.0",
                               source="llm", overwrite=False) -> Dict        # lines 269-365
    async def run_site_action(self, site, action, params=None, include_requires=True, stop_on_error=True) -> Dict   # lines 382-418

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py (after TASK-3736)
    async def get_cookies(self, urls: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]   # NotImplementedError by default

# Untracked private reference (do NOT commit or copy selectors from it beyond the defaults below):
#   examples/agents/web/services/catalog/hooba/hooba-login.json — navigate /es/login?returnUrl=%2Fdashboard →
#   conditional input[type="email"] → authenticate(form, credential_provider="hooba") → wait url_contains /dashboard
```

### Does NOT Exist
- ~~`WebBrowsingToolkit._ensure_session_driver()` as a sync call~~ — it is `async`; `await` it (the spec §6 listed it as sync — corrected here).
- ~~`exec_get_cookies` for session recovery~~ — reads `document.cookie`, cannot see HttpOnly (S8).
- ~~Any committed Hooba catalog JSON~~ — the catalog stays private (U1); tests use a tmp dir.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/web.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_web.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit.__init__",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit._ensure_session_driver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit.close_browser",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit.run_site_action",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit.get_site_action",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit.register_site",
    "sym:packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py#WebBrowsingToolkit.save_site_action"
  ]
}
```

---

## Implementation Notes

- `recover_session` never raises: any failure (action failed, `NotImplementedError`, no `sid`) → `{}` plus a WARNING without values.
- `run_navigation`: `meta = await tk.get_site_action(site, action)`; `meta["kind"] != "navigation"` → return
  `{"status": "error", "error": "only navigation actions are allowed"}` without running anything.
- `seed_catalog` needs no browser: instantiate `WebBrowsingToolkit(catalog_dir=...)` and call `register_site` +
  `save_site_action(..., kind="navigation", requires=["hooba-login"], overwrite=True)`; the login action uses
  `kind="operation"` with an `authenticate` step carrying `credential_provider="hooba"` (never literal credentials).

### Key Constraints (all FEAT-602 tasks)
- async-first: no blocking I/O inside `async def` — wrap pandas/openpyxl/filesystem work in `asyncio.to_thread` (spec §7, S10).
- aiohttp only in new code: `httpx` and `requests` are banned by ruff TID251; the only httpx surface is inside the exempt `HTTPService` / `openapitoolkit.py`.
- Pydantic v2 models for every structured value; `self.logger` (or a module `logger = logging.getLogger(__name__)`), never `print`.
- Never log cookie values, passwords, IBANs or full bank rows at INFO or above.
- Google-style docstrings and strict type hints on every function and class; `black` line length 120; `ruff check` clean.
- Drafts only: no code path may call `:issue`, `:confirm`, `:cancel`, `:send*`, a DELETE, or any write outside `DRAFT_OPERATIONS` (spec G3, AC-5).
- Worktree testing: the shared `.venv` is editable-installed against the MAIN checkout. Run tests with
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-loaders/src pytest ...` so the worktree's code is imported. Never `uv sync` in a worktree.
- Fixtures are synthetic: never commit real Hooba selectors, credentials, bank exports or personal data (AC-17).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived
> from the spec's Interface Skeletons (§3) and re-verified against the Codebase Contract
> above. Business-logic branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Write `HoobaWebAdapter` with a lazy toolkit property — *why*: AC-13, no browser unless a web tool is called.
2. `recover_session` via context cookies — *why*: S8.
3. `seed_catalog` — *why*: U1, the package ships a generator, not selectors.
4. Tests with fakes.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/web.py` (CREATE)
```python
"""Playwright fallback for Hooba over a PRIVATE action catalog (FEAT-602 M7, U1)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from parrot_tools.browsing import WebBrowsingToolkit
from parrot_tools.scraping.session_actions import CredentialResolverFn

logger = logging.getLogger(__name__)

DEFAULT_SECTIONS: Dict[str, Tuple[str, str, str]] = {
    "hooba-invoices": ("Ir a facturas", "Abrir el listado de facturas.", "/es/sales/invoices"),
    "hooba-purchases": ("Ir a gastos", "Abrir el listado de facturas de compra.", "/es/purchases/purchase-invoices"),
}


class HoobaWebAdapter:
    """Thin wrapper over :class:`WebBrowsingToolkit` for the private Hooba catalog."""

    def __init__(self, catalog_dir: Union[str, Path], credential_resolver: CredentialResolverFn, *,
                 site: str = "hooba", login_action: str = "hooba-login", headless: bool = True,
                 driver_type: str = "playwright", browser: str = "chrome", base_url: str = "https://app.hooba.com",
                 **kwargs: Any) -> None:
        self._catalog_dir = Path(catalog_dir)
        self._resolver = credential_resolver
        self.site, self.login_action, self.base_url = site, login_action, base_url
        self._tk_kwargs = dict(headless=headless, driver_type=driver_type, browser=browser, **kwargs)
        self._toolkit: Optional[WebBrowsingToolkit] = None

    @property
    def started(self) -> bool:
        """True once the underlying toolkit exists (the browser may still be lazy)."""
        return self._toolkit is not None

    def _tk(self) -> WebBrowsingToolkit:
        if self._toolkit is None:
            self._toolkit = WebBrowsingToolkit(
                catalog_dir=self._catalog_dir, credential_resolver=self._resolver, confirm_runs=False, **self._tk_kwargs
            )
        return self._toolkit

    async def recover_session(self, cookie_names: Sequence[str] = ("sid",), *,
                              api_url: str = "https://api.hooba.com") -> Dict[str, str]:
        """Log in through the catalog and return the requested cookies from the browser context (fail closed → {})."""
        # FILL IN: result = await self._tk().run_site_action(self.site, self.login_action); failed → {};
        #          driver = await self._tk()._ensure_session_driver(); cookies = await driver.get_cookies([api_url, self.base_url])
        #          (NotImplementedError → {}); keep names in cookie_names; "sid" absent → {} — bounded by AC-13, S8
        raise NotImplementedError

    async def run_navigation(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run a catalogued action only when its kind is ``navigation``."""
        # FILL IN: see Implementation Notes — bounded by AC-13
        raise NotImplementedError

    async def close(self) -> None:
        """Close the browser if it was started."""
        if self._toolkit is not None:
            await self._toolkit.close_browser()


async def seed_catalog(catalog_dir: Union[str, Path], *, base_url: str = "https://app.hooba.com",
                       sections: Optional[Dict[str, Tuple[str, str, str]]] = None,
                       username_selector: str = 'input[type="email"]', password_selector: str = 'input[type="password"]',
                       submit_selector: str = 'button[type="submit"]') -> str:
    """Write ``hooba-login`` + one navigation action per section into ``catalog_dir`` (outside the repo).

    Returns:
        The registered site slug.
    """
    # FILL IN: tk = WebBrowsingToolkit(catalog_dir=catalog_dir); await tk.register_site(base_url, name="hooba",
    #          title="Hooba", aliases=["hooba", "app.hooba.com"]); save the login action (navigate to
    #          f"{base_url}/es/login?returnUrl=%2Fdashboard", authenticate form with the three selectors and
    #          credential_provider="hooba", wait url_contains "/dashboard"); then one navigation action per section
    #          (navigate + wait url_contains path, requires=["hooba-login"]); overwrite=True — bounded by AC-17 (no secrets)
    raise NotImplementedError
```

### `packages/ai-parrot-tools/tests/hooba/test_web.py` (CREATE)
```python
"""FEAT-602 TASK-3738 — web adapter and catalog seeding (no real browser)."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.hooba.web import HoobaWebAdapter, seed_catalog


async def _resolver(action):
    return None


def test_adapter_is_lazy(tmp_path):
    # FILL IN: constructing the adapter does not build WebBrowsingToolkit (started is False)


async def test_recover_session_returns_sid(tmp_path):
    # FILL IN: inject a fake toolkit (adapter._toolkit = MagicMock) whose run_site_action succeeds and whose
    #          _ensure_session_driver returns a driver with get_cookies → [{"name": "sid", "value": "v", "httpOnly": True}]


async def test_recover_session_fails_closed(tmp_path):
    # FILL IN: login failure / NotImplementedError / no sid → {}


async def test_run_navigation_refuses_non_navigation(tmp_path):
    # FILL IN


async def test_seed_catalog_writes_login_and_sections_without_secrets(tmp_path, monkeypatch):
    # FILL IN: monkeypatch HOOBA_USERNAME/PASSWORD to sentinel values; seed; every JSON file lacks them;
    #          login JSON has credential_provider "hooba"; navigation actions require hooba-login
```

### FILL IN checklist
- [ ] `recover_session`, `run_navigation`, `seed_catalog`
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-13 (spec, adapter half): no browser unless a web method is called; `recover_session` uses `driver.get_cookies` and returns `{}` on any failure or missing `sid`; `run_navigation` refuses non-navigation actions.
- [ ] AC-17 (spec): `seed_catalog` writes no credentials; no Hooba catalog JSON is committed.
- [ ] `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_web.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_adapter_is_lazy` | AC-13 laziness |
| `test_recover_session_returns_sid` | context-cookie path |
| `test_recover_session_fails_closed` | S8 |
| `test_run_navigation_refuses_non_navigation` | navigation-only |
| `test_seed_catalog_writes_login_and_sections_without_secrets` | AC-17 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2, §3 module, §6, §7).
2. **Check dependencies** — verify every `Depends-on` task is done in `sdd/tasks/index/hooba-toolkit.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every anchor in the blueprint still has the stated occurrence count (`grep -c`)
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/hooba-toolkit.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria and run every Validation Command.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note


- Task: TASK-3738
- Feature: hooba-toolkit
- Implementation SHA: 86bd07185cfafa8f19666145e0463c6da44eccb9
- Closed at (UTC): 2026-09-25T18:16:40+00:00
- Fix commits: 065273f70b8e35801d11318b0a291012efb66729

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| merge_tier_engine_outcome | failed (workspace-wide import-impact sweep; 105 pre-existing unrelated failures across other distributions, same as chunk0/chunk1) |
| orchestrator_targeted_verification | Found and fixed a test-only defect (fragile substring match on pretty-printed JSON; implementation was correct). Post-fix: packages/ai-parrot-tools/tests/hooba/ 25/25 passed (excluding TASK-3739's not-yet-merged tests at the time), later 30/30 with the full suite. ruff/black clean. |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 190.1s · Tokens: n/a |
| verification_method | Ran pytest directly (PYTHONPATH override) with the two compiled Cython extensions temporarily copied in from the main checkout since worktrees have no compiled .so; removed afterward (never committed). Note: the parrot-sdd-coder MCP server's execution state was lost mid-wave (server restart); this validation log was recovered from durable disk storage by content hash. |
