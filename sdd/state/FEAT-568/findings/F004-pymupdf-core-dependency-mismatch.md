# F004 — `pymupdf`/`pymupdf4llm` packaging contradicts the FEAT-451 spec's own assumption

**Query**: Q006 (pymupdf/fitz grep + spec cross-check)
**Confidence**: high (discrepancy confirmed) / medium (which side is "correct")

## Evidence

- `sdd/specs/wikitoolkit-ingest-documents.spec.md` (FEAT-451), line 388:
  *"`page_count` is read via `pymupdf` (**already a core dependency**, used
  by pageindex/pdf_to_markdown.py:23)"* and line 797: *"Precedent that
  `pymupdf` + `pymupdf4llm` are core deps and importable."* — the spec was
  designed on the explicit premise that these packages are unconditional
  `ai-parrot` dependencies.
- Actual `packages/ai-parrot/pyproject.toml`: `pymupdf`/`pymupdf4llm` appear
  **only** under the `bookstore` extra (line ~319) and again inside one
  large catch-all extra block (~line 407, likely `all`/`all-fast`) — **not**
  in `[project.dependencies]` (core, unconditional), and not in
  `wiki-languages`, `wiki-structural`, `wiki`, or `graphindex`.
- CI evidence: `test-wiki-extras` (`uv sync --package ai-parrot --extra
  wiki-languages --extra wiki-structural`) running `tests/knowledge/wiki/`
  hits `ModuleNotFoundError: No module named 'pymupdf'` on every
  `DocumentAcquirer`/PDF-ingestion test (`test_documents.py`,
  `test_cli.py::TestIngestSourceArgument`,
  `test_integration.py::TestFeat451DocumentIngestEndToEnd`) — 22
  occurrences in this job alone, same in `test-core`.

## Conclusion (needs a spec-time decision, not unilateral in this proposal)

Two mutually-exclusive remediations, both consistent with *some* part of
the current design intent:

- **Option A — promote to core dependency** (matches what FEAT-451's spec
  already assumed and documented): move `pymupdf`/`pymupdf4llm` from the
  `bookstore` extra into `[project.dependencies]` of `ai-parrot` core. This
  makes the spec's own words true, and `test-wiki-extras`/`test-core` pass
  with zero test changes. Cost: every install of bare `ai-parrot` now pulls
  the pymupdf binary wheel.
- **Option B — keep it optional, make ingestion degrade gracefully**:
  correct the spec's stale claim, guard `DocumentAcquirer`'s PDF path
  behind an availability check (mirroring the Luau/tree-sitter and
  `force_no_astgrep` patterns already used elsewhere in the wiki stack), and
  add `pytest.importorskip("pymupdf")` to the PDF-specific tests so
  `test-wiki-extras` reflects reality (wiki-languages/wiki-structural
  deliberately excludes it) while a separate job (or an added `--extra
  bookstore`/`wiki` on this same job) proves the real path.

This is flagged as an open question for `/sdd-spec` rather than decided
here — the *spec itself* is what claims "already a core dependency", so
Option A restores what was already designed and documented; Option B is the
right call only if that design premise is deliberately being revisited.
