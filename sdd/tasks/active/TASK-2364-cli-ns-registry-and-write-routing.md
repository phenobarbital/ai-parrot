# TASK-2364: CLI `wikitoolkit ns list|add|remove` + `--ns <name>` write routing

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2362, TASK-2363
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (registry + write half), U1, U2, D4.3. `ns add` is the **only** way a namespace
enters `.parrot/wiki.json` or `~/.parrot/wikis.json` (U1). Writes target exactly one namespace:
local by default, or the single namespace named by `--ns <name>` on `remember` / `note` / `link`,
opened **read-write** for that call via `open_namespace_store(read_only=False)` — never through the
federation (U2). Runs after TASK-2363 because both edit `cli.py`.

---

## Scope

- New click group `ns` under `wiki` (`@wiki.group(name="ns")`) with:
  - `ns list [--path] [--json]` — merged map with columns `name  kind  origin  target  built`
    (built = `is_built`-style probe for path/vault/store sqlite; `n/a` for arangodb).
  - `ns add NAME (--path P | --store S [--backend B] | --database D [--credentials-env X] | --vault V)
    [--description TEXT] [--weight W] [--global]` — validates the name (`validate_namespace_name`),
    exactly one source option, duplicate name in the **same** registry → error (a repo entry
    shadowing a global one is allowed, print a note), resolves relative paths against the repo
    root (repo) or the registry directory (global); `--vault` additionally requires
    `(Path(V) / ".obsidian").is_dir()` (inline probe — do NOT import `vault_scan`) and prints the
    `wikitoolkit build --path <vault>` hint when `<vault-config>.is_built()` is false; writes via
    `save_project_config` / `save_global_registry`.
  - `ns remove NAME [--global]` — error if absent in the targeted registry.
- `_resolve_write_store(path_, store_opt, backend_opt, ns_opt=None)`: with `ns_opt` → resolve the
  entry from the merged map (repo, then global), reject `all`/`local`-as-foreign (`local` → normal
  local path), and return `(open_namespace_store(name, cfg, base_dir=..., read_only=False),
  storage_dir, None, None)`; `--store` together with `--ns` → error.
- Add `--ns` to `remember`, `note`, `link` (and to `memories`/`audit` **only if** they use
  `_resolve_write_store` — check). For `link` / `remember --links` a qualified page id must match
  the selected namespace or be rejected with a clear message.
- Tests in `tests/knowledge/wiki/test_cli.py` (registry CRUD repo+global under `PARROT_HOME`,
  `remember --ns other` lands in the other plane only, `--ns all` rejected, `ns add --vault`
  validation + hint).

**NOT in scope**: read routing (TASK-2363); `VaultIngestTool` / prune scoping (TASK-2366).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `ns` group, `_resolve_write_store`, `--ns` on authoring commands |
| `tests/knowledge/wiki/test_cli.py` | MODIFY | add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.project import (WikiNamespaceConfig, GlobalWikiRegistry, load_global_registry,
    save_global_registry, merge_namespaces, validate_namespace_name, global_registry_path,
    load_project_config, save_project_config)                      # project.py:323,350 + TASK-2359
from parrot.knowledge.wiki.federation import open_namespace_store   # TASK-2362
from parrot.knowledge.wiki.context import split_namespaced_id       # TASK-2360
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@click.group(name="wiki") @click.option("--verbose"...) @click.pass_context def wiki(ctx, verbose)   # 696-714
def _resolve_write_store(path_, store_opt, backend_opt) -> tuple[BaseWikiStore, Path, Path | None, WikiProjectConfig | None]   # 1470-1495
    # --store branch 1486-1493: mkdir storage_dir; returns (create_wiki_store(storage_dir, backend=backend), storage_dir, None, None)
    # project branch 1494-1495: _open_store(root, config), config.storage_path(root), root, config
def _authoring_identity(by) ; def _authoring_run_id()                                # ~1440-1467
@wiki.command() remember(text, path_, store_opt, backend_opt, title, category, links, rel, source_uri, by, extract_, as_json)   # 1647/1676
@wiki.command() note(page_id, text, path_, store_opt, backend_opt, by, as_json)     # 1802/1809
@wiki.command() link(src, dst, path_, store_opt, backend_opt, rel, by, as_json)      # 1866/1874
@wiki.command() memories(...) 1917/1923 ; audit(...) 1954/1959                       # check whether they call _resolve_write_store or _resolve_read_store
def _register_agent_command(name: str) -> None   # 2674 — example of attaching commands to `wiki` dynamically (not needed; use a static group)
# project.py
def save_project_config(root: Path, config: WikiProjectConfig) -> Path              # 350
WikiProjectConfig.is_built(root) -> bool (199); .storage_path(root) (190)
# TASK-2359: validate_namespace_name(name) raises ValueError; merge_namespaces → name -> (cfg, origin)
# TASK-2362: open_namespace_store(name, cfg, *, base_dir, read_only=True, arango_timeout=5.0) -> BaseWikiStore
```

### Does NOT Exist
- ~~`wikitoolkit ns`~~ group — you create it (`@wiki.group(name="ns")`, then `@ns.command("list")` etc.).
- ~~`_resolve_write_store(..., ns_opt=...)`~~ — current signature has three params.
- ~~`vault_scan.is_obsidian_vault` from cli for this probe~~ — importing `vault_scan` pulls `parrot.interfaces.obsidian`; `build` imports it lazily inside the command (cli.py:804-806). For `ns add --vault` use an inline `is_dir()` check.
- ~~`build --register`~~ / auto-registration — explicitly forbidden (U1).

---

## Implementation Notes

### Pattern to Follow
```python
@wiki.group(name="ns")
def ns() -> None:
    """Manage federated wiki namespaces."""

