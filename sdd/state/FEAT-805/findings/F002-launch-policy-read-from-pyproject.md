---
id: F002
query_id: Q002
type: read
intent: "Where do the sandbox network allow-list and gh_token policy come from?"
executed_at: 2026-11-04T22:21:00Z
duration_ms: 0
parent_id: F001
depth: 1
---

# F002 — Launch policy (`sandbox_allowed_domains`, `gh_token`) is read only from `pyproject.toml`

## Summary

`load_launch_config(primary)` reads `[tool.parrot.sdd]` from the PRIMARY checkout's
`pyproject.toml` and returns `([], False)` when the file is absent. The only other
inputs are per-launch CLI flags. A non-Python repository therefore cannot persist an
allow-list (e.g. `api.github.com`, a package registry) for its sandboxed worker.

## Citations

- path: `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py`
  lines: 637-675
  symbol: `load_launch_config`
  excerpt: |
    config_path = primary / "pyproject.toml"
    if not config_path.is_file():
        return [], False
    ...
    raw_domains = table.get("sandbox_allowed_domains", [])
    gh_token = table.get("gh_token", False)

- path: `packages/ai-parrot/src/parrot/sdd/launch_cli.py`
  lines: 21-24
  symbol: null
  excerpt: |
    @click.option("--sandbox", type=click.Choice(["required", "preferred", "off", "legacy"]), default=None)
    @click.option("--sandbox-allow-domain", "allowed_domains", multiple=True, metavar="HOST")
    @click.option("--no-gh-token", is_flag=True, default=False, ...)

- path: `pyproject.toml`
  lines: 298-302
  symbol: null
  excerpt: |
    [tool.parrot.sdd]
    # Read from the PRIMARY checkout only. See docs/dev_loop/claude-native-sandbox.md.
    sandbox_allowed_domains = ["api.github.com"]
    gh_token = true

## Notes

The docstring states the trust rule: "the sandboxed session can write its own worktree
`pyproject.toml`, so only the primary checkout's file is trusted."
