# TASK-3737: HoobaOpenAPIToolkit: bound cookie-auth toolkit with default-deny operation policy and OperationKind routing_meta

**Feature**: FEAT-602 — HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts
**Spec**: `sdd/specs/hooba-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3732, TASK-3734, TASK-3735
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 4**, design research S2 and S3. The generated half of the toolkit:
a bound `OpenAPIToolkit` subclass over the pinned spec with cookie auth, Hooba's
default headers, `path_defaults={"accountId": settings.account_id}`, and a
**default-deny** operation policy — every GET in the allowed tags (minus binary
downloads/exports), plus exactly the eleven writes in `DRAFT_OPERATIONS`. Nothing else
is generated: not master-data creation, not uploads, not any legal-effect action.
Every generated tool carries `routing_meta["operation_kind"]` so the D2 vocabulary is
visible to `ToolManager` (S3). On the pinned 2026.6.17 document this is 47 READ + 11
DRAFT = **58 tools**.

---

## Scope

- `hooba/openapi.py`: `DEFAULT_INCLUDE_TAGS`, `READ_PATH_BLOCKLIST`, `DRAFT_OPERATIONS`, `LEGAL_EFFECT_PATTERNS`, `MAX_TOOLS = 80`, `is_allowed`, `classify_operation`, `HoobaOpenAPIToolkit` (ctor, `_create_tool_from_method` override, `operation_kinds`).
- `tests/hooba/test_hooba_openapi.py` against the pinned document (no network: `login_hook` is a stub).

**NOT in scope**: composite tools (TASK-3742/3743); any HTTP request in tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/hooba/openapi.py` | CREATE | policy constants, classifier, HoobaOpenAPIToolkit |
| `packages/ai-parrot-tools/tests/hooba/test_hooba_openapi.py` | CREATE | surface size, default-deny, routing_meta tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (re-verified 2026-09-25 against `dev` at `ad42d9aff`).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot.tools.openapitoolkit import OpenAPIToolkit                        # verified: openapi_register.py:15
from parrot.tools.toolkit import ToolkitTool                                  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:150 (defined toolkit.py:37)
from parrot_tools.business_automation.models import OperationKind             # verified: business_automation/__init__.py:9
from parrot_tools.hooba.settings import HoobaSettings                         # created by TASK-3734
from parrot_tools.hooba.credentials import HoobaLoginHook                     # created by TASK-3734
from parrot_tools.hooba.spec import load_pinned_spec                          # created by TASK-3735
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/openapitoolkit.py (after TASK-3731/3732)
class OpenAPIToolkit(AbstractToolkit):                                        # line 45
    def __init__(self, spec, service, base_url=None, ..., debug=False, *, path_defaults=None, include_tags=None,
                 exclude_paths=None, exclude_methods=None, operation_filter=None, max_tools=None,
                 login_hook=None, extra_headers=None, **kwargs)
    def _create_method_name(self, operation) -> str                           # f"{service}_{method}_{normalized_path}" (lines 672-693)
    # generated function attrs: operation_method._operation = operation        # line 808
    #                           operation_method.__name__ = <method name>      # line 805

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    def _create_tool_from_method(self, name: str, bound_method: callable) -> ToolkitTool   # lines 647-701
    #   builds ToolkitTool(...); applies routing_meta['requires_confirmation'] for confirming_tools (lines 693-698)
# packages/ai-parrot/src/parrot/tools/abstract.py
    self.routing_meta: Dict = routing_meta if routing_meta is not None else {}   # line 382 — always a dict on instances

# packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py
class OperationKind(str, Enum): READ = "read"; DRAFT = "draft"; SUBMIT = "submit"   # lines 20-30
```

### Does NOT Exist
- ~~`routing_meta["operation_kind"]`~~ — introduced here; `ToolManager` currently reads only `requires_grant` / `requires_confirmation`.
- ~~`SUBMIT_PATH_BLOCKLIST`~~ / ~~`EXCLUDED_METHODS`~~ — superseded in the spec by `DRAFT_OPERATIONS` + `is_allowed` (S2). Do not reintroduce a regex blocklist as the write policy.
- ~~`POST /accounts/{accountId}/documents/...` as a generated tool~~ — multipart; composite tool only (TASK-3743).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/hooba/openapi.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/hooba/test_hooba_openapi.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/openapitoolkit.py#OpenAPIToolkit._create_operation_method",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._create_tool_from_method",
    "sym:packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py#OperationKind"
  ]
}
```

---

## Implementation Notes

