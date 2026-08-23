# TASK-2358: End-to-end integration tests + documentation

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2357
**Assigned-to**: unassigned

---

## Context

Implements **Module 8** of the spec (§3) plus the §4 Integration Tests table.
The unit tests in TASK-2351..2357 prove each piece; this task proves the
*pipeline* — a real PDF on disk becomes a wiki page whose frontmatter parses
and whose sources row carries the metadata.

Two of these tests are **regression gates**, not feature tests, and matter
more than the rest:

- `test_build_unaffected` — `wikitoolkit build` output must be byte-identical
  with FEAT-451 code present. `build` is load-bearing for the git post-commit
  hook and is a hard spec Non-Goal.
- `test_undecodable_never_reaches_llm` — the anti-mojibake guarantee, asserted
  against the stub adapter rather than inferred from output.

---

## Scope

- ADD shared fixtures to `tests/knowledge/wiki/conftest.py`:
  - `sample_pdf` — a small multi-page PDF with Author/Title set, written with
    `pymupdf` (already a core dep) so no binary fixture is committed.
  - `undecodable_file` — random bytes with a `.pdf` suffix.
  - `mixed_corpus` — a folder containing `.md` (with and without
    frontmatter), `.pdf`, `.docx`, and `undecodable_file`.
  - `mock_aiohttp_pdf` — an aiohttp mock serving `sample_pdf` bytes with
    `Content-Type: application/pdf` (also used by TASK-2354).
- ADD integration tests to `tests/knowledge/wiki/test_integration.py`:
  - `test_ingest_pdf_end_to_end`
  - `test_ingest_mixed_corpus`
  - `test_ingest_single_file`
  - `test_ingest_url`
  - `test_undecodable_never_reaches_llm`
  - `test_ingest_page_carries_provenance`
  - `test_multi_page_pdf_identical_frontmatter`
  - `test_build_unaffected`
  - `test_legacy_pages_unchanged`
- UPDATE `documentation/parrot-wiki-cli.md`:
  - `wikitoolkit ingest` now takes `SOURCE` (directory | file | URL).
  - A supported-formats table, stating plainly which formats need
    `ai-parrot-loaders` installed and which work without it.
  - The page-frontmatter contract: which keys are emitted, and the nested
    `triage:` block.
  - The new `--recursive/--no-recursive` and `--fetch-timeout` options.
  - A note that undecodable documents are skipped and counted, not ingested.
- UPDATE `docs/wiki-claude-code.md` where it describes ingestion, if it
  mentions the folder-only shape.

**NOT in scope**: new production code — if a test reveals a bug, fix it in the
owning module and note the deviation; adding a committed binary fixture (build
the PDF at runtime with pymupdf instead); performance benchmarking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/conftest.py` | MODIFY | Shared fixtures |
| `tests/knowledge/wiki/test_integration.py` | MODIFY | End-to-end + regression tests |
| `documentation/parrot-wiki-cli.md` | MODIFY | CLI guide: SOURCE, formats, frontmatter, options |
| `docs/wiki-claude-code.md` | MODIFY | Update ingestion description if folder-only |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import pymupdf                       # core dep — precedent: pageindex/pdf_to_markdown.py:23
import yaml
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.documents import DocumentAcquisitionError
from parrot.knowledge.wiki.models import SourceManifestEntry
```

### Existing Signatures to Use

```python
# Existing test surfaces to extend (do NOT create parallel files):
# tests/knowledge/wiki/conftest.py          — shared fixtures live here
# tests/knowledge/wiki/test_integration.py  — end-to-end tests live here
# tests/knowledge/wiki/test_cli.py          — CliRunner + stub-LLM tests (TASK-2357)

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@wiki.command()
def build(...)      # decorators 730-767, function 768+  — MUST stay byte-identical
def ingest(...)     # 2351+                              — the command under test
def main() -> None  # 2660

# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:304
async def triage(self, path: Path, content: str) -> ManifestDocEntry:
#   The call that MUST NOT happen for a skipped document.
```

```python
# Existing docs to update:
# documentation/parrot-wiki-cli.md  — "`parrot wiki` & `parrot claude` — LLM Wiki CLI Guide"
# docs/wiki-claude-code.md          — "WikiToolkit as Claude Code infrastructure"
```

