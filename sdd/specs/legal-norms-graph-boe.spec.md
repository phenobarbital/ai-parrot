---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
# Intentional FEAT-ID reuse: FEAT-449 was reserved by /sdd-proposal
# (commit a234dfe1c) for the Legal LLM Wiki initiative. This spec is the
# first deliverable of that initiative (decision D4 — Sprint 1 only), not a
# new feature, so it reuses the ID rather than burning a second one.
reuse_feature_id: FEAT-449
---

# Feature Specification: Legal Norms Graph — BOE consolidated legislation with temporal validity

**Feature ID**: FEAT-449
**Date**: 2026-08-23
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

> **Parent initiative**: [Legal LLM Wiki proposal](../proposals/legal-llm-wiki-spanish-eu-law.proposal.md)
> (FEAT-449, enrichment, confidence medium). This spec implements **only** decision
> **D4 — Sprint 1**. Sprints 2–5 (case law, CENDOJ, router, `LegalAnswer`, LLM edges)
> are follow-up features.
> **Research audit**: `sdd/state/FEAT-449/` — 20 findings, 30 queries, lint clean.

---

## 1. Motivation & Business Requirements

### Problem Statement

A Spanish lawyer needs answers grounded in primary legal sources, never in model memory.
The load-bearing requirement is **temporal**: the question is rarely "what does article X
say" but "what did article X say **on the date the facts occurred**". Spanish legislation
is amended continuously; a norm cited without its version-in-force is not merely imprecise,
it is wrong.

The parent proposal established that ai-parrot already supplies most of the surrounding
machinery — a declarative ontology layer, an incremental delta-sync pipeline, declarative
AQL traversal patterns, and read-only query enforcement — but that **no temporal-validity
model exists anywhere in `parrot/knowledge/`**: a grep for `valid_from|valid_to|as_of`
across the entire subtree returns two hits, both an unrelated local variable
(finding F011, claim C8). That absence is the whole risk of the initiative, and this spec
isolates it.

This feature therefore builds the smallest possible vertical that proves temporal validity
works, on the one source whose licensing is unambiguous (BOE open data), with **zero LLM
involvement** — so that correctness is deterministic and testable against known amendment
chains rather than judged.

### Goals

- **G1** — Declare a `legal` domain ontology (`norma`, `articulo`, `materia` entities;
  `modifica`, `deroga`, `pertenece_a` relations) as a YAML layer, using the existing
  `OntologyDefinition` schema with no framework changes.
- **G2** — Ingest BOE *legislación consolidada* through the existing
  `OntologyRefreshPipeline` by registering a `BOEDataSource` with `DataSourceFactory`.
- **G3** — Model per-article version history as an embedded `versions[]` list on the
  `articulo` node (proposal decision, source §3.2 OQ2), each entry carrying `n`, `text`,
  `valid_from`, `valid_to`, `modified_by`, `kind`, `source`, `derived`.
- **G4** — Resolve "which wording was in force on date D" as a **declarative
  `TraversalPattern`** with `as_of` as an AQL bind variable — no bespoke Python resolver.
- **G5** — Prove correctness against at least one real, hand-verified amendment chain.
- **G6** — Keep the whole path deterministic: no LLM call anywhere in ingestion or
  resolution.

### Non-Goals (explicitly out of scope)

- **Case law of any kind** — `sentencia` nodes, ECLI/ROJ parsing, `cita`, `aplica_articulo`,
  `confirma`/`revoca`. Sprint 2+.
- **CENDOJ** — the verification toolkit, its throttled client, call-budget guardrail and
  terms-of-use question are entirely out of scope (decision D3; the OQ3 spike remains
  blocking for a *later* feature, not this one).
- **EUR-Lex / CELLAR** — consolidated-text diffing is derived-by-approximation (source §3.5,
  OQ4 spike) and must not contaminate the authoritative BOE path in v1.
- **The retrieval DAG, `LegalAnswer`, `LegalClaim`, `SourceRef`, groundedness checking** —
  Sprint 4+.
- **The ontological router** — routing belongs to `IntentRouterMixin`, not to a
  `KnowledgeRouter`, which does not exist (finding F005, claim C5). Sprint 4+.
- **Namespace routing / multi-brain federation** — deferred to FEAT-450 integration after
  v1 (decision D2). *Rejected in the proposal: adding a namespace discriminator to
  GraphIndex — see `legal-llm-wiki-spanish-eu-law.proposal.md` D1.*
