# TASK-2357: CLI wiring — widen `SOURCE`, acquire via `DocumentAcquirer`, report skips

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2354, TASK-2356
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec (§3) — the user-facing surface. Two
changes, both narrow:

1. The `folder` argument becomes a `SOURCE` that accepts a directory, a single
   file, or a URL.
2. `_triage_all` stops calling `read_text(..., errors="ignore")` and acquires
   through `DocumentAcquirer`, skipping and counting documents that cannot be
   decoded.

**`cli.py` is a HOT file** — 2694 lines, touched by several features in
flight. **Hot-file discipline applies: no new logic here.** Everything beyond
argument handling and orchestration calls belongs in `documents.py`.

---

## Scope

- MODIFY the `ingest` command in
  `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`:
  - Replace the argument declaration (lines 2281-2283):
    ```python
    @click.argument("source")     # plain str: dir | file | http(s) URL
    ```
    and rename the parameter in the function signature (line 2352) from
    `folder: Path` to `source: str`. Existence validation now lives in
    `resolve_sources` (which raises `click.ClickException`).
  - Add two options:
    - `--recursive/--no-recursive` (default `True`) — directory walk depth.
    - `--fetch-timeout FLOAT` (default `30.0`) — URL fetch timeout.
  - Update the command docstring: `FOLDER` → `SOURCE`, and document the three
    accepted shapes plus the `ai-parrot-loaders` requirement for binary formats.
  - Replace `paths = _discover_documents(folder)` (line 2544) with
    `refs = resolve_sources(source, recursive=recursive)`.
  - Rewrite the `_triage_all` inner function (lines 2472-2483) to acquire via
    `DocumentAcquirer`, catching `DocumentAcquisitionError` per document:
    log a warning, append to a `skipped` list, and **continue** — one bad
    document never aborts the run.
  - Keep the acquired `AcquiredDocument` alongside its entry so `_apply_all`
    can pass it to `orch.ingest(..., acquired=...)` for the
    `--interactive` / `--auto` paths (avoids re-acquisition). The `--review`
    path re-acquires by necessity — it is a fresh process.
  - Print a skipped count in every mode's summary line, and list the skipped
    paths at `--verbose`.
  - DELETE `_discover_documents` (lines 2093-2114) once `resolve_sources`
    replaces it — do not leave a dead duplicate of the walk semantics.
- Extend `tests/knowledge/wiki/test_cli.py` (CliRunner-based, stub LLM).

**NOT in scope**: any change to `build`, `upsert`, `repo_scan.py` (hard spec
Non-Goal); any change to the charter, manifest, or review flow; new logic in
`cli.py` beyond argument handling and orchestration calls; integration tests
(TASK-2358).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | Argument, two options, `_triage_all`, remove `_discover_documents` |
| `tests/knowledge/wiki/test_cli.py` | MODIFY | CLI tests for the three source shapes + skip reporting |

---

## Codebase Contract (Anti-Hallucination)

> **`cli.py` is a HOT file (2694 lines @ 2026-08-23) and drifts fast.
> Re-anchor EVERY line number below before editing.**

### Verified Imports

