---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: AutoFinanceToolkit — deterministic personal-finance pipeline + GraphIndex ExpenseWiki

**Feature ID**: FEAT-478
**Date**: 2026-08-31
**Author**: Jesús Lara
**Status**: draft
**Target version**: next minor of `ai-parrot-tools`
**Brainstorm**: `sdd/proposals/auto-finance-agent.brainstorm.md` (Recommended Option B, user-ratified 2026-08-31)

---

## 1. Motivation & Business Requirements

### Problem Statement

A Spanish autónomo needs a personal-finance assistant that ingests bank
statements (Excel and Norma 43/AEB43), deterministically detects recurring
subscriptions, "gastos hormiga" (ant expenses), price increases and anomalies,
classifies transactions against a fixed Spanish-autónomo taxonomy using a
**local ML encoder** (never a remote LLM), proposes AEAT-deductible expenses as
drafts with rule citations, and materializes the resulting knowledge into a
**local, audited, revertible** knowledge graph (the "ExpenseWiki") that any
agent session can query. Source analysis:
`artifacts/compass_artifact_wf-cf3d7dee-2205-50aa-9903-544ad9415b27_text_markdown.md`.

Core invariant: **probabilistic components propose; deterministic components
decide.** "LLM + pandas REPL" is rejected as the decision layer
(non-reproducible, costly, RCE-prone). Bank data is sensitive: all processing
is local (DuckDB + SQLite + local ONNX models).

### Goals

- G1. A deterministic `AutoFinanceToolkit(AbstractToolkit)` in
  `parrot_tools/finance/` whose every detect/assess function is a pure,
  testable, reproducible Python function.
- G2. Idempotent statement ingestion for **Excel (BBVA layout first)** and
  **Norma 43** (`csb43`), keyed by statement digest (FEAT-453 pattern).
- G3. DuckDB database file as the analytical source of truth, plus an
  agent-facing **sandboxed read-only** `query_expenses` SQL tool.
- G4. Local-only classification: rules first pass → `multilingual-e5-small`
  embeddings (ONNX) + SetFit few-shot head over a fixed 2-level ES-autónomo
  taxonomy; below-threshold rows land in `needs_review`, never guessed.
- G5. ExpenseWiki on **GraphIndex** (`SQLitePersistence` + `GraphPublisher`,
  user-ratified): every import/correction is an audited `CommitReceipt`;
  `revert_commit` undoes a bad import; finance typing via `domain_tags`.
- G6. AEAT deductibility as a data-driven rule table producing **drafts only**
  (human approves; filing to Hooba is Spec B / `hooba-service-toolkit`).
- G7. All new dependencies declared in a `finance` optional-dependency extra of
  `ai-parrot-tools`; toolkit registered in `TOOL_REGISTRY`.

### Non-Goals (explicitly out of scope)