- **Chunking and vector retrieval of article text** — `vectorize` is deliberately left empty
  in v1; per-version chunking is a Sprint 4 concern.

---

## 2. Architectural Design

### Overview

Ingestion and resolution both run entirely on the **ontology** plane
(`parrot.knowledge.ontology`), never on the GraphIndex `UniversalNode` plane. This resolves,
for v1, the two-write-path tension the proposal flagged (finding F020, claim C21):
`UniversalNode.kind` is a closed `NodeKind` enum mapped to fixed `gi_*` collections and
cannot express `norma`/`articulo`, whereas `EntityDef` accepts arbitrary collections. Because
BOE data arrives as structured records rather than documents, it enters through
`ExtractDataSource` — the loader/`GraphIndexBuilder` path is not involved at all.

Per decision **D1**, the isolation unit is an **ontology tenant** (one ArangoDB database),
resolved via `TenantOntologyManager.resolve(tenant_id, domain="legal")`. This inverts the
source skeleton's OQ1 ("namespaces over shared collections"), which finding F002 showed is
not implementable: GraphIndex has no namespace concept and `TenantContext` carries an
`arango_db` name.

Temporal resolution is **O(1) selection over an embedded list**, not a graph traversal:
`article_in_force(as_of)` selects the `versions[]` entry whose `valid_from <= as_of` and
(`valid_to` is null or `> as_of`). `modifica`/`deroga` edges are retained for provenance —
answering "which norm changed this, and when" — but are deliberately *not* the mechanism
for validity resolution.

### Component Diagram

```
BOE datos abiertos (consolidated XML)
        │
        ▼
  BOEDataSource(ExtractDataSource)          ← NEW  (registered via
        │   .extract(fields) -> ExtractionResult      DataSourceFactory
        │                                              .register_api_source)
        ▼
  OntologyRefreshPipeline.run(tenant, domain="legal")   ← EXISTING, unmodified
        │   EXTRACT → DIFF → APPLY(upsert + soft-delete)
        │   → REDISCOVER → SYNC vectors → INVALIDATE
        ▼
  OntologyGraphStore.upsert_nodes(ctx, collection, nodes, key_field)
        │
        ▼
  ArangoDB tenant db  ──  norma / articulo / materia
                          modifica / deroga / pertenece_a
        ▲
        │  execute_traversal(ctx, aql, bind_vars={"as_of": ...})
        │
  TraversalPattern "article_in_force"       ← NEW, declared in legal.ontology.yaml
        ▲
        │
  validate_aql(...)  ← EXISTING: rejects INSERT/UPDATE/REMOVE/REPLACE/UPSERT,
                        system collections, JS; enforces max traversal depth
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `ExtractDataSource` (ABC) | subclass | `BOEDataSource` implements `extract()` + `list_fields()` |
| `DataSourceFactory` | register | `register_api_source("boe", BOEDataSource)` — classmethod, no factory edits |
| `OntologyRefreshPipeline` | uses (unmodified) | driven purely by `entity_def.source == "boe"` |
| `OntologyGraphStore` | uses (unmodified) | `upsert_nodes`, `execute_traversal`, `soft_delete_nodes` |
| `TenantOntologyManager` | uses (unmodified) | `resolve(tenant_id, domain="legal")` |
| `OntologyMerger` | uses (unmodified) | merges `base` + `legal` YAML layers |
| `OntologyDefinition` YAML schema | extends by config | new `legal.ontology.yaml` domain layer |
| `validate_aql` | uses (unmodified) | inherited read-only guarantee for the traversal |
| `@schedule` (ai-parrot-server) | optional wiring | `ScheduleType.DAILY` incremental sync (decision D5) |

### Data Models

The `versions[]` entry is the one genuinely new structure. Because `PropertyDef.type` is a
closed `Literal` (`string|int|float|boolean|date|list|dict`), `versions` is declared as
`list` in the ontology YAML, and its element shape is enforced in Python by the
`BOEDataSource` before records reach the pipeline:

```python
# Shape produced by BOEDataSource and stored inside articulo.versions[]
class ArticleVersion(BaseModel):
    n: int                       # 0-based version index
    text: str | None             # None when kind == "supresion"
    valid_from: date
    valid_to: date | None        # None = currently in force
    modified_by: str | None      # BOE id of the amending norm; None for n == 0
    kind: Literal["redaccion", "adicion", "supresion"]
    source: Literal["boe_consolidada"]
    derived: bool                # False for BOE; reserved for CELLAR diffing later
