---
id: F003
query_id: Q003
type: read
intent: "How does a worktree get gitignored build artifacts, and where is that declared?"
executed_at: 2026-11-04T22:22:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — Worktree artifact sync is declared only in `pyproject.toml` `[tool.parrot.worktree]`

## Summary

`load_manifest` parses `[tool.parrot.worktree]` from `<repo_root>/pyproject.toml` and
returns an empty `NativeManifest` (sync is a no-op) when the file or table is absent.
`ensure_worktree` calls `sync_native_artifacts` right after creating the worktree; that
is the only post-create step. The model is copy/build oriented (`copy_globs`,
`pair_sources`, `abi_scoped`, `build`), designed for Cython `.so` files.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
  lines: 103-126
  symbol: `load_manifest`
  excerpt: |
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return NativeManifest()
    with pyproject.open("rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get("parrot", {}).get("worktree")

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/native_artifacts.py`
  lines: 49-71
  symbol: `NativeGroup`
  excerpt: |
    name: str
    copy_globs: list[str] = Field(default_factory=list)
    pair_sources: list[str] = Field(default_factory=list)
    required: bool = True
    abi_scoped: bool = False
    autobuild: bool = False
    build: list[str] = Field(default_factory=list)
    build_cwd: str = "."
    build_timeout_s: int = 900

- path: `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py`
  lines: 442-451
  symbol: `main`
  excerpt: |
    native = NativeSyncReport(enabled=False)
    if not args.dry_run and not args.no_native_sync:
        ...
            native = sync_native_artifacts(
                ...
                autobuild=not args.no_autobuild,

- path: `pyproject.toml`
  lines: 304-316
  symbol: null
  excerpt: |
    [tool.parrot.worktree]
    enabled = true
    [[tool.parrot.worktree.native_group]]
    name = "cython-core"
    copy_globs = ["packages/ai-parrot/src/parrot/**/*.so"]

## Notes

`ensure_worktree.py:27-46` loads `native_artifacts.py` by file path (stdlib + pydantic
only), so a new config reader used here must stay importable the same way.