- Hooba browser automation and HITL submit — **Spec B** (`hooba-service-toolkit`,
  same brainstorm, depends only on this spec's `DeductibilityVerdict` drafts).
- Open banking / PSD2 connectors (Phase 2 of the source document).
- Invoice OCR / PDF certificate retrieval (bank record proves payment, not
  deductibility — the toolkit only flags `invoice_required`).
- PgVector/ArangoDB backends for the ExpenseWiki (local SQLite only; the
  `GraphIndexPersistence` seam keeps migration open).
- Extending `NodeKind`/`EdgeKind` core enums (rejected in brainstorm — finance
  typing goes in `domain_tags`; see brainstorm Recommendation).
- Wiki-plane (`SQLiteWikiStore`) ExpenseWiki — rejected Option A, see
  `sdd/proposals/auto-finance-agent.brainstorm.md`.
- Automatic tax filing or advice — the assistant proposes; a human decides.

---

## 2. Architectural Design

### Overview

A new `parrot_tools.finance` subpackage. `AutoFinanceToolkit` extends
`AbstractToolkit` with `auto_open = True` (FEAT-391): `_open()` creates/opens
the DuckDB file (default `~/.parrot/finance/expenses.duckdb`, configurable) and
the GraphIndex `SQLitePersistence` directory; `_close()` releases both.

Pipeline (each stage an `async def` tool; CPU-bound work runs in an executor):

1. **Ingest** — `parse_bank_excel(path)` uses `ExcelStructureAnalyzer` to
   locate the transaction table in BBVA workbooks (preamble rows), maps
   columns (fecha/concepto/importe/saldo), cross-checks row counts, computes a
   statement digest, and loads typed rows into DuckDB (amounts as `DECIMAL`,
   never float). `parse_n43(path)` does the same via `csb43.aeb43.read_batch`
   (fixed-point amount strings preserved). Both return a `statement_id`
   handle — **tools never exchange DataFrames** (schema generator drops them).
   Re-importing the same digest is a reported no-op.
2. **Normalize** — `normalize_merchants(statement_id)`: regex strips SEPA-ES
   descriptor noise (ADEUDO/RECIBO/COMPRA TARJETA/BIZUM/TRANSFERENCIA +
   terminal/city suffixes); `rapidfuzz.token_sort_ratio` clusters variants
   (≥85 auto-group, 70–85 suggestion) into canonical merchants. User
   corrections persist and outrank fuzzy matches on later runs.
3. **Detect** — `detect_recurring` (per-merchant interval series → median gap
   + coefficient of variation bands → cadence; ≥3 occurrences required; DBSCAN
   on [interval, amount] separates multi-stream merchants),
   `detect_ant_expenses` (small-amount × high-frequency + Pareto share),
   `detect_price_increases` (`ruptures` change-point on variable streams),
   `detect_anomalies` (`pyod` ECOD/IsolationForest). All thresholds live in
   one `DetectionConfig` dataclass.
4. **Classify** — `classify_transactions`: pass 1 deterministic rules
   (merchant dictionary + SEPA channel heuristics); pass 2 e5-small embeddings
   (via `EmbeddingRegistry`, `backend="onnx"`) + SetFit head over the fixed
   taxonomy (§ Data Models); confidence < threshold → `needs_review`. If model
   files are unavailable/offline, degrade to rules-only + `needs_review` —
   the pipeline never blocks on the model.
5. **Assess** — `assess_deductibility`: evaluates the AEAT rule table
   (§ Data Models) → `DeductibilityVerdict` drafts (`status="draft"`) with
   rule ids, percentages, caps and `invoice_required` flags.
6. **Project** — `build_expense_wiki(statement_id)`: mints
   `UniversalNode`/`UniversalEdge` objects (finance typing in `domain_tags`,
   node kinds overloading `CONCEPT`/`CLAIM`, edge kinds `ABOUT`/`REFERENCES`)
   and publishes via `GraphPublisher.publish(GraphUpdate)` /
   `SQLitePersistence.replace_document_slice` keyed by statement digest —
   idempotent, audited, revertible. **`GraphIndexBuilder.build()` is bypassed
   entirely** (its extractors are code/document-only).
7. **Query** — `query_expenses(sql)`: DuckDB `connect(read_only=True)` +
   `SET enable_external_access=false` + `SET disabled_filesystems='LocalFileSystem'`
   + `SET lock_configuration=true` at connection creation; sqlglot validation
   (SELECT-only) + `add_row_limit` before execution.

Agent wiring (example in `examples/agents/finance/`): a `BasicAgent` with
`AutoFinanceToolkit`; graph context optionally injected via `GraphMemoryMixin`
/ `build_graph_memory_toolkit` (both already SQLite-native). The example uses
the **CLI** human channel for reviewing drafts (brainstorm OQ6) — formal
ConfirmationGuard gating of *writes* belongs to Spec B.

### Component Diagram

```
 .xlsx (BBVA) ──► parse_bank_excel ─┐
                                    ├─► DuckDB file (source of truth)
 .n43 ────────► parse_n43 ─────────┘        │
                                            ├─► normalize_merchants ─► detect_* ─► classify_transactions
                                            │                                        │ (rules → e5-small ONNX + SetFit)
                                            ├─► assess_deductibility ◄──────────────┘
                                            │        │ drafts
                                            ▼        ▼
                                   query_expenses  build_expense_wiki ──► GraphPublisher ──► SQLitePersistence
                                   (read-only SQL)     (domain_tags)       (CommitReceipt,     (nodes/edges/fts,
                                                                            revert_commit)      commit log)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` (FEAT-391 `auto_open`) | extends | `_open`/`_close` manage DuckDB + persistence dirs; `super().__init__(**kwargs)` mandatory |
| `ExcelStructureAnalyzer` | uses | workbook/table/header detection for `parse_bank_excel` — do not rewrite |
| `parrot_tools.business_automation.ingest` | uses (import or lift) | `compute_statement_digest` idempotency + row-count cross-check pattern (FEAT-453) |
| `SQLitePersistence` + `GraphPublisher` | uses | KB write path; builder bypassed; duck-typed seam pinned by conformance tests (Module 7) |
| `build_graph_memory_toolkit` / `GraphMemoryMixin` | uses | agent-side graph read access (SQLite + deterministic `HashingGraphEmbedder`) |
| `EmbeddingRegistry` + `SentenceTransformerModel(backend="onnx")` | uses | e5-small **already catalogued** (`catalog.py:1106`) — no core change (supersedes brainstorm OQ8 assumption) |
| `add_row_limit` / `AbstractDatabaseSource.validate_query` / `QueryValidator` | uses | SQL sandbox layers for `query_expenses` |
| `TOOL_REGISTRY` (`parrot_tools/__init__.py`) | modifies | one new entry: `auto_finance` |
| `packages/ai-parrot-tools/pyproject.toml` | modifies | new `finance` extra |

### Data Models

```python
# parrot_tools/finance/models.py — Pydantic v2; amounts are Decimal everywhere
class BankTransaction(BaseModel):
    txn_id: str                      # deterministic hash(statement_digest, row)
    statement_id: str
    date: datetime.date
    value_date: datetime.date | None
    concept_raw: str                 # original descriptor, verbatim
    merchant_norm: str | None        # canonical merchant (after normalize)
    amount: Decimal                  # signed; negative = charge
    balance: Decimal | None
    sepa_channel: SepaChannel        # ADEUDO|RECIBO|TARJETA|BIZUM|TRANSFERENCIA|COMISION|OTROS
    category_l1: str | None
    category_l2: str | None
    classification_source: Literal["rule", "model", "human", "needs_review"]
    confidence: float | None

class Subscription(BaseModel):       # detect_recurring output
    merchant: str; cadence: Cadence; amount_band: tuple[Decimal, Decimal]
    occurrences: int; last_seen: date; next_expected: date | None
    variability: Literal["fixed", "variable"]

class AntExpense(BaseModel):         # frequency×amount + Pareto
    merchant: str; monthly_frequency: float; avg_amount: Decimal
    monthly_total: Decimal; pareto_share: float

class PriceChange(BaseModel):        # ruptures change-point
    merchant: str; change_date: date; before: Decimal; after: Decimal; pct: float

class Anomaly(BaseModel):            # pyod
    txn_id: str; score: float; detector: Literal["ecod", "iforest"]; reason: str

class DeductibilityVerdict(BaseModel):   # drafts consumed by Spec B
    draft_id: str; txn_id: str; rule_id: str
    deductible_pct: Decimal; capped_amount: Decimal | None
    legal_basis: str                 # human-readable AEAT citation
    invoice_required: bool
    status: Literal["draft", "approved", "rejected", "registered"]

class AeatRule(BaseModel):           # data-driven rule table (versioned data file)
    rule_id: str; matcher: RuleMatcher   # category/merchant/channel predicates
    deductible_pct: Decimal; annual_cap: Decimal | None
    requires_exclusive_use: bool; invoice_required: bool; legal_basis: str

class DetectionConfig(BaseModel):    # ALL thresholds in one place
    min_occurrences: int = 3
    cv_max_monthly: float = 0.15
    fuzzy_group_threshold: int = 85
    fuzzy_suggest_threshold: int = 70
    ant_max_amount: Decimal = Decimal("20")
    ant_min_monthly_freq: int = 4
    classify_min_confidence: float = 0.65
    # ... every other tunable
```

**Fixed taxonomy proposal (brainstorm OQ5 — review at spec approval).**
Versioned data file `parrot_tools/finance/data/taxonomy_es_autonomo_v1.yaml`,
13 level-1 / ~41 level-2 categories:

| L1 | L2 |
|---|---|
| `vivienda-suministros` | alquiler, luz, agua, gas, internet-fijo, comunidad-ibi |
| `telecomunicaciones` | movil-personal, linea-profesional |
| `software-saas` | saas, hosting-dominios, licencias |
| `servicios-profesionales` | gestoria-asesoria, legal, coworking, marketing |
| `cuotas-seguros` | cuota-reta, seguros-profesionales, mutualidades-colegios |
| `formacion` | cursos-congresos, libros-material |
| `transporte-viajes` | combustible-peajes, transporte-publico, hoteles, dietas |
| `alimentacion-restauracion` | supermercado, restaurantes-cafeterias, delivery |
| `ocio-suscripciones` | streaming, gimnasio-deporte, apps-juegos |
| `compras` | ropa, hogar, electronica, marketplaces |
| `salud` | farmacia, medico-optica |
| `finanzas-impuestos` | comisiones-bancarias, prestamos, impuestos, bizum-transferencias-personales |
| `ingresos` | facturacion-clientes, devoluciones, intereses, otros-abonos |

**Initial AEAT rule table (v1, data file `aeat_rules_v1.yaml`)** — encodes the
source document's confirmed 2026 figures: `AEAT-SAAS-100` (software/SaaS 100%
if afecto, invoice required), `AEAT-SUMINISTROS-30PROP` (30% × m² proportion,
requires 036/037 flag in user profile), `AEAT-TEL-EXCLUSIVA` (phone 100% only
if exclusive professional line), `AEAT-DIFICIL-5PCT` (5% net positive yield,
cap 2.000 €/yr — informational aggregate, not per-transaction),
`AEAT-CUOTA-RETA-100`, `AEAT-DIETAS-26_67` (electronic payment required),
`AEAT-FORMACION-100`, `AEAT-COWORKING-100`. Every verdict cites its rule.

