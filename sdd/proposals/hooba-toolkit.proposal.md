---
id: FEAT-602
title: HoobaToolkit — cookie-session OpenAPI toolkit over api.hooba.com (draft invoices, draft purchase invoices) with the private Playwright catalog as fallback, and a BBVA-Excel → expense-draft pipeline for autónomos
slug: hooba-toolkit
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-25
  summary_oneline: "HoobaToolkit — OpenAPI (api.hooba.com) + Playwright hybrid toolkit: draft invoices, draft expenses/purchases, BBVA bank Excel → expense drafts for Spanish autónomos"
overall_confidence: medium
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-tools, ai-parrot, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [hooba, openapi, toolkit, browser-automation, playwright, finance, spain-autonomos, bbva]
research_state: sdd/state/FEAT-602/
created: 2026-09-25
updated: 2026-09-25
---

# FEAT-602 — HoobaToolkit: OpenAPI-first Hooba automation with a private Playwright fallback and BBVA expense drafts

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-602/`](../state/FEAT-602/)

---

## 0. Origin

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

**Initial signals** (extracted, not interpreted):
- Verbs: construir, combinar, crear, declarar, subir, convertir → additive, feature-shaped
- Named entities: Hooba, `api.hooba.com/api/doc`, OpenAPI, Playwright, HoobaToolkit, BBVA, Excel, facturas borrador, gastos y compras, `HOOBA_*` env vars, `/auth/login`, Red.es, AEAT/autónomos
- Components / labels: none (inline source)
- Acceptance criteria provided: 3 capability bullets, no formal AC

---

## 1. Synthesis Summary

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

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-602/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/tools/openapitoolkit.py` | `OpenAPIToolkit` | 62-160, 695-770 | dynamic OpenAPI→tools generator; aiohttp transport via `HTTPService`; auth limited to bearer/apikey/basic | F001, F009 |
| 2 | `packages/ai-parrot/src/parrot/interfaces/http.py` | `HTTPService` | 140-191, 272-351 | sanctioned aiohttp client (TID251-exempt); accepts `cookies`/`headers` per session | F009 |
| 3 | `packages/ai-parrot/src/parrot/bots/factory/tools/openapi_register.py` | `_build_toolkit_subclass`, `register_openapi_toolkit` | 18-60 | pattern for binding a spec into a registrable `OpenAPIToolkit` subclass | F001 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py` | `WebBrowsingToolkit` | 1-30, `__init__` | catalogued deterministic Playwright/Selenium site actions; `execute_web_task`; `credential_resolver`; `confirm_runs` | F002 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py` | `BusinessAutomationToolkit`, `_credential_resolver_from_broker` | 52-125, 128-260, 305-422 | domain-neutral engine: READ/DRAFT unattended, SUBMIT gated by `ConfirmationGuard`; `run_operation`/`resume_operation`; broker adapter | F003, F006 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/business_automation/models.py` | `OperationKind`, `BusinessOperation`, `ImportRun` | 28-70 | read/draft/submit classification and import discriminator | F006 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py` | `build_import_plan`, `_load_expense_rows`, `compute_statement_digest`, `make_import_progress_listener`, `reconcile` | 111-151, 222-280 | per-row ExecutionPlan import with digest-keyed manifest/resume; currently two-column and browser-operation bound | F004 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/business_automation/store.py` | `PlanDirectoryStore` | 14-16, 41-62, 84-136 | loads `*.operation.json` / `*.template.json` / `*.flow.json` from a private plans dir | F006 |
| 9 | `packages/ai-parrot-tools/src/parrot_tools/scraping/session_actions.py` | `exec_authenticate`, `exec_get_cookies`, `exec_upload_file`, `CredentialResolverFn` | 65, 74-79, 288, 722 | fail-closed browser login, cookie export (bridge to the REST session), file upload | F010 |
| 10 | `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | `PlaywrightDriver` | 15 | the Playwright driver the web half runs on | F002, F010 |
| 11 | `packages/ai-parrot/src/parrot/auth/broker.py` | `CredentialBroker` | 51, 276-326 | sanctioned secret source for `HOOBA_USERNAME`/`HOOBA_PASSWORD` (vault/static resolvers, signed ledger) | F003 |
| 12 | `examples/agents/web/services/hooba_agent.py` | `build_toolkit`, `resolve_hooba_credentials`, `HoobaNavigatorAgent` | 1-25, 62-91 | **untracked** local Playwright operativa: `WebBrowsingToolkit` + navconfig credentials + 6-action catalog (login + 5 navigations, no data entry) | F007, F014 |
| 13 | `examples/agents/web/services/catalog/hooba/hooba-login.json` | `hooba-login` | 1-45 | working login script (email/password selectors, `credential_provider: "hooba"`, waits for `/dashboard`) | F007 |
| 14 | `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | `TOOL_REGISTRY` | 13, 35-36 | where the new `hooba` toolkit is registered | F011 |
| 15 | `packages/ai-parrot-tools/pyproject.toml` | optional-dependencies | 37, 66, 73, 107-108 | `excel`, `scraping` (playwright), `business_automation` extras to compose into a `hooba` extra | F011 |
| 16 | `ruff.toml` | banned-api TID251 | 113, 125-127, 156, 161 | `httpx` banned; new code must use aiohttp/`HTTPService` | F009 |
| 17 | `sdd/specs/auto-finance-toolkit.spec.md` | `DeductibilityVerdict`, `AeatRule`, `parse_bank_excel` | 11, 41-62, 196-209, 265, 298-303 | FEAT-478 (unimplemented) contracts for BBVA parsing and AEAT deductibility this feature provides a v1 of | F005, F012 |
| 18 | `sdd/specs/web-automation-infra.spec.md` | Deliverable X, §8 seam | 392-403, 420-431, 968 | the five Hooba web operations deferred out-of-repo and never written; "engine public / plans private" | F008, F016 |
| 19 | `sdd/state/FEAT-602/hooba-openapi-digest.json` | hooba API 2026.6.17 digest | — | 217 relevant operations (Authentication, Invoice, PurchaseInvoice, Contact, Document, InboxFile, …) extracted from the public spec | F015 |

### 2.2 Constraints Discovered

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

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `1d4f4abfd8` | 2026-08-26 | Claude | feat(browsing): execute_web_task — structured agentic entry point | `parrot_tools/browsing/` |
| `74262cab5c` | 2026-08-26 | Claude | fix(browsing): harden toolkit per adversarial review | `parrot_tools/browsing/` |
| `f09e2e5729` | 2026-08-26 | Claude | feat(browsing): WebBrowsingToolkit — catalogued deterministic site actions | `parrot_tools/browsing/` |
| `3466fdcd32` | 2026-08-24 | Jesus Lara | style: apply black formatting (post sdd-worker) | `parrot_tools/business_automation/` |
| `f5a5001e4c` | 2026-08-24 | Jesus Lara | fix(web-automation-infra): close remaining critical review findings (AC-5, AC-12) | `parrot_tools/business_automation/` |
| `d93dd03756` | 2026-08-24 | Jesus Lara | fix(web-automation-infra): wire PlanDirectoryStore into BusinessAutomationToolkit | `parrot_tools/business_automation/` |
| `d57345564d` | 2026-08-24 | Jesus Lara | feat(web-automation-infra): TASK-2392 — bank-statement Excel ingestion via ExecutionPlan | `parrot_tools/business_automation/ingest.py` |
| `1dba612d5a` | 2026-08-24 | Jesus Lara | feat(web-automation-infra): TASK-2390 — BusinessAutomationToolkit core + ConfirmationGuard SUBMIT gate | `parrot_tools/business_automation/` |
| `4953611047` | 2026-03-23 | Jesus Lara | feat(monorepo-migration): TASK-398 — Workspace Scaffolding | `parrot/tools/openapitoolkit.py` |

`openapitoolkit.py` has not changed in six months and the business-automation
package has been quiet since FEAT-453 closed on 2026-08-24: both are stable
foundations, not moving targets. *Evidence*: F008, F009, F002

---

## 3. Probable Scope  *(mode = enrichment)*

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

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Hooba exposes a machine-readable OpenAPI 3.0.0 document at `api/doc.json` (656 paths, version 2026.6.17) | F015 | high | fetched and parsed directly; digest persisted |
| C2 | Invoice and purchase-invoice creation via the API produces drafts; issue/confirm are separate operations | F015 | high | state enums and `:issue`/`:confirm` paths read from the spec |
| C3 | Authentication is a session cookie set by `POST /auth/login`; the spec declares no security scheme | F015 | medium | no `securitySchemes`; captured request carries `sid`; not exercised at runtime — **resolved by U5** (cookie only) |
| C4 | `OpenAPIToolkit` cannot authenticate to Hooba unmodified, but its `HTTPService` transport already accepts cookies | F009 | high | constructor and `HTTPService` read directly |
| C5 | A full FEAT-453 engine (draft/submit gate, plans dir, checkpoints, broker adapter) is shipped and stable | F006, F008, F003 | high | 14/14 tasks done; code read; git quiet since 2026-08-24 |
| C6 | The existing Playwright operativa is an untracked local example with login + 5 navigations and no data entry | F007 | high | files read; `git ls-files` confirms untracked |
| C7 | No BBVA parser, AEAT rule table or deductibility model exists in code; Spec A defines them but was never decomposed | F005, F012, F004 | high | grep across packages empty; no FEAT-478 task index |
| C8 | The sanctioned home is a new `parrot_tools/hooba/` subpackage registered in `TOOL_REGISTRY` with its own extra | F013, F011 | high | brainstorm impact table + registry conventions |
| C9 | The tool surface should be bounded rather than all 970 operations | F001, F015 | medium | inferred from naming scheme and count — **resolved by U2** (full generation with tag allowlist) |
| C10 | The web half's v1 value is session recovery, PDF download and API gaps rather than data entry | F007, F015, F010 | medium | API covers the three capabilities; catalog has no data-entry scripts |
| C11 | BBVA rows map onto simplified purchase-invoice drafts using the purchase-invoice + line endpoints | F015 | medium | endpoint fields support it — **resolved by U3** (one draft per debit row) |
| C12 | `httpx` must not be used in the new client | F009 | high | ruff TID251 read directly |
| C13 | `HOOBA_*` credentials should flow through `CredentialBroker` rather than navconfig lookups | F003, F007 | medium | sanctioned path exists; the example bypasses it for local runs |

Distribution: **8** high, **5** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Where should the Hooba Playwright catalog (real selectors/URLs) live?** — *Resolved*: Keep private, `catalog_dir` from env — honour FEAT-453 §8: ship only a seed helper, read `HOOBA_CATALOG_DIR` at runtime.
  *Resolves claims*: C8, C10
- [x] **U2 — Tool surface exposed to the agent?** — *Resolved*: Full `OpenAPIToolkit` generation — extend `OpenAPIToolkit` with cookie auth and expose the spec with a tag allowlist.
  *Resolves claims*: C9
- [x] **U3 — How does a BBVA bank row become a Hooba expense draft?** — *Resolved*: One draft per debit row, contact only if matched — purchase-invoice draft with `simplified=true` per row; `contactId` only when the merchant matches an existing contact, else `null` + note.
  *Resolves claims*: C11
- [x] **U4 — Deductibility rules for autónomos?** — *Resolved*: v1 rule table inside hooba now — data-driven YAML under `parrot_tools/hooba/rules/`, shaped like Spec A's `AeatRule`/`DeductibilityVerdict` for later extraction to `parrot_tools/finance`.
  *Resolves claims*: C7, C11
- [x] **U5 — Non-cookie API credential and legal-effect operations in v1?** — *Resolved*: Cookie session only; v1 never issues/confirms — login via `POST /auth/login` with broker credentials, `sid` cookie jar, re-login on 401; all tools stay DRAFT/READ.
  *Resolves claims*: C3

### Unresolved (defer to spec / implementation)

- [ ] **Which Hooba tags form the default allowlist, and what is the hard cap on generated tools per agent?** — *Owner*: spec author
  *Blocks claims*: C9
  *Plausible answers*: a) the 17 tags in §3 (~217 ops) · b) a narrower "drafting" set (Invoice*, PurchaseInvoice*, Contact, Tax*) · c) configurable per agent definition
- [ ] **Exact BBVA export layout** (sheet name, preamble row count, column headers, date/amount formats) for the anonymized fixture — *Owner*: Jesús (provide one anonymized workbook)
  *Blocks claims*: C11
- [ ] **Initial content of the v1 rule table** (categories, IVA/IRPF flags, simplified-invoice threshold, `legal_basis` citations) — *Owner*: Jesús / gestoría review
  *Blocks claims*: C7

> Three deferred items, all spec-level detail rather than architecture.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-602`** — *Rationale*: localization is high-confidence
(C1, C2, C4-C8), the engine and transport already exist, the API removes the
need for new browser data-entry, and every architectural fork (U1-U5) was
decided in Q&A. What remains is spec-level detail (allowlist, fixture layout,
rule content).

