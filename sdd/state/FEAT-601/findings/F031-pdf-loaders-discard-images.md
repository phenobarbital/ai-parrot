---
id: F031
query_id: Q031
type: read
intent: PDFMarkdownLoader.extract_images, PDFLoader.is_image_only skipping, ImageUnderstandingLoader._analyze_image_with_ai client method
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F031 — The PDF loaders throw images away; extract_images is stored and never used

## Summary
`PDFMarkdownLoader.__init__` accepts `extract_images: bool = False` and stores it on `self.extract_images`. Nothing in `parrot_loaders/` reads it. The pymupdf4llm backend calls `pymupdf4llm.to_markdown(str(path))` with no kwargs, so no images are written. `PDFLoader.is_image_only` is true when a page has no text and at least one image; the default page-based branch of `_load` skips such pages. The markdown and full_document branches call `to_markdown` with no image kwargs either. `ImageUnderstandingLoader._analyze_image_with_ai` calls `GoogleGenAIClient.image_understanding(prompt, images=path, model=self.model, prompt_instruction, temperature, stateless=True, detect_objects=self.detect_objects)`.

## Citations
- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdfmark.py`
  lines: 54, 67
  symbol: `PDFMarkdownLoader.__init__`
  excerpt: |
    54:        extract_images: bool = False,
    67:        self.extract_images = extract_images
- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdfmark.py`
  lines: 117-123
  symbol: `PDFMarkdownLoader._convert_to_markdown_pymupdf4llm`
  excerpt: |
    return pymupdf4llm.to_markdown(str(path))
- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py`
  lines: 54-61
  symbol: `PDFLoader.is_image_only`
  excerpt: |
    text = page.get_text("text").strip()
    if text: return False
    img_list = page.get_images(full=True)
    return len(img_list) > 0
- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py`
  lines: 328-335
  symbol: `PDFLoader._load` (default page branch)
  excerpt: |
    for i, page in enumerate(doc):
        page_text = page.get_text("text").strip()
        if self.is_image_only(page):
            self.logger.info(f"Page {i+1}: image-only, skipping.")
            continue
- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdf.py`
  lines: 221-223, 263-264
  symbol: `PDFLoader._load` markdown branches
  excerpt: |
    md_text = pymupdf4llm.to_markdown(str(path))
    md_text = pymupdf4llm.to_markdown(path)
- path: `packages/ai-parrot-loaders/src/parrot_loaders/imageunderstanding.py`
  lines: 162-187
  symbol: `ImageUnderstandingLoader._analyze_image_with_ai`
  excerpt: |
    response = await ai_client.image_understanding(
        prompt=prompt, images=image_path, model=self.model,
        prompt_instruction=instructions, temperature=self.temperature,
        stateless=True, detect_objects=self.detect_objects,)
- path: `packages/ai-parrot-client-google/src/parrot/clients/google/analysis.py`
  lines: 438
  symbol: `GoogleGenAIClient.image_understanding`
  excerpt: |
    def image_understanding(...)  # the only captioning entry point used by a loader today

## Notes
- Confirmed: `extract_images` is dead. A grep over `packages/ai-parrot-loaders/src` finds only the two lines above.
- Because figures are discarded in every existing PDF path, figure extraction has to be new code (`to_markdown(write_images=True, image_path=..., page_chunks=True)`, or `Page.get_image_info`/`get_image_bbox`, both confirmed in F026).