### New Public Interfaces

```python
# parrot_tools/finance/toolkit.py
class AutoFinanceToolkit(AbstractToolkit):
    """Deterministic personal-finance pipeline over a local DuckDB + GraphIndex ExpenseWiki."""
    auto_open = True
    tool_prefix = "fin"

    def __init__(self, data_dir: str | Path = "~/.parrot/finance",
                 detection_config: DetectionConfig | None = None,
                 taxonomy_path: str | Path | None = None,
                 rules_path: str | Path | None = None,
                 enable_model_classification: bool = True, **kwargs): ...

    async def parse_bank_excel(self, path: str, bank: str = "bbva") -> dict: ...   # → {statement_id, rows, skipped, digest}
    async def parse_n43(self, path: str) -> dict: ...
    async def normalize_merchants(self, statement_id: str | None = None) -> dict: ...
    async def detect_recurring(self, min_occurrences: int = 3) -> dict: ...        # → {subscriptions: [Subscription...]}
    async def detect_ant_expenses(self) -> dict: ...
    async def detect_price_increases(self) -> dict: ...
    async def detect_anomalies(self) -> dict: ...
    async def classify_transactions(self, statement_id: str | None = None) -> dict: ...
    async def assess_deductibility(self, statement_id: str | None = None) -> dict: ...  # → drafts
    async def correct_classification(self, txn_id: str, category_l1: str,
                                     category_l2: str) -> dict: ...                # human feedback, persisted + wiki-published
    async def build_expense_wiki(self, statement_id: str | None = None) -> dict: ...    # → {commit_id, nodes, edges}
    async def revert_wiki_commit(self, commit_id: str) -> dict: ...
    async def query_expenses(self, sql: str, max_rows: int = 200) -> dict: ...     # read-only sandbox
```