```

Entity keys follow the source's §1.2 principle — identifiers are canonical keys, not text:
`norma._key` is the BOE id (`BOE-A-2015-10566`); `articulo._key` is `{norma}:{art}`.

### New Public Interfaces

```python
# parrot_tools/legal/ids.py
def normalize_boe_id(raw: str) -> str: ...
def is_valid_boe_id(raw: str) -> bool: ...

# parrot_tools/legal/boe/datasource.py
class BOEDataSource(ExtractDataSource):
    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult: ...
    async def list_fields(self) -> list[str]: ...
```

---

## 3. Module Breakdown

### Module 1: Legal identifier utilities
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/ids.py`
- **Responsibility**: BOE-id regex, normalisation and validation. Deliberately scoped to
  BOE only in v1 — ECLI/ROJ/CELEX helpers arrive with the sources that need them.
- **Depends on**: nothing.

### Module 2: `legal.ontology.yaml` domain layer
- **Path**: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/legal.ontology.yaml`
- **Responsibility**: Declare `norma`, `articulo`, `materia` entities; `modifica`, `deroga`,
  `pertenece_a` relations; and the `article_in_force` traversal pattern. Authored against
  the shape of `field_services.ontology.yaml`.
- **Depends on**: nothing (config only; validated by `OntologyMerger`).

### Module 3: BOE consolidated parser
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/parser.py`
- **Responsibility**: Parse BOE consolidated XML into `norma` records and `articulo` records
  carrying a fully-built `versions[]` list, plus the `modifica`/`deroga` relations declared
  in the norm's *análisis* metadata. Tolerant: on parse failure, surface an error in
  `ExtractionResult.errors` rather than silently emitting an empty record.
- **Depends on**: Module 1.

### Module 4: `BOEDataSource`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/datasource.py`
- **Responsibility**: `ExtractDataSource` subclass. Fetches consolidated norms (async,
  `aiohttp`), delegates parsing to Module 3, honours the `fields` projection and a `since`
  filter for incremental runs, returns `ExtractionResult`.
- **Depends on**: Modules 1, 3.

### Module 5: Registration + scheduled sync entrypoint
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/__init__.py`
- **Responsibility**: `DataSourceFactory.register_api_source("boe", BOEDataSource)` and a
  thin `async def sync_boe(tenant_id, since=None)` entrypoint that constructs and runs
  `OntologyRefreshPipeline`. Callable from `@schedule(ScheduleType.DAILY, ...)` under
  ai-parrot-server (D5) **or** from an external cron, so the deployment shape is not baked in.
- **Depends on**: Module 4.

### Module 6: Temporal resolution helper + tests
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py`
- **Responsibility**: Thin typed wrapper that binds `as_of` and calls
  `OntologyGraphStore.execute_traversal` with the `article_in_force` pattern, returning the
  resolved version. The *logic* lives in the YAML pattern; this is ergonomics, not a second
  implementation.
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_normalize_boe_id` | 1 | Canonicalises well-formed BOE ids; rejects malformed input |
| `test_legal_ontology_merges` | 2 | `OntologyMerger.merge([base, legal])` yields a `MergedOntology` with the 3 entities and 3 relations |
| `test_legal_ontology_collections` | 2 | `get_entity_collections()` / `get_edge_collections()` return the declared names |
| `test_parse_versions_single` | 3 | Un-amended article yields exactly one version, `n=0`, `modified_by=None`, `valid_to=None` |
| `test_parse_versions_chain` | 3 | Amended article yields ordered versions with contiguous `valid_from`/`valid_to` and no gaps |
| `test_parse_supresion` | 3 | `kind="supresion"` yields `text=None` and closes the prior version |
| `test_parse_malformed_reports_error` | 3 | Malformed XML populates `ExtractionResult.errors`, never a silent empty record |
| `test_datasource_extract_projects_fields` | 4 | `extract(fields=[...])` returns only requested fields |
| `test_datasource_registered` | 5 | `DataSourceFactory().get("boe", {})` returns a `BOEDataSource` |
| `test_article_in_force_selects_version` | 6 | Given a 3-version article, each of 3 dates selects the correct wording |
| `test_article_in_force_boundary` | 6 | `as_of == valid_from` selects that version (inclusive lower bound); `as_of == valid_to` selects the *next* (exclusive upper bound) |
| `test_article_in_force_before_entry` | 6 | `as_of` before the first `valid_from` returns no version, not version 0 |

### Integration Tests

| Test | Description |
|---|---|
| `test_refresh_pipeline_ingests_boe` | `OntologyRefreshPipeline.run(tenant, domain="legal")` upserts norma+articulo nodes and reports zero errors |
| `test_refresh_is_incremental` | A second run with unchanged source yields `unchanged > 0` and `inserted == 0` |
| `test_amendment_chain_end_to_end` | Real hand-verified chain: ingest, then assert the wording in force on N dates matches the manually confirmed text |
| `test_traversal_passes_aql_validation` | The `article_in_force` `query_template` passes `validate_aql` (read-only, within depth limit) |

### Test Data / Fixtures

```python
@pytest.fixture
def boe_consolidated_xml() -> Path:
    """Checked-in BOE consolidated XML sample with a known amendment chain.

    Stored under packages/ai-parrot/tests/knowledge/fixtures/ so tests never
    hit the network. At least one article must have >= 3 versions.
    """

