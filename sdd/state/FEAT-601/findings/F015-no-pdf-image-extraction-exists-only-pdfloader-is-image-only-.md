---
id: F015
query_id: Q015
type: grep
intent: Absence proof — any PDF image extraction (write_images|extract_image(|Pixmap|get_image_bbox|image_path=|get_images() in packages/*/src
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F015 — No PDF image extraction exists; only PDFLoader.is_image_only touches get_images

## Summary
Running `grep -rnE "write_images|extract_image\(|Pixmap|get_image_bbox|image_path=|get_images\("` over `packages/*/src/**/*.py` returns exactly 2 hits. `parrot_loaders/pdf.py:60` is `page.get_images(full=True)` inside `PDFLoader.is_image_only`, which only decides whether a page has no text and should be skipped or OCR'd. `telegram/wrapper.py:3084` is an `image_path=` kwarg on `agent.ask_with_image` for a user-uploaded image and has nothing to do with PDFs. A second grep for `get_pixmap|extract_image|write_images|image_path` found nothing more PDF-related; the only other hits are image *generation* paths in `ai-parrot-client-google/.../generation.py`. This confirms the brainstorm: nothing in the monorepo extracts or saves images from PDFs today.

## Citations
- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py`
  lines: 54-61
  symbol: `PDFLoader.is_image_only`
  excerpt: |
    def is_image_only(self, page: fitz.Page) -> bool:
        """Return True if the page only contains images (no visible text)."""
        text = page.get_text("text").strip()
        if text:
            return False
        img_list = page.get_images(full=True)
        return len(img_list) > 0
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 3082-3086
  symbol: `ask_with_image call (telegram photo handler)`
  excerpt: |
    if hasattr(self.agent, "ask_with_image"):
        response = await self.agent.ask_with_image(
            self._enrich_question(enriched_caption, session),
            image_path=tmp_path,
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/generation.py`
  lines: 323-346
  symbol: `saved_image_paths (image generation, not PDF)`
  excerpt: |
    saved_image_paths = []
    saved_image_paths.append(file_path)
    images=saved_image_paths,
- path: `packages/ai-parrot/src/parrot/knowledge/pageindex/pdf_to_markdown.py`
  lines: 72
  symbol: `extract_markdown_per_page (no write_images)`
  excerpt: |
    chunks = pymupdf4llm.to_markdown(path_str, page_chunks=True)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/library.py`
  lines: 966-967
  symbol: `ContractLibrary._extract_pdf_pages (text only)`
  excerpt: |
    with pymupdf.open(str(path)) as document:
        return [page.get_text() or "" for page in document]

## Notes
- The absence is confirmed. FEAT-601 image extraction is net-new. The natural place for it is `pymupdf4llm.to_markdown(..., write_images=True, image_path=...)` inside `extract_markdown_per_page` (see F013).
- `pdf.py` L227/L318 use `source_type="pdf_markdown"` metadata labels. These are unrelated to images.