All results are JSON-serializable dicts (`model_dump()` in `_post_execute`,
`DatabaseQueryToolkit` pattern). Explicit `@tool_schema` Pydantic schemas on
every tool for good LLM-facing parameter docs (auto-generated descriptions are
`"Parameter: x"` — insufficient).

---

## 3. Module Breakdown

### Module 1: Data models, taxonomy & DuckDB store
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/finance/models.py`,
  `store.py`, `data/taxonomy_es_autonomo_v1.yaml`, `data/aeat_rules_v1.yaml`
- **Responsibility**: Pydantic models (§2), DuckDB schema (transactions,
  merchants, statements/manifests, verdicts — DECIMAL amounts), `FinanceStore`
  wrapper (open/close, migrations, import manifest, digest registry).
- **Depends on**: none (foundation).

### Module 2: Ingestion (Excel BBVA + Norma 43)
- **Path**: `parrot_tools/finance/ingest.py`
- **Responsibility**: `parse_bank_excel` (ExcelStructureAnalyzer + column
  mapping + digest + row-count cross-check), `parse_n43` (csb43 wrapper behind
  own dataclass boundary), idempotent load into `FinanceStore`.
- **Depends on**: Module 1.

### Module 3: Merchant normalization
- **Path**: `parrot_tools/finance/normalize.py`
- **Responsibility**: SEPA-ES regex cleaning + rapidfuzz grouping + canonical
  merchant registry with human-correction precedence.
- **Depends on**: Module 1.

### Module 4: Deterministic detectors
- **Path**: `parrot_tools/finance/detect.py`
- **Responsibility**: recurring (gaps+CV+DBSCAN), ant expenses, price
  increases (ruptures), anomalies (pyod). Pure functions over
  `FinanceStore`-fetched frames; `DetectionConfig` injected.
- **Depends on**: Modules 1, 3.

### Module 5: Local classifier
- **Path**: `parrot_tools/finance/classify.py`
- **Responsibility**: rules pass (merchant dict + channel heuristics),
  embeddings pass (`EmbeddingRegistry` → e5-small ONNX), SetFit head training
  helper + inference, confidence gating → `needs_review`, offline degrade,
  200-row held-out eval harness (report generator, not a CI gate).
- **Depends on**: Modules 1, 3.

### Module 6: AEAT deductibility engine
- **Path**: `parrot_tools/finance/aeat.py`
- **Responsibility**: data-driven rule evaluation → `DeductibilityVerdict`
  drafts; user fiscal profile (m² proportion, 036/037 flags, exclusive line).
- **Depends on**: Modules 1, 5.

### Module 7: ExpenseWiki projection (GraphIndex)
- **Path**: `parrot_tools/finance/wiki.py`
- **Responsibility**: DuckDB state → `UniversalNode`/`UniversalEdge` with
  `domain_tags` typing → `GraphPublisher.publish` /
  `replace_document_slice(statement_digest, ...)`; `revert_wiki_commit`;
  **persistence-seam conformance test suite** (pins the duck-typed contract
  against `SQLitePersistence` for future backend swaps).
- **Depends on**: Modules 1, 4, 5, 6.

### Module 8: Sandboxed query tool + toolkit assembly
- **Path**: `parrot_tools/finance/toolkit.py`, `query.py`, plus
  `parrot_tools/__init__.py` (TOOL_REGISTRY) and
  `packages/ai-parrot-tools/pyproject.toml` (`finance` extra)
- **Responsibility**: `query_expenses` (read-only + locked-config connection,
  sqlglot SELECT-only validation, LIMIT injection), `AutoFinanceToolkit`
  assembly (`auto_open`, `_open`/`_close`, `@tool_schema` on every tool,
  `_post_execute` model_dump), registry + extra.
- **Depends on**: Modules 1–7.

### Module 9: Example agent, fixtures & docs
- **Path**: `examples/agents/finance/`, `packages/ai-parrot-tools/tests/finance/`,
  `docs/finance-toolkit.md`
- **Responsibility**: runnable `BasicAgent` wiring (+ optional
  `GraphMemoryMixin`), CLI-channel draft review loop, BBVA anonymization
  script + anonymized Excel/N43 fixtures + synthetic SEPA fixtures, docs.
- **Depends on**: Module 8.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_models_decimal_roundtrip` | 1 | Amounts stay Decimal end-to-end; float rejected |
| `test_store_idempotent_import` | 1 | Same digest twice → second import is a no-op with report |
| `test_parse_bbva_excel_layout` | 2 | Fixture workbook → correct column mapping, row count cross-check |
| `test_parse_excel_rowcount_mismatch_refuses` | 2 | Analyzer/pandas disagreement → import refused (FEAT-453 behavior) |
| `test_parse_n43_lenient_and_strict` | 2 | csb43 lenient parses fixture; malformed record → clear error naming line |
| `test_normalize_sepa_prefixes` | 3 | ADEUDO/RECIBO/COMPRA TARJETA/BIZUM noise stripped |
| `test_fuzzy_grouping_thresholds` | 3 | ≥85 groups, 70–85 suggests, <70 leaves apart |
| `test_human_correction_precedence` | 3 | Corrected merchant outranks fuzzy match on re-run |
| `test_detect_recurring_min3_and_cv` | 4 | 2 occurrences → none; 3 stable monthly → Subscription; golden values |
| `test_dbscan_multistream_merchant` | 4 | Amazon-style mixed streams separated |
| `test_price_increase_changepoint` | 4 | Synthetic step in amount series → PriceChange at right date |
| `test_anomaly_detectors` | 4 | Injected outlier flagged by ECOD/iforest |
| `test_rules_pass_deterministic` | 5 | Same input → same categories across runs (no model needed) |
| `test_confidence_gate_needs_review` | 5 | Below-threshold → needs_review, never a guessed category |
| `test_offline_degrade_rules_only` | 5 | Model unavailable → rules-only + needs_review, no exception |
| `test_aeat_rules_table` | 6 | Each v1 rule: pct/cap/invoice_required/citation correct (incl. 5% cap 2.000€ aggregate) |
| `test_wiki_projection_idempotent` | 7 | Re-project same digest → replace_document_slice, no duplicates |
| `test_wiki_commit_revert` | 7 | revert_commit(import) restores prior graph state |
| `test_persistence_seam_conformance` | 7 | Contract suite green against `SQLitePersistence` |
| `test_query_rejects_non_select` | 8 | INSERT/UPDATE/DDL/ATTACH/COPY → rejected by validation |
| `test_query_sandbox_locked` | 8 | `SET enable_external_access=true` attempt fails (lock_configuration) |
| `test_query_limit_injected` | 8 | Unbounded SELECT gets LIMIT max_rows |
| `test_all_tools_async_and_schema` | 8 | Every public tool is coroutine; no DataFrame params in generated schemas; explicit @tool_schema present |

