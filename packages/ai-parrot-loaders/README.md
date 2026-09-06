# AI-Parrot Loaders

**ai-parrot-loaders** provides document loaders for [AI-Parrot](https://pypi.org/project/ai-parrot/) RAG (Retrieval-Augmented Generation) pipelines. Each loader transforms a specific document format into text chunks that can be embedded and searched.

## Installation

```bash
pip install ai-parrot-loaders
```

Install only the extras you need:

```bash
pip install ai-parrot-loaders[pdf]
pip install ai-parrot-loaders[youtube]
pip install ai-parrot-loaders[audio]
pip install ai-parrot-loaders[web]

# Everything
pip install ai-parrot-loaders[all]
```

## Available Extras

| Extra | Description |
|-------|-------------|
| `pdf` | PDF loading with OCR support (PaddleOCR) |
| `youtube` | YouTube transcript and video download |
| `audio` | Audio transcription (WhisperX, pyannote) |
| `web` | HTML/web page loading |
| `ebook` | Structured EPUB and MOBI e-book loading |
| `video` | Video processing (MoviePy, FFmpeg) |

## Supported Formats

| Loader | Format | Description |
|--------|--------|-------------|
| `TextLoader` | `.txt` | Plain text files |
| `CSVLoader` | `.csv` | CSV files |
| `ExcelLoader` | `.xlsx`, `.xls` | Excel spreadsheets |
| `MSWordLoader` | `.docx` | Microsoft Word documents |
| `HTMLLoader` | `.html` | HTML files |
| `MarkdownLoader` | `.md` | Markdown files |
| `PDFLoader` | `.pdf` | PDF documents |
| `PDFMarkdownLoader` | `.pdf` | PDF to Markdown conversion |
| `PDFTablesLoader` | `.pdf` | PDF table extraction |
| `PowerPointLoader` | `.pptx` | PowerPoint presentations |
| `EpubLoader` | `.epub` | EPUB e-books |
| `MobiLoader` | `.mobi` | MOBI/KF8 e-books via KindleUnpack |
| `WebLoader` | URL | Web pages |
| `YoutubeLoader` | URL | YouTube video transcripts |
| `VimeoLoader` | URL | Vimeo video transcripts |
| `AudioLoader` | `.mp3`, `.wav`, etc. | Audio transcription |
| `VideoLoader` | URL | Video download + transcription |
| `VideoLocalLoader` | `.mp4`, etc. | Local video transcription |
| `DocumentConverterLoader` | multiple | Auto-detect format and convert |

## Quick Start

### Structured EPUB and MOBI books

Install the optional ebook dependencies:

```bash
uv pip install 'ai-parrot-loaders[ebook]'
```

This includes `ebooklib`, `beautifulsoup4`, `markdownify`, and `mobi` (KindleUnpack).

```python
from parrot_loaders.epubloader import EpubLoader
from parrot_loaders.mobiloader import MobiLoader
from parrot.loaders.ebook import ebook_sections

documents = await EpubLoader("book.epub").load()
sections = ebook_sections(documents)
await pageindex.insert_ebook("my-book", [section.model_dump() for section in sections])

# Same output contract and loader options for MOBI:
mobi_documents = await MobiLoader("book.mobi").load()
```

Create the PageIndex tree before inserting. Bookstore, GraphIndex and wiki
ingestion select this structural path automatically for EPUB and MOBI documents.

```bash
bookstore add book.mobi --no-llm
```

MOBI support handles unencrypted MOBI7 HTML/NCX and KF8 EPUB output. MOBI7 uses
NCX navigation when present, then explicit nested HTML navigation, then HTML
heading structure. If the source has no hierarchy, the loader cannot recover
one that was never encoded. Invalid/encrypted books and PDF-only Print Replica
output raise `MobiLoaderError`. Decoding runs off the event loop with serialized
backend calls, and temporary files are removed on both success and failure.
Section provenance always refers to the original `.mobi` source.

Each document contains one section's body and an `ebook_section` metadata record:
`section_id`, `parent_id`, `title`, `href` (including fragments), `depth`,
`toc_order`, `reading_order`, `source_uri`, `target_found`, and `origin`.
`per_chapter=False` returns one readable book document with complete records in
`ebook_sections`. `include_toc_document=True` adds a nested navigation document.

Navigation parents and short TOC sections are retained even when they have no
body. Missing targets remain in the index with `target_found=False`. When a
document has no TOC entries, HTML headings supply its fallback structure.
Reading order follows the spine, while TOC order is recorded separately.
Repeated targets retain distinct navigation identities; their body is stored
once, on the last entry for that target, rather than duplicated.

**Compatibility:** `load()` defaults to `split_documents=False` for ebooks.
Explicit chunking remains available for vector-store callers. Section bodies no
longer carry synthetic `Section:`/`Title:` prefixes or duplicate chapter headings;
titles and relationships are metadata. Use `ebook_markdown(sections)` for a
readable Markdown export. The structural PageIndex path preserves all navigation
levels and does not merge short nodes or infer parents from Markdown headings.

### Other documents

```python
from parrot_loaders.factory import get_loader_class

# Auto-detect loader by file extension
LoaderClass = get_loader_class("report.pdf")
loader = LoaderClass(source="report.pdf")
documents = await loader.load()

for doc in documents:
    print(doc.page_content[:200])
```

Or use a specific loader directly:

```python
from parrot_loaders.youtube import YoutubeLoader

loader = YoutubeLoader(source="https://www.youtube.com/watch?v=...")
documents = await loader.load()
```

## Requirements

- Python >= 3.11
- [ai-parrot](https://pypi.org/project/ai-parrot/) >= 0.23.18

## License

MIT