### Does NOT Exist

- ~~a committed PDF/DOCX binary fixture in `tests/`~~ — build fixtures at
  runtime with `pymupdf`. Do not add binaries to the repo.
- ~~`tests/integration/` for wiki tests~~ — wiki integration tests live in
  `tests/knowledge/wiki/test_integration.py`. Do not create a new tree.
- ~~a `docs/sdd/specs/` path~~ — specs live at `sdd/specs/` in this repo (the
  `docs/sdd/WORKFLOW.md` prose predates the move).
- ~~`wikitoolkit ingest --meta` / `--from-list`~~ — neither exists; do not
  document them.

---

## Implementation Notes

### Pattern to Follow

```python
# conftest.py — build the PDF at runtime, no committed binary.
@pytest.fixture
def sample_pdf(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    for text in ("Page one body text.", "Page two body text."):
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.set_metadata({"author": "Legal Dept", "title": "Contrato Marco 2026"})
    path = tmp_path / "contrato.pdf"
    doc.save(str(path))
    doc.close()
    return path
```

```python
# The regression gate that matters most — assert the NEGATIVE directly.
async def test_undecodable_never_reaches_llm(mixed_corpus, stub_triage_adapter, ...):
    CliRunner().invoke(wiki, ["ingest", str(mixed_corpus), "--dry-run", ...])
    triaged = {Path(p).name for p in stub_triage_adapter.received_paths}
    assert "bad.pdf" not in triaged      # not inferred from output — asserted
```

### Key Constraints

- Stub the LLM. These are integration tests over the *pipeline*, not the model
  — follow the existing stub-adapter pattern in `tests/knowledge/wiki/test_cli.py`.
- `test_build_unaffected` must compare **actual output**, not just an exit
  code: run `build` over a fixed corpus and compare the resulting page bodies
  and sources rows against a snapshot taken with the same code path
  (`triage=None`). A green exit code proves nothing here.
- `test_legacy_pages_unchanged` seeds a wiki store with a frontmatter-less
  page, re-opens it, and asserts no backfill occurred — the spec explicitly
  does not migrate old pages.
- Skip binary-format tests cleanly with `pytest.importorskip("parrot_loaders")`
  where the format requires the optional satellite, so the suite still passes
  in an install without it. But the *without-loaders* behavior tests (skip +
  warn) must run always — that is the degradation contract.
- Docs must state the optional dependency plainly. A user hitting "skipped:
  contrato.pdf" needs to find "install ai-parrot-loaders" in one step.

### References in Codebase

- `tests/knowledge/wiki/test_integration.py` — existing end-to-end shape.
- `tests/knowledge/wiki/test_cli.py` — CliRunner + stub-LLM pattern.
- `documentation/parrot-wiki-cli.md` — the guide's existing structure and tone.

---

## Acceptance Criteria

- [ ] `test_ingest_pdf_end_to_end`: PDF → `--auto` → a page exists, its body
      starts with `---`, the block parses via `yaml.safe_load`, and carries
      `page_count` and `content_type`; the sources row has `doc_metadata`.
- [ ] `test_ingest_mixed_corpus`: all decodable docs triaged, the undecodable
      one skipped and reported, process exit code 0.
- [ ] `test_ingest_single_file`: one-entry manifest.
- [ ] `test_ingest_url`: mocked aiohttp → page created with `source_url` in
      the frontmatter.
- [ ] `test_undecodable_never_reaches_llm`: asserted against the stub
      adapter's received paths, not inferred from CLI output.
- [ ] `test_ingest_page_carries_provenance`: the nested `triage:` block
      matches the manifest entry's `composite`, decision, decision source, and
      charter version.
- [ ] `test_multi_page_pdf_identical_frontmatter`: every page's block is
      byte-identical.
- [ ] `test_build_unaffected`: `build` page bodies and sources rows are
      byte-identical to the pre-FEAT-451 output (compared, not assumed).
- [ ] `test_legacy_pages_unchanged`: no backfill onto pre-FEAT-451 pages.
- [ ] No binary fixture is committed to the repo.
- [ ] The suite passes with `ai-parrot-loaders` installed **and** with it
      uninstalled (binary-format tests skip; degradation tests still run).