### Integration Tests
| Test | Description |
|---|---|
| `test_e2e_excel_to_drafts` | BBVA fixture → ingest → normalize → detect → classify (rules-only) → assess → drafts with citations |
| `test_e2e_n43_to_wiki` | N43 fixture → ingest → build_expense_wiki → GraphIndexToolkit query finds merchant/subscription nodes |
| `test_e2e_reimport_noop` | Full pipeline twice on same file → identical state, no duplicate wiki commits |
| `test_model_classification_eval` | (marked `@pytest.mark.model`, skipped offline/CI) SetFit eval on 200-row held-out set → accuracy report artifact |

### Test Data / Fixtures
```python
# tests/finance/conftest.py
@pytest.fixture
def bbva_xlsx(tmp_path):        # anonymized real BBVA statement (script: tests/finance/anonymize_bbva.py)
    ...
@pytest.fixture
def n43_file(tmp_path):         # anonymized real BBVA Norma 43 export
    ...
@pytest.fixture
def synthetic_sepa_df():        # generator: ADEUDO/RECIBO/TARJETA/BIZUM descriptors,
    ...                          # known subscriptions (Netflix mensual, gym), ant expenses (cafés), one price jump, one outlier
```
Anonymization script replaces names/IBANs/references deterministically before
any fixture is committed; raw statements NEVER enter git.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit + integration tests pass (`pytest packages/ai-parrot-tools/tests/finance/ -v`), model-marked tests skippable offline.
- [ ] Every detect/assess function is deterministic: fixed fixture → identical output across runs (golden-file tests).
- [ ] Ingestion is idempotent by statement digest for both `.xlsx` and `.n43`; re-import reports a no-op.
- [ ] Amounts are `Decimal`/`DECIMAL` end-to-end — no float arithmetic on money.
- [ ] `query_expenses` provably rejects non-SELECT, ATTACH/COPY and config changes (read_only + enable_external_access=false + lock_configuration=true + sqlglot validation + LIMIT injection) — covered by tests.
- [ ] Classification below `classify_min_confidence` → `needs_review`; model absence degrades to rules-only without blocking; no transaction data leaves the machine (no remote LLM/API calls anywhere in `parrot_tools.finance`).
- [ ] `build_expense_wiki` is idempotent per digest; each publish yields a `CommitReceipt`; `revert_wiki_commit` restores prior state — covered by tests.
- [ ] Persistence-seam conformance suite passes against `SQLitePersistence`.
- [ ] `assess_deductibility` emits drafts only, each citing an `AeatRule` (v1 figures: 5% cap 2.000 €; 30%×m² utilities; exclusive-line phone; dietas 26,67 €) — nothing auto-filed.
- [ ] All tools are `async def` with explicit `@tool_schema`; no DataFrame/Series parameters; toolkit passes `_generate_tools()` exposure test.
- [ ] New deps (`duckdb`, `csb43`, `rapidfuzz`, `scipy`, `statsmodels`, `ruptures`, `pyod`, `scikit-learn`, `setfit`) declared ONLY in the new `finance` extra; `ydata-profiling`/`great_expectations` NOT introduced.
- [ ] `TOOL_REGISTRY` entry present; `from parrot_tools.finance import AutoFinanceToolkit` resolves.
- [ ] Docs: `docs/finance-toolkit.md` covers setup, taxonomy/rules versioning, privacy posture.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Carried forward from `sdd/proposals/auto-finance-agent.brainstorm.md` Code
> Context and **re-verified 2026-08-31** (anchors greped; line numbers current).

