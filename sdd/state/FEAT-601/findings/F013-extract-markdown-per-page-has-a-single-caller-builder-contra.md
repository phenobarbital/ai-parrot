---
id: F013
query_id: Q013
type: read
intent: pdf_to_markdown.py and its caller chain (PageIndexToolkit.import_pdf, ContractLibrary._to_markdown) — seam for images_dir=
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F013 — extract_markdown_per_page has a single caller (builder); ContractLibrary does not use it

## Summary
`extract_markdown_per_page(pdf_path) -> list[tuple[int,str]]` (L35-94) opens the PDF only to count pages, then calls `pymupdf4llm.to_markdown(path, page_chunks=True)` with no other kwargs. It checks that the chunk count equals the page count and returns one dense, 1-based `(page, text)` entry per page. The only code caller is `builder._extract_node_markdown` (L1622-1639), which `build_page_index` calls at L1596. `PageIndexToolkit.import_pdf` (toolkit L803+) calls `build_page_index`, pops `_node_markdown` and saves the sidecars. `ContractLibrary._to_markdown` does **not** use this function. It calls `_extract_pdf_pages` (raw `pymupdf` `page.get_text()`) and then `library.pdf_markdown(pages)`, which renders `## Page N` sections.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py`
  lines: 35-53
  symbol: `extract_markdown_per_page`
  excerpt: |
    def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]:
        """Extract per-physical-page markdown from a PDF.
        Returns: ``[(physical_page_1based, markdown_text), ...]`` ...
        Raises: FileNotFoundError, ImportError, ValueError (page-count mismatch)"""
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py`
  lines: 70-94
  symbol: `extract_markdown_per_page (body)`
  excerpt: |
    # NB: NEVER pass ``pages=`` here — restricting the page set would
    # decouple the returned index from ``get_page_tokens``' index space.
    chunks = pymupdf4llm.to_markdown(path_str, page_chunks=True)
    if len(chunks) != expected_pages: raise ValueError(...)
    for i, chunk in enumerate(chunks):
        text = chunk.get("text") or "" ...
        pages.append((i + 1, text))
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py`
  lines: 97-137
  symbol: `build_node_markdown_map`
  excerpt: |
    def build_node_markdown_map(structure: object, pages: list[tuple[int, str]]) -> dict[str, str]:
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py`
  lines: 1622-1639
  symbol: `_extract_node_markdown`
  excerpt: |
    def _extract_node_markdown(doc: str | BytesIO, structure: Any) -> dict[str, str]:
        if not isinstance(doc, str):
            return {}
        try:
            pages = extract_markdown_per_page(doc)
        except (FileNotFoundError, ImportError, ValueError) as exc:
            logger.warning(...); return {}
        return build_node_markdown_map(structure, pages)
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py`
  lines: 1545-1551
  symbol: `build_page_index`
  excerpt: |
    async def build_page_index(doc: str | BytesIO, adapter: PageIndexLLMAdapter,
        options: dict | config | None = None,
        light_adapter: Optional[PageIndexLLMAdapter] = None,
        llm_concurrency: int = DEFAULT_LLM_CONCURRENCY) -> dict:
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/builder.py`
  lines: 1596
  symbol: `build_page_index (call site)`
  excerpt: |
    node_markdown = _extract_node_markdown(doc, structure)
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py`
  lines: 803-845
  symbol: `PageIndexToolkit.import_pdf`
  excerpt: |
    async def import_pdf(self, tree_name: str, pdf_path: str, parent_node_id=None,
                         with_summaries: bool = True, with_doc_description: bool = False) -> dict[str, Any]:
        subtree = await build_page_index(doc=pdf_path, adapter=self._adapter, options={...},
                                         light_adapter=self._light_adapter)
        node_markdown = dict(subtree.pop("_node_markdown", {}) or {})
        self._save_node_markdown(tree_name, original_id_to_node, node_markdown)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 910-942
  symbol: `ContractLibrary._to_markdown`
  excerpt: |
    async def _to_markdown(self, path: Path, source_format: SourceFormat) -> tuple[str, dict[int, int]]:
        if source_format == "pdf":
            pages = await self._extract_pdf_pages(path)
            markdown = pdf_markdown(pages)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 949-970
  symbol: `ContractLibrary._extract_pdf_pages`
  excerpt: |
    with pymupdf.open(str(path)) as document:
        return [page.get_text() or "" for page in document]
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 205-221
  symbol: `pdf_markdown`
  excerpt: |
    def pdf_markdown(pages: Sequence[str]) -> str:
        chunks = [f"## Page {number}\n\n{text.strip()}" for number, text in enumerate(pages, start=1) if (text or "").strip()]

## Notes
- The brainstorm claim that `ContractLibrary._to_markdown` is in the `extract_markdown_per_page` caller chain is **wrong**. The contracts PDF path never uses pymupdf4llm.
- Proposed seam: `extract_markdown_per_page(pdf_path, *, images_dir: Path | None = None)` can forward `write_images=True, image_path=images_dir` (plus optional `image_format`/`dpi`) to `pymupdf4llm.to_markdown`. It must keep the "never pass `pages=`" rule. When `images_dir` is None the call is unchanged, so existing callers keep working.
- To get images from `import_pdf`, the parameter has to be threaded through `build_page_index`, then `_extract_node_markdown`, then `extract_markdown_per_page`. `_extract_node_markdown` returns `{}` for BytesIO input, so images only work for path inputs.
- The return type `list[tuple[int,str]]` has no room for per-page image metadata. Either add a new sibling function or return the images through a separate structure, so the `get_page_tokens` alignment contract stays intact.
- `pymupdf4llm` with `page_chunks=True` also returns `chunk["images"]`/`chunk["metadata"]`, which the current code throws away. This is from library knowledge and was not verified in the repo.

