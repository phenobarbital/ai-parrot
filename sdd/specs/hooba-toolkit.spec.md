---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-tools, ai-parrot, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [hooba, openapi, toolkit, browser-automation, playwright, finance, spain-autonomos, bbva]
research_state: sdd/state/FEAT-602/
---

# Feature Specification: HoobaToolkit — OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts

**Feature ID**: FEAT-602
**Date**: 2026-09-25
**Author**: Jesús Lara (proposal: `/sdd-proposal`, research state `sdd/state/FEAT-602/`)
**Status**: draft
**Target version**: next minor of `ai-parrot-tools` (core `ai-parrot` bumps with it — Module 1 is a core change)
**Proposal**: `sdd/proposals/hooba-toolkit.proposal.md` (accepted 2026-09-25; U1–U5 resolved in Q&A)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Hooba (https://app.hooba.com) is the bookkeeping software imposed by a Red.es
grant agreement. Today the only automation the repo has for it is an
**untracked**, navigation-only Playwright catalog (login plus five page
visits, zero data entry), and every earlier document assumed Hooba had no API
at all. Research for FEAT-602 found the opposite: Hooba publishes a real
OpenAPI 3.0 document at `https://api.hooba.com/api/doc.json` (version
`2026.6.17`, 656 paths, 970 operations), and creating an invoice or a purchase
invoice through it yields `state=draft`, with issuing (`:issue`) and confirming
(`:confirm`) as separate calls. The three capabilities the user needs — draft
sales invoices, draft expenses/purchases, and turning a BBVA bank export into
expense drafts under Spanish autónomo rules — are therefore API-first; the
browser is a fallback for session recovery and gaps, not the data-entry path.

What blocks this today:

- `OpenAPIToolkit` only knows bearer / apikey / basic auth. Hooba's spec
  declares **no** security scheme; auth is a `sid` session cookie set by
  `POST /auth/login`, plus undeclared headers (`origin`, `x-hooba-language`,
  `ngsw-bypass`). The toolkit cannot log in, cannot carry a cookie across
  calls (the shared `HTTPService._request` opens a fresh client per call), and
  exposes every path parameter — including `{accountId}` — to the LLM.
- 970 operations would flood the tool budget; nothing filters by tag or
  blocks legal-effect operations.
- No BBVA layout parser and no AEAT deductibility rule table exist anywhere in
  the code (Spec A, FEAT-478, defined them but was never decomposed).

### Goals

- G1. **Cookie-session mode in core `OpenAPIToolkit`** (`auth_type="cookie"`):
  lazy login hook, per-request cookie jar, explicit extra headers, re-login
  once on 401, `path_defaults` that hide `{accountId}`-style parameters from
  the LLM, and `include_tags` / `exclude_paths` / `exclude_methods` /
  `max_tools` filters. Backward compatible: existing bearer/apikey/basic
  behaviour and tests unchanged.
- G2. **`parrot_tools.hooba`** — a new `ai-parrot-tools` subpackage with a
  bound `HoobaOpenAPIToolkit` over a **pinned, pruned** copy of the Hooba spec,
  a `HoobaToolkit(AbstractToolkit)` that composes the generated API tools with
  typed composite draft tools, and broker-backed credentials
  (`HOOBA_USERNAME` / `HOOBA_PASSWORD` through `CredentialBroker` provider
  `hooba`).
- G3. **Drafts only, never legal effect.** Every tool is READ or DRAFT
  (`OperationKind`). `:issue`, `:confirm`, `:cancel`, `:send*`, deletes and
  bulk operations are blocklisted at generation time and a test proves no
  SUBMIT-kind path is reachable (U5).
- G4. **Bounded, default-deny tool surface**: full generation with a tag
  allowlist for reads, an explicit `(method, path)` allowlist for the eleven
  DRAFT writes, and a hard cap, overridable per agent; default surface = 58
  generated tools + ≤ 10 composite tools (design research S2).
- G5. **Private Playwright catalog as fallback** (U1): the package ships the
  web adapter and a seed helper only; real selectors live outside the repo
  and are located through `HOOBA_CATALOG_DIR`. v1 web operations: login /
  session recovery (export the browser `sid` into the API session) and
  navigation-only catalog actions.
- G6. **BBVA Excel → purchase-invoice drafts** (U3): one `simplified=true`
  purchase-invoice draft per debit row, `contactId` only when the merchant
  matches an existing Hooba contact, idempotent by statement digest + row
  index, resumable, reconciled (rows in vs drafts out).
- G7. **v1 autónomo deductibility rule table** (U4): a data-driven YAML under
  `parrot_tools/hooba/rules/`, shaped like Spec A's `AeatRule` /
  `DeductibilityVerdict` so it can later move to `parrot_tools/finance`
  unchanged; every draft carries `legal_basis` and a `review_required` flag.
- G8. Registration in `TOOL_REGISTRY`, a `hooba` optional extra, tests under
  `packages/ai-parrot-tools/tests/hooba/`, docs, and an example agent.

### Non-Goals (explicitly out of scope)

- Issuing invoices (`:issue`), confirming purchase invoices (`:confirm`),
  cancel/delete, sending e-mails, remittances, payments — SUBMIT-kind, never
  in v1 (U5). The classification hook exists so a later spec can enable them
  behind `ConfirmationGuard` without touching v1 code.
- Any change to `parrot/clients/base.py` or LLM clients.
- Changes to `BusinessAutomationToolkit`, `PlanDirectoryStore`,
  `ConfirmationGuard` — consumed as-is. The hooba package does **not** route
  API calls through `BusinessAutomationToolkit.run_operation` (that engine is
  browser-flow bound); it reuses its models, digest and checkpoint helpers.
- Norma 43 ingestion, DuckDB analytics, ExpenseWiki, ML classification — Spec
  A (FEAT-478) scope. FEAT-478 is **not** a prerequisite (U4).
- Hooba master data creation (invoice series, taxes, accounting accounts,
  document types) — read via API, never created. Contacts are matched, never
  created, by the BBVA importer (U3).
- New Playwright data-entry scripts — the API covers the three capabilities.
- Messaging channels (Telegram / WhatsApp / Teams) — the example agent is CLI.
- Committing real Hooba selectors, credentials, bank exports or personal data.
  Fixtures are synthetic/anonymized.
- Making `HTTPService` persist cookies across calls or replacing its httpx
  transport — the cookie jar lives in `OpenAPIToolkit` and is passed per call.

---

## 2. Architectural Design

### Overview

Three layers, top-down:

1. **Core transport change (Module 1).** `OpenAPIToolkit` gains a fourth
   `auth_type`, `"cookie"`. In that mode the toolkit owns a `dict[str, str]`
   cookie jar, calls an async `login_hook(http_service) -> dict[str, str]`
   lazily before the first request (and again, once, after a 401), passes
   `cookies=` and `extra_headers` on every `HTTPService._request(...)` call,
   and uses `full_response=True` so it can read `response.status_code` before
   the shared transport's `process_response()` raises `ConnectionError` on
   4xx. `path_defaults` (e.g. `{"accountId": 23549}`) are substituted in
   `_build_operation_url`, removed from the generated Pydantic schema, and
   **always win** over a caller-supplied value (dropped with a WARNING — S4).
   `include_tags`, `exclude_paths` (regex list), `exclude_methods`, an
   `operation_filter(method, path) -> bool` callable and `max_tools` filter
   `_parse_operations`. Write requests in cookie mode run with
   `num_retries=0` so a transport retry can never duplicate a POST (S11).
   Every existing auth mode, test and generated tool name is unchanged.

2. **`parrot_tools.hooba` (Modules 2–10).** `HoobaSettings` reads the
   `HOOBA_*` environment; `make_login_hook()` performs `POST /auth/login` with
   credentials resolved from a `CredentialBroker` provider `hooba` and returns
   the `sid` cookie; `HoobaOpenAPIToolkit` is a bound `OpenAPIToolkit` subclass
   (pattern: `_build_toolkit_subclass`) over the pinned, pruned spec with the
   default tag allowlist and the SUBMIT blocklist baked in;
   `HoobaToolkit(AbstractToolkit, auto_open=True)` composes those generated
   tools with typed composite tools (`hooba_create_invoice_draft`,
   `hooba_create_purchase_invoice_draft`, `hooba_find_contact`,
   `hooba_attach_document`, `hooba_list_drafts`, `hooba_download_invoice_pdf`,
   `hooba_import_bbva_statement`, `hooba_whoami`, `hooba_recover_web_session`,
   `hooba_run_web_action`) and tags every tool with an `OperationKind`. The
   BBVA half is pure Python: `parse_bbva_statement()` → `RuleEngine.assess()`
   → `BbvaImporter.plan()/apply()` with a permission-hardened manifest.

3. **Web fallback (Module 7).** `HoobaWebAdapter` wraps `WebBrowsingToolkit`
   with `catalog_dir=$HOOBA_CATALOG_DIR`, Playwright, and the broker-backed
   credential resolver. `recover_session()` runs the private `hooba-login`
   action, exports cookies via `exec_get_cookies`, and hands `sid` to the API
   toolkit's jar. The browser starts lazily and only when a web tool is
   called.

Routing policy (fixed): **API when the endpoint exists in the pruned spec;
web only for session recovery and catalogued navigation.** No composite tool
falls back to the browser silently — a failed API call returns an error
`ToolResult` naming the web tool the agent may call next.

### Component Diagram
```
Agent ──→ HoobaToolkit (M6, AbstractToolkit, auto_open)
            │  get_tools() = composite tools ∪ HoobaOpenAPIToolkit.get_tools()
            │
            ├──→ HoobaOpenAPIToolkit (M4) ──→ OpenAPIToolkit[auth_type="cookie"] (M1, core)
            │        pinned spec (M3)             │ login_hook ←── make_login_hook (M2)
            │        include_tags / exclude_paths │ cookies={"sid": …} per _request()
            │        path_defaults={"accountId"}  └──→ HTTPService._request(full_response=True)
            │
            ├──→ BbvaImporter (M10) ──→ parse_bbva_statement (M8) ──→ RuleEngine (M9, YAML)
            │        ImportManifest (M8)                │
            │        DeductibilityVerdict → PurchaseInvoiceDraft (M5) → API (M4)
            │
            └──→ HoobaWebAdapter (M7) ──→ WebBrowsingToolkit[Playwright]
                     catalog_dir=$HOOBA_CATALOG_DIR (private)
                     recover_session(): hooba-login → exec_get_cookies → sid → M4 jar

CredentialBroker[provider "hooba"] (M2 EnvCredentialResolver) ──→ M2 login hook, M7 resolver
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.tools.openapitoolkit.OpenAPIToolkit` | **extends (modified)** | Module 1 adds cookie mode, filters, `path_defaults`, `max_tools` (`openapitoolkit.py:62-174, 366-446, 500-603, 695-810, 812-837`) |
| `parrot.interfaces.http.HTTPService` | uses | `_request(cookies=…, headers=…, full_response=True)` (`http.py:1610-1787`); `process_response()` raises `ConnectionError` on ≥400 (`http.py:522-568`) — that is why cookie mode reads the status first |
| `parrot.bots.factory.tools.openapi_register._build_toolkit_subclass` | pattern | `HoobaOpenAPIToolkit` is written as an explicit subclass following the same bake-in pattern (`openapi_register.py:18-41`) |
| `parrot.tools.toolkit.AbstractToolkit` | extends | `auto_open=True`, `_open/_close`, `get_tools()` override, `exclude_tools` (`toolkit.py:203-590`) |
| `parrot.auth.broker.CredentialBroker` | uses | `register("hooba", EnvCredentialResolver(), auth_kind="static_key")`, `resolve("hooba", "hooba", user_id)` (`broker.py:468-491, 543-639`) |
| `parrot.auth.credentials.CredentialResolver` | implements | `EnvCredentialResolver.resolve()` returns a `{"username","password"}` dict — the shape `_credential_resolver_from_broker` already understands (`credentials.py:162-182`, `business_automation/toolkit.py:49-117`) |
| `parrot_tools.business_automation.toolkit._credential_resolver_from_broker` | uses | adapts the broker into the browser `CredentialResolverFn` for Module 7 |
| `parrot_tools.business_automation.models.OperationKind`, `ImportRun` | uses | tool classification; import discriminator |
| `parrot_tools.business_automation.ingest.compute_statement_digest`, `checkpoint_dir_for` | uses | statement digest and checkpoint root for the BBVA manifest |
| `parrot_tools.browsing.WebBrowsingToolkit` | uses | `run_site_action`, `_ensure_session_driver`, `close_browser` (`browsing/toolkit.py:124-188, 382-418`) |
| `parrot_tools.scraping.session_actions.exec_get_cookies` + `scraping.models.GetCookies` | uses | browser → API cookie bridge (`session_actions.py:288-331`, `models.py:393`) |
| `parrot_loaders.excel.ExcelLoader` | uses | row-count cross-check of the BBVA sheet (same pattern as `ingest._load_expense_rows`) |
| `parrot_tools.__init__.TOOL_REGISTRY` | registers | `"hooba": "parrot_tools.hooba.toolkit.HoobaToolkit"` |

### Data Models
```python
# packages/ai-parrot-tools/src/parrot_tools/hooba/models.py  (new)
from decimal import Decimal
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field

class HoobaSettings(BaseModel):
    base_url: str = "https://api.hooba.com"      # HOOBA_BASE_URL
    account_id: int                               # HOOBA_ACCOUNT_ID (required)
    member_id: Optional[int] = None               # HOOBA_MEMBER_ID
    user_id: Optional[int] = None                 # HOOBA_USER_ID
    subscription_id: Optional[int] = None         # HOOBA_SUBSCRIPTION_ID
    language: str = "es"                          # HOOBA_LANGUAGE → x-hooba-language
    origin: str = "https://app.hooba.com"         # HOOBA_ORIGIN → origin header
    catalog_dir: Optional[str] = None             # HOOBA_CATALOG_DIR (private Playwright catalog)
    spec_path: Optional[str] = None               # HOOBA_SPEC_PATH (override the pinned spec)
    include_tags: Optional[list[str]] = None      # HOOBA_INCLUDE_TAGS (comma list; default allowlist when unset)
    credential_provider: str = "hooba"
    credential_user_id: str = "hooba"

class InvoiceLineDraft(BaseModel):
    name: str
    price: Decimal
    quantity: Decimal = Decimal("1")
    discount: Decimal = Decimal("0")
    tax_code: str = "IVA21"                       # resolved to Hooba taxId via GET /taxes
    income_tax_code: Optional[str] = None         # resolved via GET /income-taxes
    notes: Optional[str] = None

class InvoiceDraft(BaseModel):
    contact_id: Optional[int] = None              # exactly one of contact_id / contact_query
    contact_query: Optional[str] = None
    invoice_serie_code: Optional[str] = None      # default serie when None
    operation_date: Optional[date] = None
    reference: Optional[str] = None
    notes: Optional[str] = None
    simplified: bool = False
    correlation_key: Optional[str] = None         # client idempotency token; uuid4 when None (S11)
    lines: list[InvoiceLineDraft] = Field(min_length=1)

class PurchaseInvoiceLineDraft(BaseModel):
    name: str
    price: Decimal
    quantity: Decimal = Decimal("1")
    tax_code: str = "IVA21"
    income_tax_code: Optional[str] = None
    accounting_account_code: Optional[str] = None
    notes: Optional[str] = None

class PurchaseInvoiceDraft(BaseModel):
    date: date
    number: Optional[str] = None                  # supplier invoice number; None for tickets
    simplified: bool = False                      # True for tickets / bank rows
    contact_id: Optional[int] = None
    contact_query: Optional[str] = None
    tax_included: bool = True
    subject_to_income_tax: bool = False
    notes: Optional[str] = None
    correlation_key: Optional[str] = None         # BBVA importer passes row_id (S11)
    lines: list[PurchaseInvoiceLineDraft] = Field(min_length=1)

class DraftReceipt(BaseModel):
    kind: Literal["invoice", "purchase_invoice"]
    id: int
    state: str                                    # must be "draft" — anything else raises HoobaStateError
    number: Optional[str] = None
    url: Optional[str] = None                     # app deep link when derivable
    line_ids: list[int] = Field(default_factory=list)
    correlation_key: str
    reused: bool = False                          # True when an existing draft with the same key was completed instead of created

class ContactMatch(BaseModel):
    contact_id: int
    legal_name: str
    score: float                                  # difflib ratio, 0..1

class BankExpenseRow(BaseModel):                  # one BBVA debit row
    row_index: int                                # 0-based index within the detected table
    booking_date: date
    value_date: Optional[date] = None
    concept: str
    movement: Optional[str] = None                # BBVA "Movimiento" column
    amount: Decimal                               # negative = debit; only debits become drafts
    currency: str = "EUR"
    balance: Optional[Decimal] = None
    observations: Optional[str] = None
    row_id: str                                   # f"{digest}:{row_index}"

class BbvaStatement(BaseModel):
    path: str
    digest: str                                   # compute_statement_digest()
    sheet: str
    header_row: int
    rows: list[BankExpenseRow]
    skipped: int                                  # non-debit / blank rows
    row_count: int                                # rows in the detected table (reconciliation unit)

class HoobaMapping(BaseModel):                    # rule → Hooba fields
    category: str
    tax_code: str                                 # IVA21 | IVA10 | IVA4 | EXENTO
    subject_to_income_tax: bool = False
    income_tax_code: Optional[str] = None
    simplified: bool = True
    accounting_account_code: Optional[str] = None

class DeductibilityVerdict(BaseModel):            # same field names as Spec A (FEAT-478) for later extraction
    draft_id: str
    txn_id: str                                   # == BankExpenseRow.row_id
    rule_id: str
    deductible_pct: Decimal                       # IRPF
    vat_deductible_pct: Decimal                   # IVA
    capped_amount: Optional[Decimal] = None
    legal_basis: str
    invoice_required: bool
    review_required: bool
    status: Literal["draft", "approved", "rejected", "registered"] = "draft"
    evidence: dict                                # raw concept / movement / amount / matched pattern (S12)
    hooba: HoobaMapping

class ExpenseDraftBatch(BaseModel):
    statement_digest: str
    period: str
    dry_run: bool
    planned: int
    created: list[DraftReceipt]
    skipped: list[dict]                           # {row_id, reason}
    reconciled: bool                              # rows planned == created + previously completed
    manifest_path: str
```

### New Public Interfaces
```python
# core — packages/ai-parrot/src/parrot/tools/openapitoolkit.py (Module 1)
LoginHook = Callable[["HTTPService"], Awaitable[Dict[str, str]]]

class OpenAPIToolkit(AbstractToolkit):
    def __init__(self, spec, service, base_url=None, api_key=None,
                 auth_type: str = "bearer",                 # "bearer" | "apikey" | "basic" | "cookie"
                 auth_header="Authorization", api_key_location="header", api_key_name="api_key",
                 credentials=None, use_proxy=False, timeout=30, debug=False,
                 *, login_hook: Optional[LoginHook] = None,
                 extra_headers: Optional[Dict[str, str]] = None,
                 path_defaults: Optional[Dict[str, Any]] = None,
                 include_tags: Optional[Sequence[str]] = None,
                 exclude_paths: Optional[Sequence[str]] = None,   # regexes matched with re.search on the raw path
                 exclude_methods: Optional[Sequence[str]] = None, # e.g. ("DELETE", "PUT")
                 operation_filter: Optional[Callable[[str, str], bool]] = None,  # (METHOD, raw path) -> keep? (default-deny hook)
                 max_tools: Optional[int] = None,                 # ValueError when exceeded
                 **kwargs): ...
    async def set_cookies(self, cookies: Dict[str, str]) -> None: ...   # inject externally obtained cookies
    def get_cookies(self) -> Dict[str, str]: ...                        # copy of the jar (values never logged)

# packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py (Module 6)
class HoobaToolkit(AbstractToolkit):
    auto_open = True
    async def hooba_whoami(self) -> dict: ...
    async def hooba_find_contact(self, query: str, limit: int = 5) -> dict: ...
    async def hooba_create_invoice_draft(self, draft: InvoiceDraft) -> dict: ...
    async def hooba_create_purchase_invoice_draft(self, draft: PurchaseInvoiceDraft) -> dict: ...
    async def hooba_attach_document(self, entity: Literal["invoice", "purchase_invoice"],
                                    entity_id: int, file_path: str) -> dict: ...
    async def hooba_list_drafts(self, kind: Literal["invoice", "purchase_invoice"], limit: int = 50) -> dict: ...
    async def hooba_download_invoice_pdf(self, invoice_id: int, dest_dir: Optional[str] = None) -> dict: ...
    async def hooba_import_bbva_statement(self, path: str, period: str, dry_run: bool = True) -> dict: ...
    async def hooba_recover_web_session(self) -> dict: ...
    async def hooba_run_web_action(self, action: str, params: Optional[dict] = None) -> dict: ...
```

All composite tools return `ToolResult(...).model_dump()`; `result` is the
Pydantic model's `model_dump(mode="json")`.

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: OpenAPIToolkit cookie mode + filters | yes | signatures below; edit anchors in §6; 401 → single re-login; `path_defaults` hidden from schema; all existing tests must stay green | — |
| M2: settings + credentials + login hook | yes | env names fixed; `EnvCredentialResolver` returns `{"username","password"}`; login = `POST {base_url}/auth/login` JSON, cookie `sid` from `response.cookies` | — |
| M3: pinned spec + pruner | yes | output file name, pruning rules and validation fields fixed below | — |
| M4: HoobaOpenAPIToolkit | yes | constants `DEFAULT_INCLUDE_TAGS`, `SUBMIT_PATH_BLOCKLIST`, `EXCLUDED_METHODS`, `MAX_TOOLS`; `classify_operation()` | — |
| M5: models | yes | §2 Data Models verbatim | — |
| M6: HoobaToolkit composite tools | no | id-resolution order and error envelopes are fixed, but the `get_tools()` merge with a nested toolkit and the lazy `_open` ordering (API session vs browser) need the thinking model | composition |
| M7: web adapter + driver cookie capability + seed helper | no | cookie hand-off across two transports (Playwright context → httpx jar), the new driver capability and the private-catalog contract are new ground | session hand-off |
| M8: BBVA parser + manifest | yes | header-detection rule, column vocabulary, debit rule, manifest layout fixed below; fixture is synthetic | — |
| M9: rule engine + YAML v1 | yes | schema fixed; starter rows listed; every row `review_required` until gestoría sign-off | — |
| M10: BBVA importer | yes | planning/apply algorithm fixed below; consumes M4/M5/M8/M9 | — |
| M11: registry, extra, docs, example | yes | anchors in §6 | — |

### Module 1: `OpenAPIToolkit` cookie-session mode, path defaults and operation filters (core)
- **Path**: `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` (MODIFY)
- **Responsibility**: add `auth_type="cookie"` with a lazy `login_hook`, a
  per-instance cookie jar passed on every request, `extra_headers`, a single
  re-login on 401, `path_defaults`, tag/path/method filters and `max_tools`.
  No behaviour change for the three existing auth modes.
- **Depends on**: none (foundation).
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # packages/ai-parrot/src/parrot/tools/openapitoolkit.py  (modifies openapitoolkit.py:62-174)
  LoginHook = Callable[["HTTPService"], Awaitable[Dict[str, str]]]   # new module-level alias, near line 44

  class OpenAPIToolkit(AbstractToolkit):                              # verified: openapitoolkit.py:45
      def __init__(self, spec, service, base_url=None, api_key=None,
                   auth_type: str = "bearer",                           # verified: openapitoolkit.py:68 — add "cookie"
                   auth_header="Authorization", api_key_location="header", api_key_name="api_key",
                   credentials=None, use_proxy=False, timeout=30, debug=False,
                   *, login_hook: Optional[LoginHook] = None,
                   extra_headers: Optional[Dict[str, str]] = None,
                   path_defaults: Optional[Dict[str, Any]] = None,
                   include_tags: Optional[Sequence[str]] = None,
                   exclude_paths: Optional[Sequence[str]] = None,
                   exclude_methods: Optional[Sequence[str]] = None,
                   operation_filter: Optional[Callable[[str, str], bool]] = None,
                   max_tools: Optional[int] = None, **kwargs) -> None:
          """auth_type="cookie" requires login_hook (ValueError otherwise). extra_headers are merged
          into the HTTPService default headers (openapitoolkit.py:151). Filters are applied inside
          _parse_operations in this order: include_tags, exclude_methods, exclude_paths, operation_filter;
          len(operations) > max_tools raises ValueError naming the count."""

      async def _ensure_session(self, force: bool = False) -> None:
          """Cookie mode only. Calls login_hook(self.http_service) when the jar is empty or force=True;
          stores the returned dict in self._cookies. Serialized by an asyncio.Lock so N concurrent first-use
          tool calls trigger exactly ONE login (S1). No-op otherwise."""

      async def set_cookies(self, cookies: Dict[str, str]) -> None:
          """Replace the jar with externally obtained cookies (e.g. exported from a browser session)."""

      def get_cookies(self) -> Dict[str, str]:
          """Return a copy of the jar. Never log values."""

      def _parse_operations(self) -> List[Dict[str, Any]]:              # verified: openapitoolkit.py:366
          """Now also records operation_spec['tags'] on each operation and drops operations whose
          first tag is not in include_tags (when set), whose method is in exclude_methods, or whose
          raw path matches any exclude_paths regex (re.search)."""

      def _create_pydantic_schema(self, operation) -> type[BaseModel]:  # verified: openapitoolkit.py:500
          """Path parameters whose name is in path_defaults are NOT added as fields."""

      def _build_operation_url(self, operation, params) -> str:         # verified: openapitoolkit.py:812
          """path_defaults are substituted FIRST and win; a caller value for a defaulted name is dropped and
          logged at WARNING (S4: an agent can never redirect a call to another account). Remaining
          placeholders are filled from params as today."""

      def _create_operation_method(self, operation):                    # verified: openapitoolkit.py:695
          """Cookie mode: await _ensure_session(); call http_service._request(..., cookies=self._cookies,
          headers={**extra_headers, **header_params}, full_response=True, raise_for_status=False,
          use_proxy=False); if response.status_code == 401 and not retried: await _ensure_session(force=True)
          and retry once; then result, error = await http_service.process_response(response, url)
          (ConnectionError from process_response becomes a ToolResult(status="error", metadata.status=...)).
          Cookie-mode writes (POST/PUT/PATCH/DELETE) pass num_retries=0 (S11: no transport-level replay of a
          non-idempotent request). Non-cookie modes keep the existing call at openapitoolkit.py:759 byte-for-byte."""
  ```

### Module 2: Settings, credentials and login hook
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/settings.py`,
  `packages/ai-parrot-tools/src/parrot_tools/hooba/credentials.py` (CREATE)
- **Responsibility**: `HoobaSettings.from_env()`; `EnvCredentialResolver`
  (a `CredentialResolver` returning `{"username": HOOBA_USERNAME, "password":
  HOOBA_PASSWORD}` or `None`); `register_hooba_provider(broker)`;
  `make_login_hook(settings, broker, user_id)` producing the Module 1 hook.
- **Depends on**: none (Module 1's `LoginHook` alias is only a type).
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/settings.py (new)
  class HoobaSettings(BaseModel):          # fields in §2 Data Models
      @classmethod
      def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "HoobaSettings":
          """Read HOOBA_* from env (default os.environ). Missing HOOBA_ACCOUNT_ID raises ValueError
          naming the variable. HOOBA_INCLUDE_TAGS is split on commas and stripped."""
      def default_headers(self) -> Dict[str, str]:
          """{'origin': origin, 'x-hooba-language': language, 'ngsw-bypass': 'true',
          'accept': 'application/json, text/plain, */*'}"""

  # parrot_tools/hooba/credentials.py (new)
  class EnvCredentialResolver(CredentialResolver):                     # verified: parrot/auth/credentials.py:162
      def __init__(self, username_var: str = "HOOBA_USERNAME", password_var: str = "HOOBA_PASSWORD",
                   env: Optional[Mapping[str, str]] = None) -> None: ...
      async def resolve(self, channel: str, user_id: str) -> Optional[Dict[str, str]]:
          """{'username','password'} when both variables are set, else None (broker → NeedsAuth)."""
      async def get_auth_url(self, channel: str, user_id: str) -> str:
          """Returns '' — there is no OOB flow; the operator sets the variables."""

  def register_hooba_provider(broker: CredentialBroker, provider: str = "hooba",
                              resolver: Optional[CredentialResolver] = None) -> None:
      """broker.register(provider, resolver or EnvCredentialResolver(), auth_kind='static_key')."""  # verified: broker.py:468

  class HoobaAuthError(RuntimeError):
      """Login rejected (401/409) or no 'sid' cookie in the login response."""

  def make_login_hook(settings: HoobaSettings, broker: CredentialBroker,
                      user_id: Optional[str] = None) -> LoginHook:
      """Returns async hook(http_service) -> {'sid': value}. Resolves broker.resolve(settings.credential_provider,
      'hooba', user_id or settings.credential_user_id); NeedsAuth → HoobaAuthError. POSTs JSON
      {username, password} to f'{settings.base_url}/auth/login' via http_service._request(..., use_json=True,
      headers=settings.default_headers(), full_response=True, raise_for_status=False, use_proxy=False);
      status != 200 → HoobaAuthError(status); reads response.cookies['sid'] (httpx.Cookies). Never logs secrets."""
  ```

### Module 3: Pinned, pruned Hooba OpenAPI document
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/spec/__init__.py`,
  `.../hooba/spec/prune.py`, `.../hooba/spec/hooba-api-2026.6.17.pruned.json` (CREATE)
- **Responsibility**: a committed, pruned copy of `https://api.hooba.com/api/doc.json`
  containing only paths whose first tag is in `DEFAULT_INCLUDE_TAGS ∪ {"Account",
  "Member", "Authentication"}` (the extra tags let composite tools and tests
  reach `/auth/*` and `/accounts/{accountId}/member` even though they are not
  generated as tools) with `components.schemas` transitively referenced by them;
  a loader that validates the pin; a CLI to regenerate it.
- **Depends on**: none.
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/spec/__init__.py (new)
  PINNED_VERSION = "2026.6.17"
  PINNED_SHA256 = "<sha256 of the committed pruned file — written by prune.py, asserted at load>"
  def load_pinned_spec(path: Optional[str] = None) -> Dict[str, Any]:
      """Load the bundled pruned JSON (or `path` / HOOBA_SPEC_PATH). The bundled file MUST hash to
      PINNED_SHA256 (HoobaSpecError otherwise — fail closed, S5); an override path skips the hash check
      but is logged at WARNING with its info.version. Raises HoobaSpecError unless
      openapi startswith '3.', info.version is present, and every path in REQUIRED_PATHS exists
      (login, auth/check, member, invoices, invoice-lines, purchase-invoices, purchase-invoice-lines,
      contacts, taxes, income-taxes, invoice-series, document-types, documents create, invoices:download).
      A different info.version logs a WARNING (drift) but loads."""
  class HoobaSpecError(ValueError): ...

  # parrot_tools/hooba/spec/prune.py (new) — `python -m parrot_tools.hooba.spec.prune --source URL|file --out path`
  def prune_spec(doc: Dict[str, Any], keep_tags: Sequence[str]) -> Dict[str, Any]:
      """Keep paths whose first tag ∈ keep_tags; keep only transitively referenced components; set
      servers=[{'url': 'https://api.hooba.com'}]; strip x-* vendor keys; sort keys for a stable digest. Pure function.
      The CLI prints the sha256 of the written file so PINNED_SHA256 is updated in the same commit."""
  async def fetch_spec(url: str) -> Dict[str, Any]:
      """aiohttp GET → JSON (never httpx — TID251)."""
  ```

### Module 4: `HoobaOpenAPIToolkit` — bound generated toolkit
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/openapi.py` (CREATE)
- **Responsibility**: bind spec, base URL, cookie auth, headers,
  `path_defaults={"accountId": settings.account_id}`, allowlist and blocklist
  into an `OpenAPIToolkit` subclass; classify operations.
- **Depends on**: Module 1, Module 2, Module 3.
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/openapi.py (new)
  DEFAULT_INCLUDE_TAGS: tuple[str, ...] = (
      "Invoice", "InvoiceLine", "InvoiceSerie", "PurchaseInvoice", "PurchaseInvoiceLine",
      "Contact", "Tax", "IncomeTax", "AccountingAccount", "PaymentMethod", "PaymentTerm",
      "Currency", "Document", "DocumentType", "InboxFile", "UnitOfMeasure",
  )   # scopes the READ (GET) surface: 47 operations on spec 2026.6.17 (proposal §5 Q1 → option b, widened with lookups)
  READ_PATH_BLOCKLIST: tuple[str, ...] = (r":download", r":export", r":pdf-", r"/avatar$")   # binary/exports: composite tools only
  DRAFT_OPERATIONS: frozenset[tuple[str, str]] = frozenset({        # the ONLY writes ever generated (S2: default-deny)
      ("POST",  "/accounts/{accountId}/invoices"),
      ("PATCH", "/accounts/{accountId}/invoices/{invoiceId}"),
      ("POST",  "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines"),
      ("PATCH", "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines/{invoiceLineId}"),
      ("POST",  "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines:sort"),
      ("POST",  "/accounts/{accountId}/purchase-invoices"),
      ("PATCH", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}"),
      ("POST",  "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines"),
      ("PATCH", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines/{purchaseInvoiceLineId}"),
      ("POST",  "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines:sort"),
      ("POST",  "/accounts/{accountId}/purchase-invoices:create-from-inbox-file"),
  })   # 11 operations; master-data creation (contacts, series, taxes, accounts), documents (multipart) and every
       # legal-effect action are NOT here — the multipart document upload is a composite tool (S6)
  LEGAL_EFFECT_PATTERNS: tuple[str, ...] = (      # used only to *label* denied operations as SUBMIT in reports/tests
      r":issue$", r":confirm$", r":cancel$", r":send", r":delete$", r":bulk-", r":schedule$", r":unschedule$",
      r":create-corrective$", r":collect$", r"^DELETE ",
  )
  MAX_TOOLS = 80

  def is_allowed(method: str, path: str) -> bool:
      """GET: first tag ∈ include_tags and no READ_PATH_BLOCKLIST match. Non-GET: (method, path) ∈ DRAFT_OPERATIONS.
      Everything else is denied (default-deny). Passed to OpenAPIToolkit as operation_filter."""

  def classify_operation(method: str, path: str) -> OperationKind:      # verified: business_automation/models.py:20
      """GET/HEAD → READ; (method, path) ∈ DRAFT_OPERATIONS → DRAFT; anything else → SUBMIT (default-deny —
      a denied write is reported as SUBMIT even when it is 'only' master-data creation)."""

  class HoobaOpenAPIToolkit(OpenAPIToolkit):                            # verified: openapitoolkit.py:45
      """Generated Hooba API tools, cookie-authenticated, account-scoped, drafts only."""
      def __init__(self, settings: HoobaSettings, login_hook: LoginHook, *,
                   spec: Optional[Dict[str, Any]] = None, include_tags: Optional[Sequence[str]] = None,
                   max_tools: int = MAX_TOOLS, **kwargs) -> None:
          """super().__init__(spec=spec or load_pinned_spec(settings.spec_path), service='hooba',
          base_url=settings.base_url, auth_type='cookie', login_hook=login_hook,
          extra_headers=settings.default_headers(), path_defaults={'accountId': settings.account_id},
          include_tags=include_tags or settings.include_tags or DEFAULT_INCLUDE_TAGS,
          exclude_methods=('DELETE', 'PUT'), exclude_paths=READ_PATH_BLOCKLIST,
          operation_filter=is_allowed, max_tools=max_tools)."""
      def _create_tool_from_method(self, name: str, bound_method) -> ToolkitTool:   # verified: parrot/tools/toolkit.py:647
          """super() then routing_meta['operation_kind'] = classify_operation(op['method'], op['path']).value using
          bound_method._operation (set at openapitoolkit.py:806); SUBMIT additionally sets
          routing_meta['requires_confirmation'] = True (S3 — unreachable in v1 by construction, tested)."""
      def operation_kinds(self) -> Dict[str, OperationKind]:
          """tool name → OperationKind; a test asserts no value is SUBMIT and len == 58 on the pinned spec."""
  ```
  Generated names follow `_create_method_name` (verified: `openapitoolkit.py:672-693`),
  e.g. `hooba_post_accounts_accountid_invoices`,
  `hooba_post_accounts_accountid_invoices_invoiceid_invoice_lines`,
  `hooba_post_accounts_accountid_purchase_invoices`, `hooba_get_taxes`.

### Module 5: Pydantic models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/models.py`,
  `packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py` (CREATE)
- **Responsibility**: the models in §2 Data Models, plus `HoobaStateError`
  (draft came back in a state other than `draft`) and `HoobaLookupError`
  (serie/tax/document type not resolvable). `__init__` exports `HoobaToolkit`,
  `HoobaSettings`, models.
- **Depends on**: none.
- **Interface Skeleton**: §2 Data Models verbatim; exceptions:
  ```python
  class HoobaStateError(RuntimeError): """Created entity is not in state 'draft'."""
  class HoobaLookupError(LookupError): """Invoice serie / tax / income tax / document type not found."""
  ```

### Module 6: `HoobaToolkit` — composite draft tools
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py` (CREATE)
- **Responsibility**: own the `HoobaOpenAPIToolkit`, `HoobaWebAdapter` (lazy)
  and `BbvaImporter`; expose the composite tools listed in §2; merge generated
  tools into `get_tools()`; tag every tool with `OperationKind`.
- **Depends on**: Modules 2, 4, 5, 7, 10.
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/toolkit.py (new)
  class HoobaToolkit(AbstractToolkit):                                  # verified: parrot/tools/toolkit.py:203
      auto_open = True                                                  # verified: toolkit.py:311
      exclude_tools = ("operation_kinds",)                              # verified: toolkit.py:240
      def __init__(self, settings: Optional[HoobaSettings] = None, credential_broker: Optional[CredentialBroker] = None,
                   *, api: Optional[HoobaOpenAPIToolkit] = None, web: Optional["HoobaWebAdapter"] = None,
                   rules_path: Optional[str] = None, headless: bool = True, **kwargs) -> None:
          """settings default HoobaSettings.from_env(); broker default CredentialBroker() with register_hooba_provider();
          api default HoobaOpenAPIToolkit(settings, make_login_hook(settings, broker)); web is built lazily from
          settings.catalog_dir (None → web tools return status='error' 'HOOBA_CATALOG_DIR not set')."""
      async def _open(self) -> None: """await self._api._ensure_session() — no browser."""       # verified: toolkit.py:398
      async def _close(self) -> None: """close the web adapter if it was started; super()._close()."""
      def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]:
          """super().get_tools() + self._api.get_tools(); ValueError on any name collision."""  # verified: toolkit.py:494
      def operation_kinds(self) -> Dict[str, OperationKind]:
          """Composite tools: hooba_whoami/find_contact/list_drafts/download_invoice_pdf/recover_web_session/
          run_web_action → READ; create_*_draft/attach_document/import_bbva_statement → DRAFT; merged with api."""
      # tools — every one returns ToolResult(...).model_dump()
      async def hooba_whoami(self) -> dict: """GET /accounts/{accountId}/member → member/user summary (no PII beyond name/e-mail)."""
      async def hooba_find_contact(self, query: str, limit: int = 5) -> dict:
          """GET /accounts/{accountId}/contacts (paginate until exhausted or 500 rows); difflib.SequenceMatcher
          ratio over legalName/tradeName/firstName+surnames, case/accents-insensitive; matches ≥ 0.85 sorted desc."""
      async def hooba_create_invoice_draft(self, draft: InvoiceDraft) -> dict:
          """key = draft.correlation_key or uuid4; scan existing drafts (hooba_list_drafts) for notes containing
          f'[parrot:{key}]' → reuse it and only POST the lines it lacks (reused=True) instead of duplicating (S11).
          Otherwise resolve contact (contact_id | best hooba_find_contact ≥ 0.85 else HoobaLookupError), invoice serie
          (invoice_serie_code | the serie flagged default for simplified/non-simplified | the only serie), taxes
          (GET /taxes: percentage 21/10/4 + operationType 'sale'; EXENTO → taxId None), income taxes; POST invoices;
          POST invoices with notes = f'{draft.notes or ""} [parrot:{key}]'; POST invoice-lines per line
          (type='product', name, price, quantity, discount, taxId, incomeTaxId — the Product oneOf branch, built explicitly, S6);
          GET invoice → state must be 'draft' else HoobaStateError; → DraftReceipt(kind='invoice')."""
      async def hooba_create_purchase_invoice_draft(self, draft: PurchaseInvoiceDraft) -> dict:
          """Same key scan/reuse and resolution with operationType 'purchase'; POST purchase-invoices (date, number,
          simplified, contactId, taxIncluded, subjectToIncomeTax, notes + '[parrot:{key}]'); POST purchase-invoice-lines;
          state must be 'draft'."""
      async def hooba_attach_document(self, entity, entity_id, file_path) -> dict:
          """documentTypeId via GET document-types (entity name match); multipart POST
          /accounts/{accountId}/documents/{documentTypeId}/{entityRecordId} with aiohttp.FormData(file, data=json)
          carrying the api cookie jar and default headers (HTTPService._request has no multipart file support)."""
      async def hooba_list_drafts(self, kind, limit: int = 50) -> dict:
          """GET invoices | purchase-invoices, client-side filter state == 'draft', newest first."""
      async def hooba_download_invoice_pdf(self, invoice_id: int, dest_dir: Optional[str] = None) -> dict:
          """GET invoices/{id}:download with full_response=True; write bytes under dest_dir or PARROT_STATE_DIR/hooba/pdf;
          → {path, size}. 0o600 file mode."""
      async def hooba_import_bbva_statement(self, path: str, period: str, dry_run: bool = True) -> dict:
          """BbvaImporter.plan() (+ apply() when dry_run=False) → ExpenseDraftBatch."""
      async def hooba_recover_web_session(self) -> dict:
          """web.recover_session() → {} means fail closed: status='error' and the API jar is left untouched;
          otherwise api.set_cookies({'sid': …}) → {recovered: True, cookie_names: [...]} (S8)."""
      async def hooba_run_web_action(self, action: str, params: Optional[dict] = None) -> dict:
          """Only actions the private catalog marks kind='navigation'; anything else → status='error'."""
  ```

### Module 7: Web adapter, driver cookie capability and catalog seed helper
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/web.py` (CREATE);
  `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`,
  `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` (MODIFY — one method each)
- **Responsibility**: wrap `WebBrowsingToolkit` for the private catalog;
  session recovery through a **context-level** cookie export (`exec_get_cookies`
  reads `document.cookie`, which cannot see an HttpOnly `sid` — S8);
  navigation passthrough; a `seed_catalog()` helper that
  writes the login + navigation actions into a *user-supplied* directory
  (generalized from the untracked local example; selectors are parameters,
  not constants in the repo except the login form defaults).
- **Depends on**: Module 2 (settings, broker resolver).
- **Interface Skeleton**:
  ```python
  # parrot_tools/scraping/drivers/abstract.py  (modifies abstract.py:232 — new method after `evaluate`)
  class AbstractDriver:                                                 # verified: abstract.py:11
      async def get_cookies(self, urls: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
          """Context-level cookies (name, value, domain, path, httpOnly, secure, expires) — includes HttpOnly.
          Default raises NotImplementedError so callers fail closed on drivers without the capability."""

  # parrot_tools/scraping/drivers/playwright_driver.py  (modifies playwright_driver.py:269 — new method after `evaluate`)
  class PlaywrightDriver(AbstractDriver):                               # verified: playwright_driver.py:15
      async def get_cookies(self, urls: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
          """return await self._context.cookies(list(urls) if urls else None)  (self._context set in start(), line 99/113);
          RuntimeError when the driver is not started."""

  # parrot_tools/hooba/web.py (new)
  class HoobaWebAdapter:
      def __init__(self, catalog_dir: Union[str, Path], credential_resolver: CredentialResolverFn, *,
                   site: str = "hooba", login_action: str = "hooba-login", headless: bool = True,
                   driver_type: str = "playwright", browser: str = "chrome", **kwargs) -> None:
          """Builds WebBrowsingToolkit(catalog_dir=..., driver_type=..., browser=..., headless=..., credential_resolver=...,
          confirm_runs=False) lazily on first use."""                    # verified: browsing/toolkit.py:124-160
      async def recover_session(self, cookie_names: Sequence[str] = ("sid",), *,
                                api_url: str = "https://api.hooba.com") -> Dict[str, str]:
          """run_site_action(site, login_action) → driver = toolkit._ensure_session_driver() →
          await driver.get_cookies([api_url, base_url]) → {name: value} for cookie_names only; empty dict (never raises)
          when login failed, the driver lacks get_cookies (NotImplementedError) or 'sid' is absent — fail closed (S8)."""   # verified: browsing/toolkit.py:382, 164
      async def run_navigation(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
          """Refuses actions whose catalog kind != 'navigation' (reads the action JSON via the catalog)."""
      async def close(self) -> None: """close_browser() if started."""    # verified: browsing/toolkit.py:176

  async def seed_catalog(catalog_dir: Union[str, Path], *, base_url: str = "https://app.hooba.com",
                         sections: Optional[Dict[str, tuple[str, str, str]]] = None,
                         username_selector: str = 'input[type="email"]', password_selector: str = 'input[type="password"]',
                         submit_selector: str = 'button[type="submit"]') -> str:
      """Register site 'hooba' and write hooba-login + one navigation action per section into catalog_dir
      (outside the repo). credential_provider='hooba'; never writes credentials."""
  ```

### Module 8: BBVA statement parser and import manifest
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/__init__.py`,
  `.../hooba/bank/bbva.py`, `.../hooba/bank/manifest.py` (CREATE)
- **Responsibility**: locate the movements table in a BBVA `.xlsx` export,
  normalize rows into `BankExpenseRow` (debits only), digest the file, and
  keep a permission-hardened per-statement manifest for resume/reconcile.
- **Depends on**: Module 5.
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/bank/bbva.py (new)
  HEADER_TOKENS = {"fecha", "f.valor", "fecha valor", "concepto", "movimiento", "importe", "divisa", "disponible", "observaciones"}
  async def parse_bbva_statement(path: Union[str, Path], *, sheet: Optional[str] = None) -> BbvaStatement:
      """digest = compute_statement_digest(path)  (verified: business_automation/ingest.py:99).
      Header row = first row (scanning the first 40) where ≥ 3 HEADER_TOKENS match case/accents-insensitively;
      none → ValueError('BBVA header row not found'). Columns mapped by token; 'fecha' and 'importe' mandatory.
      Amounts accept numeric cells and Spanish strings ('-1.234,56'). Dates accept datetime cells and dd/mm/yyyy.
      Rows with amount < 0 → BankExpenseRow; amount ≥ 0 or blank → skipped. row_count cross-checked against
      ExcelLoader(output_mode='row') like ingest._load_expense_rows (verified: ingest.py:111-151); mismatch → ValueError.
      All pandas/openpyxl work runs in asyncio.to_thread (S10); the pure sync core is `_parse_bbva_sync(path, sheet)`."""

  # parrot_tools/hooba/bank/manifest.py (new)
  class ImportManifest(BaseModel):
      statement_digest: str; period: str; started_at: datetime; row_count: int
      completed: Dict[str, int] = {}          # row_id → purchase_invoice_id
      skipped: Dict[str, str] = {}            # row_id → reason
  def manifest_path_for(digest: str) -> Path:
      """checkpoint_dir_for('hooba_bbva_import') / f'{digest}.manifest.json'"""   # verified: ingest.py:86
  def load_manifest(digest: str) -> Optional[ImportManifest]: ...
  def write_manifest(m: ImportManifest) -> Path:
      """Atomic write (tmp + os.replace), mode 0o600, dir 0o700 — same hardening as ingest._write_import_manifest.
      Sync helper; callers await it via asyncio.to_thread (S10)."""
  def reconcile(m: ImportManifest, planned_rows: int) -> Dict[str, Any]:
      """{'rows_in', 'drafts_out', 'skipped', 'delta', 'reconciled'} — reconciled iff delta == 0."""
  ```

### Module 9: Deductibility rule engine and v1 YAML
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/rules/__init__.py`,
  `.../hooba/rules/engine.py`, `.../hooba/rules/autonomo_es_v1.yaml` (CREATE)
- **Responsibility**: data-driven classification of a bank row into a
  `DeductibilityVerdict` + `HoobaMapping`; the v1 table for autónomos.
- **Depends on**: Module 5.
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/rules/engine.py (new)
  class RuleMatcher(BaseModel):
      concept_regex: Optional[str] = None        # compiled with re.IGNORECASE over concept + movement + observations
      amount_min: Optional[Decimal] = None; amount_max: Optional[Decimal] = None   # on abs(amount)
      category: str
  class AeatRule(BaseModel):                    # field names mirror Spec A (auto-finance-toolkit.spec.md:203-206)
      rule_id: str; matcher: RuleMatcher; priority: int = 100
      deductible_pct: Decimal; vat_deductible_pct: Decimal
      annual_cap: Optional[Decimal] = None; daily_cap: Optional[Decimal] = None
      requires_exclusive_use: bool = False; invoice_required: bool = True; review_required: bool = True
      skip: bool = False                          # True → not an expense (transfers, taxes, own withdrawals)
      legal_basis: str; hooba: HoobaMapping
  class RuleTable(BaseModel):
      version: str; simplified_invoice_limit_eur: Decimal; rules: list[AeatRule]; fallback_rule_id: str
  class RuleEngine:
      @classmethod
      def load(cls, path: Optional[Union[str, Path]] = None) -> "RuleEngine":
          """yaml.safe_load of the bundled autonomo_es_v1.yaml (or path); validates RuleTable; duplicate rule_id → ValueError."""
      def match(self, row: BankExpenseRow) -> AeatRule:
          """Lowest-priority-number rule whose matcher matches; TWO rules at the same priority matching → fallback
          (ambiguity is never resolved by guessing, S12); no match → fallback."""
      def assess(self, row: BankExpenseRow, *, period: str) -> Optional[DeductibilityVerdict]:
          """None when rule.skip; otherwise a draft verdict with draft_id=f'{row.row_id}:{rule.rule_id}',
          capped_amount from daily/annual caps when set, hooba.simplified = abs(amount) <= simplified_invoice_limit_eur,
          evidence={'concept', 'movement', 'observations', 'amount', 'matched_pattern'} (S12)."""
  ```
  **v1 table content** (starter rows; every row `review_required: true` until a gestoría signs off — §8 Q3):

  | rule_id | category | IRPF % | IVA % | tax_code | notes / legal_basis |
  |---|---|---|---|---|---|
  | `skip_transfers` | traspaso | — | — | — | `skip`: TRASPASO / TRANSFERENCIA A CUENTA PROPIA / BIZUM a uno mismo |
  | `skip_taxes` | impuestos | — | — | — | `skip`: AEAT / TGSS liquidaciones, modelos 130/303 (pagos de impuestos, no gasto) |
  | `reta` | cuota_autonomos | 100 | 0 | EXENTO | cuota RETA — LIRPF 35/2006 art. 30.2.1ª; sin IVA; no factura requerida |
  | `telco` | telecomunicaciones | 100 | 100 | IVA21 | MOVISTAR/VODAFONE/ORANGE/DIGI/MASMOVIL/O2 — LIRPF art. 28-30, LIVA 37/1992 art. 95.Uno; `requires_exclusive_use` |
  | `software` | software_suscripciones | 100 | 100 | IVA21 | GOOGLE/MICROSOFT/GITHUB/ADOBE/OPENAI/ANTHROPIC/JETBRAINS/AWS/HETZNER/OVH — LIRPF art. 28; LIVA art. 95 |
  | `gestoria` | asesoria | 100 | 100 | IVA21 | ASESOR/GESTOR/CONSULTOR — `subject_to_income_tax: true` (retención 15 %, RIRPF RD 439/2007 art. 101) |
  | `office` | material_oficina | 100 | 100 | IVA21 | AMAZON/PAPELERIA/CARLIN/STAPLES — LIRPF art. 28; simplified when ≤ 400 € (RD 1619/2012 art. 4) |
  | `hardware` | equipos | 0 | 100 | IVA21 | ordenadores/periféricos > 300 € → amortización (LIRPF art. 30.2, RIRPF art. 30) — review |
  | `fuel` | combustible | 0 | 50 | IVA21 | REPSOL/CEPSA/BP/GALP/SHELL — LIVA art. 95.Tres.2ª (50 % presunción vehículo); IRPF solo con afectación exclusiva |
  | `meals` | dietas_manutencion | 100 | 100 | IVA10 | restaurantes, pago electrónico, `daily_cap` 26,67 € (España) — LIRPF art. 30.2.5ª.c |
  | `home_utilities` | suministros_vivienda | 30 | 0 | IVA21 | IBERDROLA/ENDESA/NATURGY/REPSOL LUZ/AGUA — 30 % de la parte proporcional afecta (LIRPF art. 30.2.5ª.b) — review |
  | `training` | formacion | 100 | 100 | IVA21 | cursos/UDEMY/COURSERA/O'REILLY — LIRPF art. 28 |
  | `bank_fees` | comisiones_bancarias | 100 | 0 | EXENTO | COMISION/COMISIONES — LIVA art. 20.Uno.18º exento; no factura (extracto) |
  | `insurance` | seguros | 100 | 0 | EXENTO | seguro RC profesional 100 %; seguro médico cap 500 €/persona (LIRPF art. 30.2.5ª.a) — review |
  | `unclassified` (fallback) | sin_clasificar | 0 | 0 | IVA21 | `review_required`, `invoice_required` — never auto-deductible |

### Module 10: BBVA importer (rows → purchase-invoice drafts)
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/hooba/importer.py` (CREATE)
- **Responsibility**: turn a parsed statement into planned drafts, apply them
  through the API idempotently, and reconcile.
- **Depends on**: Modules 4, 5, 8, 9 (and Module 6 for `find_contact`, injected as a callable).
- **Interface Skeleton**:
  ```python
  # parrot_tools/hooba/importer.py (new)
  ContactFinder = Callable[[str], Awaitable[list[ContactMatch]]]
  DraftCreator = Callable[[PurchaseInvoiceDraft], Awaitable[DraftReceipt]]

  class PlannedDraft(BaseModel):
      row: BankExpenseRow; verdict: DeductibilityVerdict; draft: PurchaseInvoiceDraft; contact: Optional[ContactMatch]

  class BbvaImporter:
      def __init__(self, engine: RuleEngine, find_contact: ContactFinder, create_draft: DraftCreator) -> None: ...
      async def plan(self, statement: BbvaStatement, *, period: str) -> tuple[list[PlannedDraft], ImportManifest, list[dict]]:
          """Load/create manifest; for each row not in manifest.completed: verdict = engine.assess(row, period=period);
          None → skipped(reason='rule.skip'); contact = best find_contact(concept) ≥ 0.85 else None (U3);
          draft = PurchaseInvoiceDraft(date=booking_date, simplified=verdict.hooba.simplified, contact_id=…,
          tax_included=True, subject_to_income_tax=verdict.hooba.subject_to_income_tax,
          correlation_key=row.row_id,   # S11: a crash between header and lines is healed by the reuse scan
          notes=f'BBVA {row.row_id} · {concept} · {legal_basis} · review_required={…}',
          lines=[one line: name=concept, price=abs(amount), tax_code=verdict.hooba.tax_code])."""
      async def apply(self, planned: list[PlannedDraft], manifest: ImportManifest) -> list[DraftReceipt]:
          """Sequential; AWAITS each create_draft → DraftReceipt (no fire-and-forget: this path never touches
          BusinessAutomationToolkit.run_operation, S9); only then manifest.completed[row_id] = receipt.id, write_manifest();
          an exception stops the run (manifest already reflects progress → re-run resumes)."""
  ```

### Module 11: Registration, packaging, docs and example
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/__init__.py` (MODIFY),
  `packages/ai-parrot-tools/pyproject.toml` (MODIFY),
  `docs/hooba-toolkit.md` (CREATE), `docs/business-automation-runbook.md` (MODIFY),
  `examples/agents/finance/hooba_agent.py` (CREATE — `examples/**/*.py` is
  git-ignored: commit with `git add -f`).
- **Responsibility**: `TOOL_REGISTRY["hooba"]`; `hooba` extra
  (`ai-parrot-tools[business_automation,excel,scraping]` + `pyyaml>=6.0`)
  and membership in `all`; package data for `hooba/spec/*.json` and
  `hooba/rules/*.yaml`; docs (env vars, spec pin, `HOOBA_CATALOG_DIR`, seed
  helper, dry-run import walkthrough); runbook `## 8. Hooba toolkit` section;
  a CLI example agent mirroring the untracked local one but on
  `HoobaToolkit` + broker.
- **Depends on**: Module 6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_cookie_mode_requires_login_hook` | M1 | `auth_type="cookie"` without `login_hook` → `ValueError` |
| `test_cookie_mode_logs_in_lazily_once` | M1 | hook not called at construction; called once across two tool calls |
| `test_cookie_mode_sends_jar_and_extra_headers` | M1 | fake `HTTPService._request` receives `cookies={"sid": …}`, merged headers, `full_response=True` |
| `test_cookie_mode_relogins_once_on_401` | M1 | 401 → hook called again → retry succeeds; second 401 → `ToolResult.status == "error"` |
| `test_cookie_mode_concurrent_first_use_logs_in_once` | M1 | `asyncio.gather` of 5 first calls → hook invoked exactly once (S1) |
| `test_cookie_mode_no_transport_retries_on_writes` | M1 | POST/PATCH pass `num_retries=0`; GET keeps the default (S11) |
| `test_path_defaults_override_caller_value` | M1 | caller `accountId=1` is dropped, URL uses the default, WARNING logged (S4) |
| `test_operation_filter_default_deny` | M1 | `operation_filter` receives `(METHOD, raw path)`; returning False drops the operation |
| `test_path_defaults_hidden_and_substituted` | M1 | `{accountId}` absent from `_args_schema`; URL contains `23549` |
| `test_include_tags_exclude_paths_methods` | M1 | filters drop exactly the expected operations; names of survivors unchanged |
| `test_max_tools_exceeded_raises` | M1 | `ValueError` names the count |
| `test_existing_auth_modes_unchanged` | M1 | bearer/apikey/basic path still calls `_request` with `full_response=False`; `tests/test_openapi_toolkit.py` + `tests/test_openapi.py` green |
| `test_settings_from_env_and_headers` | M2 | env mapping → `HoobaSettings`; missing `HOOBA_ACCOUNT_ID` → `ValueError`; `HOOBA_INCLUDE_TAGS` split |
| `test_env_resolver_and_broker_registration` | M2 | resolver returns dict / `None`; `broker.resolve("hooba", …)` yields it; `NeedsAuth` when unset |
| `test_login_hook_extracts_sid` | M2 | fake `_request` returns a response with `cookies["sid"]` (also via `response.history`); 401 → `HoobaAuthError`; password never appears in logs (caplog) |
| `test_login_hook_fails_closed_before_network` | M2 | unregistered provider → `KeyError` surfaced as `HoobaAuthError`; empty identity → `ValueError`; secret not a dict/tuple → `HoobaAuthError`; `_request` never called (S7) |
| `test_pinned_spec_loads_and_validates` | M3 | bundled file loads and hashes to `PINNED_SHA256`; missing required path → `HoobaSpecError`; override path with other version → WARNING |
| `test_pinned_spec_sha256_mismatch_fails_closed` | M3 | tampered bundled file → `HoobaSpecError` (S5) |
| `test_prune_spec_keeps_referenced_components_only` | M3 | pure function on a small synthetic doc |
| `test_default_surface_size_and_no_submit` | M4 | with the pinned spec: `len(get_tools()) == 58` (47 READ + 11 DRAFT), every `operation_kinds()` value ∈ {READ, DRAFT} |
| `test_default_deny_writes` | M4 | every non-GET operation in the pinned spec not in `DRAFT_OPERATIONS` is absent from the tools and classified SUBMIT — including `POST contacts`, `POST invoice-series`, `:set-default`, `:schedule`, `:duplicate`, `:seed` (S2) |
| `test_generated_tools_carry_operation_kind_routing_meta` | M4 | every generated `ToolkitTool.routing_meta['operation_kind']` ∈ {read, draft}; none has `requires_confirmation` (S3) |
| `test_generated_tool_names_match_openapitoolkit_convention` | M4 | names computed via `_create_method_name`, not hard-coded |
| `test_models_roundtrip` | M5 | `model_dump(mode="json")` / validate for every model; `DraftReceipt.state` free-form |
| `test_get_tools_merges_without_collision` | M6 | composite + generated; injected duplicate name → `ValueError` |
| `test_create_invoice_draft_resolves_ids_and_posts_lines` | M6 | fake API toolkit records calls: serie/tax/contact lookups, header POST, one POST per line, state check |
| `test_create_draft_rejects_non_draft_state` | M6 | GET returns `issued` → `HoobaStateError` → error ToolResult |
| `test_create_draft_reuses_existing_by_correlation_key` | M6 | an existing draft whose notes carry `[parrot:<key>]` with 1 of 2 lines → only the missing line is posted, `reused=True`, no second header POST (S11) |
| `test_find_contact_threshold` | M6 | 0.84 excluded, 0.85 included, accents/case ignored |
| `test_attach_document_multipart` | M6 | aiohttp test server receives multipart with `file` + `data`, cookie `sid`, `x-hooba-language` |
| `test_web_tools_error_without_catalog_dir` | M6 | `catalog_dir=None` → both web tools return status error, no browser started |
| `test_recover_session_returns_sid` | M7 | fake toolkit + fake driver with `get_cookies` → `{"sid": …}`; login failure, `NotImplementedError` or missing `sid` → `{}` (fail closed, S8) |
| `test_abstract_driver_get_cookies_default_raises` | M7 | `AbstractDriver.get_cookies` → `NotImplementedError`; other drivers untouched |
| `test_run_navigation_refuses_non_navigation` | M7 | action JSON with `kind: composite` → error |
| `test_seed_catalog_writes_login_and_sections_without_secrets` | M7 | tmp dir; `credential_provider == "hooba"`; no `HOOBA_` values in any JSON |
| `test_parse_bbva_fixture` | M8 | synthetic workbook with 6 preamble rows: header detected, 5 debits, 2 credits skipped, digest stable |
| `test_parse_bbva_spanish_amounts_and_dates` | M8 | `"-1.234,56"` → `Decimal("-1234.56")`; `"03/09/2026"` → date |
| `test_parse_bbva_header_not_found` | M8 | unrelated workbook → `ValueError` |
| `test_parse_bbva_runs_off_event_loop` | M8 | `_parse_bbva_sync` is invoked through `asyncio.to_thread` (patched) — the loop stays responsive (S10) |
| `test_manifest_permissions_and_reconcile` | M8 | file 0o600, dir 0o700; delta math |
| `test_rule_table_loads_and_priorities` | M9 | YAML valid; duplicate id → `ValueError`; fallback exists |
| `test_rule_engine_matches_and_skips` | M9 | RETA → 100/0 EXENTO; fuel → 0/50; TRASPASO → `None`; unknown → fallback `review_required`; two same-priority matches → fallback; `evidence` populated (S12) |
| `test_simplified_threshold` | M9 | 399,99 → simplified; 400,01 → not |
| `test_importer_plan_dry_run_idempotent` | M10 | same statement twice → second plan skips completed rows; contact only when ≥ 0.85 |
| `test_importer_apply_resumes_after_failure` | M10 | creator fails on row 3 → manifest has 2 completed → re-run creates the remaining rows only |
| `test_registry_and_extra` | M11 | `TOOL_REGISTRY["hooba"]` importable; `importlib.metadata` extra `hooba` present |

### Integration Tests
| Test | Description |
|---|---|
| `test_hooba_end_to_end_against_fake_server` | `aiohttp.web` test server implementing `/auth/login` (sets `sid`, 401 on bad password), `/auth/check`, `member`, `invoice-series`, `taxes`, `income-taxes`, `contacts`, `invoices` (+lines, `:download`), `purchase-invoices` (+lines), `document-types`, `documents` upload, all returning 401 without `sid`. Drives `HoobaToolkit` (real M1/M2/M4/M5/M6) through: whoami → create invoice draft → create purchase invoice draft → attach document → list drafts → download PDF. Asserts `state == "draft"` everywhere and that the server never receives `:issue`/`:confirm`. |
| `test_bbva_import_end_to_end` | Same server + synthetic BBVA workbook: dry-run plan (no POSTs), then apply → N purchase-invoice drafts, manifest written, reconcile true; re-run → zero new POSTs. |
| `test_session_expiry_relogin` | Server invalidates `sid` after 2 requests; toolkit re-logs in once transparently. |
| `test_web_recover_session_fixture_site` *(opt-in, `PARROT_TEST_REAL_BROWSER=1`)* | FEAT-455 local fixture site (serving an **HttpOnly** session cookie) + a temp catalog from `seed_catalog()` pointing at it: `PlaywrightDriver.get_cookies()` returns it, `recover_session()` hands it to the API jar (S8). |
| `test_hooba_live_smoke` *(opt-in, `HOOBA_LIVE=1`)* | Real account: login, whoami, list invoice series and taxes. Read-only; never creates anything. |

### Test Data / Fixtures
```python
# packages/ai-parrot-tools/tests/hooba/conftest.py
@pytest.fixture
def hooba_env(monkeypatch) -> dict:
    """HOOBA_ACCOUNT_ID=23549, HOOBA_MEMBER_ID=61296, HOOBA_USER_ID=23725, HOOBA_SUBSCRIPTION_ID=1,
    HOOBA_USERNAME=user@example.test, HOOBA_PASSWORD=secret, HOOBA_BASE_URL=<fake server url>."""

@pytest.fixture
async def fake_hooba_server(aiohttp_server):
    """aiohttp.web.Application replaying the pruned spec's shapes; records every request; issues sid cookies."""

@pytest.fixture
def bbva_workbook(tmp_path) -> Path:
    """Synthetic BBVA export built with openpyxl by tests/hooba/fixtures/make_bbva_fixture.py:
    6 preamble rows (titular, cuenta, periodo), header
    ['Fecha', 'F.Valor', 'Concepto', 'Movimiento', 'Importe', 'Divisa', 'Disponible', 'Observaciones'],
    7 rows: 5 debits (RETA, MOVISTAR, REPSOL, RESTAURANTE, TRASPASO) and 2 credits. No real data."""

@pytest.fixture
def pinned_spec() -> dict:
    """load_pinned_spec() — the committed 2026.6.17 pruned document."""
```

The synthetic layout is an assumption pending an anonymized real export (§8 Q2);
the parser's column vocabulary is data (`HEADER_TOKENS`) so a layout correction
is a one-line change plus a fixture update, not a redesign.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1. `OpenAPIToolkit(auth_type="cookie", login_hook=…)` calls the hook lazily, sends the jar and `extra_headers` on every request, re-logs in exactly once on 401, and `set_cookies()` / `get_cookies()` work (M1 tests).
- [ ] AC-2. `path_defaults` parameters are absent from every generated tool schema and substituted into the URL.
- [ ] AC-3. `include_tags`, `exclude_paths`, `exclude_methods`, `operation_filter`, `max_tools` filter generation; `max_tools` overflow raises `ValueError`; cookie-mode writes never use transport retries; a caller can never override a `path_defaults` value.
- [ ] AC-4. All pre-existing `OpenAPIToolkit` tests (`packages/ai-parrot/tests/test_openapi_toolkit.py`, `test_openapi.py`) pass unchanged; bearer/apikey/basic request path is byte-identical.
- [ ] AC-5. `HoobaOpenAPIToolkit` over the pinned spec exposes exactly 58 tools (47 GET + the 11 `DRAFT_OPERATIONS`) with the default allowlist; every generated tool carries `routing_meta['operation_kind']` ∈ {read, draft}; **no** write outside `DRAFT_OPERATIONS` is reachable — `:issue`, `:confirm`, `:cancel`, `:send*`, deletes, bulk paths and master-data creation alike (test + grep of generated names).
- [ ] AC-6. `HoobaToolkit.get_tools()` = composite tools ∪ generated tools, ≤ 80 total by default, collision-free; `operation_kinds()` covers every tool.
- [ ] AC-7. `hooba_create_invoice_draft` and `hooba_create_purchase_invoice_draft` resolve serie / contact / tax ids, post header + lines, verify `state == "draft"`, refuse (error ToolResult) any other state, and are idempotent per `correlation_key` (a retry completes the existing draft instead of creating a second one).
- [ ] AC-8. Credentials flow only through `CredentialBroker` provider `hooba`; no password appears in logs, catalog JSON, manifests or tool results (caplog + grep tests).
- [ ] AC-9. The pinned spec is committed with its SHA-256 asserted at load (`HoobaSpecError` on mismatch or missing required path), regenerable with `python -m parrot_tools.hooba.spec.prune`, and an override path with another version logs a warning.
- [ ] AC-10. `parse_bbva_statement` detects the header row after a preamble, parses Spanish amounts/dates, keeps debits only, cross-checks row counts, and produces a stable digest.
- [ ] AC-11. `hooba_import_bbva_statement(dry_run=True)` performs zero POSTs; `dry_run=False` creates one simplified purchase-invoice draft per debit row, sets `contactId` only for matches ≥ 0.85, marks a row complete in the 0o600 manifest only after its `DraftReceipt` is returned, resumes without duplicates, parses off the event loop, and reports `reconciled`.
- [ ] AC-12. The v1 rule table loads, every verdict carries `legal_basis`, `review_required` and raw `evidence`, transfers/taxes are skipped, unknown or ambiguous rows fall back to a non-deductible `review_required` verdict (never a guessed percentage), and the 400 € simplified threshold is data-driven.
- [ ] AC-13. Web tools never start a browser unless called; without `HOOBA_CATALOG_DIR` they return an error ToolResult; `hooba_recover_web_session` exports cookies at browser-context level (HttpOnly included) via the new `AbstractDriver.get_cookies()` / `PlaywrightDriver.get_cookies()`, fails closed when `sid` is absent, and otherwise injects it into the API jar; `hooba_run_web_action` refuses non-navigation actions.
- [ ] AC-14. No `httpx`/`requests` import in `parrot_tools/hooba/**` (`ruff check` TID251 clean); multipart upload uses aiohttp.
- [ ] AC-15. `TOOL_REGISTRY["hooba"]` resolves; `pip install ai-parrot-tools[hooba]` pulls `business_automation`, `excel`, `scraping`, `pyyaml`; package data ships the spec JSON and rules YAML.
- [ ] AC-16. `docs/hooba-toolkit.md` and the runbook §8 document env vars, the spec pin, the private catalog contract, the seed helper and the dry-run import; `examples/agents/finance/hooba_agent.py` runs `--smoke` (whoami) against the fake server in tests.
- [ ] AC-17. No real Hooba selectors, credentials, bank data or personal identifiers are committed (fixtures synthetic; reviewer grep for `sid=`, IBAN patterns, the user's surname).
- [ ] AC-18. `pytest packages/ai-parrot-tools/tests/hooba -v` and `pytest packages/ai-parrot/tests/test_openapi_toolkit.py packages/ai-parrot/tests/test_openapi.py -v` pass; `black --check` and `ruff check` clean on touched files.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

Re-verified 2026-09-25 against base commit `9476f48e1` (every line number below was read, not copied from the proposal).

### Verified Imports
```python
from parrot.tools.openapitoolkit import OpenAPIToolkit                       # verified: packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py:15
from parrot.tools.toolkit import AbstractToolkit                              # verified: packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py:27
from parrot.tools.abstract import ToolResult                                  # verified: packages/ai-parrot/src/parrot/tools/openapitoolkit.py:42 (relative import `.abstract`)
from parrot.interfaces.http import HTTPService                                # verified: packages/ai-parrot/src/parrot/tools/openapitoolkit.py:41
from parrot.auth.broker import CredentialBroker                               # verified: packages/ai-parrot/src/parrot/auth/__init__.py:64
from parrot.auth.credentials import CredentialResolver, ResolvedCredential, NeedsAuth   # verified: packages/ai-parrot/src/parrot/auth/credentials.py:162, 65, 82
from parrot_tools.business_automation.models import ImportRun, OperationKind  # verified: packages/ai-parrot-tools/src/parrot_tools/business_automation/__init__.py:9
from parrot_tools.business_automation.ingest import checkpoint_dir_for, compute_statement_digest   # verified: ingest.py:86, 99
from parrot_tools.business_automation.toolkit import _credential_resolver_from_broker   # verified: toolkit.py:49 (private; same distribution — documented reuse)
from parrot_tools.browsing import WebBrowsingToolkit                          # verified: packages/ai-parrot-tools/src/parrot_tools/browsing/__init__.py:32
from parrot_tools.scraping.session_actions import CredentialResolverFn        # verified: session_actions.py:65
from parrot_tools.scraping.drivers.abstract import AbstractDriver             # verified: packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py:34
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver  # verified: playwright_driver.py:15
from parrot.tools.toolkit import ToolkitTool                                  # verified: packages/ai-parrot/src/parrot/tools/__init__.py:150
from parrot_loaders.excel import ExcelLoader                                  # verified: ingest.py:65; class at packages/ai-parrot-loaders/src/parrot_loaders/excel.py:21
import pandas as pd                                                           # verified: business_automation extra, pyproject.toml:107
import yaml                                                                   # verified: installed (6.0.2); declared in the new `hooba` extra
import aiohttp                                                                # verified: core dependency; aiohttp.test_utils available (pytest-aiohttp 1.1.1)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/openapitoolkit.py
import httpx                                                                  # line 29 — TID251-exempt file (ruff.toml:161); used only for the sync spec fetch at line 255
class OpenAPIToolkit(AbstractToolkit):                                        # line 45
    def __init__(self, spec: Union[str, Dict[str, Any]], service: str, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, auth_type: str = "bearer", auth_header: str = "Authorization",
                 api_key_location: str = "header", api_key_name: str = "api_key",
                 credentials: Optional[Dict[str, str]] = None, use_proxy: bool = False, timeout: int = 30,
                 debug: bool = False, **kwargs)                               # lines 62-76
    # self.http_service = HTTPService(accept='application/json', headers=headers, credentials=creds, use_proxy=..., timeout=..., debug=..., **kwargs)  # lines 151-159
    # self.operations = self._parse_operations()                             # line 162
    # self._generate_dynamic_methods()                                        # line 174
    def _load_spec_with_prance(self, spec) -> Dict[str, Any]                  # lines 176-330
    def _parse_operations(self) -> List[Dict[str, Any]]                       # lines 366-446 — dict keys: operation_id, path, method (UPPER), parameters{path,query,header,cookie}, request_body, summary, description (NO 'tags' today)
    def _normalize_path_for_method_name(self, path: str) -> str               # lines 448-469 — strips '/', drops braces, non-alnum → '_', lowercase
    def _create_pydantic_schema(self, operation) -> type[BaseModel]           # lines 500-603 — path params always added as required fields (lines 515-522)
    def _generate_dynamic_methods(self)                                       # lines 644-670 — setattr(self, method_name, bound_method); async_method._args_schema
    def _create_method_name(self, operation) -> str                           # lines 672-693 — f"{service}_{method}_{normalized_path}"
    def _create_operation_method(self, operation)                             # lines 695-810 — inner `operation_method(self_ref, **kwargs)`; request at lines 759-764:
    #   result, error = await self_ref.http_service._request(**request_kwargs, full_response=False, use_proxy=False, raise_for_status=False)
    #   errors → ToolResult(status="error", ...).model_dump(); generic `except Exception` at line 795
    def _build_operation_url(self, operation, params) -> str                  # lines 812-837 — substitutes only params present in `params`

# packages/ai-parrot/src/parrot/interfaces/http.py  (TID251-exempt, ruff.toml:156)
class HTTPService(CredentialsInterface, PandasDataframe):                     # line 140
    def __init__(self, *args, **kwargs)                                        # lines 150-202; self.headers merged defaults (183-191); self.cookies = kwargs.get('cookies', {}) (line 191) — NOT consumed by _request
    async def process_response(self, response, url: str) -> tuple             # lines 522-687 — status >= 400 → logs, then `raise ConnectionError(f"HTTP Error {status}: ...")` (line 568) unless self.no_errors matches
    async def _request(self, url: str, method: str = 'get', cookies: Optional[httpx.Cookies] = None,
                       params=None, data=None, headers=None, timeout=30.0, use_proxy=True, free_proxy=False,
                       use_ssl=True, use_json=False, follow_redirects=True, raise_for_status=True,
                       full_response=False, ..., num_retries=2, **kwargs) -> Dict[str, Any]   # lines 1610-1631
    #   builds a NEW httpx.AsyncClient(cookies=cookies, headers=headers, ...) per call (line 1732) — a plain dict works for `cookies`
    #   full_response=True → returns (response, None) BEFORE process_response (lines 1754-1759); response is httpx.Response (.status_code, .cookies, .content)
    #   full_response=False → return await self.process_response(response, url) (lines 1760-1764)

# packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py
def _build_toolkit_subclass(service: str, spec: Any, **defaults: Any) -> type   # lines 18-41 — pattern only; HoobaOpenAPIToolkit is an explicit subclass

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                                   # line 203
    exclude_tools: tuple[str, ...] = ()                                       # line 240
    confirming_tools: frozenset = frozenset()                                 # line 273
    credential_provider: str | None = None                                    # line 304
    auto_open: bool = False                                                   # line 311
    def __init__(self, **kwargs)                                              # lines 329-376 — sets self.logger, self._opened, self._open_lock
    async def _open(self) -> None                                             # lines 398-412
    async def _close(self) -> None                                            # lines 414-425 — MUST call super()._close()
    async def _ensure_open(self) -> None                                      # lines 427-444
    async def _prepare_kwargs(self, tool_name, kwargs) -> dict                # lines 446-461
    def get_tools(self, permission_context=None, resolver=None) -> list[AbstractTool]   # lines 494-524
    def _generate_tools(self) -> None                                         # lines 547-590 — every public coroutine method not in exclude_tools becomes a tool

# packages/ai-parrot/src/parrot/tools/abstract.py
class ToolResult(BaseModel):                                                  # line 250 — success, status, result, error, metadata, timestamp, files, images

# packages/ai-parrot/src/parrot/auth/broker.py
class CredentialBroker:                                                       # line 419
    def __init__(self, *, audit_ledger=None, identity_mapper=None) -> None    # lines 455-466
    def register(self, provider: str, resolver: CredentialResolver, auth_kind: str = "oauth2") -> None   # lines 468-491
    async def resolve(self, provider: str, channel: str, user_id: str, **ctx) -> ResolvedCredential | NeedsAuth   # lines 543-639

# packages/ai-parrot/src/parrot/auth/credentials.py
class ResolvedCredential(BaseModel): provider: str; secret: Any; key_fingerprint: str      # lines 65-79
class NeedsAuth(BaseModel): provider: str; auth_url: str; auth_kind: AuthKind; ...        # lines 82-110
class CredentialResolver(ABC):                                                # line 162
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]      # line 166
    async def get_auth_url(self, channel: str, user_id: str) -> str           # line 175

# packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py
_BROKER_INVOCATION_CHANNEL = "business_automation"                            # line 46
def _credential_resolver_from_broker(broker: "CredentialBroker", user_id: str) -> CredentialResolverFn   # lines 49-117 — dict secret → (username, password); NeedsAuth → None

# packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py
class OperationKind(str, Enum): READ = "read"; DRAFT = "draft"; SUBMIT = "submit"   # lines 20-30
class ImportRun(BaseModel): statement_digest: str; period: str; started_at: datetime  # lines 58-70

# packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py
def checkpoint_dir_for(operation: str) -> Path                                # lines 86-96 — $PARROT_STATE_DIR/business_automation/checkpoints/<operation>/
def compute_statement_digest(xlsx_path: Union[str, Path]) -> str              # lines 99-108 — sha256(bytes)[:16]
async def _load_expense_rows(xlsx_path, client_column, amount_column) -> List[Dict[str, str]]   # lines 111-151 — ExcelLoader(resolved_path, output_mode="row"); await loader.load(resolved_path, split_documents=False); pandas cross-check
def reconcile(bundle: ImportPlanBundle, registrations_out: int) -> Dict[str, Any]   # lines 415-441 — bound to ImportPlanBundle; Module 8 defines its own

# packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
class WebBrowsingToolkit(WebScrapingToolkit):                                 # line 64
    def __init__(self, catalog_dir="browsing_catalog", user_data_dir=None, profile_directory=None, browser_channel=None,
                 max_loop_iterations=50, credential_resolver=None, human_channel=None, session_based=True,
                 headless=False, confirm_runs=True, **kwargs) -> None         # lines 124-160 — driver_type/browser go through **kwargs to WebScrapingToolkit
    def _ensure_session_driver(self) -> AbstractDriver                        # lines 164-174 (sync)
    async def close_browser(self) -> Dict[str, Any]                           # lines 176-188
    async def run_site_action(self, site: str, action: str, params=None, include_requires=True, stop_on_error=True) -> Dict[str, Any]   # lines 382-418

# packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py
CredentialResolverFn = Callable[[Authenticate], Awaitable[Optional[Tuple[Optional[str], Optional[str]]]]]   # line 65
async def exec_get_cookies(driver: AbstractDriver, action: GetCookies) -> Dict[str, Any]   # lines 288-331 — reads `document.cookie` via driver.execute_script (line 302): NO HttpOnly cookies, no domain metadata (lines 320-328). NOT used by Module 7.

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver:                                                         # line 11 — no cookie API today; `evaluate` at line 232

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):                                       # line 15
    self._context: Any = None; self._page: Any = None                          # lines 35-36; context created in start() at lines 99 / 113
    async def evaluate(self, expression: str) -> Any                          # line 269

# packages/ai-parrot/src/parrot/tools/toolkit.py (cont.)
    def _create_tool_from_method(self, name: str, bound_method) -> ToolkitTool   # lines 647-701 — sets routing_meta['requires_confirmation'] only for names in confirming_tools (lines 693-698); no operation metadata
# packages/ai-parrot/src/parrot/tools/openapitoolkit.py (cont.)
    operation_method._operation = operation                                   # line 806 — the operation dict is reachable from the bound method

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py
class GetCookies(BrowserAction): names: Optional[List[str]]; domain: Optional[str]   # lines 393-400
class Authenticate(BrowserAction): method; username; password; credential_provider; username_selector; password_selector   # lines 486-510

# packages/ai-parrot-loaders/src/parrot_loaders/excel.py
class ExcelLoader(AbstractLoader):                                            # line 21
    def __init__(self, source=None, *, ..., sheets=None, header=0, ..., output_mode: Literal["sheet","row"] = "sheet", ...)   # lines 38-60
```

### Hooba API contract (external, pinned — `sdd/state/FEAT-602/hooba-openapi-digest.json`)
| Operation | Body / shape | Kind |
|---|---|---|
| `POST /auth/login` `{username, password}` → 200 `User` + `Set-Cookie: sid`; 401; 409 | JSON | session (not a tool) |
| `GET /auth/check` → current user | — | READ (not generated; used by tests) |
| `GET /accounts/{accountId}/member` → `{member, user, roleIds, ...}` | — | READ |
| `POST /accounts/{accountId}/invoices` `{invoiceSerieId, simplified, currencyId, languageId, contactId, paymentMethodId, paymentTermId, subjectToIncomeTax, reference, operationDate, notes, ...}` → `Invoice{state ∈ canceled|draft|issued|replaced|scheduled}` | JSON | DRAFT |
| `POST /accounts/{accountId}/invoices/{invoiceId}/invoice-lines` — `oneOf` Product `{type, name, price, quantity, discount, taxId, incomeTaxId, accountingAccountId, notes, ...}` / Title `{type, name}` | JSON | DRAFT |
| `POST /accounts/{accountId}/invoices/{invoiceId}:issue` | — | **SUBMIT — blocked** |
| `POST /accounts/{accountId}/purchase-invoices` `{date, number, simplified, currencyId, contactId, paymentMethodId, bankAccountId, accountingDate, operationDate, notes, subjectToIncomeTax, taxIncluded, ...}` → `PurchaseInvoice{state ∈ confirmed|draft|replaced}` | JSON | DRAFT |
| `POST /accounts/{accountId}/purchase-invoices/{id}/purchase-invoice-lines` `{accountingAccountId, productId, name, price, unitOfMeasureId, quantity, discount, taxId, incomeTaxId, notes}` | JSON | DRAFT |
| `POST /accounts/{accountId}/purchase-invoices/{id}:confirm` | — | **SUBMIT — blocked** |
| `POST /accounts/{accountId}/documents/{documentTypeId}/{entityRecordId}` `file` + `data` | multipart/form-data | DRAFT |
| `GET /accounts/{accountId}/invoices/{invoiceId}:download` | binary | READ |
| `GET /accounts/{accountId}/contacts`, `/invoice-series`, `/document-types`, `/accounting-accounts`; `GET /taxes` (`Tax{percentage, operationType, selectableForSimplifiedInvoice, ...}`), `/income-taxes` | — | READ |

No `servers`, no `securitySchemes`, no global `security` in the document; the
captured browser request used headers `origin: https://app.hooba.com`,
`x-hooba-language: es`, `ngsw-bypass: true`, `cookie: sid=…`.

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `OpenAPIToolkit` cookie branch | `HTTPService._request(cookies=, headers=, full_response=True)` then `process_response()` | method calls | `http.py:1610-1631, 1754-1764, 522-568` |
| `OpenAPIToolkit._create_pydantic_schema` | path-param loop | skip names in `path_defaults` | `openapitoolkit.py:515-522` |
| `HoobaOpenAPIToolkit` | `OpenAPIToolkit.__init__` | `super().__init__(..., auth_type="cookie", ...)` | `openapitoolkit.py:62-76` |
| `make_login_hook` | `CredentialBroker.resolve("hooba", "hooba", user_id)` | await | `broker.py:543` |
| `EnvCredentialResolver` | `CredentialBroker.register(..., auth_kind="static_key")` | registration | `broker.py:468-491` |
| `HoobaToolkit.get_tools` | `AbstractToolkit.get_tools` + nested `HoobaOpenAPIToolkit.get_tools` | list concat | `toolkit.py:494-524` |
| `HoobaToolkit._open` | `HoobaOpenAPIToolkit._ensure_session` | await (auto_open) | `toolkit.py:398-444` |
| `HoobaWebAdapter.recover_session` | `WebBrowsingToolkit.run_site_action` → `_ensure_session_driver` → `PlaywrightDriver.get_cookies` (new) | awaits | `browsing/toolkit.py:382, 164`; `playwright_driver.py:269` (insertion point) |
| `HoobaOpenAPIToolkit._create_tool_from_method` | `AbstractToolkit._create_tool_from_method` + `bound_method._operation` | override | `toolkit.py:647`; `openapitoolkit.py:806` |
| `HoobaWebAdapter` credentials | `_credential_resolver_from_broker(broker, user_id)` | `credential_resolver=` kwarg | `business_automation/toolkit.py:49`; `browsing/toolkit.py:130` |
| `parse_bbva_statement` | `compute_statement_digest`, `ExcelLoader(output_mode="row")` | calls | `ingest.py:99, 136-137` |
| `ImportManifest` | `checkpoint_dir_for("hooba_bbva_import")` | path | `ingest.py:86` |
| `BbvaImporter` | `HoobaToolkit.hooba_find_contact` / `hooba_create_purchase_invoice_draft` | injected callables | §3 M10 |
| `TOOL_REGISTRY["hooba"]` | `parrot_tools.__init__` | dict entry | `parrot_tools/__init__.py:13, 36` |

### Does NOT Exist (Anti-Hallucination)
- ~~`OpenAPIToolkit(auth_type="cookie")`~~, ~~`login_hook`~~, ~~`extra_headers`~~, ~~`path_defaults`~~, ~~`include_tags`~~, ~~`exclude_paths`~~, ~~`exclude_methods`~~, ~~`max_tools`~~, ~~`set_cookies()`~~, ~~`get_cookies()`~~, ~~`_ensure_session()`~~ — all added by Module 1; today the constructor accepts only bearer/apikey/basic (`openapitoolkit.py:68`).
- ~~`operation["tags"]`~~ in `_parse_operations` output — not recorded today (`openapitoolkit.py:436-444`); Module 1 adds it.
- ~~A persistent cookie jar in `HTTPService`~~ — `self.cookies` (`http.py:191`) is stored but **not** passed by `_request`, which creates a fresh `httpx.AsyncClient` per call (`http.py:1732`). Cookies must be passed per call.
- ~~`HTTPService._request(files=...)`~~ — no multipart file support; `**kwargs` go to `httpx.AsyncClient`, not to the request. Use `aiohttp.FormData` for the document upload.
- ~~`HTTPService.process_response` returning an error tuple on 401~~ — it **raises** `ConnectionError` (`http.py:568`). Read `response.status_code` with `full_response=True` first.
- ~~`parrot_tools.hooba`~~ (any module), ~~`HoobaToolkit`~~, ~~`HoobaOpenAPIToolkit`~~, ~~`HoobaSettings`~~, ~~`HoobaWebAdapter`~~ — all new.
- ~~`parrot_tools.finance.parse_bank_excel`~~, ~~`parrot_tools.finance.AeatRule`~~, ~~`DeductibilityVerdict`~~, ~~`aeat_rules_v1.yaml`~~, ~~`taxonomy_es_autonomo_v1.yaml`~~ — Spec A (FEAT-478) was never decomposed; no `parrot_tools/finance/` package exists (only the unrelated `finance` extra with ta-lib/yfinance, `pyproject.toml:75`).
- ~~`ExcelStructureAnalyzer` in `parrot_loaders`~~ — the class lives in core `parrot/tools/dataset_manager/excel_analyzer.py:133`; the BBVA parser does not use it (pandas + openpyxl only).
- ~~`WebBrowsingToolkit.get_cookies` tool~~ / ~~`export_cookies`~~ / ~~`AbstractDriver.get_cookies()`~~ — no driver-level cookie API exists today; Module 7 adds `get_cookies()` to `AbstractDriver` (default `NotImplementedError`) and `PlaywrightDriver` (`self._context.cookies()`). `exec_get_cookies` exists but reads `document.cookie` and is **not** suitable for an HttpOnly session cookie.
- ~~`routing_meta["operation_kind"]`~~ — no such key exists anywhere; Module 4 introduces it on generated tools. `ToolManager` today reads only `requires_grant` / `requires_confirmation` (`manager.py:527, 554, 927-928`).
- ~~`hooba-login` / any Hooba catalog JSON in the repo~~ — the catalog is private (`examples/agents/web/services/catalog/hooba/` is untracked and stays so); tests build a temp catalog via `seed_catalog()`.
- ~~Hooba API token / API key / `securitySchemes`~~ — none in the document (U5: cookie only).
- ~~`POST /accounts/{accountId}/inbox-files`~~ — no upload endpoint for inbox files; only `GET`/`DELETE`/`:download`.
- ~~`BusinessAutomationToolkit.run_operation` for API calls~~ — it binds `flow_ref` to a browser `ScrapingFlow` (`models.py:33-55`); the hooba package calls the API toolkit directly.
- ~~`sdd/tasks/index/auto-finance-toolkit.json`~~ — FEAT-478 has no task index.

### Edit Sites (Blueprint Anchors)

Verified against: `9476f48e1` (2026-09-25)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `auth_type: str = "bearer",  # "bearer", "apikey", "basic"` | `openapitoolkit.py:68` | 1 |
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `self.http_service = HTTPService(` | `openapitoolkit.py:151` | 1 |
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `self.operations = self._parse_operations()` | `openapitoolkit.py:162` | 1 |
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `def _parse_operations(self) -> List[Dict[str, Any]]:` | `openapitoolkit.py:366` | 1 |
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `def _create_pydantic_schema(` | `openapitoolkit.py:500` | 1 |
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `result, error = await self_ref.http_service._request(` | `openapitoolkit.py:759` | 1 |
| `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | MODIFY | `def _build_operation_url(` | `openapitoolkit.py:812` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | `"business_automation": "parrot_tools.business_automation.toolkit.BusinessAutomationToolkit",` | `__init__.py:36` | 1 |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `business_automation = ["pandas>=2.0", "ai-parrot-loaders"]` | `pyproject.toml:107` | 1 |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `all = [` | `pyproject.toml:108` | 1 |
| `packages/ai-parrot-tools/pyproject.toml` | MODIFY | `"parrot_tools.aws.policies" = ["*.json"]` | `pyproject.toml:132` | 1 |
| `docs/business-automation-runbook.md` | MODIFY | `## 7. Scheduled canary (\`SmokeCheck\`, Decision D4)` | `runbook.md:225` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | MODIFY | `    async def evaluate(self, expression: str) -> Any:` | `abstract.py:232` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | `    async def evaluate(self, expression: str) -> Any:` | `playwright_driver.py:269` | 1 |
| `packages/ai-parrot/tests/tools/test_openapi_cookie_session.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/settings.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/credentials.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/models.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/openapi.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/toolkit.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/web.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/importer.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/spec/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/spec/prune.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/spec/hooba-api-2026.6.17.pruned.json` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/bbva.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/bank/manifest.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/rules/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/rules/engine.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/rules/autonomo_es_v1.yaml` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/hooba/__init__.py`, `conftest.py`, `fake_server.py`, `fixtures/make_bbva_fixture.py`, `test_*.py` | CREATE | — | — | — |
| `docs/hooba-toolkit.md` | CREATE | — | — | — |
| `examples/agents/finance/hooba_agent.py` | CREATE (`git add -f`) | — | — | — |

- An anchor with occurrences `1` attaches uniquely; `/sdd-task` re-runs `grep -c` for every row it uses.

---

## 7. Implementation Notes & Constraints

> Architecture decisions stay with the thinking model. A delegated
> implementation may only express a decision already recorded here and in
> the TASK's implementation blocks — it must never invent an API, choose a
> file, or resolve an open design question.

### Patterns to Follow
- **Cookie branch is additive**: in `_create_operation_method`, branch on `self_ref.auth_type == "cookie"`; the non-cookie call at `openapitoolkit.py:759-764` stays byte-identical (AC-4).
- **Bound-subclass** pattern from `openapi_register._build_toolkit_subclass` for `HoobaOpenAPIToolkit`; `service="hooba"` so generated names are `hooba_<method>_<path>`.
- **`auto_open=True` + `_open`/`_close`** (FEAT-391) on `HoobaToolkit`; `_close()` must `await super()._close()`.
- **`OperationKind` on every tool** (Decision D2 vocabulary) — v1 has no SUBMIT, but `classify_operation()` already returns SUBMIT for blocklisted paths so a later feature only flips the blocklist and adds `confirming_tools`.
- **Broker-backed credentials** — `EnvCredentialResolver` returns the `{"username","password"}` dict `_credential_resolver_from_broker` expects; never literal secrets in catalog JSON (`PlanDirectoryStore` already rejects them for plans).
- **Idempotent import** — `compute_statement_digest` + row index identity, manifest before/after each create, resume-without-duplicates (same discipline as `ingest.py`, FEAT-453 AC-12).
- **Spanish-locale parsing is data** — `HEADER_TOKENS`, amount/date parsers are small pure functions with their own tests.
- **Pure rule engine** — no I/O inside `RuleEngine.match/assess`; YAML loaded once.
- **`ToolResult(...).model_dump()`** envelopes for every tool, `metadata.operation_kind` set; errors return `status="error"` with a `next_tool` hint (e.g. `hooba_recover_web_session`) instead of raising into the agent loop.
- **aiohttp only** in the new package (TID251); the only httpx surface is inside the exempt `HTTPService`.
- **Logging** through `self.logger`; never log cookie values, passwords, IBANs or full bank rows at INFO.

### Known Risks / Gotchas
- **Session semantics unverified at runtime** (cookie TTL, CSRF, whether `origin`/`ngsw-bypass` are enforced). Mitigation: `GET /auth/check` in `_open`, single re-login on 401, `HOOBA_LIVE=1` smoke test, and `hooba_recover_web_session` as the manual escape hatch.
- **`process_response` raises on ≥ 400** (`http.py:568`) and prints headers with `print()` (`http.py:535-536`, out of scope) — cookie mode must inspect `status_code` first; a 4xx other than 401 becomes an error ToolResult carrying the status and body excerpt.
- **Login endpoint may set the cookie on a redirect** — `follow_redirects` default is `True` in `_request`; read `response.cookies` **and** `response.history[*].cookies` in the hook.
- **Spec drift**: the pin is `2026.6.17`; `load_pinned_spec` warns on version change and fails on missing required paths. Regenerate with the pruner; review the diff of generated tool names in the PR.
- **Tool-budget**: 58 generated + ≤ 10 composite by default; `MAX_TOOLS=80` is a construction-time guard. Agents that need less pass `include_tags`; agents can never widen the write set (`DRAFT_OPERATIONS` is a constant, not a parameter).
- **HttpOnly session cookie**: Hooba's `sid` is almost certainly HttpOnly, so `document.cookie`-based export returns nothing. Session recovery uses the browser context (`PlaywrightDriver.get_cookies`) and fails closed; Selenium drivers get the default `NotImplementedError` (out of scope).
- **Orphan drafts**: a crash between the header POST and the line POSTs leaves a draft with fewer lines. The `[parrot:<key>]` marker in `notes` lets the retry find and complete it; transport retries are disabled for writes in cookie mode so the transport itself can never duplicate a POST.
- **Blocking I/O**: workbook parsing and manifest writes run in `asyncio.to_thread`; the fake-server tests assert the loop stays responsive with a 5 000-row workbook.
- **Line bodies are `oneOf`** (Product | Title): `_create_pydantic_schema` flattens only `type: object` bodies; `oneOf` falls to a single `body` field. Composite tools build the Product body explicitly; the generated line tools remain usable but coarse — document it.
- **Id lookups depend on account master data** (default invoice serie, taxes with `operationType`, document types named for invoices): missing → `HoobaLookupError`, never a guess. The live smoke test lists them.
- **Contact matching is fuzzy**: threshold 0.85 with `difflib` (stdlib; no rapidfuzz dependency outside the `scraping` extra). False positives are mitigated by writing the match score and the original concept into `notes`.
- **BBVA layout is assumed** (§8 Q2). Header detection is token-based so real exports with extra/renamed columns degrade to `ValueError('BBVA header row not found')`, never to silently wrong drafts.
- **Regulatory correctness cannot be verified from the codebase** — every verdict is `review_required` in v1, drafts only, `legal_basis` mandatory; the table is versioned data (`autonomo_es_v1`).
- **Public/private seam**: CI never sees real selectors; the web-half integration test is opt-in against the FEAT-455 fixture site.
- **Concurrency**: `_ensure_session` is lock-guarded; the web adapter inherits `WebBrowsingToolkit._run_lock`.
- **Untracked example assets** stay untracked; the new example under `examples/agents/finance/` needs `git add -f` (`examples/**/*.py` is git-ignored).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiohttp` | core dep | login hook transport is `HTTPService` (httpx, exempt); multipart upload and the spec fetch use aiohttp directly |
| `pyyaml` | `>=6.0` | rule table (already a core transitive dep; declared in the `hooba` extra) |
| `openpyxl` | `>=3.1` (extra `excel`) | BBVA `.xlsx` parsing and the synthetic fixture generator |
| `pandas` | `>=2.0` (extra `business_automation`) | sheet scanning / row cross-check |
| `ai-parrot-loaders` | workspace | `ExcelLoader` row-count cross-check |
| `playwright` | `>=1.52` (extra `scraping`) | web fallback (lazy) |
| `prance` | core | already used by `OpenAPIToolkit` to resolve `$ref` |
| `pytest-aiohttp` | dev (installed 1.1.1) | `aiohttp_server` fixture for the fake Hooba server |

---

## 8. Open Questions

> Questions that must be resolved before or during implementation.

- [x] U1 — Where does the Hooba Playwright catalog live? — *Resolved in proposal*: Keep private, `catalog_dir` from env (`HOOBA_CATALOG_DIR`); the package ships only `seed_catalog()`. → §2 Overview, M7, AC-13.
- [x] U2 — Tool surface? — *Resolved in proposal*: Full `OpenAPIToolkit` generation with cookie auth added to core and a tag allowlist. → M1, M4, AC-5/6.
- [x] U3 — BBVA row → draft mapping? — *Resolved in proposal*: One `simplified=true` purchase-invoice draft per debit row; `contactId` only when the merchant matches an existing contact (≥ 0.85), else `null` + note. → M10, AC-11.
- [x] U4 — Deductibility rules now or block on FEAT-478? — *Resolved in proposal*: v1 rule table inside `parrot_tools/hooba/rules/`, shaped like Spec A's `AeatRule`/`DeductibilityVerdict` for later extraction. → M9, AC-12.
- [x] U5 — Auth and legal-effect operations? — *Resolved in proposal*: Cookie session only (`POST /auth/login`, `sid`, re-login on 401); v1 never issues/confirms. → M1, M2, M4 blocklist, AC-1/5.
- [x] Q1 (proposal, deferred to spec) — Default tag allowlist and hard cap? — *Resolved in spec*: `DEFAULT_INCLUDE_TAGS` (16 drafting + lookup tags, 80 tools on 2026.6.17), `MAX_TOOLS = 96`, per-agent override via `include_tags` / `HOOBA_INCLUDE_TAGS`. `Product`, `Account`, `Member` are not generated (member data via `hooba_whoami`).
- [ ] Q2 — Exact BBVA export layout (sheet name, preamble rows, header labels, date/amount formats). The synthetic fixture assumes `Fecha | F.Valor | Concepto | Movimiento | Importe | Divisa | Disponible | Observaciones` after 6 preamble rows. — *Owner: Jesús (provide one anonymized workbook before M8 is verified)*
- [ ] Q3 — Gestoría review of the v1 rule table (percentages, caps, `legal_basis` citations, which categories may drop `review_required`). — *Owner: Jesús / gestoría; blocks nothing in code, gates trusting the verdicts*
- [ ] Q4 — Which document type in this account attaches to invoices / purchase invoices (`GET /document-types` names) and which invoice serie is flagged default for simplified invoices — to be confirmed by the `HOOBA_LIVE=1` smoke test on first run. — *Owner: Jesús*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.156.1, reasoning `high`, 5 min 5 s) · Status: completed
> · Transcript: `sdd/state/FEAT-602/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).
> All 24 `affected_paths` passed the containment and existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make cookie persistence an explicit session-owned contract (architecture) | CONFIRM | Verified: `_request` builds a fresh `httpx.AsyncClient` per call (`http.py:1732`) and `self.cookies` is never consumed. The jar lives in `OpenAPIToolkit`, is passed per call, login is lock-serialized, cookies are read from `response.cookies` and redirect history. | §2 Overview, M1 (`_ensure_session`), §4 `test_cookie_mode_concurrent_first_use_logs_in_once` |
| S2 | Replace tag-plus-string blocklisting with an explicit default-deny operation manifest (risk) | CONFIRM | Verified against the digest: the tag+regex design still generated `POST contacts`, `POST invoice-series`, `accounting-accounts:seed` and 30+ other writes. Writes are now an explicit 11-entry `DRAFT_OPERATIONS` set; everything else is denied. Surface drops from 80 to 58 tools. | M1 `operation_filter`, M4 `DRAFT_OPERATIONS`/`is_allowed`, AC-3, AC-5, `test_default_deny_writes` |
| S3 | Prevent raw generated tools from bypassing the submit gate (architecture) | CONFIRM | Verified: `_create_tool_from_method` marks only `confirming_tools` names (`toolkit.py:693-698`); generated tools carry no operation metadata. M4 overrides it to stamp `routing_meta['operation_kind']` (and `requires_confirmation` for SUBMIT, unreachable in v1) from `bound_method._operation` (`openapitoolkit.py:806`). | M4 `_create_tool_from_method`, AC-5, `test_generated_tools_carry_operation_kind_routing_meta` |
| S4 | Define path-default precedence and hide account identifiers from schemas (api) | CONFIRM | Hidden-from-schema was already specified; precedence was not. Defaults now always win, a caller value for a defaulted name is dropped with a WARNING. | M1 `_build_operation_url` docstring, AC-3, `test_path_defaults_override_caller_value` |
| S5 | Pin and validate the complete OpenAPI document, not only the compact digest (risk) | CONFIRM | The reviewer only saw the research digest; the spec already pins a pruned *full* document (paths + components + servers). Added: `PINNED_SHA256` asserted at load, fail closed on mismatch; override path warns. | M3, AC-9, `test_pinned_spec_sha256_mismatch_fails_closed` |
| S6 | Handle multipart, binary and oneOf payloads outside generic JSON generation (api) | CONFIRM | Verified: `_parse_operations` prefers JSON/form only, `_request` has no file support, `oneOf` bodies collapse to one `body` field. Multipart upload, PDF download and the Product-line body are composite tools with explicit models; the generated `documents` POST and `:download` GETs are excluded from generation. | M4 `READ_PATH_BLOCKLIST`/`DRAFT_OPERATIONS`, M6 docstrings, §7 gotchas |
| S7 | Specify how environment credentials become a broker provider (architecture) | CONFIRM | Verified: the broker's `static_key` factory path is vault-backed; `resolve` raises `KeyError` for an unregistered provider and `ValueError` for an empty identity (`broker.py:582-590`). M2 already defined `EnvCredentialResolver` + `register_hooba_provider`; added the fail-closed-before-network tests. | M2, AC-8, `test_login_hook_fails_closed_before_network` |
| S8 | Do not depend on `document.cookie` for REST session transfer (risk) | CONFIRM | Verified: `exec_get_cookies` runs `return document.cookie` (`session_actions.py:302`) — HttpOnly cookies are invisible. Added a context-level `get_cookies()` capability to `AbstractDriver` (default `NotImplementedError`) and `PlaywrightDriver` (`self._context.cookies()`); recovery fails closed without `sid`. | M7, AC-13, §6 edit sites (`abstract.py:232`, `playwright_driver.py:269`), opt-in fixture-site test |
| S9 | Make bank imports await actual draft completion (architecture) | REJECT | Not applicable: the reviewer assumed the importer rides `BusinessAutomationToolkit.run_operation` / `ingest.build_import_plan` (fire-and-forget). FEAT-602's `BbvaImporter.apply` never touches either — it awaits `create_draft` → `DraftReceipt` and writes the manifest only afterwards (already in M10; wording made explicit). | — (M10 docstring clarified, AC-11) |
| S10 | Keep workbook parsing off the event loop (risk) | CONFIRM | Verified: `ingest._load_expense_rows` calls `pd.read_excel` synchronously inside an `async def`. The BBVA parser wraps its sync core in `asyncio.to_thread`; manifest writes likewise. | M8, AC-11, `test_parse_bbva_runs_off_event_loop` |
| S11 | Add idempotency across header-plus-line draft creation (risk) | CONFIRM | Verified: no correlation mechanism existed and `_request` defaults to `num_retries=2` at transport level. Added `correlation_key` on drafts/receipts, a `[parrot:<key>]` marker in `notes`, a reuse scan before creating, `num_retries=0` for cookie-mode writes, and `row_id` as the BBVA key. | M1, M5, M6, M10, AC-3, AC-7, `test_create_draft_reuses_existing_by_correlation_key` |
| S12 | Preserve the existing AEAT verdict contract and fail closed on uncertainty (risk) | CONFIRM | The verdict already mirrored Spec A's field names; added raw `evidence`, same-priority ambiguity → fallback, and the explicit rule that no percentage is ever guessed. | M5, M9, AC-12 |

Summary: **11** confirmed · **1** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for FEAT-602
  (`.claude/worktrees/feat-FEAT-602-hooba-toolkit`, from `origin/dev`); the
  `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (edge = imports a symbol defined by the target):
  - M4 → M1 (`OpenAPIToolkit(auth_type="cookie", login_hook=…, path_defaults=…, include_tags=…)`)
  - M4 → M2 (`HoobaSettings`, `LoginHook` from `make_login_hook`), M4 → M3 (`load_pinned_spec`)
  - M6 → M2, M4, M5, M7, M10; M7 → M2 (settings, broker resolver); M7 also MODIFIES `scraping/drivers/{abstract,playwright_driver}.py` (no other module touches them)
  - M8 → M5 (`BankExpenseRow`, `BbvaStatement`); M9 → M5 (`DeductibilityVerdict`, `HoobaMapping`)
  - M10 → M5, M8, M9 (and M4 only through injected callables — no import)
  - M11 → M6 (registry path), M3/M9 (package data)
  - **No edge between**: M1, M2, M3, M5 (foundation — run concurrently); M8 vs M9 (concurrent); M7 vs M8/M9/M10 (concurrent).
- **Shared files**: `parrot_tools/hooba/__init__.py` — created by M5, extended by M6 (exports) and touched by nothing else; `packages/ai-parrot-tools/pyproject.toml` and `parrot_tools/__init__.py` — M11 only.
- **Exclusive resources**: `packages/ai-parrot-tools/pyproject.toml` (M11 adds the extra; run `uv lock` in the main checkout, never in the worktree) → M11 `parallel: false`. M1 touches core `ai-parrot`; its tests run with `PYTHONPATH=packages/ai-parrot/src` inside the worktree.
- **Cross-feature dependencies**: none. FEAT-478 (auto-finance) is explicitly *not* a prerequisite (U4). FEAT-453 (web-automation-infra) is merged and consumed as-is.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-25 | Jesús Lara + Claude Fable 5.1 | Initial draft from the accepted FEAT-602 proposal; codebase contract re-verified at `9476f48e1` |