### Verified Imports
```python
from parrot.tools import AbstractToolkit, tool_schema            # parrot/tools/__init__.py
from parrot.tools.dataset_manager.excel_analyzer import ExcelStructureAnalyzer
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.schema import (UniversalNode, UniversalEdge,
    GraphUpdate, CommitReceipt, NodeKind, EdgeKind)
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot.knowledge.graphindex.mixin import GraphMemoryMixin
from parrot.embeddings.registry import EmbeddingRegistry
from parrot.tools.databasequery.base import add_row_limit
from parrot.security.query_validator import QueryValidator
from parrot_tools.business_automation.ingest import compute_statement_digest
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                       # :216
    confirming_tools: frozenset = frozenset()     # :285 (unprefixed names; applied :678)
    auto_open: bool = False                       # :310 (FEAT-391)
    def __init__(self, **kwargs): ...             # :312 — subclasses MUST call super().__init__
    async def _open(self) -> None: ...            # :388
    async def _close(self) -> None: ...           # :404 — overrides must await super()._close()
    async def _ensure_open(self) -> None: ...     # :417
    async def _post_execute(self, tool_name, result, /, **kwargs) -> Any: ...  # :468
# _generate_tools (:537) exposes ONLY public `async def` methods (:560);
# pd.DataFrame/pd.Series/pa.Table params are DROPPED from schemas (:77-99).
# @tool_schema — parrot/tools/decorators.py:39 (sets func._args_schema :52; read at toolkit.py:645)

# packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py
class SQLitePersistence:                          # :138 — public API mirrors GraphIndexPersistence (:144, duck-typed)
    def __init__(self, db_dir: Path) -> None: ...                              # :153
    async def persist_graph(self, ctx, nodes, edges) -> dict[str, Any]: ...    # :263
    async def replace_document_slice(self, ctx, document_uri, nodes, edges) -> dict: ...  # :341
    async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]: ...  # :574
    async def apply_update(self, ctx, update: GraphUpdate) -> CommitReceipt: ... # :608
    async def revert_commit(self, ...) -> dict: ...                             # :856

# packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py
class GraphPublisher:                             # :37 (duck-typed persistence, :41-43)
    def __init__(self, persistence: Any, ctx: TenantContext) -> None: ...       # :47
    async def publish(self, update: GraphUpdate) -> CommitReceipt: ...          # :90
    async def revert_commit(self, commit_id: str) -> dict[str, Any]: ...        # :140
# publish() stamps AssertionMeta and flips Provenance EXTRACTED→ASSERTED for agent-minted nodes

# packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class NodeKind(str, Enum): ...                    # :36 — CLOSED: document,section,symbol,concept,rationale,skill,wiki_page,run,claim
class EdgeKind(str, Enum): ...                    # :64 — CLOSED: contains,references,defines,mentions,explains,extends,produced,about,supported_by,contradicts
class UniversalNode(BaseModel):                   # :143 — domain_tags: dict (:172) ← finance typing lives HERE
class UniversalEdge(BaseModel):                   # :178 — domain_tags: dict (:208)
class GraphUpdate(BaseModel): ...                 # :231
class CommitReceipt(BaseModel): ...               # :267

# packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
async def build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent",
    run_id=None, embedder=None, client=None, dimension=DEFAULT_DIMENSION) -> "GraphIndexToolkit"  # :203
class HashingGraphEmbedder: ...                   # :118 — deterministic, offline
class GraphMemoryMixin: ...                       # mixin.py:30 (SQLite-only; enable_graph_memory etc. :46-51)

# packages/ai-parrot/src/parrot/tools/dataset_manager/excel_analyzer.py
class ExcelStructureAnalyzer:                     # :133
    def analyze_workbook(self) -> Dict[str, SheetAnalysis]: ...                 # :163
    def extract_table_as_dataframe(self, ...) -> ...: ...                       # :170

# packages/ai-parrot-tools/src/parrot_tools/business_automation/ingest.py (FEAT-453)
def compute_statement_digest(xlsx_path) -> ...    # :99 — cross-checks ExcelLoader vs pd.read_excel row count (:138-143)
# ImportPlanBundle :189, _write_import_manifest :321, reconcile :415

# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:                          # :55 (singleton .instance() :104)
    async def get_or_create(self, model_name, model_type="huggingface", **kwargs): ...  # :223
# ONNX: SentenceTransformerModel(model_name, backend="onnx", file_name="model_quantized.onnx")
#   packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:112,:134,:150-155
# e5 "query: "/"passage: " prefixes auto-applied (_resolve_prefixes :33)
# intfloat/multilingual-e5-small ALREADY CATALOGUED — parrot/embeddings/catalog.py:1106
#   (dim 384, MIT, requires_prefix=True) — re-verified 2026-08-31; NO core catalog change needed

# SQL sandbox reuse:
def add_row_limit(query: str, max_rows: int, driver: str) -> str: ...  # parrot/tools/databasequery/base.py:213 (duckdb in _SQL_DRIVERS :202)
async def validate_query(self, query: str) -> ValidationResult: ...    # base.py:362 (sqlglot, error_level=RAISE)
class QueryValidator: ...                          # parrot/security/query_validator.py:29
# DuckDBSource (asyncdb-driven; NOT used — direct duckdb API chosen) — parrot/tools/databasequery/sources/duckdb.py:29
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AutoFinanceToolkit` | `AbstractToolkit.__init__/_open/_close` | subclass + super calls | `parrot/tools/toolkit.py:216,312,388,404` |
| `ingest.parse_bank_excel` | `ExcelStructureAnalyzer.analyze_workbook/extract_table_as_dataframe` | direct call | `excel_analyzer.py:163,170` |
| `ingest` | `compute_statement_digest` | import (or lifted shared module) | `business_automation/ingest.py:99` |
| `wiki.build_expense_wiki` | `GraphPublisher.publish` → `SQLitePersistence.replace_document_slice/apply_update` | publish path (builder bypassed) | `publish.py:90`, `persist_sqlite.py:341,608` |
| `classify` | `EmbeddingRegistry.get_or_create(..., backend="onnx")` | registry | `registry.py:223`, `huggingface.py:150-155` |
| `query.query_expenses` | `duckdb.connect(read_only=True)` + `add_row_limit` + sqlglot validation | direct duckdb API | `base.py:213,362` |
| example agent | `build_graph_memory_toolkit` / `GraphMemoryMixin` | factory/mixin | `factory.py:203`, `mixin.py:30` |

