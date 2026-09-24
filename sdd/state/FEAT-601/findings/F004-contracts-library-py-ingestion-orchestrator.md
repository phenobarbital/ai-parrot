---
id: F004
query_id: Q004
type: read
intent: TreeIndexer protocol, ContractLibrary deps, add_contract/add_folder/verify_card/refresh_card, _to_markdown, _extract_pdf_pages, tree creation.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F004 — contracts/library.py ingestion orchestrator

## Summary
`ContractLibrary` hashes the file (sha256) and dedupes by URI and then by sha. It converts the file to markdown: PDF becomes `## Page N` sections via pymupdf `page.get_text()`, DOCX gets heading promotion, TXT/MD gets deterministic sections. It then builds a PageIndex tree in a per-tenant staging root: `create_tree` → `insert_markdown` → `get_tree` → `derive_toc`. After that it runs `draft_contract`, `assemble_card`, `merge_verified_fields` (on refresh), archives evidence, calls `catalog.upsert(card, version=...)` and promotes the staging root. `TreeIndexer` is a 4-method Protocol and `_default_indexer_factory` builds a real `PageIndexToolkit`. A manuals library can copy the whole flow and swap only `draft_*`/`assemble_*`. PDF text extraction ignores figures, so assembly diagrams would be lost.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 96-115
  symbol: `TreeIndexer`
  excerpt: |
    class TreeIndexer(Protocol):
        async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]: ...
        async def insert_markdown(self, tree_name, markdown, parent_node_id=None, doc_name=None) -> dict: ...
        async def get_tree(self, tree_name: str) -> dict[str, Any]: ...
        async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 205-220
  symbol: `pdf_markdown`
  excerpt: |
    chunks = [f"## Page {number}\n\n{text.strip()}" for number, text in enumerate(pages, start=1) if (text or "").strip()]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 481-512
  symbol: `ContractLibrary.__init__`
  excerpt: |
    def __init__(self, *, catalog: ContractCatalogStore, storage_root, evidence_root, adapter: Any = None,
                 indexer_factory: Optional[Callable[[Path, Any], TreeIndexer]] = None,
                 content_store_factory=None, owner_rules=(), max_obligation_sections=12,
                 max_candidates=8, relation_stage=None, relate_on_ingest=False, now=_utcnow, today=_today)
        self.staging = StagingArea(storage_root, tenant_id=catalog.tenant_id)
        self.evidence = EvidenceArchive(evidence_root, tenant_id=catalog.tenant_id)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 516-607
  symbol: `ContractLibrary.add_contract`
  excerpt: |
    async def add_contract(self, source: str | Path, *, source_uri=None, force: bool = False) -> IngestResult:
        sha256 = hashlib.sha256(payload).hexdigest()
        existing = await self.catalog.find_by_source_uri(uri)
        by_content = await self.catalog.find_by_sha(sha256)
        markdown, pages = await self._to_markdown(path, source_format)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 609-651
  symbol: `ContractLibrary.add_folder`
  excerpt: |
    async def add_folder(self, folder, *, recursive: bool = False, force: bool = False) -> IngestReport:
        pattern = "**/*" if recursive else "*"
        result = await self.add_contract(candidate, force=force)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 653-770
  symbol: `ContractLibrary.verify_card`
  excerpt: |
    async def verify_card(self, contract_id, fields: Optional[Mapping[str, Any]] = None, *,
                          user: str, expected_revision: Optional[int] = None) -> VerificationResult:
        # equal value = confirmation; different value = correction -> origin "manual"
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 787-816
  symbol: `ContractLibrary.refresh_card`
  excerpt: |
    async def refresh_card(self, contract_id, *, source=None) -> IngestResult:
        candidate = source or card.source_path or card.source_uri
        return await self.add_contract(path, source_uri=card.source_uri)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 910-947
  symbol: `ContractLibrary._to_markdown`
  excerpt: |
    async def _to_markdown(self, path, source_format) -> tuple[str, dict[int, int]]:
        if source_format == "pdf":
            pages = await self._extract_pdf_pages(path)
            hints = {index: number for index, number in enumerate((n for n, t in enumerate(pages, 1) if t.strip()), 1)}
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 949-970
  symbol: `ContractLibrary._extract_pdf_pages`
  excerpt: |
    import pymupdf  # fallback: import fitz as pymupdf
    with pymupdf.open(str(path)) as document:
        return [page.get_text() or "" for page in document]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 1000-1030
  symbol: `ContractLibrary._ingest` (tree creation)
  excerpt: |
    staging_root = await self.staging.begin(contract_id)
    indexer = self._indexer_factory(staging_root, self.adapter)
    await indexer.create_tree(contract_id, doc_name=path.name)
    await indexer.insert_markdown(contract_id, markdown, doc_name=path.name)
    tree = await indexer.get_tree(contract_id)
    toc, toc_digest = derive_toc(tree)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 1127-1139
  symbol: `ContractLibrary._page_map`
  excerpt: |
    match = _PAGE_TITLE_RE.match((entry.title or "").strip())  # r"^page\s+(\d+)$"
    elif entry.start_page: ... elif index in page_hints: pages[node_id] = page_hints[index]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 1222-1226
  symbol: `_default_indexer_factory`
  excerpt: |
    from ..pageindex.toolkit import PageIndexToolkit
    return PageIndexToolkit(adapter=adapter, storage_dir=storage_dir)

## Notes
- `derive_toc` is imported from `..bookstore.carding` (L29).
- `SUPPORTED_FORMATS` is at L80.
- Image-only PDFs are skipped rather than OCR'd (L577-582). Assembly manuals depend heavily on diagrams, so vision or figure extraction is a real gap, not a copy target.
- The PDF tree is one node per page (`## Page N`), not per procedure step. Step-level structure would need a manuals-specific sectioner.
