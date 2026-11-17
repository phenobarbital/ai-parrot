---
id: F017
query_id: Q017
type: grep
intent: "What already works when `parrot sdd install` targets a non-Python repository?"
executed_at: 2026-11-04T22:40:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F017 — The installer itself tolerates a non-Python repository, but detects no toolchain

## Summary

The installer's only `pyproject.toml` use is an advisory note about pytest `pythonpath`
that returns `None` for a non-Python repository. Install succeeds and seeds a default
`sdd/config.json` (`test_command: null`) and an empty `sdd/CONVENTIONS.md`. Nothing
probes `package.json`, `Cargo.toml` or `go.mod`, and the external-tool audit still
lists `black` and `pylint`. Test coverage for a foreign repository stops at install,
uninstall and "fails without a traceback".

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/installer.py`
  lines: 871-982
  symbol: `worktree_test_isolation`
  excerpt: |
    _PYTHON_PROJECT_FILES: tuple[str, ...] = ("pyproject.toml", "setup.py", "setup.cfg")
    ...
    One sentence naming the cause and the recommended ``pythonpath`` setting, or None when the repo is
    not a Python project, ``test_command`` does not run pytest or already sets ``PYTHONPATH``, ...

- path: `packages/ai-parrot/src/parrot/sdd/audit.py`
  lines: 27-27
  symbol: `EXTERNAL_TOOLS`
  excerpt: |
    EXTERNAL_TOOLS: tuple[str, ...] = ("jq", "gh", "tmux", "codex", "git-lfs", "agy", "black", "pylint", "python3")

- path: `packages/ai-parrot/tests/sdd/test_installer.py`
  lines: 30-53
  symbol: `empty_repo`
  excerpt: |
    (fixture docstring) A fresh, non-Python git repository.

## Notes

Lane report, not re-read: `tests/sdd/test_wheel_only_foreign_repo.py:674-700`
(`test_c21_test_step_outcomes`) asserts `select_tests --tier task` exits 2 without a
traceback and `--tier merge --run` exits 1 with "not run" when pytest is absent;
`tests/sdd_scripts/test_check_task_graph.py:222-239` asserts vitest/pnpm/npm/cargo
validation commands pass the graph lint. No test runs `select_tests` end to end with a
vitest contract, creates a worktree of a Node repository, or exercises the guard's
rewritten command outside ai-parrot. `parrot sdd install` has no `--test-command` option.
The shipped commands need `python3`, `jq` and the `parrot` CLI on the host — a host
requirement, not a requirement that the repository be Python.
