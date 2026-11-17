---
title: "Document Loaders for RAG"
summary: "How AbstractLoader turns files, URLs and DataFrames into chunked Documents, and which concrete loaders ship in ai parrot loaders."
---

# Document Loaders for RAG

## Purpose

Loaders convert raw sources (PDF, Word, HTML, spreadsheets, web pages, audio, video, images, ebooks, DataFrames) into
`Document` objects (`parrot.stores.models.Document`) that can be embedded and written to a vector store. Use a loader
whenever you ingest content for retrieval augmented generation.

The code is split across two distributions:

- **Core** (`packages/ai-parrot/src/parrot/loaders/`) holds the base class `AbstractLoader`, the text splitters and the
  import machinery. Nothing in core is a concrete file format loader.
- **`ai-parrot-loaders`** (`packages/ai-parrot-loaders/src/parrot_loaders/`) is a top level package `parrot_loaders`
  with every concrete loader (`PDFLoader`, `HTMLLoader`, `MSWordLoader`, ...), the `LOADER_REGISTRY` dict and the
  extension factory.

`parrot.loaders` resolves names lazily: `from parrot.loaders import PDFLoader` and
`from parrot.loaders.pdf import PDFLoader` both work, because a `sys.meta_path` redirector forwards
`parrot.loaders.<x>` to `parrot_loaders.<x>` (then `plugins.loaders.<x>`) when no core submodule has that name. Prefer
the explicit `parrot_loaders.<x>` in new code.

## Public API

- [`parrot.loaders`](ref:parrot.loaders) — package exporting `AbstractLoader` and `Document`; any other attribute is
  resolved lazily from `parrot_loaders`, `plugins.loaders`, then `LOADER_REGISTRY`.
- [`parrot.loaders.abstract`](ref:parrot.loaders.abstract) — `AbstractLoader`, the base class (an `ABC`).
- [`parrot.loaders.splitters`](ref:parrot.loaders.splitters) — `BaseTextSplitter`, `MarkdownTextSplitter`,
  `TokenTextSplitter`, `SemanticTextSplitter`.
- [`parrot_loaders`](ref:parrot_loaders) — `LOADER_REGISTRY: dict[str, str]` mapping class names to dotted paths.
- [`parrot_loaders.factory`](ref:parrot_loaders.factory) — `LOADER_MAPPING` (extension to `(module, class)`) and
  `get_loader_class(extension)`.
- [`parrot_loaders.pdf`](ref:parrot_loaders.pdf) — `PDFLoader`, a representative concrete loader.

### The contract

`AbstractLoader` has one abstract method, which subclasses implement:

```python
@abstractmethod
async def _load(self, source: str | PurePath, **kwargs) -> list[Document]: ...
```

Callers use the public coroutine:

```python
async def load(
    self,
    source: Any | None = None,
    split_documents: bool = True,
    late_chunking: bool = False,
    vector_store=None,
    store_full_document: bool = True,
    auto_detect_content_type: bool | None = None,
    **kwargs,
) -> list[Document]
```

`load()` dispatches on the source type: an `http://` or `https://` string goes to `from_url`; a path or directory goes
to `from_path` (honouring `recursive`); a list is treated as URLs when every item is a URL and as paths otherwise; a
`pandas.DataFrame` goes to `from_dataframe`. With `source=None` it falls back to `self.path` and raises `ValueError`
if that is also unset. Each of `from_path`, `from_url` and `from_dataframe` returns a list of `asyncio.Task`; `load()`
awaits them through `_load_tasks()`, which bounds concurrency with a semaphore, logs failed tasks without aborting the
batch, and runs `_validate_metadata()` on every result before chunking.

Helpers available to subclasses: `create_document(content, path, metadata=None, **kwargs)`,
`create_metadata(path, doctype="document", source_type="source", doc_metadata=None, *, language=None, title=None, **kwargs)`,
`is_valid_path(path)`, `supported_extensions()`, `chunkify(lst, n=50)` and `chunk_documents(...)`.

### Loader catalogue

