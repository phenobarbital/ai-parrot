---
id: F006
query_id: Q006
type: read
intent: "How does a repository configure test runners, and does the installer deliver that file?"
executed_at: 2026-11-04T22:35:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — Runner settings live in `.parrot/test_runners.toml`, which the installer git-ignores and never seeds

## Summary

The FEAT-709 registry has four built-in runners (pytest, vitest, cargo, parrot-e2e) and
reads per-repo settings from `.parrot/test_runners.toml`. The installer's managed
`.gitignore` block ignores all of `.parrot/`, and neither `installer.py` nor
`_assets/manifest.json` mentions `test_runners`. In ai-parrot the file is tracked
(force-added), so the gap is invisible here; in a target repository the file is neither
shared with the team nor present in a fresh worktree.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py`
  lines: 14-20
  symbol: `BUILTIN_MODULES`
  excerpt: |
    CONFIG_PATH: str = ".parrot/test_runners.toml"
    BUILTIN_MODULES: Mapping[str, str] = {
        "pytest": "pytest",
        "vitest": "vitest",
        "cargo": "cargo",
        "parrot-e2e": "parrot_e2e",
    }

- path: `packages/ai-parrot/src/parrot/sdd/installer.py`
  lines: 49-54
  symbol: `GITIGNORE_BLOCK`
  excerpt: |
    "# SDD feature worktrees (parrot sdd worktree ensure)\n.claude/worktrees/\n"
    "# parrot's local state (ledger index, wiki store), ignored as parrot claude|codex|google install do\n.parrot/\n"

- path: `.parrot/test_runners.toml`
  lines: 1-1
  symbol: null
  excerpt: |
    (tracked: `git ls-files .parrot` → `.parrot/test_runners.toml`, `.parrot/wiki.local.json`)

## Notes

`grep -c test_runners` → 0 in `sdd/_assets/manifest.json` and 0 in `sdd/installer.py`.
`.parrot/sdd_hooks.toml` (`sdd/scripts/closeout_hooks_config.py:13`) has the same problem.
Open ledger issue `issue:29e8e7ad138f` (major, vulnerability): "Runner registry and vitest
cwd are read from the seat-writable attempt worktree" — a second reason to move runner
settings to a file read from the primary checkout.
New runner kinds are `[extensions] kind = "module:Class"`, i.e. a Python class; there is
no declarative shell runner (lane report, `registry.py:116-130`, not re-read).
