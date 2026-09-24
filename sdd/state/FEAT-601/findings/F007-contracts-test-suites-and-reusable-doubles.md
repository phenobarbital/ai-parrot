---
id: F007
query_id: Q007
type: tree
intent: List contracts tests (core + tools) and note reusable fixtures/fakes.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — contracts test suites and reusable doubles

## Summary
Core suite `packages/ai-parrot/tests/knowledge/contracts` has 22 files. Tools suite `packages/ai-parrot-tools/tests/contracts` has 13, and it tests `parrot_tools/contracts/{agent,cli,flow,jobs,retrieval,service,toolkit,verifier}.py`. The key doubles are defined inside test modules, not in conftest. `InMemoryContractCatalog` (test_catalog_contract.py L66) is imported by 6 other core test modules. `FakeGraphStore` (test_graph_loader.py L41) reproduces two Arango details: `create_edges` never updates existing edges, and soft-deleted nodes are hidden. There are also `FakeAdapter`, which scripts `ask_structured`, and `FakeIndexer`, which builds a real `NodeContentStore`-backed tree from markdown headings. Conftest only provides corpus markdown fixtures, docx/pdf builders, and live `pg_pool`/`temp_schema`/`arango_params` fixtures.

## Citations
- path: `packages/ai-parrot/tests/knowledge/contracts/conftest.py`
  lines: 27-33
  symbol: `FROZEN_NOW` / `TODAY` / arango env
  excerpt: |
    FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
    TODAY = date(2026, 9, 9)
    ARANGO_USER = os.environ.get("CONTRACTS_ARANGO_USER", "root")
- path: `packages/ai-parrot/tests/knowledge/contracts/conftest.py`
  lines: 153-254
  symbol: `corpus` / `docx_document` / `text_pdf` / `image_only_pdf` / `pg_pool` / `temp_schema` / `arango_params`
  excerpt: |
    @pytest.fixture() def corpus(tmp_path) -> dict[str, Path]
    @pytest.fixture() def text_pdf(tmp_path) -> Path
    @pytest.fixture() async def pg_pool() -> AsyncIterator[Any]
- path: `packages/ai-parrot/tests/knowledge/contracts/test_catalog_contract.py`
  lines: 66
  symbol: `InMemoryContractCatalog`
  excerpt: |
    class InMemoryContractCatalog(ContractCatalogStore):
- path: `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py`
  lines: 27
  symbol: import of `InMemoryContractCatalog`
  excerpt: |
    from .test_catalog_contract import InMemoryContractCatalog
- path: `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py`
  lines: 41-60
  symbol: `FakeGraphStore`
  excerpt: |
    class FakeGraphStore:
        """In-memory ``OntologyGraphStore`` ... ``create_edges`` inserts by endpoints and **never**
        updates properties, and ``get_all_nodes`` hides soft-deleted vertices."""
        self.fail_on: set[str] = set(); self.swallow_writes: set[str] = set()
- path: `packages/ai-parrot/tests/knowledge/contracts/test_graph_loader.py`
  lines: 126
  symbol: `FakeTenantManager`
  excerpt: |
    class FakeTenantManager:
- path: `packages/ai-parrot/tests/knowledge/contracts/test_carding.py`
  lines: 95-110
  symbol: `FakeAdapter`
  excerpt: |
    class FakeAdapter:
        """Counts structured calls and replays scripted structured outputs."""
        def __init__(self, header=None, clauses=None): self.calls; self.prompts; self.fail_header; self.fail_nodes
        async def ask_structured(self, prompt, output_type, ...)
- path: `packages/ai-parrot/tests/knowledge/contracts/test_ingestion.py`
  lines: 46-60
  symbol: `FakeIndexer`
  excerpt: |
    class FakeIndexer:
        """A minimal PageIndex tree builder over a real content store."""
        from parrot.knowledge.pageindex.content_store import NodeContentStore
        from parrot.knowledge.pageindex.store import JSONTreeStore
- path: `packages/ai-parrot-tools/tests/contracts/test_retrieval.py`
  lines: 59, 645, 652
  symbol: `FakeCatalog` / `FakeOntology` / `FakeGraphStore`
  excerpt: |
    class FakeCatalog(ContractCatalogStore):
    class FakeOntology:
    class FakeGraphStore:
- path: `packages/ai-parrot-tools/tests/contracts/conftest.py`
  lines: 26-41
  symbol: `pg_pool` / `live_catalog`
  excerpt: |
    @pytest.fixture() async def pg_pool() -> AsyncIterator[Any]:
    @pytest.fixture() async def live_catalog(pg_pool) -> AsyncIterator[Any]:

## Notes
- Other doubles:
  - `test_temporal.py`: `FakePersistence` (L72) and `make_ctx` (L61)
  - `test_ontology_domain.py`: `_RecordingGraphStore` (L290)
  - `test_relations.py`: `FakeAdapter` (L62)
  - `test_docx_helper.py`: `_FakeLoader` (L27)
  - tools tests: `FakeReActAgent` (test_agent L33), `FakeLibrary` (test_toolkit L33), `FakeIndexer`/`FakeDeltaTool` (test_ingest_delta L30/42)
- Recommendation: move `FakeGraphStore`, `FakeAdapter` and `FakeIndexer` into a shared test-support module or conftest before building the manuals suite, so it doesn't import from `tests.knowledge.contracts.test_*`. `InMemoryContractCatalog` is too contract-specific (40 methods) to reuse; manuals need their own in-memory catalog.
- `test_dependency_boundary.py` probably enforces import boundaries, and a manuals package would need the same guard. I did not read it.
