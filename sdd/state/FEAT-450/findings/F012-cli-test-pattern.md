---
id: F012
query_id: Q021
type: grep
intent: Existing CLI tests for --store/WIKI_STORE (pattern to extend with --ns)
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F012 — --store/WIKI_STORE are covered by CliRunner tests building temp repos

## Summary
`tests/knowledge/wiki/test_cli.py:197-245` invokes `query/page/related` with `--store`, asserts
`WIKI_STORE` env is honoured (206) and does NOT override `--path` (212-214), errors on missing
dir (224) / empty store (233), and reads `file:pkg/store.py` / `dir:pkg` ids from a second store.
`test_execution_recorder.py:224-246` queries a recorder store via `--store`. The fixture builds
real temp repos and runs `build` — the same harness can build two repos and federate them.

## Citations
- path: `tests/knowledge/wiki/test_cli.py`
  lines: 197-245
  excerpt: |
    wiki, ["query", "utility helpers", "--store", ...]
    monkeypatch.setenv("WIKI_STORE", self._store_dir(repo))
    # An ambient WIKI_STORE must NOT redirect a --path-scoped query.
    wiki, ["page", "file:pkg/store.py", "--store", sd]
    runner.invoke(wiki, ["related", "dir:pkg", "--store", sd])
- path: `tests/knowledge/wiki/test_execution_recorder.py`
  lines: 224-246
