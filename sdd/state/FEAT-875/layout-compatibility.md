# FEAT-875 — PyMuPDF Layout compatibility report

Run 2026-11-10 in an isolated venv (Python 3.12.3, outside the shared `.venv`) plus a throwaway
`PYTHONPATH` overlay for the legacy-suite runs. No shared environment, `pyproject.toml` or `uv.lock` was modified.

## Verdict

**Technically compatible; NOT shippable as-is. Three maintainer decisions are open (see end).**

- The tuple `pymupdf==1.27.1`, `pymupdf4llm==0.2.9`, `pymupdf-layout==1.27.1` installs cleanly,
  activates Layout, preserves physical pages, and leaves the legacy path and legacy suites intact.
- The `bookstore-layout` extra was **not** added: it cannot resolve against the existing `agents` pins
  (`pdf4llm==0.0.27` requires `pymupdf4llm==0.0.27`), and dependency addition needs maintainer approval (spec §8).
- Native heading quality on my generated fixtures shows two gaps (a heading dropped; hierarchy flattened).
  The spec says to stop for a design revision if the gate fails, so this needs a human call before TASK-5470 onward.

## Resolved versions

| Package | Version | Wheel / platform | Python | License |
|---|---|---|---|---|
| pymupdf | 1.27.1 | existing pin | >=3.10 | AGPL-3.0 or Artifex Commercial |
| pymupdf4llm | 0.2.9 | pure-Python wheel | >=3.10 | AGPL-3.0 or Artifex Commercial |
| pymupdf-layout | 1.27.1 | `cp312` binary wheel (`_features.so`, ONNX models, 11.8 MiB) | >=3.10 | **Polyform Noncommercial or Artifex Commercial** |

Transitive additions: `onnxruntime 1.31.1`, `numpy 2.5.4`, `flatbuffers`, `protobuf`, `networkx`, `tabulate`, `packaging`, `pyyaml`.

**Licensing flag:** `pymupdf-layout` is *Polyform Noncommercial*, not AGPL like the other two. Commercial use
needs an Artifex licence. This must be reviewed before the extra is published.

Releases considered: pymupdf4llm 0.2.4–0.2.9 (pre-automatic), 0.3.x, then 1.27.2.1+ (automatic Layout). Only 0.2.9 was exercised.

## Activation API

- **Activate:** `import pymupdf.layout` (the distribution is `pymupdf-layout`; the import is `pymupdf.layout`, **not** `pymupdf_layout`).
  Its module body calls `activate()`, which sets `pymupdf._get_layout`.
- **Order matters (critical for TASK-5470).** `pymupdf4llm/__init__.py:14` picks its code path at *import time*
  (`if pymupdf._get_layout is None:` → legacy). If `pymupdf4llm` is imported before `pymupdf.layout`, it runs in
  legacy mode (`Warning - arguments ignored in legacy mode: {'use_ocr'}`, no `page_number`).
- **The package's own import graph triggers this.** `pageindex/__init__.py:17` imports `pdf_to_markdown`, which imports
  `pymupdf4llm` at module level (`pdf_to_markdown.py:32`). So `python -m parrot.knowledge.pageindex.pdf_layout_backend`
  would load `pymupdf4llm` *first* and silently run legacy.
- **Verified workaround:** `import pymupdf.layout` then `importlib.reload(pymupdf4llm)` → page chunks carry `page_number`. The worker must do
  this (or avoid importing the package, e.g. a standalone script). **Spec §3 M2's `-m` entry point is therefore not safe as written.**
- Layout is not active without the explicit import: `pymupdf._get_layout` stayed `None` in the legacy-style run.

## OCR and image-write disabling

- `pymupdf4llm.to_markdown(..., use_ocr=False)` is accepted once Layout is active (default `True`, `helpers/document_layout.py:638,871`).
  `ocr_dpi` / `ocr_language` also exist. Tesseract data was absent here, so OCR was already off; the keyword path itself was exercised.
- `write_images=False` (default) wrote no files; none appeared in the working directory.
- **Image-only PDF:** with `use_ocr=False` the result text is empty, so `NoTextLayerError` (raised by the builder's existing
  `_read_page_tokens`) still applies.

## Page identity

- `to_markdown(..., page_chunks=True)` returns one dict per physical page. `chunk["metadata"]["page_number"]` is 1-based and
  `chunk["metadata"]["page_count"]` is the total. Checked: 3-page PDF → `[1, 2, 3]`; arxiv fixture → `1..9`, `page_count=9`.
- A blank middle page is **kept** as a chunk with `text == ""`. No reconstruction needed.
- Legacy mode (import-order failure above) returns chunks *without* `page_number`, which is the detectable symptom: the
  worker should treat a missing `page_number` as a hard error.

