---
id: F004
query_id: Q004
type: read
intent: Core dependencies and workspace root sync behaviour
executed_at: 2026-08-28T20:13:30Z
depth: 0
---
# F004 — Core `dependencies` omit rustworkx; workspace root `uv sync` installs no extras by default

## Summary
Core `dependencies` (pyproject lines 36-80+) contain numpy-bearing packages (pandas via asyncdb, faiss) but not rustworkx. The workspace root `pyproject.toml` lists all workspace members as plain deps and re-exports `wiki = ["ai-parrot[wiki]"]` as an optional extra; there is no `[tool.uv] default-groups` or default extra. Consequently a bare `uv sync` computes an exact environment without the `wiki`/`graphindex` extras and removes rustworkx — matching the reported symptom. `uv pip install ai-parrot` likewise installs only core deps. Note: sibling extra deps `aiosqlite`, `orjson`, `pathspec` are also extra-only (lines 217-219).

## Citations
- path: `pyproject.toml`
  lines: 27-42
  symbol: project.optional-dependencies
  excerpt: |
    [project.optional-dependencies]
    # Re-export key ai-parrot extras for `uv sync --extra <name>`
    google = ["ai-parrot[google]"]
    ...
    wiki = ["ai-parrot[wiki]"]
- path: `packages/ai-parrot/pyproject.toml`
  lines: 36-50
  symbol: dependencies
  excerpt: |
    dependencies = [
        "Cython==3.0.11",
        "tabulate==0.9.0",
        ...
        "tenacity>=8.2",
- path: `pyproject.toml`
  lines: 64-70
  symbol: tool.uv.environments
  excerpt: |
    [tool.uv]
    environments = [
        "sys_platform == 'linux'",
    ]
