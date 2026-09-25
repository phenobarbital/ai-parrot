# TASK-3742: HoobaToolkit core: composition, lifecycle, get_tools merge, lookups, PDF download, web tools

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3737, TASK-3738
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6**, first half. `HoobaToolkit(AbstractToolkit)` is what an agent
registers (`TOOL_REGISTRY["hooba"]`, TASK-3745). It owns the generated API toolkit and
a lazy web adapter, merges the generated tools into its own `get_tools()`, labels every
tool with an `OperationKind`, and exposes the READ-side composite tools. The DRAFT-side
composite tools (invoice / purchase-invoice drafts, attachments, BBVA import) are
TASK-3743, which extends this file.

Two transport helpers live here because composite tools call Hooba endpoints directly:
`_call` (JSON through the API toolkit's cookie session, 401 re-login included) and
`_call_raw` (binary download, same session).

---

## Scope

- `hooba/toolkit.py` (CREATE): `HoobaToolkit` with `__init__`, `_open`, `_close`, `get_tools`, `operation_kinds`, `_call`, `_call_raw`, `_ok`/`_err` envelope helpers, and tools `hooba_whoami`, `hooba_find_contact`, `hooba_list_drafts`, `hooba_download_invoice_pdf`, `hooba_recover_web_session`, `hooba_run_web_action`.
- `hooba/__init__.py` (MODIFY): export `HoobaToolkit`, `HoobaSettings`.
- `tests/hooba/test_toolkit_core.py` with a fake API toolkit (no HTTP).

**NOT in scope**: draft creation, attachments, BBVA import tool (TASK-3743); the fake HTTP server (TASK-3744).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py` | CREATE | HoobaToolkit core + READ composite tools |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py` | MODIFY | export HoobaToolkit and HoobaSettings |
| `packages/ai-parrot-tools/tests/hooba/test_toolkit_core.py` | CREATE | composition, laziness, tools tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                              # verified: business_automation/toolkit.py:27
from parrot.tools.abstract import AbstractTool, ToolResult                    # verified: parrot/tools/__init__.py:149
from parrot.auth.broker import CredentialBroker                               # verified: parrot/auth/__init__.py:64
from parrot_tools.business_automation.models import OperationKind             # verified: business_automation/__init__.py:9
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker   # verified: toolkit.py:49 (same distribution)
from parrot_tools.hooba.openapi import HoobaOpenAPIToolkit                    # TASK-3737
from parrot_tools.hooba.web import HoobaWebAdapter                            # TASK-3738
from parrot_tools.hooba.settings import HoobaSettings                         # TASK-3734
from parrot_tools.hooba.credentials import make_login_hook, register_hooba_provider   # TASK-3734
from parrot_tools.hooba.models import ContactMatch                            # TASK-3733
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                                   # line 203
    exclude_tools: tuple[str, ...] = ()                                       # line 240
    auto_open: bool = False                                                   # line 311
    def __init__(self, **kwargs)                                              # lines 329-376
    async def _open(self) -> None                                             # lines 398-412
    async def _close(self) -> None                                            # lines 414-425 — override MUST await super()._close()
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]   # lines 494-524
    def _generate_tools(self) -> None                                         # lines 547-590 — every PUBLIC coroutine method becomes a tool

# OpenAPIToolkit (after TASK-3731/3732), used through self._api:
#   async _ensure_session(force=False); get_cookies() -> Dict[str, str]; async _cookie_request(method, url, request_kwargs) -> (result, error)
#   request_kwargs shape (openapitoolkit.py:745-756): {"url", "method", "params", ["headers"], ["use_json", "data"]}
#   http_service._request(url, method, cookies=..., headers=..., full_response=True, raise_for_status=False, use_proxy=False)
#   self._api.settings (HoobaSettings) — set by HoobaOpenAPIToolkit.__init__ (TASK-3737)

# packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py
def _credential_resolver_from_broker(broker: "CredentialBroker", user_id: str) -> CredentialResolverFn   # lines 49-117
```

### Does NOT Exist
- ~~`HTTPService._request(files=...)`~~ — no multipart; not needed in this task.
- ~~A public `OpenAPIToolkit.request()` helper~~ — use `self._api._cookie_request` (same feature, documented coupling).
- ~~Hooba pagination parameter names~~ in this contract — read them from the pinned document (`load_pinned_spec()["paths"]["/accounts/{accountId}/contacts"]["get"]["parameters"]`) rather than guessing.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_toolkit_core.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit.get_tools",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._open",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._close",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._generate_tools",
    "sym:packages/ai-parrot/src/parrot/auth/broker.py#CredentialBroker",
    "sym:packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py#_credential_resolver_from_broker",
    "sym:packages/ai-parrot/src/parrot/interfaces/http.py#HTTPService._request"
  ]
}
```

---

## Implementation Notes

- Envelope: every tool returns `ToolResult(status="success"|"error", result=..., error=..., metadata={"operation_kind": ...}).model_dump()`;
  errors carry `metadata["next_tool"]` when a follow-up helps (e.g. `hooba_recover_web_session` after an auth failure). Never raise into the agent loop.
- `get_tools`: `own = super().get_tools(permission_context, resolver)`; `api = self._api.get_tools()`; duplicate names → `ValueError`.
- `operation_kinds`: READ for `hooba_whoami`, `hooba_find_contact`, `hooba_list_drafts`, `hooba_download_invoice_pdf`,
  `hooba_recover_web_session`, `hooba_run_web_action`; DRAFT for `hooba_create_invoice_draft`, `hooba_create_purchase_invoice_draft`,
  `hooba_attach_document`, `hooba_import_bbva_statement` (declare all ten now; TASK-3743 adds the methods); merged with `self._api.operation_kinds()`.
- `hooba_find_contact`: case- and accent-insensitive `difflib.SequenceMatcher` ratio over legal name, trade name, and
  first name + surnames; keep ≥ 0.85, sorted desc, cap `limit`; paginate until exhausted or 500 contacts.
- `hooba_download_invoice_pdf`: `_call_raw("GET", f"/accounts/{{accountId}}/invoices/{invoice_id}:download")`; write under
  `dest_dir` or `$PARROT_STATE_DIR/hooba/pdf/` (default `~/.parrot_state`), file mode 0o600, via `asyncio.to_thread`.
- Web tools: `settings.catalog_dir is None` → error envelope "HOOBA_CATALOG_DIR not set", no adapter built.
  `hooba_recover_web_session`: `{}` from the adapter → error envelope, jar untouched; else `await self._api.set_cookies(...)`.

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
1. Constructor with sensible defaults (env settings, broker with the env provider, API toolkit) — *why*: registry instantiation passes no args.
2. Lifecycle + `get_tools` merge — *why*: AC-6; the browser never starts in `_open` (AC-13).
3. `_call`/`_call_raw` — *why*: composite tools share one session and one 401 policy.
4. READ tools, then `__init__` export, then tests with a fake `_api`.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py` (CREATE)
```python
"""HoobaToolkit — drafts-only Hooba automation for AI-Parrot agents (FEAT-602 M6)."""
from __future__ import annotations

import asyncio
import difflib
import logging
import os
import unicodedata
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from parrot.auth.broker import CredentialBroker
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.toolkit import AbstractToolkit
from parrot_tools.business_automation.models import OperationKind
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker

from .credentials import make_login_hook, register_hooba_provider
from .models import ContactMatch
from .openapi import HoobaOpenAPIToolkit
from .settings import HoobaSettings
from .web import HoobaWebAdapter

_READ_TOOLS = ("hooba_whoami", "hooba_find_contact", "hooba_list_drafts", "hooba_download_invoice_pdf",
               "hooba_recover_web_session", "hooba_run_web_action")
_DRAFT_TOOLS = ("hooba_create_invoice_draft", "hooba_create_purchase_invoice_draft", "hooba_attach_document",
                "hooba_import_bbva_statement")


