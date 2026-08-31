---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Auto-Finance Agent (Phase 1) — deterministic FinanceToolkit + local ExpenseWiki + Hooba HITL registration

**Date**: 2026-08-31
**Author**: Jesús Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

A Spanish autónomo needs a personal-finance assistant that ingests bank statements
(Excel today, Norma 43/AEB43 as the robust path), deterministically detects
recurring subscriptions, "gastos hormiga" (ant expenses), price increases and
anomalies, classifies transactions against a fixed Spanish-autónomo taxonomy,
proposes AEAT-deductible expenses, materializes the resulting knowledge into a
**local** queryable knowledge graph ("ExpenseWiki"), and — with mandatory
human-in-the-loop approval — registers approved deductible expenses/invoices in
the Hooba web application via browser automation (Hooba has no public API).

The source analysis is `artifacts/compass_artifact_wf-cf3d7dee-2205-50aa-9903-544ad9415b27_text_markdown.md`
(Phase 1 + Phase 1.5). Its core invariant: **probabilistic components propose;
deterministic components decide.** "LLM + pandas REPL" is explicitly rejected as
the decision layer (non-reproducible, costly, RCE-prone — cf. LangChain
`create_pandas_dataframe_agent`, PandasAI CVEs). Bank data is sensitive:
processing must be local (DuckDB/SQLite/local ML), with minimal data sent to any
remote LLM.

Deviations from the source document, decided during discovery:
- KB starts **local** (SQLite plane), not PgVector+ArangoDB (migration path kept open).
- Classification uses a **local ML encoder model** (16GB VRAM available; ONNX or
  HF), not a remote LLM.
- **DuckDB** is adopted as the internal analytical engine AND as a sandboxed
  read-only SQL query tool for the agent (research confirmed: worth it).
