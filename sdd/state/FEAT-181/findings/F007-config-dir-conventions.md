---
id: F007
query_id: Q015
type: grep
intent: Config-directory conventions for picking where AGENT_CONTEXT.md lives.
executed_at: 2026-05-18T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — `parrot/conf.py` defines BASE_DIR + dir conventions via `config.get(..., fallback=BASE_DIR.joinpath(...))`

## Summary

The project uses **navconfig** (`from navconfig import config, BASE_DIR`)
as its config layer. `parrot/conf.py:5-160` is the single source of
truth for project paths and follows a consistent pattern:
`X_DIR = config.get('X_DIR', fallback=BASE_DIR.joinpath('x'))`. Existing
dirs declared this way: `PLUGINS_DIR`, `STATIC_DIR`, `OUTPUT_DIR`,
`AGENTS_DIR`, `PLANOGRAM_FOLDER`, `ONTOLOGY_DIR`, plus an MCP servers
dir. The pattern is well-established and the natural home for a new
`AGENT_CONTEXT_DIR` (or whatever name) so deployments can override via
env var. Most modules already import this style: `from navconfig import
config` is used by `bots/github_reviewer.py:43`, `agents/demo.py:32`, and
≥50 other files.

## Citations

- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: 5-160
  symbol: `BASE_DIR`-based directory declarations
  excerpt: |
    from navconfig import config, BASE_DIR
    ...
    PROJECT_ROOT = BASE_DIR
    PLUGINS_DIR = config.get('PLUGINS_DIR', fallback=BASE_DIR.joinpath('plugins'))
    STATIC_DIR = config.get('STATIC_DIR', fallback=BASE_DIR.joinpath('static'))
    OUTPUT_DIR = ... fallback=BASE_DIR.joinpath('outputs') ...
    AGENTS_DIR = config.get('AGENTS_DIR', fallback=BASE_DIR.joinpath('agents'))
    PLANOGRAM_FOLDER = config.get('PLANOGRAM_FOLDER', fallback=BASE_DIR.joinpath('images'))
    ONTOLOGY_DIR = config.get('ONTOLOGY_DIR', fallback=BASE_DIR.joinpath('ontologies'))
    ... fallback=BASE_DIR.joinpath('mcp_servers')

- path: `packages/ai-parrot/src/parrot/bots/github_reviewer.py`
  lines: 43, 320, 332, 404, 528
  symbol: navconfig usage in consumer
  excerpt: |
    from navconfig import config
    ...
    secret = config.get("GITHUB_REVIEW_WEBHOOK_SECRET")
    config.get("JIRA_ACCEPTANCE_CRITERIA_FIELD", fallback="customfield_10100")
    config.get("GIT_DEFAULT_BRANCH", fallback="main")

## Notes

navconfig `Kardex` (per user memory) uses `fallback=` not `default=`. The
pattern is consistent: each new path-style env var should use `fallback=`
and lazily call `.joinpath(...)` to defer disk I/O.
