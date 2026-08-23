# TASK-2363: CLI `--ns` on read commands + federated `_resolve_read_store` + `status` namespaces

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2362
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (read half), G4, G7, G9. `_resolve_read_store` (cli.py:199-251) returns one
store with precedence `--store > --path > WIKI_STORE > project`. It must now return a
`FederatedWikiStore` (TASK-2362) whenever the merged namespace map resolves to ≥1 namespace and
`--store` was **not** given, narrowed by `--ns`. `status` (1241-1288) must show a per-namespace
block and skips. `cli.py` is a HOT file — FEAT-451 edits the `ingest` region (2093-2544); keep
edits to the helper block (87-272) and the read commands (1075-1288).

---

## Scope

- Add a shared `ns_option = click.option("--ns", "ns_opt", default=None, help=...)` accepting a
  name, a comma-separated list of names, `all`, or `local`; attach to `query`, `page`, `related`,
  `status`.
- `_resolve_read_store(path_, store_opt, backend_opt, ns_opt=None)`: after the existing
  precedence decides the **local** store, if `store_opt` is set → return it unchanged (never
  federate `--store`); else `handles, skipped = _run(resolve_namespaces(root, config, only=...))`;
  if no namespaces are configured → return the local store unchanged (zero behaviour change);
  else build `FederatedWikiStore(local, config.wiki_name, handles, skipped)` and return
  `.scoped(ns_opt)` (`None` → broadcast). Unknown name → `ClickException` listing known names.
  `--ns local` → local store. For the arangodb local backend keep the existing eager
  `initialize()` block.
- `query`: after results, if the store has `skipped` entries (or `last_skipped`) print one
  trailing line per skip: `(namespace 'x' skipped: unbuilt — wikitoolkit build --path …)`.
  `--json` output rows already carry `namespace` (from the federated store).
- `page` / `related`: accept qualified ids transparently (the federated store routes); when
  `--ns <name>` is given and the id is unqualified, qualify it with that name before lookup.
- `status`: after the existing block print `Namespaces:` table rows
  `name  kind  backend  origin  pages  status` from `stats()["namespaces"]` plus skip lines; `--json`
  payload gains `"namespaces"` and `"skipped"`. Without configured namespaces output is unchanged.
- Tests in `tests/knowledge/wiki/test_cli.py`: broadcast default, `--ns other`, `--ns local`,
  unknown name, `--store` never federates, existing precedence test still holds with namespaces
  configured, `status` shows unbuilt skip with exit 0.

**NOT in scope**: `ns add/list/remove`, write commands (`--ns` on `remember/note/link`) —
TASK-2364; tools/MCP — TASK-2365.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `--ns`, `_resolve_read_store`, `query/page/related/status` |
| `tests/knowledge/wiki/test_cli.py` | MODIFY | add namespace tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces   # TASK-2362
from parrot.knowledge.wiki.context import qualify_id, split_namespaced_id               # TASK-2360
# already imported in cli.py: click, json, asyncio, Path, BaseWikiStore, create_wiki_store, WikiProjectConfig,
#   find_project_root, load_project_config, pack_results, truncate_to_tokens, all_scanners, SourceCollectionManager
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
path_option = click.option("--path", "path_", default=None, help="Repo root (default: auto-detect).")   # ~82
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]            # 87
def _require_built(root, config) -> BaseWikiStore                                   # 108
def _open_store(root, config) -> BaseWikiStore                                      # 118 (mkdirs storage at 132 — local only)
def _open_sources(root, config, store=None) -> SourceCollectionManager              # 138
def _normalize_scores(rows: list[dict]) -> list[dict]                               # 164 (min-max; idempotent on [0,1] rows)
def _run(coro) -> Any                                                               # 176 (asyncio.run)
def _env_setting(name: str) -> str | None                                           # 181
def _resolve_read_store(path_, store_opt, backend_opt) -> BaseWikiStore             # 199-251
    # arangodb branch 212-224 (eager initialize → ClickException); store_override 236-249; return _require_built(root, config) 251
def _store_options(func)                                                            # 255 — adds --backend (258-264) and --store (265-271)
@wiki.command() query(question, path_, top_k, budget, category, store_opt, backend_opt, as_table, show_body, as_json)   # 1075-1158
    # rows = _run(store.search_fts(question, category=category, limit=top_k)); rows = _normalize_scores(rows); pack_results(...)
