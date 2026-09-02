# TASK-2748: `sym:` pages, `defines`/`contains` edges, `content_hash`, `SymbolResolver`, atomic ingest

**Feature**: FEAT-498 — ast-grep Structural Plane for wikitoolkit
**Spec**: `sdd/specs/ast-grep-for-wikitoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2740, TASK-2741, TASK-2747
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Turns `FileSlice.symbols`/`refs` into persisted graph
facts: `sym:` pages (`category="symbol"`), `defines` (file → sym) and
`contains` (parent sym → member sym) edges, `content_hash` on `file:` pages,
and the deterministic three-step `SymbolResolver` producing `calls` /
`extends` / `implements` edges with `provenance`. `sym:` pages travel in the
**same `replace_source_slice()`** as their `file:` page (atomic per source).

---

## Scope

- `repo_scan.build_file_slice()`: set `record.content_hash = sha1_of_text(content)`
  (equal to `SourceCollectionManager._compute_hash` for the same bytes — note
  `content` is decoded with `errors="replace"`; hash the **raw bytes** `data`
  instead to keep both digests identical), copy `lang_outline.symbols/refs`
  into the slice (filtered by `symbol_depth`), assign ordinals for repeated
  qualnames in source order.
- New `repo_scan.build_symbol_pages(slice: FileSlice) -> tuple[list[WikiPageRecord], list[tuple[str,str,str,str]]]`
  producing one `sym:` `WikiPageRecord` per symbol (`concept_id=sym_concept_id(...)`,
  `node_id=rel_path`, `title=qualname`, `category="symbol"`, `summary=doc`,
  `body` per spec §7 format with node excerpt ≤ 2 000 chars read from `data`
  via `start_byte:end_byte`, `token_count=estimate_tokens(body)`,
  `content_hash=symbol.content_hash`) plus `defines`/`contains` edges with
  provenance `extracted`. Use `symbols.symbol_to_page_fields()` (TASK-2747)
  so `symbol_from_page()` can decode it back.
- `RepoScan.symbol_records` / `symbol_edges` populated by `scan_repository()`.
- `SymbolResolver(files, reference_edges)` in `repo_scan.py`, invoked from
  `build_import_edges()` (or right after it in `scan_repository()` — keep
  `build_import_edges` signature unchanged; add `build_symbol_edges(files,
  import_edges)`): step 1 same file by qualname/name; step 2 files reachable
  via the source file's `references` edges by name; step 3 globally unique
  name → `inferred`; else no edge. `target_text` normalisation: last
  identifier segment for dotted/`::`/`\\`/`->` targets, keep the full text as
  a second key.
- `cli._ingest_files()`: per-slice `replace_source_slice(source_id,
  [file_record, *sym_records], slice_edges + symbol_edges_for_file)` then
  `upsert_symbols(symbols, source_id)`; bulk path adds the sym records/edges
  too; `sym:` records get the file's `source_id`.
- `upsert --changed` path inherits all of this via `scan_repository(rel_paths=…)`.
- Tests: `test_repo_scan.py` additions, `test_symbol_resolver.py`,
  `test_ingest_symbols.py` (sqlite + memory).

**NOT in scope**: read-repair, tools, CLI output.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/repo_scan.py` | MODIFY | `content_hash`, `build_symbol_pages`, `SymbolResolver`, `build_symbol_edges`, `RepoScan` population |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `_ingest_files` per-slice + bulk paths include symbols |
| `tests/knowledge/wiki/test_repo_scan.py` | MODIFY | content_hash, sym pages, edges, ordinals, depth |
| `tests/knowledge/wiki/test_symbol_resolver.py` | CREATE | Three-step resolution |
| `tests/knowledge/wiki/test_ingest_symbols.py` | CREATE | Atomic slice on sqlite + memory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.repo_scan import FileSlice, RepoScan, build_file_slice, build_import_edges, scan_repository, file_concept_id   # repo_scan.py:159/182/556/718/776/249
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens, BaseWikiStore     # store.py:224/172/332
from parrot.knowledge.wiki.symbols import SymbolRecord, SymbolRef, sym_concept_id, sha1_of_text, symbol_to_page_fields   # TASK-2738/2747
from parrot.knowledge.wiki.sources import SourceCollectionManager                          # sources.py:107
from parrot.knowledge.wiki.languages import scanner_for                                    # languages/__init__.py:47
```

### Existing Signatures to Use
```python
# repo_scan.py
def build_file_slice(root: Path, rel_path: str, body_max_chars=DEFAULT_BODY_MAX_CHARS, max_file_bytes=DEFAULT_MAX_FILE_BYTES) -> FileSlice | None   # :556
    data = path.read_bytes() (:577) ; content = data.decode("utf-8", errors="replace") (:581) ; scanner_for(suffix).outline(content, rel_path) (:588)
    record = WikiPageRecord(concept_id=file_concept_id(rel_path), node_id=rel_path, title=rel_path, category=category, summary=summary, body=body, token_count=estimate_tokens(body))   # ~:618