@pytest.fixture
def legal_tenant_ctx() -> TenantContext:
    """TenantContext resolved with domain='legal' for integration tests."""
```

> Network access is forbidden in unit tests. The BOE fetch path is exercised only by
> mocking `aiohttp`; parsing is exercised against checked-in fixtures.

---

## 5. Acceptance Criteria

- [ ] `legal.ontology.yaml` merges cleanly with `base.ontology.yaml` via `OntologyMerger`
      and declares `norma`, `articulo`, `materia`, `modifica`, `deroga`, `pertenece_a`.
- [ ] `articulo.versions[]` entries carry all eight fields (`n`, `text`, `valid_from`,
      `valid_to`, `modified_by`, `kind`, `source`, `derived`) with `source="boe_consolidada"`
      and `derived=false` for every BOE-sourced version.
- [ ] `norma._key` is the BOE id; `articulo._key` is `{norma}:{art}`. No node is created
      without a stable public identifier.
- [ ] `article_in_force` is declared as a `TraversalPattern` in the YAML with `as_of` as a
      bind variable — **not** implemented as a bespoke Python resolver.
- [ ] The `article_in_force` `query_template` passes `validate_aql` with default settings.
- [ ] `DataSourceFactory().get("boe", {})` resolves to `BOEDataSource` after import.
- [ ] `OntologyRefreshPipeline.run(tenant_id, domain="legal")` completes with
      `RefreshReport.errors == []` against the fixture source.
- [ ] A second consecutive run reports no insertions (incremental behaviour verified).
- [ ] The end-to-end amendment-chain test passes for at least one real, hand-verified norm
      (e.g. an article of LOPDGDD or another norm with a documented amendment).
- [ ] Boundary semantics are explicit and tested: `valid_from` inclusive, `valid_to` exclusive.
- [ ] **Zero LLM calls** in the ingestion or resolution path — asserted by test, not by
      convention.
- [ ] No modifications to `parrot/knowledge/ontology/` Python modules or to
      `parrot/knowledge/graphindex/` (config + new toolkit package only).
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/knowledge/ontology -v`
      and the new legal test module).
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry below was re-verified by reading
> the source during this spec run (not carried over unchecked from the proposal).

### Verified Imports