@wiki.command() page(page_id, path_, max_tokens, store_opt, backend_opt, as_json)   # 1160-1200 — store.get_page(page_id, include_body=True)
@wiki.command() related(page_id, path_, rel, direction, store_opt, backend_opt, as_json)   # 1203-1239 — store.neighbors(page_id, rel=rel, direction=direction)
@wiki.command() status(path_, as_json)                                              # 1241-1288 — _open_store, _open_sources, store.stats(); payload dict 1263-1272; prints 1276-1288
# federation.py (TASK-2362)
class FederatedWikiStore(BaseWikiStore): local_name; namespaces: dict[str, NamespaceHandle]; skipped: list[NamespaceSkip]; last_skipped; def scoped(self, selector: str | None) -> BaseWikiStore
async def resolve_namespaces(root, config, *, only=None, registry_path=None, arango_timeout=5.0) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]
# tests/knowledge/wiki/test_cli.py — fixtures `repo` (42: temp repo built with PY_STORE/PY_UTIL), `runner` (55); `--store` tests 197-245; `_store_dir(repo)` helper
```

### Does NOT Exist
- ~~`--ns`~~ option, ~~`ns_option`~~ — you add them.
- ~~`_resolve_read_store(..., ns_opt=...)`~~ — current signature has three params (199-203).
- ~~`WIKI_NS`~~ env var — explicitly a non-goal; do not add.
- ~~`store.namespaces`~~ on a plain `SQLiteWikiStore` — only the federated store has it; use `isinstance(store, FederatedWikiStore)` or `getattr(store, "skipped", None)`.

---

## Implementation Notes

### Pattern to Follow
```python
# cli.py:236-251 — keep this exact precedence, add federation only on the project branch
root, config = _resolve_project(path_)
local = _require_built(root, config)
if not config.namespaces and not _global_has_namespaces():   # cheap check via load_global_registry()
    return local
handles, skipped = _run(resolve_namespaces(root, config, only=_wanted(ns_opt)))
fed = FederatedWikiStore(local, config.wiki_name, handles, skipped)
try:
    return fed.scoped(ns_opt)
except KeyError:
    raise click.ClickException(f"Unknown namespace {ns_opt!r}. Known: {', '.join(sorted(fed.namespaces))} (plus 'all', 'local').")
```

### Key Constraints
- `--store` must never federate (spec AC); the precedence test at `test_cli.py:212-214` must stay green.
- Zero output change when no namespaces are configured (all existing CLI tests unchanged).
- Do not touch lines 2093-2544 (`ingest`, FEAT-451).

### References in Codebase
- `cli.py:1276-1288` status printing style; `cli.py:1133-1150` query footer style.

---

## Acceptance Criteria

- [ ] Broadcast by default with ≥1 namespace; `--ns other` / `--ns local` / `--ns all` honoured; unknown → exit ≠0 listing names
- [ ] `--store DIR` → single store, no qualified ids, even with namespaces configured
- [ ] `page other::file:pkg/store.py` / `related other::dir:pkg` succeed
- [ ] `status` prints the namespaces table + skips, exit 0 with an unbuilt namespace; `--json` has `namespaces`/`skipped`
- [ ] All pre-existing `tests/knowledge/wiki/test_cli.py` tests pass unchanged
- [ ] `pytest tests/knowledge/wiki/test_cli.py -v`; `ruff check .../cli.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_cli.py (append) — reuse `repo`/`runner`; build a second repo the same way
def _second_repo(tmp_path, runner): ...  # copy of the `repo` fixture body into tmp_path/"other", then runner.invoke(wiki, ["build", "--path", ...])

def test_query_broadcasts_and_qualifies(runner, repo, tmp_path, monkeypatch):
    other = _second_repo(tmp_path, runner)
    _write_namespaces(repo, {"other": {"path": str(other)}})     # helper: edit .parrot/wiki.json
    res = runner.invoke(wiki, ["query", "store", "--path", str(repo), "--json"])
    ids = {r["concept_id"] for r in json.loads(res.output)}
    assert "file:pkg/store.py" in ids and "other::file:pkg/store.py" in ids

def test_query_ns_explicit_and_unknown(runner, repo, tmp_path): ...   # --ns other → only other::; --ns local → none qualified; --ns nope → exit != 0

def test_store_flag_never_federates(runner, repo, tmp_path): ...       # --store <other store> → no "::" in ids

def test_status_shows_unbuilt_namespace(runner, repo, tmp_path):
    (tmp_path / "empty").mkdir(); _write_namespaces(repo, {"empty": {"path": str(tmp_path / "empty")}})
    res = runner.invoke(wiki, ["status", "--path", str(repo)])
    assert res.exit_code == 0 and "unbuilt" in res.output and "wikitoolkit build --path" in res.output
```

---

## Agent Instructions

1. Read spec §2 (CLI surface), §3 Module 4, §6 (`cli.py` block), §7 (rebase risk).
2. Verify the contract against the current `cli.py` (FEAT-451 may have shifted line numbers).
3. Implement; run the whole `tests/knowledge/wiki` directory.
4. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