def build_dir_pages(...)                                        # :645
def build_import_edges(files: list[FileSlice], index_paths: Iterable[str] | None = None) -> list[tuple[str, str, str]]   # :718 — returns ("file:a", "file:b", "references")
def scan_repository(root, suffixes=None, exclude_dirs=None, body_max_chars=…, max_file_bytes=…, use_git=True, rel_paths=None) -> RepoScan   # :776
class RepoScan: root; files; dir_records; dir_edges; import_edges; skipped (+ symbol_records / symbol_edges from TASK-2738)   # :182

# cli.py
async def _ingest_files(store, sources, root, scan, force=False) -> dict[str, int]   # :622
    for edge in scan.import_edges: …                              # ~:644 (edge bucketing per source)
    registered = await asyncio.to_thread(sources.add_sources, …)  # ~:674 ; id_by_uri = {entry.source_uri: entry.source_id}
    file_slice.record.source_id = source_id                       # ~:680
    await store.replace_source_slice(source_id, [file_slice.record], slice_edges)   # ~:689  ← extend pages/edges lists
    await store.upsert_pages(bulk_records); await store.add_edges(bulk_edges)      # ~:694-696 (fresh plane bulk path)
    await asyncio.to_thread(sources.mark_ingested_many, ingested_pages)             # ~:698

# sources.py: SourceCollectionManager._compute_hash(self, path) -> str  :1115 — SHA-1 over file BYTES (8 KiB chunks)
# store.py: edges table (src, dst, rel, provenance) — add_edges accepts 4-tuples (:354 / SQLite :919)
```

### Does NOT Exist
- ~~`repo_scan.build_symbol_pages` / `SymbolResolver` / `build_symbol_edges`~~ — created here.
- ~~`RepoScan.symbol_records`~~ populated anywhere yet — TASK-2738 added the fields with empty defaults only.
- ~~`_ingest_files` handling anything but `[file_slice.record]`~~ — today one record per slice.
- ~~type-based resolution~~ — names only; ambiguous → no edge (spec Non-Goals).
- ~~a `SymbolResolver` that follows `sym:` → `file:` edges~~ — step 2 uses the **file-level `references` edges** produced by `build_import_edges`.

---

## Implementation Notes

### Pattern to Follow
```python
# provenance by step
edges.append((src_sym, dst_sym, ref.rel, "extracted"))   # steps 1-2
edges.append((src_sym, dst_sym, ref.rel, "inferred"))    # step 3 (globally unique name)
```

### Key Constraints
- `content_hash` for `file:` = `hashlib.sha1(data).hexdigest()` over the raw
  bytes so it equals `sources.file_hash` for the same file.
- Symbol excerpt slicing uses `data[start_byte:end_byte].decode("utf-8", errors="replace")`.
- Ordinals: count `qualname` occurrences within one file in `start_byte`
  order; the first keeps ordinal 1.
- Edges whose `dst` symbol is filtered out by `symbol_depth` are dropped (no
  dangling edges created by our own depth filter).
- `replace_source_slice()` semantics: pages + edges for the source replaced
  atomically; do not call `upsert_pages` separately for `sym:` pages on the
  per-slice path.

### References in Codebase
- `repo_scan.py:556-643` — file slice construction.
- `cli.py:622-700` — ingest loop.
- `tests/knowledge/wiki/test_ingest_files_batching.py` — batching expectations that must still hold.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/test_repo_scan.py tests/knowledge/wiki/test_symbol_resolver.py tests/knowledge/wiki/test_ingest_symbols.py tests/knowledge/wiki/test_ingest_files_batching.py tests/knowledge/wiki/languages/test_repo_scan_integration.py -v` passes.
- [ ] `build_file_slice(...).record.content_hash == SourceCollectionManager(...)._compute_hash(path)` for the same file.
- [ ] A Python fixture file (no extra) yields one `sym:` page per class/function/method, `defines` file→sym, `contains` class→method, ordinals `~2` for a duplicate qualname, and `symbol_depth=1` drops methods.
- [ ] Resolver: same-file → `extracted`; import-reachable → `extracted`; globally unique → `inferred`; ambiguous → no edge.
- [ ] After `_ingest_files` on sqlite + memory: `sym:` pages carry the file's `source_id`; re-ingesting the same file leaves no duplicate pages/rows; `broken_edges()` is empty for a self-contained fixture.
- [ ] `ruff` / `mypy` clean.

---

## Test Specification