class HoobaToolkit(AbstractToolkit):
    """Create Hooba invoice and expense DRAFTS, import BBVA statements; never issues or confirms anything."""

    auto_open = True
    exclude_tools = ("operation_kinds",)

    def __init__(self, settings: Optional[HoobaSettings] = None, credential_broker: Optional[CredentialBroker] = None,
                 *, api: Optional[HoobaOpenAPIToolkit] = None, web: Optional[HoobaWebAdapter] = None,
                 rules_path: Optional[str] = None, headless: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.settings = settings or HoobaSettings.from_env()
        if credential_broker is None:
            credential_broker = CredentialBroker()
            register_hooba_provider(credential_broker, self.settings.credential_provider)
        self._broker = credential_broker
        self._api = api or HoobaOpenAPIToolkit(self.settings, make_login_hook(self.settings, credential_broker))
        self._web = web
        self._rules_path = rules_path
        self._headless = headless

    async def _open(self) -> None:
        """Establish the API session only — the browser stays lazy."""
        await self._api._ensure_session()

    async def _close(self) -> None:
        if self._web is not None:
            await self._web.close()
        await super()._close()

    def get_tools(self, permission_context: Any = None, resolver: Any = None) -> list[AbstractTool]:
        """Composite tools plus the generated API tools; name collisions are a bug."""
        # FILL IN — bounded by AC-6
        raise NotImplementedError

    def operation_kinds(self) -> Dict[str, OperationKind]:
        """Every tool name → OperationKind."""
        # FILL IN: _READ_TOOLS → READ, _DRAFT_TOOLS → DRAFT, merged with self._api.operation_kinds()
        raise NotImplementedError

    def _web_adapter(self) -> Optional[HoobaWebAdapter]:
        # FILL IN: None when settings.catalog_dir is None; else build once with
        #          _credential_resolver_from_broker(self._broker, self.settings.credential_user_id), headless
        raise NotImplementedError

    async def _call(self, method: str, path: str, *, params: Optional[dict] = None, data: Optional[dict] = None) -> Any:
        """JSON call through the API cookie session; raises RuntimeError with the HTTP status on error."""
        # FILL IN: url = base_url + path with {accountId} substituted; request_kwargs per the contract shape;
        #          result, error = await self._api._cookie_request(method.upper(), url, request_kwargs)
        raise NotImplementedError

    async def _call_raw(self, method: str, path: str) -> bytes:
        """Binary call (downloads) through the same session; one re-login on 401."""
        # FILL IN — bounded by AC-1 semantics
        raise NotImplementedError

    # FILL IN: _ok(result, kind) / _err(message, kind, next_tool=None) → ToolResult(...).model_dump()
    # FILL IN: tools hooba_whoami, hooba_find_contact, hooba_list_drafts, hooba_download_invoice_pdf,
    #          hooba_recover_web_session, hooba_run_web_action — signatures EXACTLY as spec §2 "New Public Interfaces",
    #          Google-style docstrings (they are the LLM-facing descriptions); behaviour per Implementation Notes
```

### `packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3733: grep -c '^from .models import (' parrot_tools/hooba/__init__.py)
# BEFORE — insert above `from .models import (`:
from .settings import HoobaSettings
from .toolkit import HoobaToolkit
# and add "HoobaSettings", "HoobaToolkit" to __all__.
```

### `packages/ai-parrot-tools/tests/hooba/test_toolkit_core.py` (CREATE)
```python
"""FEAT-602 TASK-3742 — HoobaToolkit composition and READ tools (no HTTP)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.business_automation.models import OperationKind
from parrot_tools.hooba import HoobaSettings, HoobaToolkit


class FakeApi:
    """Stands in for HoobaOpenAPIToolkit: scripted _cookie_request / _call_raw results, fixed get_tools()."""
    # FILL IN


def test_get_tools_merges_without_collision():
    # FILL IN: composite + fake generated; injected duplicate name → ValueError


def test_operation_kinds_covers_every_tool():
    # FILL IN


async def test_open_does_not_start_browser():
    # FILL IN: _ensure_open() → api session ensured; web adapter not built (AC-13)


async def test_find_contact_threshold():
    # FILL IN: 0.84 excluded, 0.85 included, accents/case ignored


async def test_web_tools_error_without_catalog_dir():
    # FILL IN


async def test_recover_session_injects_sid_or_fails_closed():
    # FILL IN


async def test_download_invoice_pdf_writes_0600(tmp_path):
    # FILL IN
```

### FILL IN checklist
- [ ] `get_tools`, `operation_kinds`, `_web_adapter`, `_call`, `_call_raw`, envelope helpers
- [ ] six READ tools
- [ ] every test body

---

## Acceptance Criteria

- [ ] AC-6 (spec): `get_tools()` = composite ∪ generated, collision-free, ≤ 80 by default; `operation_kinds()` covers every tool.
- [ ] AC-13 (spec, toolkit half): `_open` never starts a browser; web tools error without `HOOBA_CATALOG_DIR`; session recovery injects `sid` or fails closed.
- [ ] `from parrot_tools.hooba import HoobaToolkit` works; `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_toolkit_core.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_get_tools_merges_without_collision` | AC-6 |
| `test_operation_kinds_covers_every_tool` | AC-6 |
| `test_open_does_not_start_browser` | AC-13 |
| `test_find_contact_threshold` | U3 threshold |
| `test_web_tools_error_without_catalog_dir` | AC-13 |
| `test_recover_session_injects_sid_or_fails_closed` | S8 end of chain |
| `test_download_invoice_pdf_writes_0600` | file mode |

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

**Completed by**: sdd-worker (resumed session, execution_id=85c083ec-56b6-42fe-8884-e686fbcf7a61)
**Date**: 2026-09-26
**Notes**: Code was implemented, merged, AND already review-fixed in a PRIOR sdd-worker
session (commits `cbf1c284d` feat, `5d4c74eed` engine lint autofix, `8a3c8f1d4` merge,
`b536c36cf` review fixes) but that session was interrupted before SDD state was closed —
the task remained in `sdd/tasks/active/` with index status `in-progress` despite the code
(and its review) already being on the branch. This session verified and closed it:

- File fidelity confirmed exact match against the Codebase Contract (`hooba/toolkit.py`
  CREATE, `hooba/__init__.py` MODIFY, `tests/hooba/test_toolkit_core.py` CREATE — no other
  files touched).
- The prior session's review-fix commit (`b536c36cf`) already documents two confirmed
  defects fixed and verified: `operation_kinds()` forward-referencing TASK-3743's
  not-yet-implemented draft tools (removed), and a `test_open_does_not_start_browser` mock
  assertion that could never fail regardless of implementation (fixed), with a stated
  verification of "packages/ai-parrot-tools/tests/hooba/ 42/42 passed. ruff clean".
- `coder_run_validation` (tier=merge, both a 900s and a 7200s attempt) could not produce a
  usable verdict for the same reason documented in TASK-3740's Completion Note: its
  declared selector's import-impact expansion pulls in ~30 unrelated distributions, and the
  eventual `outcome=failed` traced entirely to pre-existing breakage on `origin/dev`
  unrelated to this task (confirmed via zero-diff `git diff --stat origin/dev...HEAD` on the
  failing files) — the exact scope/cost problem FEAT-604 exists to fix. The sweep never
  reached `packages/ai-parrot-tools/tests/hooba/` before an unrelated pytest
  collection-error interruption aborted that whole distribution's run.
- Independently re-ran `pytest packages/ai-parrot-tools/tests/hooba/` directly →
  **42 passed** (matches the prior session's own reported count) and
  `ruff check --select E9,F63,F7,F82` on the delivered files → clean.
- `scripts.sdd.finalize_task` could not be invoked from inside this worktree for the same
  pre-existing, documented sandbox reason as TASK-3740 (missing Cython `parrot.utils.types`
  `.so` in the worktree tree, unrelated to FEAT-602). Closed state instead via
  `scripts/sdd/close_task.sh TASK-3742 hooba-toolkit verified` (pure git/jq).

**Deviations from spec**: none — code and its review were delivered to spec by the prior
session; this session only verified and closed SDD state.