```python
import click                                       # >=8.1.7, core dep
from parrot.knowledge.wiki.documents import (      # TASK-2351/2353/2354
    DocumentAcquirer,
    DocumentAcquisitionError,
    resolve_sources,
)
# Already imported inside the ingest() function body (cli.py:2366-2390):
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.charter import TriageExample, append_example, load_charter
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.review import (
    ManifestReader, ManifestRunHeader, ManifestWriter, stratified_sample,
)
from parrot.knowledge.wiki.triage import IngestTriageRouter
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py

def _discover_documents(folder: Path) -> list[Path]:            # 2093-2114  <-- DELETE
def _resolve_charter_path(root, charter_opt) -> Path:           # 2116
def _resolve_model_id(cli_value, env_name) -> str:              # 2144
def _build_triage_adapters(lightweight_model, model)            # 2166
def _build_novelty_scorer(root, config, store)                  # 2204
def _print_triage_summary(entries: list[Any]) -> None:          # 2266

@wiki.command()                                                 # 2280
@click.argument(
    "folder", type=click.Path(exists=True, file_okay=False, path_type=Path)
)                                                               # 2281-2283  <-- REPLACE
@path_option                                                    # shared --path decorator, defined 71-73
@click.option("--charter", "charter_opt", ...)                  # 2285-2291
@click.option("--dry-run", "dry_run", is_flag=True, ...)        # 2292-2297
@click.option("--review", "review_opt", ...)                    # 2298-2304
@click.option("--interactive", "interactive_flag", is_flag=True, ...)   # 2305-2310
@click.option("--auto", "auto_flag", is_flag=True, ...)         # 2311-2316
@click.option("--extract", "extract_flag", is_flag=True, ...)   # 2317-2323
@click.option("--lightweight-model", ...)                       # 2324-2329
@click.option("--model", "model_opt", ...)                      # 2330-2336
@click.option("--audit-rate", "audit_rate", default=0.1, ...)   # 2337-2343
@click.option("--manifest", "manifest_opt", ...)                # 2344-2350
def ingest(folder: Path, path_: str | None, charter_opt: str | None,
           dry_run: bool, review_opt: Path | None, interactive_flag: bool,
           auto_flag: bool, extract_flag: bool,
           lightweight_model_opt: str | None, model_opt: str | None,
           audit_rate: float, manifest_opt: Path | None) -> None:    # 2351-2364

    # THE READ TO REPLACE (2472-2483):
    async def _triage_all(paths: list[Path], router: Any) -> list[Any]:
        entries = []
        for doc_path in paths:
            content = await asyncio.to_thread(
                doc_path.read_text, encoding="utf-8", errors="ignore"    # 2474-2477
            )
            entry = await router.triage(doc_path, content)               # 2478
            if not extract_flag:
                entry.claims = []
            entries.append(entry)
            await asyncio.to_thread(_log_triage, entry)
        return entries

    async def _apply_all(entries, wiki_config, charter_version) -> None:  # 2485-2497
        for entry in entries:
            if entry.decision is None:
                continue
            await orch.ingest(entry.source_uri, wiki_config,
                              triage=entry, charter_version=charter_version)

    paths = _discover_documents(folder)                                   # 2544  <-- REPLACE
    entries = _run(_triage_all(paths, router))                            # 2545

    # Mode dispatch (already implemented — DO NOT restructure):
    #   review     2508-2530     dry-run 2547-2559
    #   interactive 2561-2606    auto    2608-2643
def _run(coro: Any) -> Any:                                     # 176
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/triage.py:304
async def triage(self, path: Path, content: str) -> ManifestDocEntry:
#   SIGNATURE IS FROZEN (spec §1 Non-Goals). Keep passing a Path and a str.
#   For a URL ref, pass Path(ref.uri) — triage only uses it for identity/hashing.
```

### Does NOT Exist

- ~~a `--from-list` / `--sources-file` option~~ — offered during spec Q&A and
  **not selected**. Do not add it.
- ~~a `--meta key=value` option~~ — operator-supplied metadata is an explicit
  spec Non-Goal.
- ~~`click.Path(exists=True)` accepting a URL~~ — that is exactly why the
  argument becomes a plain `str`. Do not try to make a Click type validate both.
- ~~a fifth ingest mode~~ — `--dry-run` / `--review` / `--interactive` /
  `--auto` remain mutually exclusive and exhaustive (cli.py:2399-2415).
  Do not add or restructure modes.
- ~~an `ingest` flag on `build`~~ — explicitly rejected by FEAT-402 §1.
- ~~`_discover_documents` surviving~~ — it must be deleted, not kept as a
  second copy of the walk semantics that can drift from `resolve_sources`.

---

## Implementation Notes

### Pattern to Follow

```python
async def _triage_all(refs, router, acquirer) -> tuple[list[Any], list[str]]:
    entries, skipped = [], []
    for ref in refs:
        try:
            acquired = await acquirer.acquire(ref)
        except DocumentAcquisitionError as exc:
            _cli_logger.warning("Skipping %s: %s", ref.uri, exc)
            skipped.append(ref.uri)
            continue                      # one bad doc never aborts the run
        entry = await router.triage(Path(ref.uri), acquired.text)
        if not extract_flag:
            entry.claims = []
        entries.append((entry, acquired))
        await asyncio.to_thread(_log_triage, entry)
    return entries, skipped
```

### Key Constraints

- **Hot-file discipline**: the diff should be the argument declaration, two
  options, the docstring, `_triage_all`, the `resolve_sources` swap, the
  summary lines, and the `_discover_documents` deletion. Nothing else.
  Rebase on `dev` immediately before starting AND before committing.
- Follow the file's existing conventions: `path_option` for `--path`,
  `_run(...)` for async entry (line 176), `click.echo` for output,
  `_cli_logger` for warnings.