- `is_allowed(method, path)` is passed as `operation_filter`; `include_tags` still scopes the GET surface (the filter runs after it).
  Non-GET: allowed iff `(method, path) in DRAFT_OPERATIONS`. GET: allowed unless `READ_PATH_BLOCKLIST` matches.
- `classify_operation`: GET/HEAD → READ; in DRAFT_OPERATIONS → DRAFT; anything else → SUBMIT (default-deny labelling).
- `_create_tool_from_method` override: `tool = super()._create_tool_from_method(name, bound_method)`; if the bound method has
  `_operation`, set `tool.routing_meta["operation_kind"] = kind.value`; if SUBMIT also set `requires_confirmation = True`.
  Methods without `_operation` (none today) are left untouched.
- If the pinned document yields a count other than 47 READ + 11 DRAFT, do NOT tune the constants to hit 58 — report the actual numbers
  in the Completion Note and assert the real ones (the spec number came from the research digest).

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
1. Write the policy constants and the two pure functions — *why*: S2 default-deny must be testable without HTTP.
2. Write `HoobaOpenAPIToolkit` — *why*: bakes every Hooba-specific argument so callers pass only settings + hook.
3. Override `_create_tool_from_method` — *why*: S3, OperationKind visible on every generated tool.
4. Tests on the pinned document.

### `packages/ai-parrot-tools/src/parrot_tools/hooba/openapi.py` (CREATE)
```python
"""Generated Hooba API tools: cookie-authenticated, account-scoped, drafts only (FEAT-602 M4)."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Sequence

from parrot.tools.openapitoolkit import OpenAPIToolkit
from parrot.tools.toolkit import ToolkitTool
from parrot_tools.business_automation.models import OperationKind

from .credentials import HoobaLoginHook
from .settings import HoobaSettings
from .spec import load_pinned_spec

DEFAULT_INCLUDE_TAGS: tuple[str, ...] = (
    "Invoice", "InvoiceLine", "InvoiceSerie", "PurchaseInvoice", "PurchaseInvoiceLine", "Contact", "Tax",
    "IncomeTax", "AccountingAccount", "PaymentMethod", "PaymentTerm", "Currency", "Document", "DocumentType",
    "InboxFile", "UnitOfMeasure",
)
READ_PATH_BLOCKLIST: tuple[str, ...] = (r":download", r":export", r":pdf-", r"/avatar$")
DRAFT_OPERATIONS: frozenset[tuple[str, str]] = frozenset({
    ("POST", "/accounts/{accountId}/invoices"),
    ("PATCH", "/accounts/{accountId}/invoices/{invoiceId}"),
    ("POST", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines"),
    ("PATCH", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines/{invoiceLineId}"),
    ("POST", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines:sort"),
    ("POST", "/accounts/{accountId}/purchase-invoices"),
    ("PATCH", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}"),
    ("POST", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines"),
    ("PATCH", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines/{purchaseInvoiceLineId}"),
    ("POST", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines:sort"),
    ("POST", "/accounts/{accountId}/purchase-invoices:create-from-inbox-file"),
})
LEGAL_EFFECT_PATTERNS: tuple[str, ...] = (
    r":issue$", r":confirm$", r":cancel$", r":send", r":delete$", r":bulk-", r":schedule$", r":unschedule$",
    r":create-corrective$", r":collect$",
)
MAX_TOOLS = 80
_READ_BLOCK = [re.compile(p) for p in READ_PATH_BLOCKLIST]


def is_allowed(method: str, path: str) -> bool:
    """Default-deny policy passed to ``OpenAPIToolkit(operation_filter=...)``."""
    # FILL IN: GET/HEAD → not any(_READ_BLOCK .search(path)); other methods → (method, path) in DRAFT_OPERATIONS
    raise NotImplementedError


def classify_operation(method: str, path: str) -> OperationKind:
    """GET/HEAD → READ; DRAFT_OPERATIONS → DRAFT; anything else → SUBMIT."""
    # FILL IN — bounded by AC-5
    raise NotImplementedError


class HoobaOpenAPIToolkit(OpenAPIToolkit):
    """Generated Hooba API tools, cookie-authenticated, account-scoped, drafts only."""

    def __init__(self, settings: HoobaSettings, login_hook: HoobaLoginHook, *,
                 spec: Optional[Dict[str, Any]] = None, include_tags: Optional[Sequence[str]] = None,
                 max_tools: int = MAX_TOOLS, **kwargs: Any) -> None:
        self.settings = settings
        super().__init__(
            spec=spec or load_pinned_spec(settings.spec_path),
            service="hooba",
            base_url=settings.base_url,
            auth_type="cookie",
            login_hook=login_hook,
            extra_headers=settings.default_headers(),
            path_defaults={"accountId": settings.account_id},
            include_tags=include_tags or settings.include_tags or DEFAULT_INCLUDE_TAGS,
            exclude_methods=("DELETE", "PUT"),
            exclude_paths=READ_PATH_BLOCKLIST,
            operation_filter=is_allowed,
            max_tools=max_tools,
            **kwargs,
        )

    def _create_tool_from_method(self, name: str, bound_method: Any) -> ToolkitTool:
        """Stamp ``routing_meta['operation_kind']`` (and confirmation for SUBMIT) on generated tools."""
        tool = super()._create_tool_from_method(name, bound_method)
        # FILL IN: op = getattr(bound_method, "_operation", None); if op: kind = classify_operation(op["method"], op["path"]);
        #          tool.routing_meta["operation_kind"] = kind.value; SUBMIT → tool.routing_meta["requires_confirmation"] = True
        return tool

    def operation_kinds(self) -> Dict[str, OperationKind]:
        """Map every generated tool name to its OperationKind."""
        # FILL IN: {self._create_method_name(op): classify_operation(op["method"], op["path"]) for op in self.operations}
        raise NotImplementedError
```
**Why this shape**: the write set is a constant, not a parameter, so no agent configuration can widen it (spec §7).
`exclude_paths=READ_PATH_BLOCKLIST` is belt-and-braces with `is_allowed`: both must pass.