@ns.command("add")
@click.argument("name")
@path_option
@click.option("--path", "src_path", ...)  # NOTE: path_option already binds "--path"/"path_" for the repo root —
# use distinct flag names for the source: --project (alias) is NOT in spec; keep spec names but bind the repo root
# with path_option and the source with "--path"?? → CONFLICT. Resolution: the repo root keeps `--path`; the
# namespace source flags are `--project P` (kind path), `--store S`, `--database D`, `--vault V`.
```
**Decision to record in the Completion Note**: the spec's `ns add --path P` collides with the global
`--path` repo-root option used by every command. Use `--project P` for the `path` kind and document
it in the docs task (TASK-2368). Everything else keeps the spec names.

### Key Constraints
- Registry writes are atomic (`save_global_registry` from TASK-2359); repo writes go through
  `save_project_config` (preserves all other fields).
- `remember --ns other` must run the same bookkeeping (`WikiBookkeeper.log_operation`) against the
  *other* namespace's storage dir — reuse the tuple shape `(store, storage_dir, None, None)`.
- Do not touch `cli.py` 2093-2544 (FEAT-451).

### References in Codebase
- `cli.py:1486-1493` — `--store` write branch to mirror for `--ns`.
- `cli.py:1676-1800` `remember` — how `storage_dir`/`root`/`config` are consumed after resolution.

---

## Acceptance Criteria

- [ ] `ns add/list/remove` for repo and `--global` (under `PARROT_HOME`) with validation + shadowing note
- [ ] `ns add --vault` rejects a dir without `.obsidian/`; prints build hint when unbuilt
- [ ] `remember --ns other` writes only to the other plane; `note`/`link --ns` likewise; `--ns all` → exit ≠0
- [ ] Default `remember` still writes local; `--store` + `--ns` → exit ≠0
- [ ] `pytest tests/knowledge/wiki/test_cli.py tests/knowledge/wiki/test_authoring.py -v`; `ruff check .../cli.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_cli.py (append)
def test_ns_add_list_remove(runner, repo, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    other = _second_repo(tmp_path, runner)
    assert runner.invoke(wiki, ["ns", "add", "other", "--project", str(other), "--path", str(repo)]).exit_code == 0
    assert runner.invoke(wiki, ["ns", "add", "brain", "--store", str(tmp_path / "brain"), "--global", "--path", str(repo)]).exit_code == 0
    out = json.loads(runner.invoke(wiki, ["ns", "list", "--path", str(repo), "--json"]).output)
    assert {n["name"]: n["origin"] for n in out} == {"other": "repo", "brain": "global"}
    assert runner.invoke(wiki, ["ns", "add", "all", "--project", str(other), "--path", str(repo)]).exit_code != 0
    assert runner.invoke(wiki, ["ns", "remove", "brain", "--global", "--path", str(repo)]).exit_code == 0

def test_ns_add_vault_requires_obsidian(runner, repo, tmp_path): ...

def test_remember_ns_writes_foreign_only(runner, repo, tmp_path):
    other = _second_repo(tmp_path, runner); _write_namespaces(repo, {"other": {"path": str(other)}})
    r = runner.invoke(wiki, ["remember", "zebra fact", "--ns", "other", "--path", str(repo), "--json"])
    assert r.exit_code == 0, r.output
    assert "zebra" in runner.invoke(wiki, ["query", "zebra", "--path", str(other), "--json"]).output
    assert "zebra" not in runner.invoke(wiki, ["query", "zebra", "--path", str(repo), "--ns", "local", "--json"]).output
    assert runner.invoke(wiki, ["remember", "x", "--ns", "all", "--path", str(repo)]).exit_code != 0
```

---

## Agent Instructions

1. Read spec §2 (CLI surface), §3 Module 4, §5 AC (U1/U2 lines), §6, §7.
2. Verify the contract against current `cli.py` after TASK-2363 landed.
3. Implement; run the whole `tests/knowledge/wiki` directory.
4. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note (record the `--project` flag decision).

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: `ns add --path` → `--project` (flag collision with the repo-root `--path`)