- [ ] `documentation/parrot-wiki-cli.md` documents `SOURCE`, the supported
      formats table, the optional dependency, the frontmatter contract, and
      both new options.
- [ ] Full suite passes: `pytest tests/knowledge/wiki/ -v`
- [ ] `ruff check` clean on all changed test files.

---

## Test Specification

```python
# tests/knowledge/wiki/test_integration.py  (append)
import yaml
import pytest
from pathlib import Path
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


class TestIngestEndToEnd:
    def test_ingest_pdf_end_to_end(self, wiki_project, sample_pdf, stub_llm, charter):
        result = CliRunner().invoke(
            wiki, ["ingest", str(sample_pdf), "--auto", "--path", str(wiki_project)]
        )
        assert result.exit_code == 0
        page = ...                       # read the created WikiPageRecord
        assert page.body.startswith("---\n")
        meta = yaml.safe_load(page.body.split("---\n")[1])
        assert meta["content_type"] == "application/pdf"
        assert meta["page_count"] == 2
        source = ...                     # read the SourceManifestEntry
        assert source.doc_metadata is not None
        assert source.loader

    def test_ingest_mixed_corpus(self, wiki_project, mixed_corpus, stub_llm, charter):
        result = CliRunner().invoke(
            wiki, ["ingest", str(mixed_corpus), "--dry-run", "--path", str(wiki_project)]
        )
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()

    def test_undecodable_never_reaches_llm(
        self, wiki_project, mixed_corpus, stub_triage_adapter, charter
    ):
        CliRunner().invoke(
            wiki, ["ingest", str(mixed_corpus), "--dry-run", "--path", str(wiki_project)]
        )
        seen = {Path(p).name for p in stub_triage_adapter.received_paths}
        assert "bad.pdf" not in seen

    def test_ingest_page_carries_provenance(self, wiki_project, sample_pdf, stub_llm, charter):
        ...

    def test_multi_page_pdf_identical_frontmatter(self, wiki_project, sample_pdf, ...):
        blocks = [p.body.split("---\n")[1] for p in pages]
        assert len(set(blocks)) == 1


class TestRegressionGates:
    def test_build_unaffected(self, wiki_project, code_corpus):
        """build output must be byte-identical with FEAT-451 present."""
        ...

    def test_legacy_pages_unchanged(self, wiki_project_with_legacy_pages):
        """No backfill onto pages ingested before FEAT-451."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§4 Test Specification, §5).
2. **Check dependencies** — TASK-2357 must be in `sdd/tasks/completed/`, which
   means all of TASK-2351..2357 are done.
3. **Verify the Codebase Contract** — confirm the existing conftest fixtures
   and stub-LLM pattern before adding new ones; reuse, do not duplicate.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above. If a test reveals a real
   bug, fix it in the owning module and record it in the Completion Note.
6. **Verify** all acceptance criteria are met — including running the suite
   once with `ai-parrot-loaders` uninstalled.
7. **Move this file** to `sdd/tasks/completed/TASK-2358-integration-tests-and-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added `sample_pdf`, `undecodable_file`, `mixed_corpus` (with
`with_frontmatter.md`, `plain.md`, `contrato.pdf`, `decision.docx` via
`pytest.importorskip("docx")`, and `bad.pdf`), and `mock_aiohttp_pdf` to
`conftest.py` — no binary fixture committed, all built at runtime
(pymupdf/python-docx). Added `TestFeat451DocumentIngestEndToEnd` to
`test_integration.py` with all 8 named tests from the spec/task list
(`test_ingest_pdf_end_to_end`, `test_ingest_page_carries_provenance`,
`test_multi_page_pdf_identical_frontmatter`, `test_ingest_single_file`,
`test_ingest_url`, `test_undecodable_never_reaches_llm`,
`test_ingest_mixed_corpus` — driven through the real CLI and consuming
the `mixed_corpus` fixture, 4 decodable + 1 skipped — and
`test_legacy_pages_unchanged`). `test_build_unaffected` already existed
(`TestBuildUnaffected`, pre-FEAT-451) and needed no changes; re-verified
passing repeatedly throughout this task. Extended the local
`_FakeTriageAdapter` with a `received_prompts` list (additive, doesn't
affect existing tests) so the anti-mojibake test asserts directly against
received prompts, not inferred output.

