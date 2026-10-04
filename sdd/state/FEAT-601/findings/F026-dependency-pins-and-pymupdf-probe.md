---
id: F026
query_id: Q026
type: read
intent: Dependency pins + read-only library probe (pymupdf4llm.to_markdown kwargs, Page image APIs, rapidfuzz/bm25s)
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F026 — pymupdf4llm 0.0.27 / PyMuPDF 1.27.1 installed; every to_markdown kwarg the brainstorm names exists

## Summary
The venv has pymupdf4llm 0.0.27, PyMuPDF 1.27.1, rapidfuzz 3.11.0, bm25s 0.2.14, yt-dlp 2026.8.19, whisperx 3.8.5 and asyncdb 2.16.2. python-arango and openai-whisper are NOT installed. `pymupdf4llm.to_markdown` has all of `write_images, embed_images, image_path, image_format='png', image_size_limit=0.05, dpi=150, page_chunks, extract_words`, among others. `pymupdf.Page` has `get_image_bbox`, `get_image_info`, `get_image_rects` and `get_images`. rapidfuzz is declared only in core `[graphindex]` (added by FEAT-539) and in tools `[scraping]`. bm25s is declared only in core `[bookstore]`.

## Citations
- path: `packages/ai-parrot/pyproject.toml`
  lines: 273-283
  symbol: `[project.optional-dependencies].graphindex`
  excerpt: |
    # FEAT-539: deterministic fuzzy matching for contract parent resolution
    "rapidfuzz>=3.0",
- path: `packages/ai-parrot/pyproject.toml`
  lines: 338-345
  symbol: `bookstore` extra
  excerpt: |
    bookstore = [
        "bm25s>=0.2",
        "pymupdf>=1.27",
        "pymupdf4llm>=0.0.27",
- path: `packages/ai-parrot/pyproject.toml`
  lines: 431-433
  symbol: `agents` extra (starts L395)
  excerpt: |
    "pymupdf==1.27.1",
    "pymupdf4llm==0.0.27",
    "pdf4llm==0.0.27",
- path: `packages/ai-parrot/pyproject.toml`
  lines: 126, 228, 364-365
  symbol: asyncdb / arango
  excerpt: |
    "asyncdb>=2.16.2",
    "asyncdb[bigquery,mongodb,arangodb,influxdb,boto3,sqlalchemy]>=2.16.2",   # [db] extra
    # arango extra removed in FEAT-201; use ai-parrot-embeddings[arango] instead
- path: `packages/ai-parrot-loaders/pyproject.toml`
  lines: 37-43, 83-88
  symbol: `youtube`, `audio`, `documents` extras
  excerpt: |
    "yt-dlp>=2026.02.21"
    "whisperx==3.8.5",
    documents = [ ..., "pymupdf>=1.27", "pymupdf4llm>=0.0.27", ]
- path: `packages/ai-parrot-tools/pyproject.toml`
  lines: 73
  symbol: `scraping` extra
  excerpt: |
    scraping = [..., "playwright>=1.52", "rapidfuzz>=3.0"]
- path: `.venv/lib/python3.12/site-packages/pymupdf4llm/helpers/pymupdf_rag.py`
  lines: n/a (probe output)
  symbol: `pymupdf4llm.to_markdown`
  excerpt: |
    (doc, *, pages=None, hdr_info=None, write_images=False, embed_images=False, ignore_images=False,
     ignore_graphics=False, detect_bg_color=True, image_path='', image_format='png', image_size_limit=0.05,
     filename=None, force_text=True, page_chunks=False, page_separators=False, margins=0, dpi=150,
     page_width=612, page_height=None, table_strategy='lines_strict', graphics_limit=None, fontsize_limit=3,
     ignore_code=False, extract_words=False, show_progress=False, use_glyphs=False, ignore_alpha=False) -> str
- path: probe `dir(pymupdf.Page)`
  lines: n/a
  symbol: `pymupdf.Page` image members
  excerpt: |
    ['_insert_image','delete_image','get_image_bbox','get_image_info','get_image_rects','get_images',
     'get_svg_image','insert_image','replace_image']

## Notes
- The brainstorm's claim that every one of these kwargs exists on 0.0.27 is TRUE.
- The return annotation is `-> str`, but with `page_chunks=True` the function returns a list of page dicts at runtime.
- pymupdf4llm has no hard dependency declared in core deps. It comes only through the extras (`bookstore`, `agents`, loaders `documents`).
- rapidfuzz is not in the core base deps. A procedures feature that fuzzy-matches would need `[graphindex]`, or a new extra entry.
- python-arango is missing from the venv. Arango access goes through `asyncdb[arangodb]` or `ai-parrot-embeddings[arango]`.