### Does NOT Exist (Anti-Hallucination)
- ~~any finance/expense/merchant/recurrence/deductibility code in the workspace~~ — `AutoFinanceToolkit`, `parse_bank_excel`, `normalize_merchants`, `detect_recurring`, AEAT rules, "gastos hormiga": all greenfield
- ~~finance `NodeKind`/`EdgeKind` members or an enum-extension mechanism~~ — closed enums (schema.py:36,64); use `domain_tags` + CONCEPT/CLAIM/ABOUT/REFERENCES overloading (ratified)
- ~~ABC/Protocol for GraphIndex persistence~~ — pure duck typing (zero abstractmethod hits in persist/publish/builder); Module 7's conformance suite pins the contract
- ~~a tabular/transactional extractor in `GraphIndexBuilder`~~ — stage-1 extractors are code/loader/skill only; `SourceConfig` has no CSV/statement field → builder MUST be bypassed
- ~~generic classifier abstraction (`AbstractClassifier`, zero-shot helper, taxonomy machinery)~~ — only special-purpose guardrail ONNX classifiers exist (`_OnnxInjectionEngine`, prompt_injection.py:187 — pattern reference only)
- ~~`ruptures`, `pyod`, `setfit`, `csb43`, `great_expectations` in the workspace~~ — absent from all pyprojects and uv.lock; `ydata-profiling` deliberately removed (numpy pin clash) — do NOT reintroduce
- ~~a declared `duckdb` dependency~~ — installed v1.2.2 transitively via asyncdb (`uv.lock:2879`) but undeclared; the `finance` extra must declare it (`>=1.2`)
- ~~direct `duckdb.connect()` usage anywhere~~ — DuckDB exists only as an asyncdb driver behind `DuckDBSource`; this spec introduces the first direct-API usage (sync API → run in executor)
- ~~`DatabaseAgent` accepting a plain `AbstractToolkit`~~ — typed/coupled to `DatabaseToolkit` (dsn, primary_schema, …); the example agent uses `BasicAgent`
- ~~SQLite `AbstractStore` backend / sqlite-vec / sqlite-vss~~ — vector search on the SQLite planes is brute-force cosine in Python
- ~~`examples/agents/web/services/hooba_agent.py`~~ — does not exist (Spec B concern; private assets out-of-repo)
- ~~pandas DataFrame tool parameters~~ — silently dropped from generated schemas (toolkit.py:77-99); tools exchange `statement_id`/`draft_id`/paths
- ~~sync tool methods~~ — `_generate_tools` requires `inspect.iscoroutinefunction` (toolkit.py:560); every tool is `async def`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Toolkit conventions: `QuantToolkit` (pure-deterministic numeric tools →
  `model_dump()` results), `DatabaseQueryToolkit` (`tool_prefix`,
  `_post_execute` serialization), `BaseResearchToolkit`/`BusinessAutomationToolkit`
  (FEAT-391 `auto_open` + `_open`/`_close` for connections).
- Async-first: DuckDB's Python API and sklearn/SetFit inference are sync —
  wrap in `asyncio.get_running_loop().run_in_executor(...)`; never block the loop.
- Google-style docstrings + strict type hints; `self.logger`, never print.
- Wrap `csb43` behind `parrot_tools.finance.ingest._N43Statement` dataclasses so
  the parser is swappable without touching callers.
- Taxonomy and AEAT rules are **versioned data files**, not code constants —
  updating 2027 fiscal figures must not require a code change.
- Fiscal user profile (m² afectos, 036/037 flag, exclusive phone line) is
  explicit config; rules referencing it are skipped (with note) when unset.
- e5 prefixes (`"query: "`/`"passage: "`) are auto-applied by
  `_resolve_prefixes` — do NOT hand-prefix.
- Privacy: `parrot_tools.finance` performs no network I/O except the one-time
  HuggingFace model download (overridable via local model path / HF cache).

### Known Risks / Gotchas
- **BBVA layout drift**: Excel exports change; the analyzer + column-mapping
  heuristics must fail loudly (refuse import) rather than mis-map. N43 is the
  stable fallback ingestion path by design.
