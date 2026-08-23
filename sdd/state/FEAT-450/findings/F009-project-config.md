---
id: F009
query_id: Q014
type: read
intent: Confirm WikiProjectConfig fields, root discovery, config load/save
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F009 — WikiProjectConfig is a flat Pydantic model with no namespaces field; root discovery is single-root

## Summary
`WikiProjectConfig` (project.py:125-215): `wiki_name`, `storage_dir` (152, default
`.parrot/wiki`, may be absolute), `backend`, scan options, `claude`, `sync_graph`,
`arango_*`, `vault_dir`; helpers `storage_path` (190), `db_path` (195), `is_built` (199).
`resolve_arango_params` (217) builds connection params from env prefix + `arango_database or
wiki_{name}`. `find_project_root` (296-316) walks up to the nearest `.parrot/wiki.json` (else
`.git`). `load_project_config`/`save_project_config` (323-366) read/write the JSON.
`PARROT_DIR=".parrot"` is relative to a repo root — there is no user-level (`~/.parrot`)
registry today. The module is declared dependency-light (stdlib + pydantic) for the hook.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 125-215
  symbol: `WikiProjectConfig`
  excerpt: |
    wiki_name: str = Field(default="codebase")
    storage_dir: str = Field(default=f"{PARROT_DIR}/wiki")          # 152
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")
    def storage_path(self, root: Path) -> Path:                        # 190
    def is_built(self, root: Path) -> bool:                            # 199
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 217-243
  symbol: `resolve_arango_params`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 291-316
  symbol: `config_path`, `find_project_root`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 319-366
  symbol: `WikiConfigError`, `load_project_config`, `save_project_config`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 1-40
  excerpt: |
    All helpers here are dependency-light (stdlib + pydantic) so the PreToolUse hook can import them
    PARROT_DIR = ".parrot"