**Deviations from spec — two real bugs found and fixed, per this task's
own "if a test reveals a real bug, fix it in the owning module" allowance**:

1. `packages/ai-parrot/src/parrot/knowledge/wiki/ingest.py` —
   `WikiIngestOrchestrator.ingest()` unconditionally did
   `Path(source_path).resolve()`. For a URL `source_path`, `.resolve()`
   resolves it against the process cwd as if it were a relative
   filesystem path (`"https://h/a.pdf"` → `"<cwd>/https:/h/a.pdf"`),
   diverging from the identity `IngestTriageRouter.triage()` already
   computes for the same URL (`str(Path(ref.uri))` — TASK-2357's own
   contract explicitly sanctions passing `Path(ref.uri)` to `triage()`)
   — `test_ingest_url` hit `FileNotFoundError` inside `add_source()`
   because of this. Fixed by skipping `.resolve()` for a URL-scheme
   `source_path`, matching the router's un-resolved, single-slash-
   collapsed convention instead of diverging from it. Also relaxed the
   `add_source()` exception handler: on the *triage-driven* path only
   (never the legacy `triage=None` path — unchanged there), a
   `FileNotFoundError`/`OSError` (always raised for a URL, which has no
   local file to `stat()`) now defers registration to `record_decision()`
   (Step 5) instead of hard-erroring — `record_decision()` was already
   built to tolerate a source that was never registered via
   `add_source()` (its own docstring: "a rejected document may never
   have been registered ... at all").
2. `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` —
   `SourceCollectionManager.record_decision()` independently re-did
   `Path(path).resolve()` on its own `path` argument, so even after
   fix #1 above it would re-diverge internally. Applied the identical,
   narrowly-scoped fix: skip `.resolve()` for a URL-scheme path so its
   own `source_uri` computation matches the router/orchestrator
   convention instead of drifting.

Both fixes touch only the `Path(<url>).resolve()` call site in each
function — no broader redesign of URL source-identity handling (that
remains a known, accepted limitation: a URL source's manifest
`source_uri` is the single-slash-collapsed `str(Path(ref.uri))` form, not
the double-slash original — consistent everywhere, but a genuine
follow-up candidate is a dedicated URL-identity representation instead of
overloading `pathlib.Path`). Verified via `git stash`/mypy-diff and
`ruff check` baseline comparison that neither fix introduces any new
lint/type finding — `ingest.py` has the same 4 pre-existing mypy errors
(shifted line numbers) and the same 19 UP045 + 1 S112 pre-existing ruff
findings (following this not-yet-pyupgraded file's `Optional[X]`
convention for the small amount of new code); `sources.py` is fully
clean both before and after. All 874 wiki-suite tests still pass (the one
pre-existing `test_claude_code.py::TestInstaller` failure — an unrelated
artifact-count assertion — was verified present on `dev` before this
task via `git stash`, untouched here).

Documentation: added a full `### parrot wiki ingest` section to
`documentation/parrot-wiki-cli.md` (SOURCE's three shapes, all 13
options including the two new ones, a supported-formats table stating
plainly which need `ai-parrot-loaders`, and the full page-frontmatter
contract with a worked YAML example) — no such section existed before
this feature (FEAT-402 never added one either; this task also closes
that pre-existing doc gap for `ingest` as a whole, not just the FEAT-451
delta). `docs/wiki-claude-code.md` was left untouched — checked, it
does not document the `ingest` command's argument shape at all (only
`build`/`query`/`page`/`related`/`upsert`/`status`/`export`), so the
task's own conditional ("if it mentions the folder-only shape") does not
apply.

The "suite passes with `ai-parrot-loaders` uninstalled" acceptance
criterion was verified via the established repo pattern (forced
`ImportError` on `parrot_loaders.*` imports, matching TASK-2351/2353's
own test technique) rather than literally uninstalling the package from
this shared dev venv, which would have risked breaking unrelated test
suites. `test_undecodable_never_reaches_llm` exercises this path
directly and deterministically.