- **Norma 43 parsing (doc's Phase 1.5) is folded into this feature.**

## Constraints & Requirements

- Deterministic decision layer: every detect/assess function must be a pure,
  testable, reproducible Python function — the LLM only orchestrates, names
  clusters, and writes explanations.
- 100% local data processing: no IBAN/balances/raw statements to remote LLMs;
  classification model runs locally (<16GB VRAM; targets <2GB).
- Human-in-the-loop is **mandatory and fail-closed** before any write to Hooba
  (financial submit). Use the formal `ConfirmationGuard`/`parrot.human` machinery,
  with `window_seconds=0` (no auto-approve window for financial writes).
- Toolkit conventions: all agent-facing tools are `async def` on an
  `AbstractToolkit`; **DataFrames cannot be tool parameters** (schema generator
  drops `pd.DataFrame` — verified `toolkit.py:77-99`); tools exchange dataset
  handles / file paths / statement IDs.
- Concrete toolkits live in `packages/ai-parrot-tools/src/parrot_tools/` with a
  `TOOL_REGISTRY` entry and an optional-dependency extra (pattern:
  `research`/`business_automation` extras).
- AEAT rules encoded as data-driven deterministic rules (5% difficult-to-justify
  cap 2.000€/yr; 30%×m² proportion for home-office utilities; phone only if
  exclusive line; invoice ≠ bank record — the assistant **proposes**, never files).
- Real Excel + Norma 43 statements are available from the user's bank for
  anonymized fixtures; synthetic SEPA-descriptor fixtures complement them.
- Do NOT reintroduce `ydata-profiling` (removed on purpose: numpy<2.2 pin clash,
  `packages/ai-parrot/pyproject.toml:558`); do not add `great_expectations`
  (heavy; the FEAT-453 digest/cross-check pattern + Pydantic suffices).
- Two specs (user decision): **Spec A** `auto-finance-toolkit` (pipeline + wiki +
  DuckDB + classifier + N43), **Spec B** `hooba-service-toolkit` (browser
  automation + HITL). B depends on A's `DeductibleExpense` draft model only.

---

## Options Explored

### Option A: Wiki-plane ExpenseWiki + DuckDB analytical file + SetFit local classifier (two toolkits)

`AutoFinanceToolkit(AbstractToolkit)` in `parrot_tools/finance/`, `auto_open=True`,
holding one DuckDB database file (`~/.parrot/finance/expenses.duckdb`) as the
transactional/analytical source of truth. Deterministic tools:
`parse_bank_excel` (reusing `ExcelStructureAnalyzer` header detection + the
FEAT-453 `compute_statement_digest` idempotency pattern), `parse_n43` (via
`csb43>=1.1.0`), `normalize_merchants` (regex SEPA-ES + `rapidfuzz`),
`detect_recurring` (interval gaps + coefficient of variation, ≥3 occurrences;
DBSCAN via scikit-learn for multi-stream merchants), `detect_ant_expenses`
(frequency×amount + Pareto), `detect_price_increases` (`ruptures` change-point),
`detect_anomalies` (scikit-learn IsolationForest — **no pyod**),
`classify_transactions` (rules first pass → local encoder embeddings + SetFit
few-shot head against the fixed ES-autónomo taxonomy), `assess_deductibility`
(data-driven AEAT rule table → verdicts with rule citations), `query_expenses`
(read-only sandboxed SQL: `duckdb.connect(read_only=True)` +
`enable_external_access=false` + `lock_configuration=true`, sqlglot-validated,
LIMIT-injected), and `build_expense_wiki`.

The **ExpenseWiki is the existing wiki plane**: pages + typed edges on SQLite
(`SQLiteWikiStore`, FTS5, embeddings blob) — merchants, subscriptions,
categories, monthly summaries and deductibility verdicts become pages with open
`category` strings ("merchant", "subscription", "expense-summary") and open
`rel` edges ("paid_to", "categorized_as", "supersedes"). Registered as a
satellite backend via `register_wiki_backend("expense", ...)` mirroring
`parrot_tools/legal/` (FEAT-450 seam), so `wikitoolkit query` / federation /
context packing work immediately.

Classifier: `intfloat/multilingual-e5-small` (MIT, official ONNX incl. int8,
<1GB, dim 384) through the existing `EmbeddingRegistry.get_or_create(...,
backend="onnx")` path for embedding+clustering, plus **SetFit** (v1.1.3) on the
same body for the few-shot fixed-taxonomy head. Migration path to
`jhu-clsp/mmBERT-base` (MIT, native `modernbert` arch, optimum-ONNX) once >~500
labeled rows exist.

Spec B: `HoobaServiceToolkit` built on `WebBrowsingToolkit`'s action catalog
(site actions as JSON on disk, credentials via `credential_provider="hooba"` +
broker, never LLM-improvised selectors), gated by `ConfirmationGuard` wired
through `ToolManager.set_confirmation_guard()` — confirm **before** the browser
opens (the `BusinessAutomationToolkit.run_operation` pattern, `window_seconds=0`,
fail-closed when no `human_manager`).

✅ **Pros:**
- Zero core changes for the KB: `pages.category`/`edges.rel` are open strings by
  design (`wiki/store.py:11-14`); `BaseWikiStore` is a real 16-method ABC;
  `register_wiki_backend` is an exercised plugin seam (legal toolkit).
- ExpenseWiki is instantly queryable by `wikitoolkit` CLI/MCP and mountable as a
  federated namespace (`WikiNamespaceConfig.backend` is an open str).
- DuckDB gives native `read_xlsx`, zero-copy DataFrame registration, real SQL
  (windows, PIVOT, SUMMARIZE) AND a documented lockable read-only sandbox pandas
  cannot offer — one engine for pipeline internals and the agent query surface.
- Maximum reuse: Excel analyzer, FEAT-453 ingest digest, embeddings
  registry+catalog (e5 already catalogued), ONNX backend path (FEAT-237),
  ConfirmationGuard/HumanInteractionManager, WebBrowsingToolkit catalog.
- Local, private, cheap: hashing/ONNX models, no per-token cost, reproducible.

❌ **Cons:**
- Diverges from the Round-1 answer "GraphIndex over SQLite" — wiki plane has no
  audited/revertible commit log (GraphPublisher's `CommitReceipt`/`revert_commit`).
  Mitigation: DuckDB file is the source of truth with append-only import
  manifests; wiki is a rebuildable projection (`replace_source_slice`).
- Two storage artifacts (DuckDB file + wiki.db) to keep consistent —
  `build_expense_wiki` must be idempotent per statement digest.
- SetFit/e5 fine-tune quality on Spanish bank descriptors is unbenchmarked
  publicly; needs a 200-row held-out eval before trusting auto-classification.

📊 **Effort:** Medium (Spec A) + Medium (Spec B)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `duckdb>=1.5` | Analytical engine + read-only agent SQL | v1.2.2 installed but **undeclared** — declare in new `finance` extra; native xlsx via `excel` core extension (st_read/spatial route is obsolete) |
| `csb43>=1.1.0` | Norma 43/AEB43 parsing | LGPL-3.0+, released 2026-05-24, typed, Py3.8–3.14; `csb43.aeb43.read_batch`; wrap behind own dataclass boundary |
| `rapidfuzz>=3.0` | Merchant fuzzy grouping | Installed (3.11.0) but only in `scraping` extra — add to `finance` extra |
| `scipy`, `statsmodels` | Interval stats / ACF | Installed transitively — declare explicitly |
| `ruptures` | Price-increase change-point | New dep, pure-python+numpy, small |
| `scikit-learn` | DBSCAN, IsolationForest, classifier eval | Installed (1.9.0); declared unpinned in advisors — pin in finance extra |
| `setfit>=1.1.3` | Few-shot fixed-taxonomy classifier | Active (2025-08); drop-in over sentence-transformers body |
| `sentence-transformers>=5.0`, `optimum[onnxruntime]` | e5-small ONNX inference | Already declared (embeddings pkg / onnx extra) |
| `openpyxl` | Excel fallback/cross-check | Already declared (root override ≤3.1.5) |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/store.py:332,488` — `BaseWikiStore` ABC + `SQLiteWikiStore`; `register_wiki_backend` (`:318`), `create_wiki_store` (`:1359`)
- `parrot_tools/legal/__init__.py:16-20` + `legal/wiki_store.py:49` — satellite wiki-backend template
- `parrot/tools/excel_intelligence.py:18` + `parrot/tools/dataset_manager/excel_analyzer.py:133` — workbook/table/header detection for `parse_bank_excel`
- `parrot_tools/business_automation/ingest.py:99,189,321,415` — FEAT-453 statement digest, import manifest, reconcile
- `parrot/embeddings/registry.py:223` (`get_or_create`), `catalog.py:88-89,485,508` (e5 entries), `ai-parrot-embeddings .../huggingface.py:112,134` (`backend="onnx"`, e5 prefix handling `:33`)
- `parrot/tools/databasequery/base.py:213,362` — `add_row_limit` + sqlglot `validate_query`; `parrot/security/query_validator.py:29`
- `parrot/tools/toolkit.py:216` — `AbstractToolkit` (+ FEAT-391 `auto_open` lifecycle `:388-435`); exemplars: `QuantToolkit` (pure-numeric), `DatabaseQueryToolkit` (`_post_execute` model_dump), `BaseResearchToolkit` (auto_open)
- `parrot/auth/confirmation.py:66,378,417` — `ConfirmationConfig`/`ConfirmationGuard.confirm`; `parrot/tools/manager.py:496` — `set_confirmation_guard`
- `parrot_tools/browsing/toolkit.py:64,124,462` — `WebBrowsingToolkit` + `execute_web_task`; `browsing/catalog.py:39`; `scraping/models.py:486,527` (`Authenticate`, `AwaitHuman`)
- `parrot_tools/business_automation/toolkit.py:120,349-356,429-453` — confirm-before-browser + per-call dynamic gating stub
- `parrot/human/manager.py:51,321` — `HumanInteractionManager`; channels CLI/Telegram/Teams/web; wiring reference `integrations/agentd/service.py:385-405`

---

### Option B: ExpenseWiki on GraphIndex (`SQLitePersistence` + `GraphPublisher`)

Same deterministic toolkit and DuckDB layer as Option A, but the KB is the
GraphIndex plane: `build_expense_wiki` mints `UniversalNode`/`UniversalEdge`
objects and publishes them through `GraphPublisher.publish(GraphUpdate)` onto
`SQLitePersistence` (nodes + edges + nodes_fts + commit log), bypassing
`GraphIndexBuilder.build()` entirely (its stage-1 extractors are code/document
only — wrong entry point for tabular data, verified). Agent-side access via
`GraphIndexToolkit` from `build_graph_memory_toolkit` (`factory.py:203`), which
already wires SQLite + `HashingGraphEmbedder` (deterministic, offline).

✅ **Pros:**
- **Audited, revertible commits for free**: `CommitReceipt`, `list_commits`,
  `revert_commit`, `AssertionMeta` provenance stamping — genuinely valuable for
  financial state ("undo this import").
- `GraphMemoryMixin` gives any bot injected graph context with zero extra wiring.
- Matches the Round-1 discovery answer ("GraphIndex sobre SQLite").

❌ **Cons:**
- `NodeKind`/`EdgeKind` are **closed enums** (`schema.py:36,64`): no TRANSACTION/
  MERCHANT/CATEGORY kinds, no PAID_TO/CATEGORIZED_AS rels. Either edit core enums
  (touches the foundation for one domain) or overload CONCEPT/CLAIM + ABOUT and
  carry real typing in `domain_tags` JSON — semantics become second-class.
- GraphIndex persistence contract is **pure duck typing** — no ABC/Protocol
  (verified zero hits) — a fragile seam to build a domain product on.
- Not visible to `wikitoolkit query`/federation without extra bridging; loses
  FTS-over-page-bodies UX that the wiki plane gives for free.
- Vector search is brute-force cosine either way; no advantage.

📊 **Effort:** Medium-High

📦 **Libraries / Tools:** same as Option A (KB layer swaps only).

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/graphindex/persist_sqlite.py:138` — `SQLitePersistence` (`persist_graph:263`, `apply_update:608`, `revert_commit:856`)
- `parrot/knowledge/graphindex/publish.py:37,90` — `GraphPublisher.publish`
- `parrot/knowledge/graphindex/factory.py:203` — `build_graph_memory_toolkit`; `mixin.py:30` — `GraphMemoryMixin`
- `parrot/knowledge/graphindex/schema.py:143,178,231,267` — `UniversalNode/UniversalEdge/GraphUpdate/CommitReceipt`

---

### Option C (unconventional): DuckDB-only — the database *is* the wiki

No graph plane at all. One DuckDB file holds transactions, merchants,
subscriptions, categories, verdicts as relational tables plus SQL views
(`monthly_summary`, `active_subscriptions`, `deductible_drafts`). "Wiki pages"
are generated markdown reports written to disk per month; the agent's only KB
access is the sandboxed `query_expenses` SQL tool and those reports. Edges are
foreign keys.

✅ **Pros:**
- Smallest possible surface: one storage artifact, no consistency problem, no
  new backend registration; fastest to ship and trivially testable.
- SQL views are a very natural fit for finance aggregates; DuckDB sandbox is
  already the agent surface.

❌ **Cons:**
- Not a knowledge graph: no typed edges, no FTS-ranked page retrieval, no
  `wikitoolkit`/federation integration, no semantic search over merchant pages —
  gives up the "LLM Wiki" concept that motivated the design (Era's cross-agent
  memory analog).
- Free-text knowledge (user corrections, canonical merchant notes, rule
  rationales) fits poorly in relational rows; would grow ad-hoc columns.
- Migration to PgVector/Arango later means inventing the graph model then anyway.

📊 **Effort:** Low

📦 **Libraries / Tools:** Option A minus wiki plane.

🔗 **Existing Code to Reuse:** DuckDB/validation/toolkit rows from Option A.

---

## Recommendation

**Option A**, with one explicit deviation to ratify: during discovery the user
picked "GraphIndex over SQLite", but codebase research shows the **wiki plane is
the better substrate for a domain KB** — it *is* already a SQLite
pages+typed-edges graph, with open `category`/`rel` vocabularies (GraphIndex's
`NodeKind`/`EdgeKind` are closed enums with no finance kinds), a real ABC
contract (vs. undocumented duck typing), a proven satellite plugin seam
(`register_wiki_backend`, legal toolkit), and immediate `wikitoolkit`
query/federation integration. What Option B uniquely offers — audited revertible
commits — is covered differently: the DuckDB file is the append-only source of
truth keyed by statement digest (FEAT-453 pattern), and the wiki is a
rebuildable projection; if commit-level auditing of *graph* assertions later
matters, `GraphPublisher` can be layered on without redesign. Option C is kept
as the fallback floor: Option A's DuckDB layer is Option C, so if wiki work
slips, the toolkit still ships useful.

Trade-offs accepted: two storage artifacts (mitigated by idempotent
`build_expense_wiki` per digest), unbenchmarked ES-descriptor classification
(mitigated by rules-first pass + held-out eval + human review of drafts), and
the divergence from the Round-1 answer (flagged as Open Question #1).

---

## Feature Description

### User-Facing Behavior

1. The user hands the agent a bank statement (`.xlsx` or Norma 43 `.n43`) or a
   directory of them. The agent parses, validates and imports idempotently
   (re-importing the same statement is a no-op, reported as such).
2. The agent reports, with deterministic numbers: detected subscriptions
   (merchant, cadence, amount band, next expected charge), ant expenses
   (frequency×amount, Pareto share), price increases, anomalies, and a
   classification of every transaction against the fixed ES-autónomo taxonomy
   (with confidence; low-confidence rows flagged "needs review", never guessed).
3. The agent proposes deductible expenses as **drafts** with AEAT rule citations
   (e.g., "SaaS 100% afecto — requires supplier invoice; bank record is proof of
   payment only"). Nothing is filed anywhere.
4. The user can ask free-form analytical questions; the agent answers via the
   read-only `query_expenses` SQL tool and wiki lookups — never by generating
   pandas code.
5. (Spec B) When the user says "register these in Hooba", each SUBMIT operation
   triggers a formal approval interaction (CLI/Telegram/Teams/web channel) showing
   exactly what will be filed; deny/timeout cancels fail-closed **before the
   browser opens**; approvals execute catalogued Hooba site actions and report
   results; every run is resumable (`resume_operation`).
6. The ExpenseWiki persists across sessions: merchants, subscriptions, category
   decisions and user corrections are pages any future session (or `wikitoolkit
   query`) can retrieve — corrections are remembered, not re-asked.

### Internal Behavior

- **Ingestion**: `parse_bank_excel` uses `ExcelStructureAnalyzer` to locate the
  transaction table (Spanish bank layouts have preamble rows), maps columns
  (fecha/concepto/importe/saldo), cross-checks row counts, computes the FEAT-453
  digest, and loads rows into DuckDB (`all_varchar` then typed casts; amounts as
  DECIMAL, never float). `parse_n43` does the same via `csb43.aeb43.read_batch`
  (amounts are fixed-point strings — preserved). Both return a `statement_id`
  handle, not data.
- **Normalization**: regex strips SEPA-ES prefixes (ADEUDO/RECIBO/COMPRA
  TARJETA/BIZUM/TRANSFERENCIA + terminal/city noise); `rapidfuzz`
  (`token_sort_ratio`, threshold ~85 grouping / ~70 suggestion) clusters variants
  into canonical merchants stored as wiki pages; user corrections become
  authored-origin page edits that outrank fuzzy matches on subsequent runs.
- **Detection**: per-merchant interval series → median gap + CV bands map to
  cadence (weekly/monthly/quarterly/yearly); ≥3 occurrences required (Plaid
  convention); DBSCAN on [interval, amount] separates multiple streams per
  merchant; `ruptures` flags change-points in variable-amount streams;
  IsolationForest flags outliers. All pure functions over DuckDB-fetched frames;
  all thresholds in one config dataclass; all unit-tested against fixtures.
- **Classification**: pass 1 deterministic rules (merchant dictionary + SEPA
  channel heuristics); pass 2 e5-small embeddings (ONNX, via
  `EmbeddingRegistry`) + SetFit head for the remainder; below-threshold →
  `needs_review`. Taxonomy is a versioned data file (2-level, ES-autónomo).
  CPU-bound inference runs in an executor (async-first rule).
- **Deductibility**: a rule table (rule_id, matcher, percentage, cap, legal
  basis, invoice_required) evaluated deterministically → `DeductibilityVerdict`
  drafts persisted in DuckDB with status `draft`.
- **Wiki materialization**: `build_expense_wiki` projects DuckDB state into wiki
  pages+edges via `replace_source_slice` keyed by statement digest (idempotent);
  embeddings via the wiki store's existing blob path.
- **Hooba (Spec B)**: `HoobaServiceToolkit` wraps a private action catalog
  (site actions JSON live outside the repo, per the business-automation runbook);
  `register_expense(draft_id)` builds a per-call confirmation stub
  (`routing_meta={"requires_confirmation": True, "confirm_window_seconds": 0}`)
  → `ConfirmationGuard.confirm()` → only then `run_site_action`. Dedicated
  `HumanChannel` instance (documented collision hazard when sharing with
  `exec_await_human`). Wiring copied from `agentd/service.py:385-405`.

### Edge Cases & Error Handling

- Re-import of an already-ingested statement → digest hit → no-op with report.
- Excel row-count mismatch between analyzer and pandas cross-check → refuse
  import (FEAT-453 behavior), report which sheet/range failed.
- Malformed N43 (encoding, padding, pre-euro codes) → csb43 lenient mode first,
  strict-mode diff reported; unparseable → clear error naming the record line.
- <3 occurrences or <6 months history → subscriptions of longer cadence
  explicitly reported as "not detectable with current history" (doc caveat).
- Ambiguous ADEUDO with truncated creditor → classified `needs_review`, never
  auto-deducted.
- `query_expenses`: non-SELECT/DDL/DML rejected by sqlglot validation; external
  access disabled and configuration locked at connection creation; row limit
  injected; connection is `read_only=True` so even a bypass cannot write.
- Deductible drafts never auto-submit: missing invoice flag forces
  `invoice_required` warning in the draft; Hooba submit denied when
  `human_manager` is absent (fail-closed), on timeout, or on user denial —
  denial recorded in DuckDB (`status=rejected`) and wiki.
- Browser/site failure mid-run → operation checkpointed; `resume_operation`
  continues; no double-filing because confirmation window is 0 and drafts are
  keyed by draft_id with status transitions.
- Model files unavailable/offline → classification degrades to rules-only with
  everything else marked `needs_review`; pipeline never blocks on the model.

---

## Capabilities

### New Capabilities
- `auto-finance-toolkit`: deterministic finance pipeline (Excel + Norma 43
  ingestion, merchant normalization, recurrence/ant-expense/price/anomaly
  detection, fixed-taxonomy local-ML classification, AEAT deductibility drafts),
  DuckDB analytical store + sandboxed read-only `query_expenses`, and the
  ExpenseWiki backend (`register_wiki_backend("expense", ...)`) with
  `build_expense_wiki` projection. → Spec A.
- `hooba-service-toolkit`: Hooba browser-automation toolkit on the
  WebBrowsingToolkit action catalog with fail-closed ConfirmationGuard HITL
  (approve/deny/edit before submit), draft-keyed idempotency and resumable runs.
  → Spec B (depends on A's draft model only).

### Modified Capabilities
- None (additive: new `parrot_tools.finance` + `parrot_tools.hooba` subpackages,
  new `finance` extra, TOOL_REGISTRY entries).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/finance/` | new | AutoFinanceToolkit, models, taxonomy data, AEAT rules, wiki backend, classifier |
| `packages/ai-parrot-tools/src/parrot_tools/hooba/` | new | HoobaServiceToolkit (Spec B); private action catalog stays out-of-repo |
| `packages/ai-parrot-tools/pyproject.toml` | modifies | new `finance = [...]` extra (duckdb, csb43, rapidfuzz, scipy, statsmodels, ruptures, scikit-learn, setfit) |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | modifies | `TOOL_REGISTRY` entries for both toolkits |
| `parrot.knowledge.wiki` backend registry | depends on | `register_wiki_backend("expense", ...)` at import time — no core change |
| `parrot.embeddings` registry/catalog | depends on | e5-small entry may need adding to `catalog.py` (only -base/-large catalogued) |
| `parrot.auth.confirmation` + `parrot.human` | depends on | wiring in the example agent, agentd-style; no core change |
| `parrot_tools/business_automation/ingest.py` | depends on / possibly extracts | digest/manifest helpers may be imported or lifted to a shared module |
| `examples/agents/finance/` | new | runnable agent wiring both toolkits + HITL channel |

No breaking changes. No server/handler changes in Phase 1.

---

## Code Context

### User-Provided Code
None — the user referenced `examples/agents/web/services/hooba_agent.py`, which
**does not exist in this repo or its git history** (see Does NOT Exist). If a
private version exists outside the repo, its selectors/flows should seed the
Hooba action catalog (Open Question #2).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/tools/toolkit.py:216
class AbstractToolkit:
    exclude_tools: tuple[str, ...] = ()          # :253
    tool_prefix: Optional[str] = None            # :267
    confirming_tools: frozenset = frozenset()    # :285 (unprefixed method names)
    credential_provider: Optional[str] = None    # :303
    auto_open: bool = False                      # :310 (FEAT-391)
    def __init__(self, **kwargs): ...            # :312 — subclasses MUST call super().__init__
    async def _open(self) -> None: ...           # :388
    async def _close(self) -> None: ...          # :404 — overrides must await super()._close()
    async def _ensure_open(self) -> None: ...    # :417
    async def _prepare_kwargs(self, tool_name: str, kwargs: Dict[str, Any]) -> Dict[str, Any]: ...  # :436
    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs) -> Any: ...  # :468
# _generate_tools (:537) exposes ONLY public `async def` methods (:560);
# DataFrame/Series/pa.Table params are DROPPED from schemas (:77-99).
# Explicit schemas via @tool_schema (parrot/tools/decorators.py:39).

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                        # :332 — 16 abstract methods
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...        # :351
    async def add_edges(self, edges: list[tuple]) -> int: ...                    # :354
    async def replace_source_slice(self, source_id: str, pages, edges=None) -> dict: ...  # :357
    async def search_fts(self, query: str, category=None, limit: int = 10) -> list[dict]: ...  # :383
    async def neighbors(self, concept_id: str, rel=None, direction="both") -> list[dict]: ...  # :389
class SQLiteWikiStore(BaseWikiStore):            # :488
    def __init__(self, db_path, wiki_name="", *, read_only=False): ...           # :536
class WikiPageRecord(BaseModel): ...             # :224 — concept_id, title, category, summary, body, origin, asserted_by
def register_wiki_backend(name: str, factory) -> None: ...  # :318 — factory MUST be sync + non-connecting
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore: ...  # :1359
# pages.category and edges.rel are OPEN strings (schema :49-125; design note :11-14)

# From packages/ai-parrot/src/parrot/auth/confirmation.py
class ConfirmationConfig(BaseModel):             # :66 — window_seconds=0, approval_timeout=120.0, default_channel="telegram"
class ConfirmationGuard:                         # :378
    def __init__(self, store, human_manager=None, config=None): ...              # :399
    async def confirm(self, *, tool, parameters, permission_context=None) -> ConfirmationDecision: ...  # :417
# fail-closed: human_manager=None => "cancelled" (:435-506)
# ToolManager.set_confirmation_guard(guard) — parrot/tools/manager.py:496; enforced pre-execute :1593-1625, :1718-1742

# From packages/ai-parrot/src/parrot/human/manager.py
class HumanInteractionManager:                   # :51
    async def request_human_input(self, interaction: HumanInteraction, channel: str = "telegram") -> InteractionResult: ...  # :321
# Channels: CLI (channels/cli.py), web (channels/web.py), Telegram/Teams (ai-parrot-integrations)
# Reference wiring: packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py:385-405

# From packages/ai-parrot-tools/src/parrot_tools/browsing/toolkit.py
class WebBrowsingToolkit(WebScrapingToolkit):    # :64
    confirming_tools = {...run_site_action, run_site_sequence, execute_web_task, delete_site_action}  # :115-122
    def __init__(self, catalog_dir="browsing_catalog", user_data_dir=None, ...,
                 credential_resolver=None, human_channel=None, session_based=True,
                 headless=False, confirm_runs=True, **kwargs): ...               # :124-160
    async def run_site_action(self, site, action, params=None, ...) -> Dict: ... # :382
    async def execute_web_task(self, request: Dict[str, Any]) -> Dict: ...       # :462

# From packages/ai-parrot-tools/src/parrot_tools/business_automation/toolkit.py
class BusinessAutomationToolkit(AbstractToolkit):  # :120, auto_open=True :137
    async def run_operation(self, name, params=None) -> Dict: ...  # :305 — SUBMIT ops confirm BEFORE browser opens (:349-356)
    # per-call gating stub pattern (SimpleNamespace + routing_meta) :429-453; window_seconds=0 rationale :440-443

# From packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py (FEAT-453)
def compute_statement_digest(xlsx_path) -> ...:  # :99 — idempotency digest + row-count cross-check (:138-143)
# ImportPlanBundle :189, _write_import_manifest :321, reconcile :415

# From packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py
class ExcelStructureAnalyzer:                    # :133
    def analyze_workbook(self) -> ...: ...       # :163
    def extract_table_as_dataframe(self, ...): ...  # :170
# Exposed as ExcelIntelligenceToolkit — parrot/tools/excel_intelligence.py:18

# From packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:                         # :55 (singleton :104)
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs): ...  # :223
# ONNX path: SentenceTransformerModel(model_name, backend="onnx", file_name="model_quantized.onnx")
#   — packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:112,:134,:150-155
# e5 "query: "/"passage: " prefixes applied automatically (_resolve_prefixes :33)
# Catalog: E5_MULTI_BASE catalog.py:88 (entry :485), E5_MULTI_LARGE :89 (entry :508)

# SQL sandbox reuse:
# add_row_limit(query, max_rows, driver) — parrot/tools/databasequery/base.py:213 (duckdb in _SQL_DRIVERS :202)
# AbstractDatabaseSource.validate_query — base.py:362 (sqlglot, error_level=RAISE)
# QueryValidator — parrot/security/query_validator.py:29
# DuckDBSource (asyncdb-driven alternative) — parrot/tools/databasequery/sources/duckdb.py:29

# GraphIndex (Option B / future layering):
# SQLitePersistence — parrot/knowledge/graphindex/persist_sqlite.py:138 (apply_update :608, revert_commit :856)
# GraphPublisher — publish.py:37 (publish :90); build_graph_memory_toolkit — factory.py:203
# NodeKind/EdgeKind are CLOSED enums — schema.py:36,:64
```

#### Verified Imports
```python
from parrot.tools import AbstractToolkit, tool_schema        # parrot/tools/__init__.py
from parrot.knowledge.wiki.store import (BaseWikiStore, SQLiteWikiStore,
    WikiPageRecord, register_wiki_backend, create_wiki_store)
from parrot.auth.confirmation import (ConfirmationGuard, ConfirmationConfig,
    InMemoryConfirmationWindowStore)
from parrot.human import HumanInteractionManager             # parrot/human/__init__.py (namespace pkg, core side)
from parrot.embeddings.registry import EmbeddingRegistry
from parrot_tools.browsing import WebBrowsingToolkit, ActionCatalog
```

#### Key Attributes & Constants
- `AbstractToolkit.confirming_tools` → `frozenset` of **unprefixed** method names (toolkit.py:285, applied :673-681)
- `WebBrowsingToolkit.confirm_runs=True` keeps run tools in `confirming_tools` (browsing/toolkit.py:152-155)
- `TOOL_REGISTRY: dict[str, str]` — parrot_tools/__init__.py:12 (name → dotted path; discovery.py:31)
- DuckDB installed v1.2.2 (transitive via asyncdb, `uv.lock:2879`) — **undeclared by any workspace package**
- `duckdb` sandbox stack: `connect(read_only=True)` + `SET enable_external_access=false` + `SET disabled_filesystems='LocalFileSystem'` + `SET lock_configuration=true`
- Deps present: rapidfuzz 3.11.0 (scraping extra only), scipy 1.15.1 (transitive), statsmodels (transitive), scikit-learn 1.9.0 (advisors, unpinned), onnxruntime 1.29.0, sentence-transformers 5.7.0, sqlglot 30.17.0, openpyxl 3.1.5

### Does NOT Exist (Anti-Hallucination)
- ~~`examples/agents/web/services/hooba_agent.py`~~ — no `hooba*` file exists anywhere in the repo or git history; Hooba appears only in docstrings/spec examples; the Hooba plan is deliberately out-of-repo (`docs/business-automation-runbook.md:234`)
- ~~any finance/expense/merchant/recurrence/deductibility code~~ — no `AutoFinanceToolkit`, `parse_bank_excel`, `normalize_merchants`, `detect_recurring`, tax rules, or "gastos hormiga" concept anywhere
- ~~SQLite `AbstractStore` backend~~ — `parrot/stores/` has pgvector/milvus/faiss/arango/bigquery only; `AbstractStore` is a vector-store ABC, not a graph/page store
- ~~sqlite-vec / sqlite-vss~~ — wiki/graph vector search is brute-force cosine in Python
- ~~finance `NodeKind`/`EdgeKind` members~~ — closed enums, code/document-oriented only; no extension mechanism
- ~~ABC/Protocol for GraphIndex persistence~~ — pure duck typing (zero `abstractmethod` hits in persist/publish/builder)
- ~~generic classifier abstraction~~ — no `AbstractClassifier`/zero-shot/fixed-taxonomy machinery (only special-purpose guardrail ONNX classifiers, e.g. `_OnnxInjectionEngine`, prompt_injection.py:187 — pattern reference only)
- ~~`ruptures`, `pyod`, `great_expectations` in the workspace~~ — absent from all pyprojects and uv.lock; `ydata-profiling` deliberately removed (numpy pin clash)
- ~~direct `duckdb.connect()` usage / in-process analytics layer~~ — DuckDB exists only as an asyncdb driver behind `DuckDBSource`
- ~~`DatabaseAgent` accepting plain `AbstractToolkit`~~ — typed/coupled to `DatabaseToolkit` (dsn, primary_schema, allowed_schemas…); attach finance toolkits to a `BasicAgent` instead
- ~~default `ConfirmationGuard` wiring in `Agent`~~ — without explicit `set_confirmation_guard()`, `confirming_tools` is inert (only production wiring: agentd service.py:402)
- ~~`RedisConfirmationWindowStore`~~ — only in-memory; windows lost on restart
- ~~per-step mid-script approval in WebBrowsingToolkit~~ — confirmation is whole-tool-call; `await_human` DSL step is a wait, not approve/reject
- ~~CDP/Chrome-DevTools session manager in the modern browsing path~~ — Chrome profile via driver options; CDP only in legacy scraping/tool.py

---

## Parallelism Assessment

- **Internal parallelism**: High within Spec A once the data model + DuckDB
  schema task lands: (ingestion Excel/N43), (normalization+detection), (classifier),
  (deductibility rules), (wiki backend + build_expense_wiki), (query_expenses)
  are largely independent modules over the shared schema. Spec B is fully
  independent of A's internals (consumes only the draft model + DuckDB ids).
- **Cross-feature independence**: No in-flight spec touches `parrot_tools/finance`
  or `parrot_tools/hooba` (both new). Shared-file risk limited to
  `parrot_tools/__init__.py` (TOOL_REGISTRY) and `ai-parrot-tools/pyproject.toml`
  — trivial merge surface. Note `parrot/bots/database/agent.py` currently has
  uncommitted changes (issue #1269) — unrelated; do not base work on it.
- **Recommended isolation**: per-spec (two worktrees, one per spec; tasks within
  each run sequentially).
- **Rationale**: two specs map cleanly to two worktrees per the FEAT-145 model;
  intra-spec tasks share the DuckDB schema and models file, so sequential
  execution in one worktree avoids schema-merge conflicts while the two specs
  never touch the same modules.

---

## Open Questions

- [ ] Ratify the KB substrate: recommendation is the **wiki plane** (`SQLiteWikiStore` + `register_wiki_backend`) instead of the Round-1 answer "GraphIndex over SQLite" — GraphIndex's closed `NodeKind`/`EdgeKind` enums and duck-typed persistence make it a worse fit; `GraphPublisher` auditing can be layered later. Accept? — *Owner: Jesús*
- [ ] `hooba_agent.py` does not exist in this repo — does a private version (selectors, flows, catalog JSON) exist on disk elsewhere to seed the Hooba action catalog, or is Spec B greenfield against the live Hooba UI? — *Owner: Jesús*
- [ ] Which bank(s) produce the real Excel/N43 fixtures (column layouts differ per bank; anonymization script needed before committing fixtures)? — *Owner: Jesús*
- [ ] Anomalies via scikit-learn `IsolationForest` (already installed) instead of adding `pyod` — accept dropping pyod? — *Owner: Jesús*
- [ ] Initial fixed taxonomy: propose ~12 top-level / ~40 second-level ES-autónomo categories in Spec A — review the concrete list at spec time. — *Owner: Jesús*
- [ ] Default HITL channel for the example agent: CLI (simplest) or Telegram (already integrated, matches `ConfirmationConfig.default_channel`)? — *Owner: Jesús*
- [ ] Spec B engine: thin `HoobaServiceToolkit` over `WebBrowsingToolkit` catalog (recommended) vs. reusing `BusinessAutomationToolkit` operations/plans model — decide at Spec B time based on the private Hooba plan's shape. — *Owner: Jesús*
- [ ] Add `intfloat/multilingual-e5-small` to `parrot/embeddings/catalog.py` (only -base/-large are catalogued) or pass it uncatalogued via `get_or_create`? — *Owner: dev*