### Alternatives

- **`/sdd-brainstorm FEAT-602`** — only if you want to revisit U2 (full
  generation vs curated tools) with a cost/benefit on tool budget.
- **`/sdd-task FEAT-602`** — not suitable: the work spans core
  (`openapitoolkit.py`) and a new multi-module package.
- **Manual review** — not needed; research completed without truncation.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-602/state.json` |
| Source (raw, redacted) | `sdd/state/FEAT-602/source.md` |
| Research plan | `sdd/state/FEAT-602/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-602/findings/F001-*.md` … `F016-*.md` |
| Hooba OpenAPI digest | `sdd/state/FEAT-602/hooba-openapi-digest.json` (217 ops, version 2026.6.17) |
| Synthesis (JSON) | `sdd/state/FEAT-602/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed**:
- Files read: 24 / 40
- Grep calls: 21 / 25
- Git calls: 4 / 10
- Wall time: ~2400s / 300s (includes the interactive plan gate; all 38 planned queries plus 3 depth-1 follow-ups executed)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs:
construir, combinar, crear, declarar, subir).

**External evidence**: F015 comes from a public, read-only fetch of
`https://api.hooba.com/api/doc.json` on 2026-09-25; the session cookie in the
original request was redacted and never stored.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara + Claude Fable 5.1 |