Verified in `LOADER_REGISTRY` and `LOADER_MAPPING` of `parrot_loaders`:

| Family | Classes (module) |
|---|---|
| Text and office | `TextLoader` (`txt`), `CSVLoader` (`csv`), `ExcelLoader` (`excel`), `MSWordLoader` (`docx`), `PowerPointLoader` (`ppt`), `HTMLLoader` (`html`), `MarkdownLoader` (`markdown`), `QAFileLoader` (`qa`), `DocumentConverterLoader` (`doc_converter`) |
| PDF | `PDFLoader` (`pdf`), `PDFMarkdownLoader` (`pdfmark`), `PDFTablesLoader` (`pdftables`), base `BasePDF` (`basepdf`) |
| Ebooks | `EpubLoader` (`epubloader`), `MobiLoader` (`mobiloader`) |
| Web | `WebLoader` (`web`), `WebScrapingLoader` (`webscraping`) |
| Audio, video, images | `AudioLoader`, `VideoLoader`, `VideoLocalLoader`, `VideoUnderstandingLoader`, `BaseVideoLoader`, `ImageLoader`, `ImageUnderstandingLoader`, `YoutubeLoader`, `VimeoLoader` |
| Database | `DatabaseLoader` (`database`) |

`LOADER_MAPPING` selects a class by extension, for example `.pdf` to `PDFLoader`, `.docx` to `MSWordLoader`,
`.xlsx`/`.xls`/`.xlsm` to `ExcelLoader`, `.pptx` to `PowerPointLoader`, `.csv` to `CSVLoader`, `.md`/`.json`/`.xml` to
`MarkdownLoader`, `.mp3`/`.wav` to `AudioLoader`, common video extensions to `VideoUnderstandingLoader` and common image
extensions to `ImageUnderstandingLoader`.

## Configuration & Parameters

`AbstractLoader.__init__(self, source=None, *, tokenizer=None, text_splitter=None, source_type="file", language="en", **kwargs)`.
Values read from `**kwargs`, with their defaults:

| Key | Default | Meaning |
|---|---|---|
| `chunk_size` | `2048` | Target chunk size handed to the splitter (also the batch size used by `_load_tasks`) |
| `chunk_overlap` | `200` | Overlap between chunks |
| `min_chunk_size` | `30` | Minimum chunk size for `SemanticTextSplitter` |
| `semaphore` | `10` | Maximum concurrent loads |
| `extensions` | class attribute (`[".*"]` on the base) | File suffixes accepted by `from_path` |
| `skip_directories` | `[]` | Directory names to ignore |
| `recursive` | `False` | Recurse into subdirectories |
| `category` | `"document"` | Written to metadata `category` |
| `doctype` | `"text"` | Default document type (concrete loaders override it, `PDFLoader` sets `"pdf"`) |
| `encoding` | `"utf-8"` | Text encoding |
| `use_markdown_splitter` | `True` | If `False`, use `TokenTextSplitter` instead of the semantic default |
| `use_huggingface_splitter` | `False` | Build a `TokenTextSplitter` from a HuggingFace tokenizer (`model_name`) |
| `auto_detect_content_type` | `True` | Pick a splitter per document (markdown, code, html or text) |
| `use_llm`, `llm_model`, `model_kwargs` | `False`, `None`, `{}` | Optional LLM support for subclasses |

Subclasses add their own options; `PDFLoader` for instance accepts `as_markdown`, `use_chapters` and `use_pages`.

### Chunking

When `split_documents=True` (the default), `load()` calls `chunk_documents()`. Unless you pass `text_splitter`, the
default splitter is `SemanticTextSplitter(chunk_size, chunk_overlap, min_chunk_size, model_name)`. Documents detected as
code (by extension such as `.py` or `.js`) are split with a `TokenTextSplitter` capped at 2048. Documents whose
`metadata["content_kind"]` marks an atomic unit (for example `fragment`, `faq`, `table`, `video_transcript` or the
`jsonld-*` kinds) pass through unsplit with `splitter_type="passthrough"`. Every chunk carries `chunk_id`,
`token_count`, `start_position`, `end_position`, `content_type`, `splitter_type`, `is_chunk` and `parent_document_id`
in its metadata. With `late_chunking=True` a `vector_store` is mandatory and chunking is delegated to the late
chunking path; see [Parent Child Retrieval](parent-child-retrieval.md).

