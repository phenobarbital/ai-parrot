---
id: F004
query_id: Q004
type: git_log
intent: "Determine how much of FEAT-704 exists on origin/feat-FEAT-704-semantic-layer and whether it can merge"
executed_at: 2026-10-25T10:20:00Z
duration_ms: 9000
parent_id: null
depth: 0
---

# F004 — `origin/feat-FEAT-704-semantic-layer` has all 20 tasks done, never merged, conflicts with dev

## Summary

The branch (tip `25b1fa594`, 2026-10-21; base `05d62af07`, 2026-10-19) carries 20/20 tasks `done` in its copy of the index, 56 new files / 6,698 insertions under `packages/ai-parrot-semantic/` and 16 files / 914 insertions outside it (server handler, `manager.py`, `duckdb.py` source fix, `authorizing.py` RLS fix, CI, docs, `ruff.toml`, `release.py`, `uv.lock`). No PR exists for it (`gh pr list --head` empty); `dev` is 1,379 commits ahead of the merge-base; `git merge-tree` reports content conflicts in `handlers/datasets.py`, `test_datasets_clone.py`, `dataset_manager/sources/authorizing.py`, `test_authorizing_data_source.py` and `uv.lock`.

## Citations

- path: `sdd/tasks/index/semantic-layer.json`
  lines: 1-20
  symbol: `tasks[].status` (branch copy)
  excerpt: |
    git show origin/feat-FEAT-704-semantic-layer:sdd/tasks/index/semantic-layer.json →
    [('TASK-4463','done'), ..., ('TASK-4482','done')]   # 20/20

- path: `packages/ai-parrot-semantic/pyproject.toml`
  lines: 1-40
  symbol: `[project] dependencies` (branch)
  excerpt: |
    dependencies = [
        "ai-parrot",
        "sidemantic==0.12.0",   # AGPL-3.0 — see README "License notice"; exact pin (spec §7)
        "sqlglot>=30.1,<31",
        "jsonschema>=4.20",
        "pyyaml>=6",
    ]

- path: `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py`
  lines: 1-101
  symbol: commit `b9f9983d67`
  excerpt: |
    fix(databasequery): DuckDB source executes via duckdb API in a worker thread   (+101/-? on branch)

- path: `packages/ai-parrot-server/src/parrot/handlers/semantic.py`
  lines: 1-202
  symbol: `SemanticLayerHandler` (branch, new file)
  excerpt: |
    202 lines, new on branch; registered from manager.py (+7)

### Commits (newest first, excerpt)
| SHA | Date | Message |
|---|---|---|
| `25b1fa594` | 2026-10-21 | style(semantic-layer): FEAT-704 — full lint pass |
| `d63ac6bf4` | 2026-10-21 | fix(semantic-layer): compile cache records model digest; PBAC probes the real module |
| `b9f9983d6` | 2026-10-21 | fix(databasequery): DuckDB source executes via duckdb API in a worker thread |
| `8018e7eae` | 2026-10-21 | sdd: complete TASK-4481 for semantic-layer |
| `05d62af07` | 2026-10-19 | sdd: add 20 tasks for FEAT-704 — semantic-layer (merge-base with dev) |

## Notes

Owner decision received mid-run (2026-10-25): "we can discard that branch because was focused on sidemantic [...] or re-use the code no related to sidemantic". The branch is therefore a **salvage source**, not a merge base. Conflicting files overlap FEAT-738 (F014).
