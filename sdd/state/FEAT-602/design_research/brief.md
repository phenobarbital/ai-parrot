<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
The original request, preserved (session cookie and personal data redacted).
The full source is at `sdd/state/FEAT-602/source.md`.

> Hooba (https://app.hooba.com/) es un software contable de gestión exigido por
> un convenio "Red.es", posee un API openAPI: https://api.hooba.com/api/doc
>
> Propiedades a registrar en `.env`: `HOOBA_ACCOUNT_ID`, `HOOBA_MEMBER_ID`,
> `HOOBA_USER_ID`, `HOOBA_SUBSCRIPTION_ID`; URLs como
> `https://api.hooba.com/accounts/{accountId}/member`, con headers
> `cookie: sid=…`, `origin: https://app.hooba.com`, `x-hooba-language: es`,
> `ngsw-bypass: true`. Authentication: `POST /auth/login {username, password}`
> con `HOOBA_USERNAME` / `HOOBA_PASSWORD`.
>
> **Task**: Construir una interfaz HTTP openAPI para interactuar con Hooba tanto
> via http (API REST openAPI) como vía web con playwright (operativa disponible
> previamente), construir una HoobaToolkit que combine ambas operativas (usar la
> API cuando se deba, via web para automatizar operaciones disponibles vía web).
> El Toolkit le debe permitir a un agente de ai-parrot:
> - crear facturas en modo borrador
> - declarar gastos y compras en modo borrador
> - subir un excel de relación de gastos del banco (BBVA) para convertirlos en
>   declaraciones de gastos, según la normativa vigente del Reino de España
>   para autónomos

Hooba publishes a real OpenAPI 3.0 document at `https://api.hooba.com/api/doc.json`
(version 2026.6.17, 656 paths), and creating an invoice or a purchase invoice
through it yields `state=draft` while issuing and confirming are separate calls —
so all three requested capabilities are API-first, and the Playwright half is a
fallback for session recovery, PDF downloads and gaps, not the data-entry path.
The repo already ships the pieces: `OpenAPIToolkit` generates tools from a spec
but only knows bearer/apikey/basic auth (Hooba needs a cookie session, and the
spec declares no security scheme), FEAT-453's `BusinessAutomationToolkit`
provides the draft/submit gate, plans directory, checkpoints and broker-backed
credentials, and `WebBrowsingToolkit` runs the existing — untracked,
navigation-only — Hooba catalog on Playwright. What does not exist is a BBVA
layout parser or any AEAT deductibility rule (Spec A, FEAT-478, was never
decomposed). The recommendation is a new `parrot_tools/hooba/` package built as
a cookie-authenticated, tag-allowlisted `OpenAPIToolkit` subclass plus composite
draft tools, a private-catalog web adapter, a BBVA parser and a v1 rule table,
with every legal-effect operation excluded from v1. Next step: `/sdd-spec`.

### Constraints and goals
- **Cookie-session auth, undeclared.** The spec has no `securitySchemes` and no
  global `security`; the only documented entry is `POST /auth/login
  {username, password}` → `User`, and the captured request carries `sid`,
  `origin`, `x-hooba-language`, `ngsw-bypass` headers none of which the spec
  declares. *Implication*: `OpenAPIToolkit` cannot authenticate unmodified; it
  needs a cookie auth mode with a login hook, cookie jar and re-login on 401.
  *Evidence*: F015, F009

- **httpx is banned (TID251).** `openapitoolkit.py` and `interfaces/http.py`
  are per-file exemptions. *Implication*: the new client goes through
  `HTTPService`/aiohttp; no new exemptions. *Evidence*: F009

- **Create = draft; issue/confirm are separate.** `InvoiceState =
  canceled|draft|issued|replaced|scheduled`, `PurchaseInvoiceState =
  confirmed|draft|replaced`; `:issue` and `:confirm` are their own POSTs.
  *Implication*: "borrador" maps 1:1 to the create calls (DRAFT-kind, unattended
  per Decision D2); `:issue`, `:confirm`, `:cancel`, `delete` are SUBMIT-kind and
  stay out of v1 (U5). *Evidence*: F015

- **970 operations.** Generated tool names follow `{service}_{method}_{path}`.
  *Implication*: full generation (U2) must be tag-allowlisted and SUBMIT-kind
  paths blocklisted, or the LLM tool budget floods. *Evidence*: F001, F015

- **Decision D2 gate vocabulary.** READ/DRAFT never touch `ConfirmationGuard`;
  SUBMIT always does, before the browser opens. *Implication*: classify every
  API tool with `OperationKind` so a future submit path inherits the gate.
  *Evidence*: F006, F016

- **Public engine / private plans.** FEAT-453 §8 resolved that site plans stay
  out of the repo; the auto-finance brainstorm later sanctioned an in-repo
  `parrot_tools/hooba/` package with `plans_dir` private. *Implication*: the
  package is public, the Playwright catalog stays private and is located via
  `HOOBA_CATALOG_DIR` (U1). *Evidence*: F008, F013, F016

- **The existing web operativa is navigation-only and untracked.** Login + 5
  navigations, no `draft_invoice`/`register_expense` script exists.
  *Implication*: "web for what is available via web" routes to session
  recovery, PDF download and API gaps in v1 — not to data entry. *Evidence*:
  F007, F008

- **No BBVA parser, no AEAT rules.** `ingest.py` maps only `client`+`amount`
  columns to a browser operation; Spec A's `parse_bank_excel`, `AeatRule` and
  `DeductibilityVerdict` were never implemented (no FEAT-478 task index).
  *Implication*: a real BBVA layout parser and a v1 rule table are net-new
  work (U4). *Evidence*: F004, F005, F012

- **Credentials through the broker.** `CredentialBroker` +
  `_credential_resolver_from_broker` is the sanctioned path; the local example
  bypasses it with navconfig. *Implication*: `HOOBA_USERNAME`/`HOOBA_PASSWORD`
  feed a static broker provider `hooba` used by both halves; never literal
  secrets in catalog JSON. *Evidence*: F003, F007

- **Packaging conventions.** New `parrot_tools` subpackages register in
  `TOOL_REGISTRY`, declare an optional extra, and test under
  `packages/ai-parrot-tools/tests/<pkg>/`. *Evidence*: F011

### Recommended option / probable scope
*(mode = enrichment)*

### What's New

- **`packages/ai-parrot-tools/src/parrot_tools/hooba/`** — new subpackage
  (already anticipated by the auto-finance brainstorm impact table). F013
- **`hooba/openapi.py`** — `HoobaOpenAPIToolkit`, a bound `OpenAPIToolkit`
  subclass (pattern: `_build_toolkit_subclass`) over the pinned spec digest
  with a **tag allowlist** (Authentication, Account, Member, Invoice,
  InvoiceLine, InvoiceSerie, PurchaseInvoice, PurchaseInvoiceLine, Contact,
  Tax, IncomeTax, AccountingAccount, PaymentMethod, PaymentTerm, Document,
  DocumentType, InboxFile) and a **SUBMIT blocklist** (`:issue`, `:confirm`,
  `:cancel`, `:send*`, `DELETE *`, `*:delete`, `:bulk-*`) — decision U2/U5.
  F001, F015
- **`hooba/session.py`** — `HoobaSession`: settings from `HOOBA_ACCOUNT_ID` /
  `HOOBA_MEMBER_ID` / `HOOBA_USER_ID` / `HOOBA_SUBSCRIPTION_ID`, login via
  `POST /auth/login` with credentials resolved from `CredentialBroker`
  provider `hooba`, `sid` cookie jar on `HTTPService`, explicit `origin`,
  `x-hooba-language`, `ngsw-bypass` headers, `GET /auth/check` probe, re-login
  on 401, account-scoped path substitution (`{accountId}` injected so the LLM
  never supplies it). F015, F009, F003
- **`hooba/models.py`** — Pydantic: `InvoiceDraft` + `InvoiceLineDraft`,
  `PurchaseInvoiceDraft` + `PurchaseInvoiceLineDraft` (gastos y compras),
  `ContactMatch`, `BankExpenseRow`, `ExpenseDraftBatch`, `DraftReceipt` (Hooba
  id + `state`). F015
- **`hooba/toolkit.py`** — `HoobaToolkit(AbstractToolkit, auto_open=True)`
  composing the generated API tools with **composite draft tools**:
  `create_invoice_draft` (resolves `invoiceSerieId`, `contactId`, `taxId`,
  posts header + lines), `create_purchase_invoice_draft` (same for expenses,
  `simplified` for tickets), `attach_document`, `list_drafts`,
  `import_bbva_statement`; every tool tagged with `OperationKind`; routing
  policy "API when the endpoint exists, web action otherwise". F006, F015
- **`hooba/web.py`** — thin adapter wiring `WebBrowsingToolkit` with
  `catalog_dir = $HOOBA_CATALOG_DIR` (private, U1) and the broker-backed
  `credential_resolver`; v1 web operations: login/session recovery (export
  `sid` via `exec_get_cookies` into the REST session), download invoice PDF,
  uploads the API lacks. F002, F007, F010
- **`hooba/bank/bbva.py`** — BBVA Excel layout parser (preamble-row detection,
  date/concept/amount/balance columns, `compute_statement_digest`) →
  `BankExpenseRow` list; debits only; dedupe by digest+row; row-count
  cross-check and `reconcile()` reuse. F004, F005, F012
- **`hooba/rules/autonomo_es_v1.yaml` + `hooba/rules/engine.py`** — v1
  data-driven deductibility table for autónomos (category matchers → `taxId`,
  `subjectToIncomeTax`, `simplified`, deductible %, `legal_basis`), shaped
  like Spec A's `AeatRule`/`DeductibilityVerdict` for later extraction to
  `parrot_tools/finance` — decision U4. F005, F012
- **`TOOL_REGISTRY["hooba"]`** + `hooba` extra in `ai-parrot-tools`
  (composes `business_automation` + `excel` + `scraping`). F011
- **`packages/ai-parrot-tools/tests/hooba/`** — aiohttp test server replaying
  the spec digest, anonymized BBVA fixture, rule-table tests, a "no SUBMIT
  path reachable" guarantee test, allowlist/blocklist tests. F011
- **Docs** — Hooba section in the business-automation runbook: env vars, spec
  pin `2026.6.17`, `HOOBA_CATALOG_DIR`, seed helper.

### What Changes

- **`packages/ai-parrot/src/parrot/tools/openapitoolkit.py`::`OpenAPIToolkit`**
  — add `auth_type="cookie"` (or `session`): an async `login_hook` invoked
  lazily before the first request, a cookie jar passed to `HTTPService`,
  `extra_headers`, and a `path_defaults` map for `{accountId}`-style
  parameters; plus `include_tags` / `exclude_paths` filters in
  `_parse_operations`. Required by decision U2 (full generation). *Evidence*:
  F009, F001
- **`packages/ai-parrot-tools/src/parrot_tools/__init__.py`::`TOOL_REGISTRY`**
  — add `"hooba": "parrot_tools.hooba.toolkit.HoobaToolkit"`. *Evidence*: F011
- **`packages/ai-parrot-tools/pyproject.toml`** — new `hooba` extra; include
  in `all`. *Evidence*: F011
- **`examples/agents/web/services/`** (untracked) — stays private; only a
  `seed_catalog` helper is generalized into the package. *Evidence*: F007

### What's Untouched (Non-Goals)

Explicitly out of scope, to prevent later scope creep:
- `parrot/clients/base.py` and every LLM client
- `BusinessAutomationToolkit`, `PlanDirectoryStore`, `ConfirmationGuard` —
  consumed as-is (Decision D2)
- Issuing invoices (`:issue`), confirming purchase invoices (`:confirm`),
  cancel/delete, sending emails, remittances/payments — SUBMIT-kind, never in
  v1 (U5)
- Norma 43 ingestion, DuckDB analytics, ExpenseWiki, ML classifier — Spec A
  (FEAT-478) scope
- Telegram / WhatsApp / Teams channels — CLI channel only for the example agent
- Hooba-side master data (invoice series, taxes, accounting accounts) — read
  via API, never created
- New Playwright data-entry scripts — the API covers the three capabilities

### Patterns to Follow

- Bound-subclass pattern from `openapi_register._build_toolkit_subclass` for
  the generated toolkit. *Evidence*: F001
- `auto_open=True` + `_open`/`_close` for the HTTP session and the lazy
  browser. *Evidence*: F006
- `OperationKind` tagging and D2 gate semantics for anything with legal effect.
  *Evidence*: F006, F016
- `compute_statement_digest` + manifest/resume + `reconcile()` for idempotent
  Excel imports. *Evidence*: F004
- Broker-backed credentials via `_credential_resolver_from_broker`; never
  literal secrets in JSON. *Evidence*: F003
- Catalog JSON DSL (`navigate` / `conditional` / `authenticate` / `wait`,
  `requires: ["hooba-login"]`) for any new web action. *Evidence*: F007, F002

### Integration Risks

- **Session semantics unknown at runtime** (cookie TTL, CSRF, whether the
  `origin`/`ngsw-bypass` headers are enforced): mitigate with the
  `GET /auth/check` probe, re-login on 401, and a live integration test gated
  by `HOOBA_LIVE=1`. *Evidence*: F015
- **Spec drift**: version `2026.6.17`, no `servers` block, Nelmio-generated —
  pin the digest in-repo, validate required fields at import, fail loudly on
  schema change. *Evidence*: F015
- **Tool-budget flood** with full generation: the tag allowlist bounds it to
  roughly the 217 digested operations; the spec must state a hard cap and a
  per-agent sub-allowlist. *Evidence*: F001, F015
- **Line bodies are `oneOf`** (product | title) and need `invoiceSerieId`,
  `contactId`, `taxId` lookups first — the composite tools must resolve ids
  before creating drafts. *Evidence*: F015
- **BBVA layout parser is net-new**; wrong column detection silently produces
  wrong drafts — row-count cross-check, `reconcile`, and an anonymized fixture
  are mandatory. *Evidence*: F004, F005
- **Regulatory correctness** of the deductibility table cannot be verified
  from the codebase — drafts only, `legal_basis` on every draft, human review
  before any confirmation. *Evidence*: F012, F005
- **Public/private seam**: the catalog stays private (U1), so CI cannot run
  the web half against real selectors — tests use the FEAT-455 fixture site.
  *Evidence*: F008, F016

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot/src/parrot/tools/openapitoolkit.py
packages/ai-parrot/src/parrot/interfaces/http.py
packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py
packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py
packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py
packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py
packages/ai-parrot-tools/src/parrot_tools/business_automation/store.py
packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py
packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
packages/ai-parrot/src/parrot/auth/broker.py
examples/agents/web/services/hooba_agent.py
examples/agents/web/services/catalog/hooba/hooba-login.json
packages/ai-parrot-tools/src/parrot_tools/__init__.py
packages/ai-parrot-tools/pyproject.toml
ruff.toml
sdd/specs/auto-finance-toolkit.spec.md
sdd/specs/web-automation-infra.spec.md
sdd/state/FEAT-602/hooba-openapi-digest.json

### Questions still open in the exploration document
- [ ] **Which Hooba tags form the default allowlist, and what is the hard cap on generated tools per agent?** — *Owner*: spec author
  *Blocks claims*: C9
  *Plausible answers*: a) the 17 tags in §3 (~217 ops) · b) a narrower "drafting" set (Invoice*, PurchaseInvoice*, Contact, Tax*) · c) configurable per agent definition
- [ ] **Exact BBVA export layout** (sheet name, preamble row count, column headers, date/amount formats) for the anonymized fixture — *Owner*: Jesús (provide one anonymized workbook)
  *Blocks claims*: C11
- [ ] **Initial content of the v1 rule table** (categories, IVA/IRPF flags, simplified-invoice threshold, `legal_basis` citations) — *Owner*: Jesús / gestoría review
  *Blocks claims*: C7

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
