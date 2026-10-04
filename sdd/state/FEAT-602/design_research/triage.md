# FEAT-602 design research triage

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