```python
def test_symbol_resolver_steps(tmp_path):
    # a.py defines helper(); b.py imports a and calls helper(); c.py calls unique_fn() defined only in d.py; e.py and f.py both define dup()
    scan = scan_repository(tmp_path, use_git=False)
    prov = {(s, d): p for s, d, rel, p in scan.symbol_edges if rel == "calls"}
    assert prov[("sym:b.py#run", "sym:a.py#helper")] == "extracted"
    assert prov[("sym:c.py#go", "sym:d.py#unique_fn")] == "inferred"
    assert not any(d.endswith("#dup") for (_, d) in prov)
```

---

## Agent Instructions

1. Read spec §2 Overview ("Symbol plane"), §3 Module 6, §7 "Slice atomicity" +
"`sym:` page body". 2. Confirm TASK-2740, 2741, 2747 completed. 3. Verify
contract lines. 4. Index → `in-progress`. 5. Implement repo_scan first, then
ingest. 6. Tests. 7. Move to `completed/`. 8. Index → `done`. 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: `build_file_slice()` hashes the raw bytes (not the decoded
text) so `content_hash` equals `SourceCollectionManager._compute_hash`
byte-for-byte (verified live); it also filters `lang_outline.symbols` by
a new `symbol_depth: int = 2` keyword-only parameter (threaded through
`scan_repository()` too — AC20-permitted additive kwarg) so
`symbol_depth=1` genuinely drops methods, verified live. `build_symbol_pages(root,
slice)` re-reads the file's bytes itself (a deliberate signature widening
from the task's literal `(slice)` — the excerpt needs raw bytes
`FileSlice` doesn't carry; documented below) and builds one `sym:`
`WikiPageRecord` per symbol via `symbol_to_page_fields()`, plus
`defines`/`contains` edges; ordinal assignment
(`_ordinal_concept_ids`, shared with `SymbolResolver` so both agree on
the same ids) is source-byte-order, first-occurrence-clean, verified
stable across re-scans of an unchanged file. `SymbolResolver` implements
the exact three-step algorithm from the task's own test spec (verified
byte-for-byte against it: same-file → `extracted`, import-reachable →
`extracted`, globally-unique → `inferred`, ambiguous → no edge), using
`target_text` normalization (last segment after `->`/`::`/`.`/`\`) tried
alongside the raw text at every step. `cli._ingest_files()` groups
`scan.symbol_records`/`symbol_edges` by owning rel_path (`_owning_rel_path`,
parsing `file:`/`sym:` concept ids) and threads them into the SAME
`replace_source_slice()` call as the file record (atomic per source,
both the sqlite and per-slice-bulk paths), then calls `upsert_symbols()`
per file.
`pytest tests/knowledge/wiki/test_repo_scan.py
tests/knowledge/wiki/test_symbol_resolver.py
tests/knowledge/wiki/test_ingest_symbols.py
tests/knowledge/wiki/test_ingest_files_batching.py
tests/knowledge/wiki/languages/test_repo_scan_integration.py -v` → 84
passed (`test_ingest_symbols.py` parametrized over sqlite + memory).
Full `tests/knowledge/wiki`: 1346 passed (same single pre-existing
unrelated failure). `ruff check` clean; `mypy --ignore-missing-imports`
— every finding on both touched files verified byte-for-byte present in
the pre-task versions too, except one I introduced and fixed (see
Deviations).
**Deviations from spec**: Two adjustments, both necessary and narrowly
scoped:
1. `build_symbol_pages`'s signature is `(root: Path, slice: FileSlice)`,
   not the task's literal `(slice: FileSlice)` — the ≤2000-char source
   excerpt (spec §7 "sym: page body") needs `data[start_byte:end_byte]`,
   and `FileSlice` does not carry the file's raw bytes (by design — only
   `record`/`imports`/`language`/`symbols`/`refs`). Re-reading the file
   inside this function (rather than threading `data` through
   `scan_repository`'s per-file loop) keeps the call site simple and the
   function usable standalone (e.g. from a future read-repair path).
2. `store.replace_source_slice`'s declared `edges` parameter type
   (`Optional[list[tuple[str, str, str]]]`, in `store.py`/
   `arango_store.py`/`file_store.py` — none touched here) does not admit
   the 4-tuples (with `provenance`) `symbol_edges` carries, even though
   every backend's own edge-insertion helper already accepts a 4th
   provenance element (mirrors `add_edges`, verified: my
   `test_ingest_symbols.py` writes 4-tuple `calls`/`extends` edges
   through this exact path on both sqlite and memory and reads back the
   correct `provenance`). Rather than widen three files not in this
   task's list, `cli.py` uses one local `typing.cast` at the call site —
   a type-annotation-only fix, zero behavior change.
