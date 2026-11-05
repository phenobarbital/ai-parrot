# Loader Metadata Standard

> **FEAT-125 — AI-Parrot Loaders Metadata Standardization**
>
> This document describes the canonical `Document.metadata` shape that every
> loader in AI-Parrot must produce. It is the foundation for contextual-retrieval
> embedding headers (upcoming feature) and ensures downstream consumers can
> rely on a consistent metadata structure.

---

## Canonical Shape

Every `Document.metadata` dict produced by a loader follows this structure:

```python
{
    # ── Core top-level fields ─────────────────────────────────────────
    "url":         str,   # Source URL or "file://<path>" for filesystem files
    "source":      str,   # Original path or URL (filename or URL string)
    "filename":    str,   # Human-readable filename or URL
    "type":        str,   # Document type / doctype (e.g. "pdf", "webpage")
    "source_type": str,   # Source kind (e.g. "file", "url", "video", "audio")
    "created_at":  str,   # ISO-formatted timestamp of when the doc was loaded
    "category":    str,   # Loader-level category (from AbstractLoader.category)

    # ── Canonical sub-dict (closed shape) ────────────────────────────
    "document_meta": {
        "source_type": str,   # Same as top-level source_type
        "category":    str,   # Same as top-level category
        "type":        str,   # Same as top-level type
        "language":    str,   # ISO 639-1 language code (e.g. "en", "es")
        "title":       str,   # Human-readable document title
    },

    # ── Loader-specific extras (zero or more) ────────────────────────
    # Any additional key-value pairs are added at the top level.
    # They are NEVER placed inside document_meta.
    # Examples: content_kind, author, topic_tags, start, chunk_id, etc.
}
```

---

## `document_meta` Contract

The `document_meta` sub-dict has exactly **5 canonical keys** and is
**closed-shape**: no loader may add extra keys to it.

| Key | Type | Description |
|-----|------|-------------|
| `source_type` | `str` | High-level source kind (`"file"`, `"url"`, `"video"`, `"audio"`) |
| `category` | `str` | Loader-level category (configurable on the loader instance) |
| `type` | `str` | Document type / doctype string (e.g. `"pdf"`, `"audio_transcript"`) |
| `language` | `str` | ISO 639-1 language code |
| `title` | `str` | Human-readable document title |

### Rule: extras live at the top level, never inside `document_meta`

```python
# CORRECT ✓
{
    "document_meta": {"source_type": "url", "category": "...", "type": "webpage",
                      "language": "en", "title": "My Page"},
    "author": "Jane Doe",          # ← top level
    "content_kind": "fragment",    # ← top level
    "topic_tags": ["AI", "ML"],    # ← top level
}

# WRONG ✗
{
    "document_meta": {"source_type": "url", ..., "author": "Jane Doe"},  # ← DO NOT add extras here
}
```

---

## `language` and `title` Defaults

Both `language` and `title` have automatic defaults:

| Field | Default | Override |
|-------|---------|---------|
| `language` | `loader.language` (default `"en"`) | Pass `language="fr"` to `create_metadata()` |
| `title` | Derived from `path` by `_derive_title()` | Pass `title="My Title"` to `create_metadata()` |

`_derive_title(path)` rules (in order):

1. **PurePath / Path** → `path.stem` with underscores/hyphens replaced by spaces, title-cased.
2. **URL string** → last non-empty decoded path segment, stripped of common file extensions.
3. **Fallback** → `str(path)`.

To override the loader-level default language, pass `language=` when constructing the loader:

```python
loader = PDFLoader(language="es")
# All create_metadata() calls default to language="es"
```

---

## Writing a New Loader

When implementing a new loader that extends `AbstractLoader`:

### 1. Call `create_metadata()` for every emitted `Document`

```python
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document

class MyLoader(AbstractLoader):
    async def _load(self, path, **kwargs) -> list[Document]:
        # ✓ Use create_metadata — do NOT build the metadata dict by hand
        metadata = self.create_metadata(
            path,
            doctype="my_doc_type",
            source_type="file",
            # Loader-specific extras → top-level kwargs
            section="intro",
            page_number=1,
        )
        return [Document(page_content="...", metadata=metadata)]
```

### 2. Pass loader-specific extras as `**kwargs`

Any field that is not one of the 5 canonical `document_meta` keys should be
passed as a keyword argument to `create_metadata()`. It will be placed at the
top level of the metadata dict automatically.

```python
metadata = self.create_metadata(
    url,
    doctype="webpage",
    source_type="url",
    content_kind="fragment",   # ← top-level kwarg
    author="Jane Doe",         # ← top-level kwarg
    crawl_depth=2,             # ← top-level kwarg
)
```

### 3. For content-kind variants, spread `{**base_meta, "content_kind": "..."}`

When a single page produces multiple Document variants (e.g. full-page, fragments,
video links), compute the base metadata once and spread it:

```python
base_meta = self.create_metadata(url, doctype="webpage", source_type="url", ...)

# Full-page document
docs.append(Document(
    page_content=md_text,
    metadata={**base_meta, "content_kind": "markdown_full"},
))

# Fragment documents
for chunk in fragments:
    docs.append(Document(
        page_content=chunk,
        metadata={**base_meta, "content_kind": "fragment"},
    ))
```

### 4. Do NOT build raw `metadata = {...}` dicts with a `document_meta` key

The `document_meta` sub-dict is managed exclusively by `create_metadata()` and
`_validate_metadata()`. Building it by hand breaks the closed-shape contract.

```python
# WRONG ✗
metadata = {
    "source": url,
    "document_meta": {"language": "en", "custom_field": "bad"},  # ← DO NOT DO THIS
}

# CORRECT ✓
metadata = self.create_metadata(url, doctype="...", source_type="...", custom_field="good")
```

---

## `create_metadata()` Signature Reference

```python
def create_metadata(
    self,
    path: Union[str, PurePath],
    doctype: str = "document",
    source_type: str = "source",
    doc_metadata: Optional[dict] = None,
    *,
    language: Optional[str] = None,
    title: Optional[str] = None,
    **kwargs
) -> dict:
    ...
```

| Parameter | Description |
|-----------|-------------|
| `path` | Filesystem path or URL of the source document. |
| `doctype` | Document type identifier (e.g. `"pdf"`, `"audio_transcript"`). Becomes `document_meta["type"]`. |
| `source_type` | High-level source kind (e.g. `"file"`, `"url"`, `"video"`). Becomes `document_meta["source_type"]`. |
| `doc_metadata` | Legacy dict. Canonical keys are folded into `document_meta`; non-canonical keys are hoisted to top level. |
| `language` | ISO language code. Defaults to `self.language`. |
| `title` | Human-readable title. Defaults to `_derive_title(path)`. |
| `**kwargs` | Loader-specific extras — all go to **top level**, never inside `document_meta`. |

---

## Contextual Retrieval Foundation

This metadata standard is the foundation for the upcoming **contextual-retrieval
embedding headers** feature. Each document chunk will be prefixed with a compact
context header derived from `document_meta` fields before embedding:

```
[Source: My Report.pdf | Type: pdf | Language: en | Category: reports]
<chunk content>
```

Keeping `document_meta` closed-shape (exactly 5 keys, no extras) ensures the
header generator can rely on a stable, predictable structure across all loaders.

---

## Validation

`AbstractLoader._validate_metadata(metadata)` provides a non-fatal validator that
auto-fills any missing canonical fields with defaults and logs a WARNING. It
**never raises**. Use it to validate metadata from external or legacy sources:

```python
# Validate/auto-fill a metadata dict from an external source
safe_meta = loader._validate_metadata(raw_metadata)
```