```python
# Ontology schema — packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
from parrot.knowledge.ontology.schema import (
    PropertyDef,        # line 18
    EntityDef,          # line 40
    RelationDef,        # line 116
    TraversalPattern,   # line 263
    OntologyDefinition, # line 300
    MergedOntology,     # line 330
    TenantContext,      # line 406
)
from parrot.knowledge.ontology.merger import OntologyMerger        # line 26
from parrot.knowledge.ontology.graph_store import (
    OntologyGraphStore,  # line 33
    UpsertResult,        # line 19
)
from parrot.knowledge.ontology.tenant import TenantOntologyManager  # line 29
from parrot.knowledge.ontology.refresh import (
    OntologyRefreshPipeline,  # line 61
    RefreshReport,            # line 41
    DiffResult,               # line 27
)
from parrot.knowledge.ontology.validators import validate_aql       # line 36 (async)
from parrot.knowledge.ontology.exceptions import AQLValidationError

# Extraction — packages/ai-parrot-loaders/src/parrot_loaders/extractors/
from parrot_loaders.extractors.base import (
    ExtractDataSource,   # line 50 (ABC)
    ExtractionResult,    # line 30
    ExtractedRecord,     # line 18
)
from parrot_loaders.extractors.factory import DataSourceFactory     # line 13

# Scheduling (ai-parrot-server[scheduler] only — see "Does NOT Exist")
from parrot.scheduler import schedule, ScheduleType   # lazy __getattr__ shim
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
class PropertyDef(BaseModel):                                        # line 18
    type: Literal["string","int","float","boolean","date","list","dict"]
    required: bool = False
    unique: bool = False
    default: Any = None
    enum: list[str] | None = None
    description: str | None = None
    model_config = ConfigDict(extra="forbid")

class EntityDef(BaseModel):                                          # line 40
    collection: str | None = None
    source: str | None = None            # drives OntologyRefreshPipeline
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    vectorize: list[str] = Field(default_factory=list)
    extend: bool = False
    def get_property_names(self) -> set[str]: ...

class RelationDef(BaseModel):                                        # line 116
    from_entity: str = Field(alias="from")   # YAML key is `from`
    to_entity: str = Field(alias="to")       # YAML key is `to`
    edge_collection: str
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

class TraversalPattern(BaseModel):                                   # line 263
    description: str
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str                       # AQL with @binds / @@collection binds
    post_action: Literal["vector_search","tool_call","none"] = "none"
    post_query: str | None = None
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None
    model_config = ConfigDict(extra="forbid")

class OntologyDefinition(BaseModel):                                 # line 300
    name: str
    version: str = "1.0"
    extends: str | None = None
    description: str | None = None
    entities: dict[str, EntityDef] = Field(default_factory=dict)
    relations: dict[str, RelationDef] = Field(default_factory=dict)
    traversal_patterns: dict[str, TraversalPattern] = Field(default_factory=dict)
    model_config = ConfigDict(extra="forbid")

class MergedOntology(BaseModel):                                     # line 330
    name: str; version: str
    entities: dict[str, EntityDef]
    relations: dict[str, RelationDef]
    traversal_patterns: dict[str, TraversalPattern]
    layers: list[str]; merge_timestamp: datetime
    def get_entity_collections(self) -> list[str]: ...
    def get_edge_collections(self) -> list[str]: ...
    def get_vectorizable_fields(self, entity_name: str) -> list[str]: ...
    def build_schema_prompt(self) -> str: ...

class TenantContext(BaseModel):                                      # line 406
    tenant_id: str
    arango_db: str          # ONE DATABASE PER TENANT — the isolation unit (D1)
    pgvector_schema: str
    ontology: MergedOntology

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class UpsertResult(BaseModel):                                       # line 19
    inserted: int = 0; updated: int = 0; unchanged: int = 0

class OntologyGraphStore:                                            # line 33
    def __init__(self, arango_client: Any = None) -> None: ...       # line 49
    async def initialize_tenant(self, ctx: TenantContext) -> None: ...          # line 71
    async def execute_traversal(                                                # line 185
        self, ctx: TenantContext, aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]: ...
    async def upsert_nodes(                                                     # line 225
        self, ctx: TenantContext, collection: str,
        nodes: list[dict[str, Any]], key_field: str,
    ) -> UpsertResult: ...
    async def create_edges(...) -> Any: ...                                     # line 312
    async def get_all_nodes(...) -> Any: ...                                    # line 386
    async def soft_delete_nodes(...) -> Any: ...                                # line 413
    async def ensure_collection(...) -> Any: ...                                # line 462

# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py
class TenantOntologyManager:                                         # line 29
    def resolve(self, tenant_id: str, domain: str | None = None) -> TenantContext: ...  # line 92
    def invalidate(self, tenant_id: str | None = None) -> None: ...  # line 183
    def list_tenants(self) -> list[str]: ...                         # line 198

# packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py
class OntologyRefreshPipeline:                                       # line 61
    def __init__(                                                    # line 76
        self,
        tenant_manager: TenantOntologyManager,
        graph_store: OntologyGraphStore,
        discovery: RelationDiscovery,
        datasource_factory: Any,
        cache: OntologyCache,
        vector_store: Any = None,
        source_configs: dict[str, dict[str, Any]] | None = None,
    ) -> None: ...
    async def run(self, tenant_id: str, domain: str | None = None) -> RefreshReport: ...  # line 94
    # NOTE (line ~200): entities whose `entity_def.source` is falsy are SKIPPED.

# packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py
class ExtractedRecord(BaseModel):                                    # line 18
    data: dict[str, Any]                                             # line 26
    metadata: dict[str, Any] = Field(default_factory=dict)           # line 27

class ExtractionResult(BaseModel):                                   # line 30
    records: list[ExtractedRecord]                                   # line 42
    total: int                                                       # line 43
    errors: list[str] = Field(default_factory=list)                  # line 44
    warnings: list[str] = Field(default_factory=list)                # line 45
    source_name: str                                                 # line 46
    extracted_at: datetime                                           # line 47

class ExtractDataSource(ABC):                                        # line 50
    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None: ...  # line 62
    @abstractmethod
    async def extract(                                                            # line 70
        self, fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult: ...
    @abstractmethod
    async def list_fields(self) -> list[str]: ...                                 # line 91
    async def validate(...) -> Any: ...                                           # line 102

# packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py
class DataSourceFactory:                                             # line 13
    _builtin_types = {"csv","json","sql","records"}   # BOE is NOT builtin
    @classmethod
    def register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None: ...  # line 35
    def get(self, source_name: str, source_config: dict[str, Any] | None = None) -> ExtractDataSource: ...  # line 46

# packages/ai-parrot/src/parrot/knowledge/ontology/validators.py
async def validate_aql(aql: str, max_depth: int | None = None) -> Any: ...        # line 36
# Rejects INSERT|UPDATE|REMOVE|REPLACE|UPSERT, _system/_graphs/_modules/_analyzers/
# _jobs/_queues, and APPLY|CALL|V8. Defaults max_depth to ONTOLOGY_MAX_TRAVERSAL_DEPTH.

# packages/ai-parrot-server/src/parrot/scheduler/manager.py
def schedule(                                                        # line 64
    schedule_type: ScheduleType = ScheduleType.DAILY, *,
    success_callback: Optional[Callable] = None,
    send_result: Optional[Dict[str, Any]] = None,
    callbacks: Optional[List[Dict[str, Any]]] = None,
    **schedule_config,
): ...
class ScheduleType(Enum):                                            # line 52
    ONCE="once"; DAILY="daily"; WEEKLY="weekly"; MONTHLY="monthly"
    INTERVAL="interval"; CRON="cron"; CRONTAB="crontab"
```