### `packages/ai-parrot-tools/tests/hooba/test_hooba_openapi.py` (CREATE)
```python
"""FEAT-602 TASK-3737 — generated Hooba tool surface."""
import pytest

from parrot_tools.business_automation.models import OperationKind
from parrot_tools.hooba.openapi import DRAFT_OPERATIONS, HoobaOpenAPIToolkit, classify_operation, is_allowed
from parrot_tools.hooba.settings import HoobaSettings
from parrot_tools.hooba.spec import load_pinned_spec


async def _no_login(http):  # never called: no request is made in these tests
    raise AssertionError("login must not run during generation")


@pytest.fixture
def toolkit():
    return HoobaOpenAPIToolkit(HoobaSettings(account_id=23549), _no_login)


def test_default_surface_size_and_no_submit(toolkit):
    # FILL IN: len(toolkit.get_tools()) == 58 (see Implementation Notes); no SUBMIT in operation_kinds()


def test_default_deny_writes(toolkit):
    # FILL IN: for every non-GET op in load_pinned_spec() not in DRAFT_OPERATIONS → absent from tool names and
    #          classify_operation == SUBMIT; spot-check POST contacts, POST invoice-series, :set-default, :schedule,
    #          :duplicate, :issue, :confirm (S2)


def test_generated_tools_carry_operation_kind_routing_meta(toolkit):
    # FILL IN: every tool.routing_meta["operation_kind"] in {"read", "draft"}; no requires_confirmation (S3)


def test_account_id_hidden_from_schemas(toolkit):
    # FILL IN


def test_generated_tool_names_match_openapitoolkit_convention(toolkit):
    # FILL IN: compute expected names with toolkit._create_method_name, never hard-code


def test_is_allowed_and_classify_unit():
    # FILL IN
```

### FILL IN checklist
- [ ] `is_allowed`, `classify_operation`, `_create_tool_from_method` stamp, `operation_kinds`
- [ ] every test body (use the real count from the pinned document)

---

## Acceptance Criteria

- [ ] AC-5 (spec): exactly the pinned document's GET operations in the allowed tags (minus downloads/exports) plus the 11 `DRAFT_OPERATIONS` are generated (58 on 2026.6.17); every tool carries `routing_meta['operation_kind']` ∈ {read, draft}; no other write is reachable.
- [ ] `accountId` never appears in a generated schema.
- [ ] No network during tests; `ruff check` and `black --check` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. In a worktree, prefix with the
> `PYTHONPATH=` shown in Key Constraints.

- `pytest packages/ai-parrot-tools/tests/hooba/test_hooba_openapi.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_default_surface_size_and_no_submit` | AC-5 size and kinds |
| `test_default_deny_writes` | S2 |
| `test_generated_tools_carry_operation_kind_routing_meta` | S3 |
| `test_account_id_hidden_from_schemas` | AC-2 end to end |
| `test_generated_tool_names_match_openapitoolkit_convention` | naming |
| `test_is_allowed_and_classify_unit` | pure functions |

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
