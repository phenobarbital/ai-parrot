---
id: F007
query: Q008
type: glob+read
target: packages/ai-parrot-loaders/
---

# F007 — ai-parrot-loaders Package Verification

**Status**: Confirmed with interface details

## Location
`packages/ai-parrot-loaders/` — import as `parrot_loaders`

## Base class
`AbstractLoader` at `packages/ai-parrot/src/parrot/loaders/abstract.py`
- Abstract method: `async def _load(source, **kwargs) -> List[Document]`
- Public entry: `async def load(source, split_documents=True, ...) -> List[Document]`
- Dispatches to `from_path()`, `from_url()`, or `from_dataframe()`

## Output format
`List[Document]` from `parrot.stores.models.Document`
- `page_content: str` — normalized text
- `metadata: dict` — canonical keys: url, source, filename, type, source_type, created_at, category, document_meta
- `document_meta` sub-dict: source_type, category, type, language, title

## Available loaders (24+)
Text/Doc: TextLoader, CSVLoader, ExcelLoader, MSWordLoader, HTMLLoader, MarkdownLoader,
PDFLoader, QAFileLoader, EpubLoader, PowerPointLoader, DocumentConverterLoader
PDF: BasePDF, PDFMarkdownLoader, PDFTablesLoader
Web: WebLoader, WebScrapingLoader
Video: BaseVideoLoader, VideoLoader, VideoLocalLoader, VideoUnderstandingLoader
Audio: AudioLoader
Image: ImageLoader, ImageUnderstandingLoader
YouTube: YoutubeLoader, VimeoLoader
DB: DatabaseLoader

## Built-in chunking
SemanticTextSplitter (default), MarkdownTextSplitter, TokenTextSplitter
Also supports late chunking (2/3-level).

## Open question
No `is_hierarchical()` method. Hierarchical detection must be done by the
GraphIndex extractor based on loader type or content inspection.