### Verified Configuration References

| Key | Location | Default | Use |
|---|---|---|---|
| `ONTOLOGY_MAX_TRAVERSAL_DEPTH` | `packages/ai-parrot/src/parrot/conf.py:150` | `4` | Upper bound `validate_aql` enforces on the `article_in_force` template |

### Verified YAML Authoring Shape

Confirmed against `defaults/domains/field_services.ontology.yaml` (relations at line 61,
traversal patterns at line 86) — note `from`/`to` are the YAML keys, and `@@name` denotes an
edge-collection bind:

```yaml
relations:
  assigned_to:
    from: Employee
    to: Project
    edge_collection: assigned_to
    discovery:
      strategy: field_match
      rules:
        - source_field: project_code
          target_field: project_id
          match_type: exact

traversal_patterns:
  find_project:
    description: Find the project an employee is assigned to
    trigger_intents: [my project, which project]
    query_template: >
      FOR v IN 1..1 OUTBOUND @user_id @@assigned_to RETURN v
    post_action: none
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `BOEDataSource` | `ExtractDataSource` | subclass | `parrot_loaders/extractors/base.py:50` |
| `BOEDataSource` | `DataSourceFactory` | `register_api_source("boe", ...)` | `parrot_loaders/extractors/factory.py:35` |
| `legal.ontology.yaml` | `OntologyMerger` | `merge([base, legal])` | `ontology/merger.py:51` |
| `legal.ontology.yaml` | `TenantOntologyManager` | `resolve(tenant, domain="legal")` | `ontology/tenant.py:92` |
| `sync_boe()` | `OntologyRefreshPipeline` | `run(tenant_id, domain="legal")` | `ontology/refresh.py:94` |
| `article_in_force` | `OntologyGraphStore` | `execute_traversal(ctx, aql, bind_vars={"as_of": d})` | `ontology/graph_store.py:185` |
| `sync_boe()` | `@schedule` | `ScheduleType.DAILY` (optional, D5) | `parrot/scheduler/manager.py:64` |

### Does NOT Exist (Anti-Hallucination)

- ~~`KnowledgeRouter`~~ — **no such class anywhere in the repo.** Routing is
  `IntentRouterMixin` (`parrot/bots/mixins/intent_router.py:123`). Finding F005.
- ~~GraphIndex namespaces~~ — no `namespace` field, filter or discriminator exists in
  `parrot/knowledge/graphindex/`. Isolation is `TenantContext.arango_db`. Finding F002.
- ~~`valid_from` / `valid_to` / `as_of` anywhere in `parrot/knowledge/`~~ — no temporal
  model exists; this feature introduces the first one. Finding F011.
- ~~An XML loader in `parrot_loaders`~~ — only `html.py`, `web.py`, `webscraping.py`. BOE
  XML parsing belongs inside `BOEDataSource`, **not** to a loader.
- ~~`parrot.interfaces.legal`~~ — `parrot/interfaces/` is documented as a **mixins** package
  for bot functionality, not a home for domain models. Finding F012. Legal contracts live
  under `parrot_tools/legal/`.
- ~~`parrot.scheduler.manager` in core~~ — `parrot/scheduler/__init__.py` is a 38-line lazy
  shim; the implementation ships in `ai-parrot-server[scheduler]`. Finding F009.
- ~~Any existing legal-domain code~~ — a grep for `cendoj|eurlex|celex|BOE-A-|ECLI:` across
  all of `packages/` returns **zero** matches. Finding F004.
- ~~`UniversalNode` kinds for legal entities~~ — `NodeKind` is a closed enum mapped to fixed
  `gi_*` collections; it cannot express `norma`/`articulo`. Do not route legal data through
  `GraphIndexBuilder`. Finding F020.
- ~~A counting/rate-limiting guardrail~~ — zero matches for `rate_limit|max_calls|quota` in
  `parrot/bots/guardrails/`. Not needed in v1 (no CENDOJ), but do not assume it exists.
  Finding F007.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Declarative first.** Entities, relations and the temporal traversal are *configuration*
  in `legal.ontology.yaml`. If you find yourself writing a Python function that re-implements
  version selection, stop — it belongs in `query_template`.
- **Async-first**, `aiohttp` only. Never `requests`/`httpx` (CLAUDE.md).
- **Pydantic** for `ArticleVersion` and every structured record.
- `self.logger` (inherited from `ExtractDataSource.__init__`), never `print`.
- Google-style docstrings and strict type hints on every function and class.
- Follow `field_services.ontology.yaml` for YAML shape and
  `tests/knowledge/ontology/test_ontology_merger.py` for merge-test style.

### Known Risks / Gotchas

- **`extra="forbid"` on every ontology model.** A typo'd YAML key raises rather than being
  ignored. Validate the layer with `OntologyMerger.merge` in a unit test before wiring
  anything else — it is the cheapest failure signal.
- **`RelationDef` aliases.** YAML uses `from:`/`to:`; Python attributes are `from_entity`/
  `to_entity`. Using `from_entity:` as a YAML key will fail validation.
- **Entities without `source` are silently skipped** by `OntologyRefreshPipeline.run`
  (`refresh.py` ~line 200). `articulo` and `norma` must declare `source: boe`; `materia` is
  a static taxonomy and deliberately has no source.
- **`PropertyDef.type` is a closed Literal.** `versions` must be declared `list`; the
  per-entry shape is enforced in Python, not by the ontology schema.
- **Boundary semantics must be decided once and tested.** This spec fixes `valid_from`
  inclusive, `valid_to` exclusive. Off-by-one here silently returns the wrong law.
- **BOE is the authoritative source; `derived` stays `false`.** The flag exists only so the
  later CELLAR path can mark diff-derived versions. Never set it true from BOE data.
- **No network in tests.** Parsing is fixture-driven; the fetch path is mocked.
- **Rate/etiquette toward BOE.** Even though bulk access is licensed, the sync should pace
  requests and identify itself; do not parallelise aggressively.
- **`validate_aql` is async** (`validators.py:36`) — await it in tests.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | already a core dep | async BOE fetch |
| *(XML parsing)* | stdlib `xml.etree` or an existing dep | BOE consolidated XML — prefer stdlib; do not add a new dependency without justification |

> No new third-party dependency is expected. If the BOE XML proves to need a tolerant
> parser, raise it as an open question rather than adding one silently.

---

## 8. Open Questions

### Resolved (carried forward from the FEAT-449 proposal)

- [x] **Which multiplicity model, given GraphIndex has no namespaces?** — *Resolved (D1)*:
  Layered — FEAT-450 wiki namespaces for brain selection and document ingest, with one
  ontology tenant per materia beneath carrying the typed legal graph. This inverts the
  source skeleton's OQ1: isolation is a database per materia, not namespaces over shared
  collections. *Reflected in*: §2 Overview, §2 Integration Points, §6 `TenantContext`.
- [x] **Block on FEAT-450, or proceed independently?** — *Resolved (D2)*: Proceed
  independently and integrate later; the seam is the wiki ingest `sync_graph` bridge.
  *Reflected in*: §1 Non-Goals ("namespace routing deferred").
- [x] **Does the firm hold a vLex/Aranzadi licence?** — *Resolved (D3)*: No. CENDOJ is the
  only verification path for Spanish ordinary case law, so the OQ3 spike is blocking — for
  a later feature. *Reflected in*: §1 Non-Goals (CENDOJ entirely out of scope).
- [x] **What is the v1 deliverable?** — *Resolved (D4)*: Sprint 1 only — the BOE norms
  graph with zero LLM. *Reflected in*: the entire scope of this spec.
- [x] **Is ai-parrot-server in the deployment?** — *Resolved (D5)*: Yes, so `@schedule` and
  the autonomous orchestrator are available. *Reflected in*: §3 Module 5, §6 `schedule`
  signature — while keeping the entrypoint callable from an external cron too.
- [x] **How are the two write paths reconciled?** — *Resolved during this spec's codebase
  research*: for v1 the question dissolves. BOE arrives as structured records, so ingestion
  runs through `ExtractDataSource` → `OntologyRefreshPipeline` → `OntologyGraphStore` and
  never touches `GraphIndexBuilder`/`UniversalNode`. *Reflected in*: §2 Overview, §6 Does
  NOT Exist. The question returns for Sprint 2 (case-law *documents*).

### Unresolved (defer to spec review / implementation)

- [ ] **Which specific norm and article back the end-to-end amendment-chain test?** —
  *Owner: Jesus Lara*. Needs a real norm with a documented amendment and hand-verified
  wording on chosen dates. The proposal suggested LOPDGDD vs RGPD; any norm with a clean,
  citable chain works. Blocks the final acceptance criterion, not the design.
- [ ] **Does the BOE consolidated XML expose per-article dated wording blocks as uniformly
  as the source skeleton assumes (§3.5)?** — *Owner: implementer, first task*. If article
  segmentation turns out to be inconsistent across norms, Module 3 grows a normalisation
  step and the fixture set must widen. Verify against 3 norms before building the parser.
- [ ] **Tenant naming convention for legal materias** — *Owner: Jesus Lara*. D1 fixes
  "one tenant per materia"; the concrete `tenant_id` scheme (e.g. `legal_civil`) and
  `_db_template` value are unspecified. Only matters once a second materia exists.

---

## Worktree Strategy

**Default isolation unit**: `per-spec` — all tasks run sequentially in one worktree.

The six modules form a near-linear dependency chain (1 → 3 → 4 → 5, with 2 and 6 coupled
through the YAML contract), and several tasks touch the same new package directory. There is
no meaningful parallelism to buy, and per-task worktrees would add ceremony for no benefit.

```bash
git checkout dev
git worktree add -b feat-449-legal-norms-graph-boe \
  .claude/worktrees/feat-449-legal-norms-graph-boe HEAD
```

**Cross-feature dependencies**: none. Per decision D2 this feature does **not** depend on
FEAT-450 (wiki-namespaces) and must not block on it. Coordinate only if FEAT-450 lands a
change to `parrot/knowledge/ontology/`, which its current scope does not indicate.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-23 | Jesus Lara | Initial draft — scoped to FEAT-449 decision D4 (Sprint 1, BOE norms graph, zero LLM); codebase contract re-verified against source |