- Skipped documents are **reported, not silent** — a count in every mode's
  summary. A run where half the corpus was unreadable must look different from
  a clean run.
- Preserve exact mode-dispatch behavior. The four modes and their
  mutual-exclusion errors (2399-2415) are unchanged.
- `--review` reads `source_uri` from the manifest and re-acquires; do not try
  to thread `acquired` through that path.
- Keep the `Path(ref.uri)` shape when calling `router.triage` — the signature
  is frozen by the spec.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2013-2091` — the `ground` command: how this file constructs stacks and runs async code.
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:2266-2278` — `_print_triage_summary`, where the skipped count belongs.
- `tests/knowledge/wiki/test_cli.py` — CliRunner + stub-LLM test shape.

---

## Acceptance Criteria

- [ ] `wikitoolkit ingest <dir> --dry-run` behaves exactly as before for a
      plain-text corpus (same manifest entries, same decisions).
- [ ] `wikitoolkit ingest <file.pdf> --dry-run` produces a one-entry manifest.
- [ ] `wikitoolkit ingest https://host/doc.pdf --dry-run` fetches and triages.
- [ ] `wikitoolkit ingest /no/such/path --dry-run` exits non-zero with a clean
      Click error message (no traceback).
- [ ] `--recursive/--no-recursive` controls directory depth.
- [ ] `--fetch-timeout` reaches `DocumentAcquirer.__init__`.
- [ ] An undecodable document is skipped, counted, and reported — the run
      still exits 0 and the other documents are triaged.
- [ ] `router.triage()` is **never** called for a skipped document (assert
      against the stub adapter, do not infer).
- [ ] `--interactive` / `--auto` pass the already-acquired document into
      `orch.ingest(..., acquired=...)` — no double acquisition.
- [ ] The four modes remain mutually exclusive with unchanged error messages.
- [ ] `_discover_documents` no longer exists in `cli.py`.
- [ ] `git diff --stat` on `cli.py` shows a focused diff — no reformatting or
      unrelated edits.
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_cli.py -v`
- [ ] `ruff check` and `mypy` clean.

---

## Test Specification

```python
# tests/knowledge/wiki/test_cli.py  (append)
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


class TestIngestSourceArgument:
    def test_directory_dry_run(self, wiki_project, md_corpus, stub_llm):
        result = CliRunner().invoke(
            wiki, ["ingest", str(md_corpus), "--dry-run", "--path", str(wiki_project)]
        )
        assert result.exit_code == 0
        assert "Triaged" in result.output

    def test_single_file_dry_run(self, wiki_project, sample_pdf, stub_llm):
        result = CliRunner().invoke(
            wiki, ["ingest", str(sample_pdf), "--dry-run", "--path", str(wiki_project)]
        )
        assert result.exit_code == 0

    def test_url_dry_run(self, wiki_project, mock_aiohttp_pdf, stub_llm):
        result = CliRunner().invoke(
            wiki,
            ["ingest", "https://example.test/doc.pdf", "--dry-run",
             "--path", str(wiki_project)],
        )
        assert result.exit_code == 0

    def test_missing_path_clean_error(self, wiki_project):
        result = CliRunner().invoke(
            wiki, ["ingest", "/no/such/path", "--dry-run", "--path", str(wiki_project)]
        )
        assert result.exit_code != 0
        assert "Traceback" not in result.output

    def test_no_recursive(self, wiki_project, nested_corpus, stub_llm):
        ...

    def test_undecodable_skipped_and_reported(
        self, wiki_project, mixed_corpus, stub_llm
    ):
        """One bad doc: skipped, counted, run still succeeds."""
        result = CliRunner().invoke(
            wiki, ["ingest", str(mixed_corpus), "--dry-run", "--path", str(wiki_project)]
        )
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()
        assert stub_llm.triage_calls_for("bad.pdf") == 0

    def test_modes_still_mutually_exclusive(self, wiki_project, md_corpus):
        result = CliRunner().invoke(
            wiki, ["ingest", str(md_corpus), "--dry-run", "--auto",
                   "--path", str(wiki_project)]
        )
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_discover_documents_removed(self):
        from parrot.knowledge.wiki import cli
        assert not hasattr(cli, "_discover_documents")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 7, §7 hot-file discipline).
2. **Check dependencies** — TASK-2354 and TASK-2356 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — `cli.py` drifts fast. Re-`grep` every
   line number above; they WILL have moved. Update this contract first, then
   implement.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2357-cli-source-argument-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
