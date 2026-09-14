---
id: F002
query_id: Q002
type: read
executed_at: 2026-09-14T00:05:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F002 — Worktree plane resolution exists outside the wiki project API

## Summary

`WikiProjectConfig.storage_path()` already accepts an absolute storage directory, but `find_project_root()` stops at the nearest `.parrot/wiki.json` or `.git` marker. The async `resolve_plane_root()` helper in `parrot.tools.repo.graph_search` resolves Git's common directory and returns its parent, allowing a linked worktree to read the main checkout's wiki plane without rebuilding it.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 472-496
  symbol: `WikiProjectConfig.storage_path`, `WikiProjectConfig.db_path`, `WikiProjectConfig.is_built`
  excerpt: |
    def storage_path(self, root: Path) -> Path:
        storage = Path(self.storage_dir)
        return storage if storage.is_absolute() else root / storage
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 640-660
  symbol: `find_project_root`
  excerpt: |
    for candidate in (current, *current.parents):
        if config_path(candidate).exists():
            return candidate
        if git_root is None and (candidate / ".git").exists():
            git_root = candidate
- path: `packages/ai-parrot/src/parrot/tools/repo/graph_search.py`
  lines: 31-81
  symbol: `resolve_plane_root`
  excerpt: |
    ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
    ...
    plane_root = common.parent
- path: `packages/ai-parrot/src/parrot/tools/repo/graph_search.py`
  lines: 84-119
  symbol: `open_plane`
  excerpt: |
    plane_root = await resolve_plane_root(repo_root)
    config = load_project_config(plane_root)
    store = create_wiki_store(config.storage_path(plane_root), ...)

## Notes

The existing helper is a read-only consumer seam. It does not establish shared-root behavior for wiki writers or ledger storage.