## Native heading quality

Generated fixtures (`pymupdf` drawn), native Layout, `use_ocr=False`:

| Fixture | Result |
|---|---|
| Two columns (12 + 12 sentinels) | PASS — all 24 present, left column before right, not interleaved |
| Ruled table (6×3) | PASS — all 15 cell values present, markdown pipe table |
| Bold body sentence (10pt bold) | PASS — not promoted to a heading |
| Chapter / `1.1` / `1.1.1` headings | **FAIL** — `1.1 Background` (16pt bold) **dropped**; `Chapter 1` and `1.1.1` both rendered as `##` (hierarchy flattened) |
| arxiv_2408_09869.pdf | 17 native headings vs 18 legacy; native headings are **all one level** and wrapped in `**…**`; legacy gives `##/###/####` |

**`hdr_info` is silently ignored** when Layout is active: output was byte-identical with and without a custom `hdr_info`.
So `LayoutHeaders` cannot be applied to the native backend, as the spec already expects.

Caveats: the synthetic heading fixture is tiny and the ONNX model classifies from visual layout, so the dropped heading may be
fixture-specific. The flattened levels on the real arxiv paper are not. TASK-5473's real-corpus comparison is the right place to settle
this, but the flat hierarchy may degrade `layout`-mode structure selection, which keys off heading depth.

## Legacy behavior

`test_pdf_to_markdown.py` + `test_pdf_page_images.py` (worktree, absolute `PYTHONPATH`):

| Environment | Result |
|---|---|
| Layout absent (shared venv: pymupdf4llm 0.0.27) | 8 passed |
| Layout packages present (overlay: pymupdf4llm 0.2.9, pymupdf-layout 1.27.1; `pymupdf.layout` not imported) | 8 passed |

Importing `pymupdf4llm` 0.2.9 alone does **not** activate Layout; legacy behavior is unchanged.
The broader legacy suites (`test_builder_layout`, `test_layout_integration`, Bookstore) were not run here; they belong to TASK-5471/5472/5473.

## Smoke commands

```text
uv venv --python 3.12 env && uv pip install --python env/bin/python pymupdf==1.27.1 pymupdf4llm==0.2.9 pymupdf-layout==1.27.1
env/bin/python -I -c "import pymupdf.layout, pymupdf4llm; ..."            # activation / page_number / use_ocr
env/bin/python -I -c "import pymupdf4llm, pymupdf, pymupdf.layout; ..."    # wrong order → legacy mode, no page_number
env/bin/python -I -c "...; importlib.reload(pymupdf4llm); ..."             # reload fixes it
PYTHONPATH=<overlay>:<worktree>/packages/ai-parrot/src pytest <2 legacy suites> -q   # 8 passed (absent and present)
```
Measurements (arxiv, 9 pages, native): first call 5.2 s, second 5.1 s, peak RSS ≈ 723 MB (parent process incl. ONNX model).
Legacy: 7.6 s (includes `analyze_layout`). Single machine, indicative only; the formal comparison is TASK-5473.
Logs: `artifacts/logs/FEAT-875-legacy-layout-absent.log`, `artifacts/logs/FEAT-875-legacy-layout-present.log`.

## Resolution against the workspace (why the extra was not added)

- `packages/ai-parrot/pyproject.toml:490-492` pins `pymupdf==1.27.1`, `pymupdf4llm==0.0.27`, `pdf4llm==0.0.27`.
- `pdf4llm 0.0.27` declares `Requires-Dist: pymupdf4llm==0.0.27`. A `bookstore-layout` extra needing `pymupdf4llm==0.2.9`
  therefore conflicts with the `agents` extra in one workspace lock.
- Options: (a) drop `pdf4llm` from `agents` (a wrapper distribution — check who imports `pdf4llm`), (b) bump `agents` to the
  0.2.9 family, which changes its heading behaviour only if Layout is imported, or (c) declare a uv `conflicts` entry
  (root `pyproject.toml:93` already uses this mechanism). None was applied.

## Decisions needed from the maintainer

1. **Licence:** is a *Polyform Noncommercial* optional dependency acceptable for this project's distribution?
2. **Pins:** which of (a)/(b)/(c) above resolves the `pdf4llm==0.0.27` conflict?
3. **Heading gate:** native hierarchy is flat and one fixture heading was dropped. Proceed to TASK-5470 and let TASK-5473's real-corpus
   comparison decide, or revise the design first (spec §2 says stop rather than weaken assertions)?

And for TASK-5470, regardless of the above: the worker needs the import-order fix (reload or standalone script), not the bare `-m` entry from the spec.
