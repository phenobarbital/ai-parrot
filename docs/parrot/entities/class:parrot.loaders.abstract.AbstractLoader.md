---
type: Wiki Entity
title: AbstractLoader
id: class:parrot.loaders.abstract.AbstractLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for all loaders.
---

# AbstractLoader

Defined in [`parrot.loaders.abstract`](../summaries/mod:parrot.loaders.abstract.md).

```python
class AbstractLoader(ABC)
```

Base class for all loaders.
Loaders are responsible for loading data from various sources.

## Methods

- `def get_default_llm(self, model: str=None, model_kwargs: dict=None, use_groq: bool=False, use_openai: bool=False) -> Any` — Return a AI Client instance.
- `def clear_cuda(self)`
- `def supported_extensions(self)` — Get the supported file extensions.
- `def is_valid_path(self, path: Union[str, Path]) -> bool` — Check if a path is valid.
- `async def from_path(self, path: Union[str, Path], recursive: bool=False, **kwargs) -> List[asyncio.Task]` — Load data from a path.
- `async def from_url(self, url: Union[str, List[str]], **kwargs) -> List[asyncio.Task]` — Load data from a URL.
- `async def from_dataframe(self, source: pd.DataFrame, **kwargs) -> List[asyncio.Task]` — Load data from a pandas DataFrame.
- `def chunkify(self, lst: List[T], n: int=50) -> Generator[List[T], None, None]` — Split a List of objects into chunks of size n.
- `async def load(self, source: Optional[Any]=None, split_documents: bool=True, late_chunking: bool=False, vector_store=None, store_full_document: bool=True, auto_detect_content_type: bool=None, **kwargs) -> List[Document]` — Load data from a source and return it as a list of Documents.
- `def create_metadata(self, path: Union[str, PurePath], doctype: str='document', source_type: str='source', doc_metadata: Optional[dict]=None, *, language: Optional[str]=None, title: Optional[str]=None, **kwargs) -> dict` — Build a canonical ``Document.metadata`` dict.
- `def create_document(self, content: Any, path: Union[str, PurePath], metadata: Optional[dict]=None, **kwargs) -> Document` — Create a Parrot Document from content.
- `async def summary_from_text(self, text: str, max_length: int=500, min_length: int=50) -> str` — Get a summary of a text.
- `def get_summarization_model(self, model_name: str='facebook/bart-large-cnn')`
- `def translate_text(self, text: str, source_lang: str=None, target_lang: str='es') -> str` — Translate text from source language to target language.
- `def get_translation_model(self, source_lang: str='en', target_lang: str='es', model_name: str=None)` — Get or create a translation model.
- `def create_translated_document(self, content: str, metadata: dict, source_lang: str='en', target_lang: str='es') -> Document` — Create a document with translated content.
- `def saving_file(self, filename: PurePath, data: Any)` — Save data to a file.
- `async def chunk_documents(self, documents: List[Document], use_late_chunking: bool=False, vector_store=None, store_full_document: bool=True, auto_detect_content_type: bool=None) -> List[Document]` — Chunk documents using the configured text splitter or late chunking strategy.