- **csb43 bus-factor 1** (single maintainer, Beta classifier) — mitigated by
  the dataclass boundary and the frozen AEB43 format.
- **Duck-typed persistence seam** — no compiler enforcement; the Module 7
  conformance suite is the guard. Do not call private `SQLitePersistence`
  internals.
- **Closed graph enums** — semantic typing lives in `domain_tags`; queries via
  `GraphIndexToolkit` must filter on tags, not kinds. If this proves too weak,
  an enum-extension proposal is a separate mini-spec (out of scope here).
- **DuckDB sandbox is defense-in-depth, not an OS sandbox** (DuckDB docs'
  own caveat) — acceptable for a personal local agent; documented in docs.
- **Model download in CI** — all model-dependent tests marked
  `@pytest.mark.model` and skipped when the model/cache is absent.
- **<6 months of history** → quarterly/annual subscriptions undetectable;
  the report must state this explicitly (source-doc caveat).
- **Truncated ADEUDO creditors** (140-char SEPA concept) → `needs_review`,
  never auto-deducted.
- **DECIMAL in DuckDB↔pandas round-trips** — fetch as Arrow/objects, not
  float64; add a regression test (`test_models_decimal_roundtrip`).
- Uncommitted-work hazard: `parrot/bots/database/agent.py` had unrelated WIP
  (issue #1269) during spec authoring — do not base anything on it.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `duckdb` | `>=1.2` | analytical store + sandboxed read-only agent SQL (installed transitively; must be DECLARED) |
| `csb43` | `>=1.1.0` | Norma 43/AEB43 parsing (LGPL-3.0+, maintained 2026-05) |
| `rapidfuzz` | `>=3.0` | merchant fuzzy grouping (present in `scraping` extra; add to `finance`) |
| `scipy` | `>=1.11` | interval statistics (installed transitively; declare) |
| `statsmodels` | `>=0.14` | ACF cross-check on long histories (installed transitively; declare) |
| `ruptures` | `>=1.1` | price-increase change-point detection (new) |
| `pyod` | `>=2.0` | anomaly detection ECOD/IsolationForest (new; user decision) |
| `scikit-learn` | `>=1.4` | DBSCAN, eval metrics (installed; pin in extra) |
| `setfit` | `>=1.1.3` | few-shot fixed-taxonomy classifier head (new) |
| `sentence-transformers` | `>=5.0` | e5-small body (already declared, embeddings pkg) |
| `optimum[onnxruntime]` | `>=2.0` | ONNX inference backend (already declared, onnx extra) |

All new entries go in a `finance = [...]` extra of
`packages/ai-parrot-tools/pyproject.toml` (pattern: `research`,
`business_automation` extras).

---

## 8. Open Questions

- [x] KB substrate — *Resolved in brainstorm*: **GraphIndex on SQLite** (`SQLitePersistence` + `GraphPublisher`, builder bypassed), user-ratified 2026-08-31; finance typing via `domain_tags`, enum extension out of scope, conformance suite pins the seam.
- [x] Fixture bank — *Resolved in brainstorm*: **BBVA** (real Excel + Norma 43, anonymized by script before commit).
- [x] Anomaly library — *Resolved in brainstorm*: **add `pyod`** (ECOD + IsolationForest).
- [x] Taxonomy — *Resolved in brainstorm*: propose the concrete 2-level list in this spec (§2 Data Models) for review at spec approval.
- [x] HITL channel for the example agent — *Resolved in brainstorm*: **CLI**; formal ConfirmationGuard write-gating is Spec B.
- [x] e5-small catalog entry — *Resolved in brainstorm as "add it"*; **superseded by re-verification**: the entry already exists (`parrot/embeddings/catalog.py:1106`) — no core change needed.
- [ ] Taxonomy v1 concrete list (§2): confirm/amend the 13×~41 categories at spec approval — *Owner: Jesús*
- [ ] SetFit initial training set: how many labeled examples per category can the user provide from their own history (target ≥8/category for few-shot)? Decidable during Module 5 implementation — *Owner: Jesús*
- [ ] Fiscal profile defaults (m² afectos %, 036/037 flag, exclusive phone line) for the example agent config — *Owner: Jesús* (implementation-time)

*(Spec B-only question — private hooba_agent assets path — remains in the brainstorm and does not block this spec.)*

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks sequential in one worktree
  (`.claude/worktrees/feat-478-auto-finance-toolkit`, branched from `dev`).
- **Rationale**: Modules 2–8 share Module 1's DuckDB schema and models file;
  sequential execution avoids schema-merge conflicts. Module ordering follows
  the dependency chain (1 → 2/3 → 4/5 → 6 → 7 → 8 → 9).
- **Cross-feature dependencies**: none to merge first. Spec B
  (`hooba-service-toolkit`) depends on this spec's `DeductibilityVerdict` and
  must be decomposed AFTER this spec merges (or based on its worktree).
  Shared-file merge surface with other in-flight work is limited to
  `parrot_tools/__init__.py` (TOOL_REGISTRY) and `ai-parrot-tools/pyproject.toml`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-31 | Jesús Lara (+ Claude) | Initial draft from auto-finance-agent brainstorm (Option B ratified) |
