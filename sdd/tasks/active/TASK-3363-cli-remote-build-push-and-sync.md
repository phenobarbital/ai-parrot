# TASK-3363: Remote-mode `build`/`upsert`/`ingest` delta push and `sync push|pull` via bulk tools (M6b)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3362, TASK-3357
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (push part), AC10, AC11, §8 Q4 (per-slice atomicity, re-run
converges). Scanning stays local (AST/tree-sitter need the checkout); the
result must reach the server through `wiki_page_hashes` + `wiki_ingest_batch`
(TASK-3356), chunked ≤200 slices / ≤1 MiB. `sync push|pull` must stop opening
ArangoDB from the laptop and use `wiki_sync_push` / `wiki_sync_pull`
(TASK-3357). Depends on TASK-3362 for `remote_cli.py` and because both edit
`cli.py`; on TASK-3357 for the payload models/tool names.

---

## Scope

- `remote_cli.push_slices(client, store, rel_paths, *, deleted_rel_paths=()) -> IngestBatchReport`: for each changed file build a `SourceSlicePayload` (pages with `source_id == f"file:{rel}"` via `store.list_pages`/`get_page`, edges via `store.neighbors`/`dump_edges` filtered to those pages, symbols via `store.symbols_for(rel)`); ask `wiki_page_hashes` for the file pages' ids and drop slices whose `content_hash` matches; chunk by both limits; call `wiki_ingest_batch` per chunk with a fresh `batch_id`; retry a `tool_error` chunk once; aggregate reports.
- `build`, `upsert`, `ingest` gain `--no-push` and, in remote mode, run the local path unchanged then push the changed/deleted files (`_changed_files_from_git` for `upsert --changed`; all scanned files for `build`; ingest's produced sources for `ingest`) and print the aggregated `IngestBatchReport`.
- `sync push` in remote mode: collect local memory pages (`_synced_memory_pages`) + asserted edges → `wiki_sync_push`; `sync pull`: iterate `wiki_sync_pull` with cursor → merge into the local plane via `_sync_records(source=mem, destination=local, direction="pull", skip_asserted_by=default_local_identity() unless --include-own)`.
- Tests with the fake remote recording calls.

**NOT in scope**: server-side tools (done), stdio pass-through (TASK-3364), `sync obsidian` (refused).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py` | MODIFY | `push_slices`, `sync_push_remote`, `sync_pull_remote` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `--no-push` + push after build/upsert/ingest; sync remote branches |
| `packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.remote_cli import remote_client, call_remote, RemoteCliError, remote_aware   # TASK-3362
from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError                              # TASK-3359
from parrot.knowledge.wiki.tools import SourceSlicePayload, IngestBatchReport, INGEST_MAX_SLICES, INGEST_MAX_BYTES, HASHES_MAX_IDS   # TASK-3356
from parrot.knowledge.wiki.sync import _sync_records, _synced_memory_pages, default_local_identity, SyncReport   # sync.py:221, :180, :86, :59
from parrot.knowledge.wiki.file_store import InMemoryWikiStore                                           # file_store.py:71 (bundle_dir, wiki_name="")
from parrot.knowledge.wiki.store import WikiPageRecord, BaseWikiStore                                    # store.py:409, :525
from parrot.knowledge.wiki.symbols import file_concept_id                                                # symbols.py (used by structural/service.py:~440) — verify exact name/line before use
import uuid, json
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
build(...) :1401 (options :1363-1400: --name --force --no-git --quiet …; body uses _resolve_project, _open_store, scans, _write_build_stats :1239) · def _changed_files_from_git(root: Path) -> list[str] :1616 · upsert(...) :1670 · ingest(...) :4292
sync group :3740 · sync_push_cmd(path_, target_env, dry_run) :3762 (calls sync_push(root, target_env=…, dry_run=…)) · sync_pull_cmd(path_, target_env, dry_run, include_own) :3805
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
list_pages(category=None, limit=100, origin=None) :568 · get_page(concept_id, include_body=True) :565 · neighbors(...) :582 · dump_edges() :593 · symbols_for(rel_path) :707 · page_hashes(ids) :803
# WikiPageRecord.source_id / content_hash fields :409-455 — file pages carry source_id == f"file:{rel_path}" and content_hash (FEAT-498)
# packages/ai-parrot/src/parrot/knowledge/wiki/sync.py
async def _sync_records(*, source, destination, direction, env, dry_run, skip_asserted_by) -> tuple[SyncReport, set[str]]   # :221
def default_local_identity() -> str :86 · async def _synced_memory_pages(store) :180
```

### Does NOT Exist
- ~~`store.pages_for_source(source_id)`~~ — no such method; use `list_pages(limit=…)` + filter `source_id`, or `get_page` on `file_concept_id(rel)` plus its `sym:`/`dir:` children (read how `replace_source_slice` groups by `source_id`, store.py:1557).
- ~~`store.edges_for(concept_ids)`~~ — use `dump_edges()` filtered, or `neighbors()` per page (choose one; document).
- ~~client-side ArangoDB in remote mode~~ — `sync._open_remote` must NOT be called when a remote is configured.
- ~~tombstones in sync~~ — deletions are not exchanged (S9).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#build",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#upsert",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ingest",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_changed_files_from_git",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#sync_push_cmd",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#sync_pull_cmd",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sync.py#_sync_records",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.page_hashes"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The local scan is untouched: remote mode only appends a push step after today's code (AC10, S10 "never changes scan semantics").
- Chunking must respect **both** limits; a single slice > 1 MiB is reported in `rejected`, never sent.
- Retry policy: one retry per chunk on `tool_error`; on second failure abort, print the failed `source_id`s and exit 2 (the hash oracle makes a re-run converge).
- `build`/`upsert`/`ingest` are decorated `@remote_cli.remote_aware(proxied=True)` (they *are* supported remotely — locally scanned, then pushed).

---

## Implementation Blueprint

### Steps (in order)
1. `push_slices` in `remote_cli.py` — *why*: one tested function used by three commands.
2. `sync_push_remote` / `sync_pull_remote` in `remote_cli.py` — *why*: same file, same client plumbing.
3. Wire the three build-like commands (`--no-push`, push step) — *why*: AC10.
4. Wire `sync push|pull` remote branches — *why*: AC11.
5. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py` (MODIFY — append)
```python
# AFTER — append below `remote_aware` (end of file as written by TASK-3362)
async def _collect_slice(store: BaseWikiStore, rel_path: str) -> SourceSlicePayload:
    """Pages, edges and symbols the local plane holds for one file (source_id == f"file:{rel_path}")."""
    # FILL IN: pages = [WikiPageRecord(**p) for p in <pages with source_id == f"file:{rel_path}">] (list_pages(limit=large) + filter, or get_page(file_concept_id(rel_path)) + children);
    #          edges = [(src, dst, rel) for e in await store.dump_edges() if e["src"] in ids or e["dst"] in ids]; symbols = await store.symbols_for(rel_path)
    #          — bounded by replace_source_slice semantics (store.py:1557: the slice is everything with that source_id)
    raise NotImplementedError


async def push_slices(client: RemoteWikiClient, store: BaseWikiStore, rel_paths: list[str], *,
                      deleted_rel_paths: tuple[str, ...] = ()) -> IngestBatchReport:
    """Delta-push changed files: hash oracle → chunk (≤200 slices, ≤1 MiB) → wiki_ingest_batch with one retry per chunk."""
    slices = [await _collect_slice(store, rel) for rel in rel_paths]
    ids = [p.concept_id for s in slices for p in s.pages]
    remote_hashes: dict[str, str | None] = {}
    for i in range(0, len(ids), HASHES_MAX_IDS):
        remote_hashes.update((await client.call_tool("wiki_page_hashes", {"concept_ids": ids[i:i + HASHES_MAX_IDS]}))["structuredContent"]["hashes"])  # FILL IN: exact result key (MCPToolAdapter._toolresult_to_mcp, adapter.py:108-148)
    changed = [s for s in slices if any(remote_hashes.get(p.concept_id) != p.content_hash for p in s.pages)]
    report = IngestBatchReport()
    # FILL IN: chunk `changed` by INGEST_MAX_SLICES and serialized size INGEST_MAX_BYTES (a single oversize slice → report.rejected);
    #          for each chunk: batch_id = uuid.uuid4().hex; try call_tool("wiki_ingest_batch", {...}) except tool_error → retry once → else raise RemoteCliError listing source_ids;
    #          deleted_source_ids=[f"file:{r}" for r in deleted_rel_paths] go in the first chunk; merge each chunk's report into `report` — bounded by AC10
    return report


async def sync_push_remote(client: RemoteWikiClient, local: BaseWikiStore) -> dict[str, Any]:
    pages = [WikiPageRecord(**p) for p in await _synced_memory_pages(local)]
    # FILL IN: edges = asserted edges touching those ids (dump_edges + kind == "asserted") as 4-tuples; return client.call_tool("wiki_sync_push", {"pages": [...json...], "edges": edges}) result
    raise NotImplementedError


async def sync_pull_remote(client: RemoteWikiClient, local: BaseWikiStore, *, wiki_name: str, include_own: bool, dry_run: bool) -> SyncReport:
    """Page through wiki_sync_pull into an InMemoryWikiStore, then merge with _sync_records(direction="pull")."""
    # FILL IN: skip = None if include_own else default_local_identity(); loop cursor until next_cursor is None collecting pages/edges into InMemoryWikiStore(tempdir);
    #          report, _ = await _sync_records(source=mem, destination=local, direction="pull", env=wiki_name, dry_run=dry_run, skip_asserted_by=skip); return report — bounded by AC11
    raise NotImplementedError
```
**Why this shape**: the client never sees ArangoDB; the oracle + keyed UPSERT (TASK-3355/3356) make repeated pushes idempotent, which is what §8 Q4 relies on.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — pattern for build/upsert/ingest)
```python
# occurrences: 1 (verified: grep -c '^def build(' packages/ai-parrot/src/parrot/knowledge/wiki/cli.py) — same for `^def upsert(` and `^def ingest(`
# 1) Add option (above each def, next to --quiet): @click.option("--no-push", "no_push", is_flag=True, help="Remote mode: scan locally but do not push to the remote server.")
# 2) Add `@remote_cli.remote_aware(proxied=True)` as the LAST decorator; add `no_push: bool` to the signature.
# 3) At the END of each command body (after today's summary output), append:
    remote = click.get_current_context().obj.get("remote")
    if remote is not None and not no_push:
        client = remote_cli.remote_client(remote)
        # FILL IN: rel_paths = <files this run wrote> (build: every scanned rel path; upsert: the --changed list from _changed_files_from_git or the explicit args; ingest: the source ids it produced),
        #          deleted = <files removed since last run> (upsert --changed: deleted entries from git; else ())
        report = remote_cli._run_push(client, store, rel_paths, deleted)   # thin sync wrapper around push_slices via _run
        click.echo(f"Pushed {report.slices_applied} slices ({report.pages_written} pages, {report.symbols_written} symbols, "
                   f"{report.slices_deleted} deleted, {len(report.rejected)} rejected) to {remote.url}")
# sync push (cli.py:3762) / sync pull (:3805): as the FIRST statements:
    remote = click.get_current_context().obj.get("remote")
    if remote is not None:
        root, config = _resolve_project(path_); local = _require_built(root, config); client = remote_cli.remote_client(remote)
        # push: result = _run(remote_cli.sync_push_remote(client, local)); echo counts. pull: report = _run(remote_cli.sync_pull_remote(client, local, wiki_name=config.wiki_name, include_own=include_own, dry_run=dry_run)); echo report
        return
# Both sync commands get `@remote_cli.remote_aware(proxied=True)`; `--env` is ignored in remote mode (echo a note).
```
**Why**: the push is strictly additive after the unchanged local flow; `sync` short-circuits before `sync_push()`/`sync_pull()` so `_open_remote` (client-side ArangoDB) is never reached in remote mode.

### FILL IN checklist
- [ ] `_collect_slice` page/edge collection — bounded by `replace_source_slice` slice semantics.
- [ ] `push_slices` chunking/retry/`rejected` — bounded by AC10 and the two limits.
- [ ] `wiki_page_hashes` result key — read `MCPToolAdapter._toolresult_to_mcp` (adapter.py:108-148).
- [ ] Which files each command pushes (build/upsert/ingest) — read each body.
- [ ] `sync_push_remote` edges; `sync_pull_remote` cursor loop.

---

## Acceptance Criteria

- [ ] Remote mode `build` of a fixture repo: fake remote receives ≥1 `wiki_page_hashes` then `wiki_ingest_batch` calls whose payload includes pages, edges and symbols; a second `build` with no file change sends `wiki_page_hashes` and **zero** `wiki_ingest_batch` calls (fake returns matching hashes).
- [ ] `--no-push` sends nothing; local plane still updated.
- [ ] 450 changed slices → 3 `wiki_ingest_batch` calls (200/200/50); one slice > 1 MiB → listed in `rejected`, not sent.
- [ ] Fake returns a JSON-RPC error for a chunk once → retried and succeeds; twice → exit 2 with the failed `source_id`s printed.
- [ ] `sync push` sends memory pages (+ asserted edges) to `wiki_sync_push`; `sync pull` iterates cursors and merges into the local plane (LWW); `sync._open_remote` is never called (monkeypatch to raise).
- [ ] Local mode unchanged (`test_cli.py`, `test_cli_sync.py`); `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py -q`
- `pytest tests/knowledge/wiki/test_cli_sync.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_cli_remote_push.py
import json, pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
# reuse `server`/Fake from test_remote_client.py, extended: record every tools/call name+arguments; answer wiki_page_hashes from a dict `fake.hashes`; answer wiki_ingest_batch with an IngestBatchReport dict


def test_build_pushes_then_converges(repo_with_remote):     # fixture: repo with 3 python files, remote configured, WIKITOOLKIT_TOKEN set
    root, fake = repo_with_remote
    assert CliRunner().invoke(wiki, ["build", "--quiet"]).exit_code == 0
    names = [c["name"] for c in fake.tool_calls]
    assert "wiki_page_hashes" in names and names.count("wiki_ingest_batch") >= 1
    batch = next(c for c in fake.tool_calls if c["name"] == "wiki_ingest_batch")["arguments"]
    assert batch["slices"][0]["pages"] and "symbols" in batch["slices"][0] and batch["batch_id"]
    fake.hashes = {p["concept_id"]: p["content_hash"] for s in batch["slices"] for p in s["pages"]}; fake.tool_calls.clear()
    assert CliRunner().invoke(wiki, ["build", "--quiet"]).exit_code == 0
    assert [c["name"] for c in fake.tool_calls].count("wiki_ingest_batch") == 0


def test_no_push(repo_with_remote):
    root, fake = repo_with_remote
    assert CliRunner().invoke(wiki, ["build", "--quiet", "--no-push"]).exit_code == 0 and fake.tool_calls == []


def test_sync_pull_never_opens_arango(repo_with_remote, monkeypatch):
    import parrot.knowledge.wiki.sync as sync
    monkeypatch.setattr(sync, "_open_remote", lambda *a, **k: (_ for _ in ()).throw(AssertionError("client-side arango")))
    fake = repo_with_remote[1]; fake.pull_pages = [{"concept_id": "memory:x", "title": "x", "body": "b", "origin": "memory", "asserted_by": "human:z", "updated_at": "2026-01-01T00:00:00+00:00"}]
    r = CliRunner().invoke(wiki, ["sync", "pull"]); assert r.exit_code == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3362, TASK-3357 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `build`/`upsert`/`ingest` bodies to find what each writes; read `_toolresult_to_mcp` for result keys
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