### Metadata

Every `Document.metadata` follows the canonical shape: top level `url`, `source`, `filename`, `type`, `source_type`,
`created_at`, `category`, plus a closed `document_meta` sub dict with exactly `source_type`, `category`, `type`,
`language` and `title`. Extras always go at the top level. The full standard and the rules for writing a new loader
are in [Loader Metadata Standard](loaders-metadata.md).

## Usage Examples

Load and chunk a directory of PDFs:

```python
import asyncio

from parrot_loaders.pdf import PDFLoader


async def main() -> None:
    loader = PDFLoader(
        "./reports",
        recursive=True,
        chunk_size=1024,
        chunk_overlap=100,
        category="reports",
        language="en",
    )
    docs = await loader.load()
    for doc in docs[:3]:
        print(doc.metadata["filename"], doc.metadata["chunk_id"], len(doc.page_content))


asyncio.run(main())
```

Pick a loader from a file extension with the factory:

```python
import asyncio

from parrot_loaders.factory import get_loader_class


async def main() -> None:
    loader_cls = get_loader_class(".docx")      # MSWordLoader
    loader = loader_cls()
    docs = await loader.load("./handbook.docx", split_documents=False)
    print(len(docs))


asyncio.run(main())
```

Write a custom loader:

```python
from pathlib import Path

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document


class NotesLoader(AbstractLoader):
    """Load plain `.notes` files."""

    extensions = [".notes"]

    async def _load(self, path: Path, **kwargs) -> list[Document]:
        text = Path(path).read_text(encoding=self.encoding)
        return [self.create_document(text, path, **kwargs)]
```

## Gotchas

- **Entry point is `_load`, not `load`.** Subclasses implement the abstract async `_load()`; `load()` is the
  orchestrator and should not be overridden for a new format.
- **Unknown extensions fall back to `MarkdownLoader`.** `get_loader_class` returns it for any extension missing from
  `LOADER_MAPPING`, and also when a loader module fails to import (it prints the error). Only `.epub` and `.mobi`
  raise an `ImportError` that points at `ai-parrot-loaders[ebook]`.
- **Optional extras.** `ai-parrot-loaders` declares extras such as `youtube`, `audio`, `pdf`, `images`, `web`, `ebook`,
  `video` and `all`; a loader whose dependency is missing raises an `ImportError` naming it when imported through
  `parrot.loaders`.
- **Missing loader name raises `ImportError`**, not `AttributeError`, from `parrot.loaders.__getattr__` (private names
  starting with an underscore raise `AttributeError`).
- **Extension filter.** `is_valid_path` rejects empty files, dotfiles and suffixes not in `extensions`, so a directory
  load silently skips them. `PDFLoader.extensions` is a set, the base default is a list.
- **`async with` swallows exceptions.** `AbstractLoader.__aexit__` returns `True`, so errors raised inside the block are
  suppressed; it also calls optional `open()`/`close()` methods only if the subclass defines them.
- **Failed files are dropped.** `_load_tasks` logs per task errors and continues, so a partially successful `load()`
  returns fewer documents without raising.
- **Do not hand build `document_meta`.** Use `create_metadata()` or `create_document()`; see the metadata page.
- **Late chunking needs a store.** `late_chunking=True` without `vector_store` raises `ValueError`.

## Related

- [Loader Metadata Standard](loaders-metadata.md) — canonical `Document.metadata` shape and `create_metadata()`.
- [Parent Child Retrieval](parent-child-retrieval.md) — the late chunking path that `load(late_chunking=True)` feeds.
- [Contextual Embedding](contextual-embedding.md) — embedding headers built from the loader metadata.
