---
id: F005
query_id: Q005
type: read
intent: ContractCatalogStore ABC methods, FTS/search, upsert, verification queue query.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F005 — contracts catalog ABC and Postgres implementation

## Summary
`ContractCatalogStore` is an ABC tied to one tenant, with 40 abstract methods: cards, parties and aliases, answers audit, delta tokens and source items, relations, and the publication outbox. A `ManualCatalogStore` should cut this down to cards, versions, search, verification queue and outbox. `PostgresContractCatalog` stores the whole card as `card_json jsonb` with denormalized columns. It adds a generated English `tsvector` over title, summary, toc_digest and topics with a GIN index; `search` uses `plainto_tsquery` and `ts_rank`. `upsert` runs in one transaction with a `FOR UPDATE` revision check, a sha/URI clash check, history rows and outbox rows. The verification queue is pure SQL over `jsonb_each(card_json->'field_provenance')`, so it works for any card that has `field_provenance` and `stale_fields`.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 188-223
  symbol: `SearchHit` / `UpsertResult` / `VerificationQueueEntry`
  excerpt: |
    class SearchHit(BaseModel): card: ContractCard; rank: float = 0.0
    class UpsertResult(BaseModel): contract_id; revision; created; version_n; queued: list[PublicationRecord]
    class VerificationQueueEntry(BaseModel): card; reason: VerificationReason; fields: list[str]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 292-334
  symbol: `ContractCatalogStore.__init__`
  excerpt: |
    class ContractCatalogStore(ABC):
        def __init__(self, *, tenant_id: str, schema: str = "contracts", principal: Optional[str] = None):
            self._schema = validate_sql_identifier(schema, what="catalog schema")
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 339-364
  symbol: `ContractCatalogStore.upsert`
  excerpt: |
    async def upsert(self, card: ContractCard, *, expected_revision: Optional[int] = None,
                     version: Optional[ContractVersion] = None,
                     targets: tuple[PublicationTarget, ...] = ("ontology", "temporal")) -> UpsertResult:
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 367-396
  symbol: `ContractCatalogStore.get` / `find_by_sha` / `find_by_source_uri` / `list_cards`
  excerpt: |
    async def get(self, contract_id: str) -> Optional[ContractCard]:
    async def find_by_sha(self, sha256: str) -> Optional[ContractCard]:
    async def list_cards(self, *, status=None, verification=None, active_only: bool = True)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 398-408
  symbol: `ContractCatalogStore.search`
  excerpt: |
    async def search(self, query: str, top_k: int = 8) -> list[SearchHit]:
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 430-436
  symbol: `ContractCatalogStore.verification_queue`
  excerpt: |
    async def verification_queue(self, *, limit: int = 50) -> list[VerificationQueueEntry]:
        Missing evidence first, then low-confidence unresolved fields, then stale cards
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog.py`
  lines: 631-681
  symbol: `ContractCatalogStore` outbox methods
  excerpt: |
    enqueue_publication / pending_publications / claim_publication /
    complete_publication / fail_publication / setup / close
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py`
  lines: 85-119
  symbol: `contracts` DDL / `search_vector`
  excerpt: |
    card_json jsonb NOT NULL, title, summary, toc_digest, topics, ...
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english',
        coalesce(title,'')||' '||coalesce(summary,'')||' '||coalesce(toc_digest,'')||' '||coalesce(topics,''))) STORED
    CREATE INDEX ... contracts_search_idx ON {schema}.contracts USING GIN (search_vector)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py`
  lines: 294-316
  symbol: `PostgresContractCatalog.__init__`
  excerpt: |
    def __init__(self, dsn=None, *, pool=None, tenant_id: str, schema="contracts", principal=None, now=_utcnow):
        if dsn is None and pool is None: raise ValueError("... no default DSN fallback.")
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py`
  lines: 531-560
  symbol: `PostgresContractCatalog.upsert`
  excerpt: |
    async with conn.transaction():
        current = await conn.fetchrow("SELECT revision ... WHERE contract_id = $1 FOR UPDATE", ...)
        if expected_revision is not None and actual != expected_revision: raise CatalogConflictError(...)
        clash = ... WHERE contract_id <> $1 AND (source_uri = $2 OR (source_sha256 = $3 AND $3 <> ''))
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py`
  lines: 914-944
  symbol: `PostgresContractCatalog.search`
  excerpt: |
    SELECT c.*, ts_rank(c.search_vector, q.query) AS rank
    FROM {self.schema}.contracts c, plainto_tsquery('english', $1) AS q(query)
    WHERE c.active AND c.search_vector @@ q.query
    ORDER BY rank DESC, c.contract_id LIMIT $2
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/catalog_postgres.py`
  lines: 998-1060
  symbol: `PostgresContractCatalog.verification_queue`
  excerpt: |
    LEFT JOIN LATERAL jsonb_each(coalesce(c.card_json -> 'field_provenance', '{}'::jsonb)) AS fp ON true
    CASE WHEN missing_fields THEN 0 WHEN low_fields THEN 1 ELSE 2 END AS priority
    OR jsonb_array_length(coalesce(c.card_json -> 'stale_fields', '[]'::jsonb)) > 0

## Notes
- FTS is English-only (`'english'` config). Multilingual technicians or manuals would need a configurable regconfig.
- 40 `@abstractmethod`s. Party, answer, relation and delta-token methods are contract-only.
- `LOW_CONFIDENCE_THRESHOLD`, `MAX_SEARCH_TOP_K` and `MAX_QUEUE_LIMIT` are module constants in catalog_postgres (not read in detail).
